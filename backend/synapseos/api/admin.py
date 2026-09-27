"""Admin endpoints: metrics, learning curves, drift, human review queue."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from synapseos.api.deps import get_db, get_engine, require_admin, require_api_key
from synapseos.db.models import (Document, DriftEvent, Feedback, Interaction,
                                 LearnedFact, ReviewItem, SystemState, User)
from synapseos.engine import SynapseEngine
from synapseos.schemas import ResolveIn

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_api_key)])


def _days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _state(db: Session, key: str) -> dict:
    row = db.get(SystemState, key)
    return dict(row.value) if row else {}


@router.get("/overview", summary="Dashboard aggregate (auth: admin)",
            dependencies=[Depends(require_admin)])
def overview(db: Session = Depends(get_db), engine: SynapseEngine = Depends(get_engine)):
    n_inter = db.query(func.count(Interaction.id)).scalar() or 0
    n_flagged = db.query(func.count(Interaction.id)).filter(Interaction.flagged).scalar() or 0
    n_feedback = db.query(func.count(Feedback.id)).scalar() or 0
    n_docs = db.query(func.count(Document.id)).filter(Document.active).scalar() or 0
    n_facts_active = db.query(func.count(LearnedFact.id)).filter(
        LearnedFact.status == "active").scalar() or 0
    n_facts_pending = db.query(func.count(LearnedFact.id)).filter(
        LearnedFact.status == "pending").scalar() or 0
    n_open_review = db.query(func.count(ReviewItem.id)).filter(
        ReviewItem.status == "open").scalar() or 0
    n_drift = db.query(func.count(DriftEvent.id)).filter(~DriftEvent.resolved).scalar() or 0
    n_users = db.query(func.count(User.id)).scalar() or 0
    avg_reward = db.query(func.avg(Interaction.reward)).filter(
        Interaction.reward.isnot(None)).scalar()
    avg_conf = db.query(func.avg(Interaction.confidence)).scalar()
    avg_latency = db.query(func.avg(Interaction.latency_ms)).scalar()
    kinds = dict(db.query(Feedback.kind, func.count(Feedback.id)).group_by(Feedback.kind).all())
    return {
        "totals": {
            "interactions": n_inter, "feedback": n_feedback, "users": n_users,
            "documents": n_docs, "facts_active": n_facts_active,
            "facts_pending": n_facts_pending, "flagged": n_flagged,
            "open_reviews": n_open_review, "drift_events": n_drift,
        },
        "averages": {
            "reward": round(float(avg_reward or 0), 4),
            "confidence": round(float(avg_conf or 0), 4),
            "latency_ms": round(float(avg_latency or 0), 1),
        },
        "feedback_by_kind": {k: int(v) for k, v in kinds.items()},
        "reward_model": engine.reward.snapshot(db),
        "vector_store": engine.store.stats(),
        "drift_current": engine.drift.check_psi(db),
    }


@router.get("/metrics/learning-curve", summary="Daily reward / volume / flag curve")
def learning_curve(days: int = 30, db: Session = Depends(get_db)):
    cutoff = _days_ago(days)
    rows = (db.query(
        func.date(Interaction.created_at).label("day"),
        func.count(Interaction.id),
        func.avg(Interaction.reward),
        func.avg(Interaction.confidence),
        func.sum(cast(Interaction.flagged, Integer)),
    ).filter(Interaction.created_at >= cutoff).group_by("day")
      .order_by("day").all())
    series = [{
        "day": str(day), "interactions": int(n),
        "avg_reward": round(float(r), 4) if r is not None else None,
        "avg_confidence": round(float(c), 4) if c is not None else None,
        "flagged": int(f or 0),
    } for day, n, r, c, f in rows]
    return {"series": series}


@router.get("/metrics/feedback", summary="Feedback statistics")
def feedback_metrics(days: int = 30, db: Session = Depends(get_db)):
    cutoff = _days_ago(days)
    rows = (db.query(func.date(Feedback.created_at).label("day"), Feedback.kind,
                     func.count(Feedback.id), func.avg(Feedback.value))
            .filter(Feedback.created_at >= cutoff).group_by("day", Feedback.kind)
            .order_by("day").all())
    by_day: dict[str, dict] = {}
    for day, kind, n, avg in rows:
        by_day.setdefault(str(day), {})[kind] = {"count": int(n),
                                                 "avg_reward": round(float(avg), 4)}
    totals = dict(db.query(Feedback.kind, func.count(Feedback.id)).group_by(Feedback.kind).all())
    return {"by_day": by_day, "totals": {k: int(v) for k, v in totals.items()}}


@router.get("/metrics/topics", summary="Per-topic reward EMAs and volumes")
def topic_metrics(db: Session = Depends(get_db)):
    rows = (db.query(Interaction.topic, func.count(Interaction.id),
                     func.avg(Interaction.reward), func.avg(Interaction.confidence))
            .group_by(Interaction.topic).all())
    emas = _state(db, "reward_emas")
    return {"topics": [
        {"topic": t, "interactions": int(n),
         "avg_reward": round(float(r), 4) if r is not None else None,
         "avg_confidence": round(float(c), 4) if c is not None else None,
         "reward_ema": emas.get(t)} for t, n, r, c in rows]}


@router.get("/interactions", summary="Browse interactions (full explanations)")
def interactions(limit: int = 50, flagged: bool | None = None,
                 user_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Interaction).order_by(Interaction.id.desc())
    if flagged is not None:
        q = q.filter(Interaction.flagged == flagged)
    users = {u.id: u.ext_id for u in db.query(User).all()}
    if user_id:
        u = db.query(User).filter(User.ext_id == user_id).first()
        if not u:
            return []
        q = q.filter(Interaction.user_id == u.id)
    out = []
    for i in q.limit(min(limit, 500)).all():
        out.append({
            "id": i.id, "user": users.get(i.user_id, "?"), "session": i.session_id,
            "input": i.input_text[:300], "answer": i.output_text[:500],
            "confidence": i.confidence, "reward": i.reward, "topic": i.topic,
            "flagged": i.flagged, "model": i.model, "modality": i.modality,
            "critique": i.critique, "explanation": i.explanation,
            "latency_ms": i.latency_ms, "created_at": i.created_at.isoformat(),
        })
    return out


@router.get("/drift/events", summary="Drift / anomaly events")
def drift_events(limit: int = 50, db: Session = Depends(get_db)):
    evs = db.query(DriftEvent).order_by(DriftEvent.id.desc()).limit(limit).all()
    return [{"id": e.id, "kind": e.kind, "severity": e.severity, "details": e.details,
             "resolved": e.resolved, "created_at": e.created_at.isoformat()} for e in evs]


@router.get("/drift/status", summary="Current drift detector state")
def drift_status(db: Session = Depends(get_db), engine: SynapseEngine = Depends(get_engine)):
    return engine.drift.run_all(db)


@router.post("/drift/recompute", summary="Run drift checks now",
             dependencies=[Depends(require_admin)])
def drift_recompute(db: Session = Depends(get_db), engine: SynapseEngine = Depends(get_engine)):
    return engine.drift.run_all(db)


@router.get("/review", summary="Human-review queue (low confidence + proposed facts)")
def review_queue(status: str = "open", kind: str | None = None,
                 db: Session = Depends(get_db)):
    q = db.query(ReviewItem).filter(ReviewItem.status == status)
    if kind:
        q = q.filter(ReviewItem.kind == kind)
    items = q.order_by(ReviewItem.id.desc()).limit(200).all()
    out = []
    for it in items:
        payload = it.payload
        if it.kind == "low_confidence" and it.ref_id:
            inter = db.get(Interaction, it.ref_id)
            if inter:
                payload = {"question": inter.input_text, "answer": inter.output_text,
                           "critique": inter.critique, "explanation": inter.explanation,
                           "interaction_id": inter.id, "topic": inter.topic,
                           "created_at": inter.created_at.isoformat()}
        out.append({"id": it.id, "kind": it.kind, "ref_id": it.ref_id,
                    "reason": it.reason, "payload": payload, "status": it.status,
                    "created_at": it.created_at.isoformat()})
    return out


@router.post("/review/{item_id}/resolve", summary="Resolve a review item",
             dependencies=[Depends(require_admin)])
def resolve_review(item_id: int, req: ResolveIn, db: Session = Depends(get_db)):
    it = db.get(ReviewItem, item_id)
    if not it:
        raise HTTPException(404, "not found")
    it.status = "resolved" if req.decision == "resolved" else "dismissed"
    db.commit()
    return {"id": it.id, "status": it.status}
