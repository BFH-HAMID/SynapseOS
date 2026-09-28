"""Admin action audit trail helper — append-only logging of privileged actions."""
from __future__ import annotations

from sqlalchemy.orm import Session

from synapseos.db.models import AuditLog


def record_action(db: Session, actor: str, action: str,
                  target: str | int = "", details: dict | None = None) -> None:
    """Record a privileged action. Call before the surrounding code commits."""
    db.add(AuditLog(actor=(actor or "unknown")[:120], action=action[:60],
                    target=str(target)[:250], details=details or {}))
    db.commit()  # audit rows must survive even if the caller never commits
