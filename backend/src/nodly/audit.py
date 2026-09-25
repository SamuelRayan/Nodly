"""Writing to the audit log. Entries are added to the caller's session and commit with it."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nodly.log import current_log_context
from nodly.models import ActorType, AuditLog


def record_audit(
    session: AsyncSession,
    *,
    actor_type: ActorType,
    action: str,
    actor_id: uuid.UUID | None = None,
    family_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: object | None = None,
    data: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        family_id=family_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        data=data or {},
        request_id=current_log_context().get("request_id"),
    )
    session.add(entry)
    return entry
