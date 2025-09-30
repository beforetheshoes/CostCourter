from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from decimal import Decimal

import structlog
from sqlmodel import Session

from app.models import AuditLog

_logger = structlog.get_logger(__name__)


def _normalize_value(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, AbstractSet):
        normalized = [_normalize_value(item) for item in value]
        return sorted(normalized, key=lambda item: repr(item))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_normalize_value(item) for item in value]
    return str(value)


def record_audit_log(
    session: Session,
    *,
    action: str,
    actor_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    ip_address: str | None = None,
    context: Mapping[str, object] | None = None,
) -> AuditLog:
    """Persist an ``AuditLog`` entry and emit a structured log event."""

    payload_context: dict[str, object] | None = None
    if context is not None:
        payload_context = {
            str(key): _normalize_value(value) for key, value in context.items()
        }

    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
        context=payload_context,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)

    _logger.info(
        "audit.recorded",
        action=action,
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
    )
    return entry


__all__ = ["record_audit_log"]
