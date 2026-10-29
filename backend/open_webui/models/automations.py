import logging
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, JSON, Text, update

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Automation DB Schema
####################


class Automation(Base):
    __tablename__ = "automation"

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False)

    name = Column(Text, nullable=False)
    prompt = Column(Text, nullable=False)
    model_id = Column(Text, nullable=False)

    # iCalendar RRULE (e.g. "FREQ=WEEKLY;BYDAY=MO,FR") evaluated from dtstart
    # in the user's IANA timezone, so "every day at 9" stays at 9 across DST.
    rrule = Column(Text, nullable=False)
    dtstart = Column(BigInteger, nullable=False)
    timezone = Column(Text, nullable=False, default="UTC")

    # {"web_search": bool, "folder_id": str | None, ...}
    options = Column(JSON, nullable=True)

    enabled = Column(Boolean, nullable=False, default=True)
    next_run_at = Column(BigInteger, nullable=True)
    last_run_at = Column(BigInteger, nullable=True)
    run_count = Column(BigInteger, nullable=False, default=0)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)


class AutomationRun(Base):
    __tablename__ = "automation_run"

    id = Column(Text, primary_key=True)
    automation_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=True)

    status = Column(Text, nullable=False)  # running | success | error
    error = Column(Text, nullable=True)
    trigger = Column(Text, nullable=False)  # schedule | manual

    started_at = Column(BigInteger, nullable=False)
    finished_at = Column(BigInteger, nullable=True)


class AutomationModel(BaseModel):
    id: str
    user_id: str

    name: str
    prompt: str
    model_id: str

    rrule: str
    dtstart: int
    timezone: str = "UTC"
    options: Optional[dict] = None

    enabled: bool = True
    next_run_at: Optional[int] = None
    last_run_at: Optional[int] = None
    run_count: int = 0

    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


class AutomationRunModel(BaseModel):
    id: str
    automation_id: str
    user_id: str
    chat_id: Optional[str] = None

    status: str
    error: Optional[str] = None
    trigger: str

    started_at: int
    finished_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class AutomationForm(BaseModel):
    name: str
    prompt: str
    model_id: str
    rrule: str
    dtstart: int
    timezone: str = "UTC"
    options: Optional[dict] = None
    enabled: bool = True


class AutomationResponse(AutomationModel):
    last_run: Optional[AutomationRunModel] = None


class AutomationTable:
    def insert_new_automation(
        self, user_id: str, form_data: AutomationForm, next_run_at: Optional[int]
    ) -> Optional[AutomationModel]:
        with get_db() as db:
            now = int(time.time())
            automation = AutomationModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "next_run_at": next_run_at,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            result = Automation(**automation.model_dump())
            db.add(result)
            db.commit()
            db.refresh(result)
            return AutomationModel.model_validate(result)

    def get_automation_by_id(self, id: str) -> Optional[AutomationModel]:
        with get_db() as db:
            automation = db.get(Automation, id)
            return AutomationModel.model_validate(automation) if automation else None

    def get_automations_by_user_id(self, user_id: str) -> list[AutomationModel]:
        with get_db() as db:
            return [
                AutomationModel.model_validate(automation)
                for automation in db.query(Automation)
                .filter_by(user_id=user_id)
                .order_by(Automation.created_at.desc())
                .all()
            ]

    def count_automations_by_user_id(self, user_id: str) -> int:
        with get_db() as db:
            return db.query(Automation).filter_by(user_id=user_id).count()

    def get_due_automations(self, now: int) -> list[AutomationModel]:
        with get_db() as db:
            return [
                AutomationModel.model_validate(automation)
                for automation in db.query(Automation)
                .filter(
                    Automation.enabled == True,  # noqa: E712
                    Automation.next_run_at.isnot(None),
                    Automation.next_run_at <= now,
                )
                .all()
            ]

    def update_automation_by_id(
        self, id: str, updated: dict
    ) -> Optional[AutomationModel]:
        with get_db() as db:
            db.query(Automation).filter_by(id=id).update(
                {**updated, "updated_at": int(time.time())}
            )
            db.commit()
            return self.get_automation_by_id(id)

    def claim_due_run(
        self, id: str, expected_next_run_at: int, next_run_at: Optional[int]
    ) -> bool:
        """Move next_run_at forward only if nobody else did first.

        With several workers polling the same database, exactly one of them
        wins this compare-and-swap and gets to execute the occurrence.
        """
        with get_db() as db:
            values = {"next_run_at": next_run_at}
            if next_run_at is None:
                values["enabled"] = False
            result = db.execute(
                update(Automation)
                .where(
                    Automation.id == id,
                    Automation.next_run_at == expected_next_run_at,
                )
                .values(**values)
            )
            db.commit()
            return result.rowcount == 1

    def mark_ran(self, id: str, ran_at: int) -> None:
        with get_db() as db:
            db.query(Automation).filter_by(id=id).update(
                {
                    "last_run_at": ran_at,
                    "run_count": Automation.run_count + 1,
                }
            )
            db.commit()

    def delete_automation_by_id(self, id: str) -> bool:
        with get_db() as db:
            db.query(AutomationRun).filter_by(automation_id=id).delete()
            db.query(Automation).filter_by(id=id).delete()
            db.commit()
            return True


class AutomationRunTable:
    def insert_new_run(
        self, automation: AutomationModel, trigger: str
    ) -> AutomationRunModel:
        with get_db() as db:
            run = AutomationRunModel(
                id=str(uuid.uuid4()),
                automation_id=automation.id,
                user_id=automation.user_id,
                status="running",
                trigger=trigger,
                started_at=int(time.time()),
            )
            db.add(AutomationRun(**run.model_dump()))
            db.commit()
            return run

    def update_run_by_id(self, id: str, updated: dict) -> None:
        with get_db() as db:
            db.query(AutomationRun).filter_by(id=id).update(updated)
            db.commit()

    def get_runs_by_automation_id(
        self, automation_id: str, limit: int = 20
    ) -> list[AutomationRunModel]:
        with get_db() as db:
            return [
                AutomationRunModel.model_validate(run)
                for run in db.query(AutomationRun)
                .filter_by(automation_id=automation_id)
                .order_by(AutomationRun.started_at.desc())
                .limit(limit)
                .all()
            ]

    def get_last_run_by_automation_id(
        self, automation_id: str
    ) -> Optional[AutomationRunModel]:
        runs = self.get_runs_by_automation_id(automation_id, limit=1)
        return runs[0] if runs else None

    def fail_stale_runs(self) -> None:
        """Runs left 'running' by a crash or restart can never finish."""
        with get_db() as db:
            db.query(AutomationRun).filter_by(status="running").update(
                {
                    "status": "error",
                    "error": "Interrupted by a server restart",
                    "finished_at": int(time.time()),
                }
            )
            db.commit()


Automations = AutomationTable()
AutomationRuns = AutomationRunTable()
