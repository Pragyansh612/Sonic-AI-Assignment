from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.integrations.imap_client import ImapMailer
from app.integrations.llm_client import OpenAICompatibleLlm
from app.integrations.smtp_client import SmtpMailer
from app.rate_limit import SlidingWindowLimiter
from app.routes.deps import DbDep
from app.security import require_admin_token
from app.services.inbound_service import InboundService, NeedsAttentionService
from app.services.reminder_service import ReminderService
from app.repositories.collections import CollectionsRepository

router = APIRouter(prefix="/collections", tags=["collections"])

_inbox_limiter = SlidingWindowLimiter(max_calls=20, window_seconds=60.0)
_reminder_limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60.0)


async def _limit_inbox() -> None:
    _inbox_limiter.check("inbox")


async def _limit_reminders() -> None:
    _reminder_limiter.check("reminders")


class DraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: str = Field(min_length=1, max_length=20_000)


class SendEdited(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: str | None = Field(default=None, max_length=20_000)
    acknowledge_warnings: bool = False


def _smtp(db: DbDep) -> SmtpMailer:
    return SmtpMailer(get_settings(), db=db)


@router.post(
    "/reminders/send",
    dependencies=[Depends(require_admin_token), Depends(_limit_reminders)],
)
async def send_reminders(db: DbDep) -> dict[str, Any]:
    return await ReminderService(db, _smtp(db)).send_reminders()


@router.post(
    "/inbox/check",
    dependencies=[Depends(require_admin_token), Depends(_limit_inbox)],
)
async def check_inbox(db: DbDep) -> dict[str, Any]:
    settings = get_settings()
    return await InboundService(
        db,
        imap=ImapMailer(settings),
        smtp=_smtp(db),
        llm=OpenAICompatibleLlm(settings),
        settings=settings,
    ).check_inbox()


@router.get(
    "/conversations",
    dependencies=[Depends(require_admin_token)],
)
async def list_conversations(
    db: DbDep, status: str | None = None
) -> list[dict[str, Any]]:
    return await CollectionsRepository(db).list_conversations(status=status)


@router.get(
    "/conversations/{conversation_id}",
    dependencies=[Depends(require_admin_token)],
)
async def get_conversation(conversation_id: str, db: DbDep) -> dict[str, Any]:
    from fastapi import HTTPException

    repo = CollectionsRepository(db)
    conv = await repo.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    messages = await repo.list_messages(conversation_id)
    return {**conv, "messages": messages}


@router.get(
    "/needs-attention",
    dependencies=[Depends(require_admin_token)],
)
async def needs_attention(db: DbDep) -> list[dict[str, Any]]:
    return await NeedsAttentionService(db, _smtp(db)).list_items()


@router.patch(
    "/needs-attention/{conversation_id}",
    dependencies=[Depends(require_admin_token)],
)
async def edit_draft(
    conversation_id: str, payload: DraftUpdate, db: DbDep
) -> dict[str, Any]:
    return await NeedsAttentionService(db, _smtp(db)).update_draft(
        conversation_id, payload.draft
    )


@router.post(
    "/needs-attention/{conversation_id}/send",
    dependencies=[Depends(require_admin_token)],
)
async def send_needs_attention(
    conversation_id: str, payload: SendEdited, db: DbDep
) -> dict[str, Any]:
    return await NeedsAttentionService(db, _smtp(db)).send_edited(
        conversation_id,
        draft=payload.draft,
        acknowledge_warnings=payload.acknowledge_warnings,
    )


@router.post(
    "/needs-attention/{conversation_id}/dismiss",
    dependencies=[Depends(require_admin_token)],
)
async def dismiss_needs_attention(conversation_id: str, db: DbDep) -> dict[str, Any]:
    return await NeedsAttentionService(db, _smtp(db)).dismiss(conversation_id)
