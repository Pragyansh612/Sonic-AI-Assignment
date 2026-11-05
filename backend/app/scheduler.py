"""Optional APScheduler jobs for reminders and inbox poll (off by default)."""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings, get_settings
from app.db import get_db
from app.integrations.imap_client import ImapMailer
from app.integrations.llm_client import OpenAICompatibleLlm
from app.integrations.smtp_client import SmtpMailer
from app.services.inbound_service import InboundService
from app.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_reminders() -> None:
    settings = get_settings()
    db = get_db(settings)
    try:
        result = await ReminderService(db, SmtpMailer(settings, db=db), settings).send_reminders()
        logger.info("Scheduled reminders: %s", result.get("ok"))
    except Exception:
        logger.exception("Scheduled reminder run failed")


async def _run_inbox() -> None:
    settings = get_settings()
    db = get_db(settings)
    try:
        result = await InboundService(
            db,
            imap=ImapMailer(settings),
            smtp=SmtpMailer(settings, db=db),
            llm=OpenAICompatibleLlm(settings),
            settings=settings,
        ).check_inbox()
        logger.info("Scheduled inbox check: processed=%s", len(result.get("processed") or []))
    except Exception:
        logger.exception("Scheduled inbox check failed")


def start_scheduler(settings: Settings | None = None) -> AsyncIOScheduler | None:
    global _scheduler
    settings = settings or get_settings()
    if not settings.enable_reminder_scheduler and not settings.enable_inbox_poll:
        return None
    if _scheduler is not None:
        return _scheduler

    sched = AsyncIOScheduler()
    if settings.enable_reminder_scheduler:
        # Daily at 09:00 local; overlap prevented by ReminderService lock
        sched.add_job(_run_reminders, "interval", hours=24, id="reminders", replace_existing=True)
        logger.info("Reminder scheduler enabled (interval 24h)")
    if settings.enable_inbox_poll:
        secs = max(30, int(settings.inbox_poll_seconds))
        sched.add_job(_run_inbox, "interval", seconds=secs, id="inbox", replace_existing=True)
        logger.info("Inbox poll enabled (every %ss)", secs)
    sched.start()
    _scheduler = sched
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
