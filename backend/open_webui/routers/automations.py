import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from open_webui.constants import ERROR_MESSAGES
from open_webui.env import (
    AUTOMATION_MAX_COUNT,
    BYPASS_MODEL_ACCESS_CONTROL,
    ENABLE_AUTOMATIONS,
    SRC_LOG_LEVELS,
)
from open_webui.models.automations import (
    AutomationForm,
    AutomationModel,
    AutomationResponse,
    AutomationRunModel,
    AutomationRuns,
    Automations,
)
from open_webui.utils.access_control import has_permission
from open_webui.utils.auth import get_verified_user
from open_webui.utils.automations import (
    ScheduleError,
    spawn_run,
    upcoming_occurrences,
    validate_schedule,
)
from open_webui.utils.models import check_model_access, get_all_models

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


def get_automations_user(request: Request, user=Depends(get_verified_user)):
    if not ENABLE_AUTOMATIONS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.DEFAULT("Automations are disabled"),
        )
    if user.role != "admin" and not has_permission(
        user.id, "features.automations", request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return user


def get_owned_automation(id: str, user) -> AutomationModel:
    automation = Automations.get_automation_by_id(id)
    if automation is None or automation.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    return automation


def checked_first_run(form_data: AutomationForm) -> Optional[int]:
    try:
        return validate_schedule(form_data.rrule, form_data.dtstart, form_data.timezone)
    except ScheduleError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(str(e)),
        )


async def check_model(request: Request, model_id: str, user) -> None:
    if not request.app.state.MODELS or model_id not in request.app.state.MODELS:
        await get_all_models(request, user=user)

    model = request.app.state.MODELS.get(model_id)
    try:
        if model is None:
            raise Exception("Model not found")
        if not BYPASS_MODEL_ACCESS_CONTROL and user.role == "user":
            check_model_access(user, model)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(f"Model '{model_id}' is not available"),
        )


def check_form(form_data: AutomationForm) -> None:
    if not form_data.name.strip() or not form_data.prompt.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Name and prompt are required"),
        )


def with_last_run(automation: AutomationModel) -> AutomationResponse:
    return AutomationResponse(
        **automation.model_dump(),
        last_run=AutomationRuns.get_last_run_by_automation_id(automation.id),
    )


############################
# Get Automations
############################


@router.get("/", response_model=list[AutomationResponse])
async def get_automations(user=Depends(get_automations_user)):
    return [
        with_last_run(automation)
        for automation in Automations.get_automations_by_user_id(user.id)
    ]


############################
# Preview Schedule
############################


class SchedulePreviewForm(BaseModel):
    rrule: str
    dtstart: int
    timezone: str = "UTC"


@router.post("/preview")
async def preview_schedule(
    form_data: SchedulePreviewForm, user=Depends(get_automations_user)
):
    try:
        validate_schedule(form_data.rrule, form_data.dtstart, form_data.timezone)
        return {
            "occurrences": upcoming_occurrences(
                form_data.rrule,
                form_data.dtstart,
                form_data.timezone,
                int(time.time()) - 1,
            )
        }
    except ScheduleError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(str(e)),
        )


############################
# Create Automation
############################


@router.post("/create", response_model=AutomationResponse)
async def create_automation(
    request: Request,
    form_data: AutomationForm,
    user=Depends(get_automations_user),
):
    check_form(form_data)
    if (
        user.role != "admin"
        and Automations.count_automations_by_user_id(user.id) >= AUTOMATION_MAX_COUNT
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                f"You can have at most {AUTOMATION_MAX_COUNT} automations"
            ),
        )

    next_run_at = checked_first_run(form_data)
    await check_model(request, form_data.model_id, user)

    automation = Automations.insert_new_automation(
        user.id, form_data, next_run_at if form_data.enabled else None
    )
    return with_last_run(automation)


############################
# Get Automation By Id
############################


@router.get("/{id}", response_model=AutomationResponse)
async def get_automation_by_id(id: str, user=Depends(get_automations_user)):
    return with_last_run(get_owned_automation(id, user))


@router.get("/{id}/runs", response_model=list[AutomationRunModel])
async def get_automation_runs(id: str, user=Depends(get_automations_user)):
    automation = get_owned_automation(id, user)
    return AutomationRuns.get_runs_by_automation_id(automation.id)


############################
# Update Automation
############################


@router.post("/{id}/update", response_model=AutomationResponse)
async def update_automation_by_id(
    request: Request,
    id: str,
    form_data: AutomationForm,
    user=Depends(get_automations_user),
):
    get_owned_automation(id, user)
    check_form(form_data)

    next_run_at = checked_first_run(form_data)
    await check_model(request, form_data.model_id, user)

    automation = Automations.update_automation_by_id(
        id,
        {
            **form_data.model_dump(),
            "next_run_at": next_run_at if form_data.enabled else None,
        },
    )
    return with_last_run(automation)


@router.post("/{id}/toggle", response_model=AutomationResponse)
async def toggle_automation_by_id(id: str, user=Depends(get_automations_user)):
    automation = get_owned_automation(id, user)

    if automation.enabled:
        updated = {"enabled": False, "next_run_at": None}
    else:
        form_data = AutomationForm(**automation.model_dump())
        updated = {"enabled": True, "next_run_at": checked_first_run(form_data)}

    return with_last_run(Automations.update_automation_by_id(id, updated))


############################
# Run Automation Now
############################


@router.post("/{id}/run", response_model=AutomationResponse)
async def run_automation_by_id(
    request: Request, id: str, user=Depends(get_automations_user)
):
    automation = get_owned_automation(id, user)
    await check_model(request, automation.model_id, user)

    # Runs can take minutes (tools, web search); don't hold the request open.
    spawn_run(request.app, automation, "manual")
    # Give the run a moment to register so the response already shows it.
    await asyncio.sleep(0.2)
    return with_last_run(Automations.get_automation_by_id(id))


############################
# Delete Automation
############################


@router.delete("/{id}/delete", response_model=bool)
async def delete_automation_by_id(id: str, user=Depends(get_automations_user)):
    get_owned_automation(id, user)
    return Automations.delete_automation_by_id(id)
