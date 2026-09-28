"""Security endpoints: guard events, admin audit trail, in-app security audit."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from synapseos.api.deps import admin_actor, get_db, get_engine, require_admin, require_api_key
from synapseos.core.config import get_settings
from synapseos.db.models import AuditLog, SecurityEvent
from synapseos.engine import SynapseEngine
from synapseos.security.trail import record_action

router = APIRouter(prefix="/admin/security", tags=["security"],
                   dependencies=[Depends(require_api_key)])


@router.get("/events", summary="Guard events (flagged / blocked inputs)",
            dependencies=[Depends(require_admin)])
def events(limit: int = 100, category: str | None = None,
           db: Session = Depends(get_db)):
    q = db.query(SecurityEvent)
    if category:
        q = q.filter(SecurityEvent.category == category)
    rows = q.order_by(SecurityEvent.id.desc()).limit(min(limit, 500)).all()
    return [{"id": e.id, "category": e.category, "action": e.action,
             "user": e.user_ext, "snippet": e.snippet, "details": e.details,
             "created_at": e.created_at.isoformat()} for e in rows]


@router.get("/stats", summary="Guard event statistics",
            dependencies=[Depends(require_admin)])
def stats(db: Session = Depends(get_db)):
    by_cat = dict(db.query(SecurityEvent.category, func.count(SecurityEvent.id))
                  .group_by(SecurityEvent.category).all())
    by_action = dict(db.query(SecurityEvent.action, func.count(SecurityEvent.id))
                     .group_by(SecurityEvent.action).all())
    total = db.query(func.count(SecurityEvent.id)).scalar() or 0
    return {"total": int(total),
            "by_category": {k: int(v) for k, v in by_cat.items()},
            "by_action": {k: int(v) for k, v in by_action.items()},
            "guard_mode": get_settings().guard_mode}


@router.get("/audit-log", summary="Admin action audit trail",
            dependencies=[Depends(require_admin)])
def audit_log(limit: int = 100, action: str | None = None,
              db: Session = Depends(get_db)):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    rows = q.order_by(AuditLog.id.desc()).limit(min(limit, 500)).all()
    return [{"id": r.id, "actor": r.actor, "action": r.action, "target": r.target,
             "details": r.details, "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/audit", summary="Run the security audit battery against this instance",
             dependencies=[Depends(require_admin)])
def run_audit(request: Request, db: Session = Depends(get_db),
              engine: SynapseEngine = Depends(get_engine),
              actor: str = Depends(admin_actor)):
    """Light in-app audit (skips rate-limit hammering and 8MB payload probes —
    run `synapseos audit` from a terminal for the full battery)."""
    from synapseos.security.audit import run_audit as _run_audit

    settings = get_settings()
    token = getattr(request.app.state, "internal_token", None)
    target = str(request.base_url).rstrip("/")
    report = _run_audit(target, light=True, internal_token=token,
                        out_path=str(settings.data_dir / "audit-report.json"))
    record_action(db, actor, "security.audit_run", target,
                  {"high_count": report.high_count, "light": True})
    db.commit()
    return {
        "target": target,
        "light": True,
        "duration_s": round(report.duration_s, 2),
        "high_count": report.high_count,
        "findings": [f.as_dict() for f in report.findings],
    }
