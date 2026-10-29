"""Scheduled automations: run a saved prompt against a model on a schedule.

Every occurrence creates a regular chat owned by the automation's user, so the
result shows up in the sidebar and can be continued like any other chat.
"""

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr
from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse

from open_webui.env import (
    AUTOMATION_MAX_CONCURRENT,
    AUTOMATION_MIN_INTERVAL,
    AUTOMATION_POLL_INTERVAL,
    BYPASS_MODEL_ACCESS_CONTROL,
    SRC_LOG_LEVELS,
)
from open_webui.models.automations import (
    AutomationModel,
    AutomationRunModel,
    AutomationRuns,
    Automations,
)
from open_webui.models.chats import ChatForm, Chats
from open_webui.models.folders import Folders
from open_webui.models.models import Models
from open_webui.models.users import Users
from open_webui.socket.main import get_active_status_by_user_id, get_event_emitter
from open_webui.utils.access_control import has_permission
from open_webui.utils.chat import generate_chat_completion
from open_webui.utils.middleware import process_chat_payload
from open_webui.utils.models import check_model_access, get_all_models
from open_webui.utils.webhook import post_webhook

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

AUTOMATIONS_FOLDER_NAME = "Automations"


####################
# Schedules
####################


class ScheduleError(ValueError):
    pass


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ScheduleError(f"Unknown timezone '{timezone}'")


def _parse_rule(rrule: str, dtstart: int, timezone: str):
    rule = rrule.strip()
    if rule.upper().startswith("RRULE:"):
        rule = rule[len("RRULE:") :]
    if not rule or "\n" in rule or "DTSTART" in rule.upper():
        raise ScheduleError("Schedule must be a single RRULE without DTSTART")

    zone = _zone(timezone)
    # The rule is expanded in naive wall-clock time and only localized at the
    # end, so "09:00 every day" stays 09:00 local across DST changes.
    start = datetime.fromtimestamp(dtstart, zone).replace(tzinfo=None)
    try:
        return rrulestr(rule, dtstart=start), zone
    except (ValueError, TypeError) as e:
        raise ScheduleError(f"Invalid schedule: {e}")


def next_occurrence(
    rrule: str, dtstart: int, timezone: str, after: int
) -> Optional[int]:
    """First occurrence strictly after the `after` epoch, or None when finished."""
    rule, zone = _parse_rule(rrule, dtstart, timezone)
    local_after = datetime.fromtimestamp(after, zone).replace(tzinfo=None)
    occurrence = rule.after(local_after, inc=False)
    if occurrence is None:
        return None
    return int(occurrence.replace(tzinfo=zone).timestamp())


def upcoming_occurrences(
    rrule: str, dtstart: int, timezone: str, after: int, count: int = 5
) -> list[int]:
    occurrences = []
    cursor = after
    for _ in range(count):
        cursor = next_occurrence(rrule, dtstart, timezone, cursor)
        if cursor is None:
            break
        occurrences.append(cursor)
    return occurrences


def validate_schedule(rrule: str, dtstart: int, timezone: str) -> Optional[int]:
    """Raise ScheduleError for unusable schedules; return the first run time."""
    now = int(time.time())
    upcoming = upcoming_occurrences(rrule, dtstart, timezone, now - 1, count=6)
    if not upcoming:
        raise ScheduleError("This schedule has no future runs")

    gaps = [b - a for a, b in zip(upcoming, upcoming[1:])]
    if gaps and min(gaps) < AUTOMATION_MIN_INTERVAL:
        raise ScheduleError(
            f"Automations can run at most once every {AUTOMATION_MIN_INTERVAL // 60} minutes"
        )
    return upcoming[0]


####################
# Running
####################


def _build_request(app: FastAPI) -> Request:
    """A synthetic request so the regular chat pipeline can run outside HTTP."""
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "POST",
            "scheme": "http",
            "server": ("localhost", 8080),
            "client": ("127.0.0.1", 0),
            "path": "/api/chat/completions",
            "root_path": "",
            "query_string": b"",
            "headers": [],
            "state": {},
        }
    )


async def _collect_streaming_content(response: StreamingResponse) -> str:
    """Some pipes stream even when asked not to; fold the SSE body into text."""
    content = ""
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8", "ignore")
        for line in chunk.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            for choice in payload.get("choices", []):
                content += (choice.get("delta") or {}).get("content") or ""
    return content


def _format_reasoning(content: str, duration: int) -> str:
    """Render <think> blocks the way the chat UI shows streamed reasoning."""

    def replace(match: re.Match) -> str:
        thought = "\n".join(f"> {line}" for line in match.group(1).strip().splitlines())
        return (
            f'<details type="reasoning" done="true" duration="{duration}">\n'
            "<summary>Thought</summary>\n"
            f"{thought}\n"
            "</details>\n"
        )

    return re.sub(r"<think>(.*?)</think>\s*", replace, content, flags=re.DOTALL)


def _get_automations_folder_id(user_id: str) -> Optional[str]:
    folder = Folders.get_folder_by_parent_id_and_user_id_and_name(
        None, user_id, AUTOMATIONS_FOLDER_NAME
    )
    if folder is None:
        folder = Folders.insert_new_folder(user_id, AUTOMATIONS_FOLDER_NAME)
    return folder.id if folder else None


def _create_run_chat(automation: AutomationModel, model: dict, started_at: int):
    user_message_id = str(uuid.uuid4())
    assistant_message_id = str(uuid.uuid4())

    user_message = {
        "id": user_message_id,
        "parentId": None,
        "childrenIds": [assistant_message_id],
        "role": "user",
        "content": automation.prompt,
        "timestamp": started_at,
        "models": [automation.model_id],
    }
    assistant_message = {
        "id": assistant_message_id,
        "parentId": user_message_id,
        "childrenIds": [],
        "role": "assistant",
        "content": "",
        "model": automation.model_id,
        "modelName": model.get("name", automation.model_id),
        "modelIdx": 0,
        "userContext": None,
        "timestamp": started_at,
    }

    zone = _zone(automation.timezone)
    when = datetime.fromtimestamp(started_at, zone).strftime("%Y-%m-%d %H:%M")
    chat = Chats.insert_new_chat(
        automation.user_id,
        ChatForm(
            chat={
                "title": f"{automation.name} · {when}",
                "models": [automation.model_id],
                "params": {},
                "history": {
                    "messages": {
                        user_message_id: user_message,
                        assistant_message_id: assistant_message,
                    },
                    "currentId": assistant_message_id,
                },
                "messages": [user_message, assistant_message],
                "tags": [],
                "timestamp": started_at * 1000,
                "automation_id": automation.id,
            }
        ),
    )

    folder_id = (automation.options or {}).get("folder_id") or (
        _get_automations_folder_id(automation.user_id)
    )
    if folder_id:
        Chats.update_chat_folder_id_by_id_and_user_id(
            chat.id, automation.user_id, folder_id
        )

    return chat, assistant_message_id


async def _generate(
    request: Request,
    automation: AutomationModel,
    user,
    model: dict,
    chat_id: str,
    message_id: str,
) -> str:
    options = automation.options or {}
    model_info = Models.get_model_by_id(automation.model_id)
    tool_ids = (model_info.meta.model_dump().get("toolIds") if model_info else None) or None
    features = {"web_search": bool(options.get("web_search"))}

    messages = [{"role": "user", "content": automation.prompt}]
    zone = _zone(automation.timezone)
    now_local = datetime.now(zone).strftime("%A %Y-%m-%d %H:%M %Z")
    messages.insert(
        0,
        {
            "role": "system",
            "content": (
                f'This message was sent automatically by the scheduled automation "{automation.name}". '
                f"The current date and time for the user is {now_local}. "
                "The user is not watching live, so answer completely without asking follow-up questions."
            ),
        },
    )

    form_data = {
        "model": automation.model_id,
        "messages": messages,
        "stream": False,
        "tool_ids": tool_ids,
        "features": features,
    }
    metadata = {
        "user_id": user.id,
        "chat_id": chat_id,
        "message_id": message_id,
        "session_id": None,
        "tool_ids": tool_ids,
        "files": None,
        "features": features,
        "variables": {},
        "model": model,
        "direct": False,
    }
    request.state.metadata = metadata
    form_data["metadata"] = metadata

    form_data, metadata, _ = await process_chat_payload(
        request, form_data, user, metadata, model
    )
    # The payload pipeline may set stream back from the model's params.
    form_data["stream"] = False

    started = time.monotonic()
    response = await generate_chat_completion(request, form_data, user)

    if isinstance(response, StreamingResponse):
        content = await _collect_streaming_content(response)
    elif isinstance(response, dict):
        if "error" in response:
            error = response["error"]
            raise Exception(
                error.get("detail", error.get("message", str(error)))
                if isinstance(error, dict)
                else str(error)
            )
        choices = response.get("choices") or []
        content = (choices[0].get("message") or {}).get("content", "") if choices else ""
    else:
        raise Exception(f"Unexpected response from model: {type(response).__name__}")

    if not content:
        raise Exception("The model returned an empty response")
    return _format_reasoning(content, max(1, round(time.monotonic() - started)))


async def _notify(request: Request, user, chat_id: str, message_id: str, content: str):
    title = Chats.get_chat_title_by_id(chat_id)
    emitter = get_event_emitter(
        {"user_id": user.id, "chat_id": chat_id, "message_id": message_id},
        update_db=False,
    )
    await emitter({"type": "chat:title", "data": title})
    await emitter(
        {
            "type": "chat:completion",
            "data": {"done": True, "content": content, "title": title},
        }
    )

    if get_active_status_by_user_id(user.id) is None:
        webhook_url = Users.get_user_webhook_url_by_id(user.id)
        if webhook_url:
            post_webhook(
                request.app.state.WEBUI_NAME,
                webhook_url,
                f"{title} - {request.app.state.config.WEBUI_URL}/c/{chat_id}\n\n{content}",
                {
                    "action": "automation",
                    "message": content,
                    "title": title,
                    "url": f"{request.app.state.config.WEBUI_URL}/c/{chat_id}",
                },
            )


_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(AUTOMATION_MAX_CONCURRENT)
    return _semaphore


async def run_automation(
    app: FastAPI, automation: AutomationModel, trigger: str = "schedule"
) -> AutomationRunModel:
    run = AutomationRuns.insert_new_run(automation, trigger)
    Automations.mark_ran(automation.id, run.started_at)

    async with _get_semaphore():
        chat_id = None
        message_id = None
        try:
            user = Users.get_user_by_id(automation.user_id)
            if user is None:
                raise Exception("The owner of this automation no longer exists")
            if user.role != "admin" and not has_permission(
                user.id, "features.automations", app.state.config.USER_PERMISSIONS
            ):
                raise Exception("The owner is no longer allowed to use automations")

            request = _build_request(app)
            if not app.state.MODELS or automation.model_id not in app.state.MODELS:
                await get_all_models(request, user=user)

            model = app.state.MODELS.get(automation.model_id)
            if model is None:
                raise Exception(f"Model '{automation.model_id}' is not available")
            if not BYPASS_MODEL_ACCESS_CONTROL and user.role == "user":
                check_model_access(user, model)

            chat, message_id = _create_run_chat(automation, model, run.started_at)
            chat_id = chat.id
            AutomationRuns.update_run_by_id(run.id, {"chat_id": chat_id})

            content = await _generate(
                request, automation, user, model, chat_id, message_id
            )

            Chats.upsert_message_to_chat_by_id_and_message_id(
                chat_id, message_id, {"content": content, "done": True}
            )
            AutomationRuns.update_run_by_id(
                run.id, {"status": "success", "finished_at": int(time.time())}
            )
            run.status = "success"

            await _notify(request, user, chat_id, message_id, content)
        except Exception as e:
            log.exception(f"Automation {automation.id} failed: {e}")
            if chat_id and message_id:
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    chat_id, message_id, {"error": {"content": str(e)}, "done": True}
                )
            AutomationRuns.update_run_by_id(
                run.id,
                {"status": "error", "error": str(e), "finished_at": int(time.time())},
            )
            run.status = "error"
            run.error = str(e)

    run.chat_id = chat_id
    return run


# asyncio only keeps weak references to tasks; hold them until they finish.
_running_tasks: set[asyncio.Task] = set()


def spawn_run(app: FastAPI, automation: AutomationModel, trigger: str) -> None:
    task = asyncio.create_task(run_automation(app, automation, trigger))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)


####################
# Scheduler
####################


def _advance(automation: AutomationModel, now: int) -> bool:
    """Claim the due occurrence and move the automation to its next one.

    Missed occurrences (e.g. while the server was down) collapse into a single
    run instead of firing once per missed slot.
    """
    try:
        next_run_at = next_occurrence(
            automation.rrule, automation.dtstart, automation.timezone, now
        )
    except ScheduleError as e:
        log.warning(f"Disabling automation {automation.id}: {e}")
        next_run_at = None
    return Automations.claim_due_run(automation.id, automation.next_run_at, next_run_at)


async def scheduler_tick(app: FastAPI) -> None:
    now = int(time.time())
    for automation in Automations.get_due_automations(now):
        if _advance(automation, now):
            spawn_run(app, automation, "schedule")


async def automation_scheduler(app: FastAPI) -> None:
    AutomationRuns.fail_stale_runs()
    log.info("Automation scheduler started")
    while True:
        try:
            await scheduler_tick(app)
        except Exception as e:
            log.exception(f"Automation scheduler tick failed: {e}")
        await asyncio.sleep(AUTOMATION_POLL_INTERVAL)
