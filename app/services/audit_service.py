"""Append-only audit logging helper.

`record_audit` is the single write path for the audit trail. It performs its
own committed insert (decoupled from the caller's transaction) so the log stays
truly append-only, and it swallows any failure so an audit hiccup can never
break the business operation it is recording.
"""

import logging
import uuid

from sqlalchemy.orm import Session

from app.crud import audit_log as audit_log_crud
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

SYSTEM_ROLE = "system"


def record_audit(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    summary: str | None = None,
    details: dict | None = None,
) -> AuditLog | None:
    """Insert one audit record. Returns the row, or None if logging failed."""
    try:
        entry = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            actor_role=actor_role,
            summary=summary,
            details=details,
        )
        return audit_log_crud.create_audit_log(db, entry)
    except Exception:  # never let auditing break the underlying operation
        logger.exception("Failed to record audit event action=%s entity=%s", action, entity_type)
        try:
            db.rollback()
        except Exception:
            pass
        return None
