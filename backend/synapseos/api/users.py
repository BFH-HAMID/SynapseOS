"""User & personalization-profile endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from synapseos.api.deps import get_db, get_engine, require_api_key
from synapseos.db.models import Interaction, Memory, User
from synapseos.engine import SynapseEngine
from synapseos.learning.personalization import Personalization
from synapseos.schemas import UserIn

router = APIRouter(tags=["users"], dependencies=[Depends(require_api_key)])


@router.get("/users", summary="List users with learned profiles")
def list_users(db: Session = Depends(get_db)):
    out = []
    for u in db.query(User).order_by(User.id).all():
        p = Personalization.profile_of(u)
        n = db.query(Interaction).filter(Interaction.user_id == u.id).count()
        out.append({"id": u.id, "ext_id": u.ext_id, "name": u.name,
                    "interactions": n, "profile": p,
                    "created_at": u.created_at.isoformat()})
    return out


@router.post("/users", summary="Create/ensure a user")
def create_user(req: UserIn, db: Session = Depends(get_db)):
    user = Personalization.ensure_user(db, req.ext_id, req.name)
    db.commit()
    return {"id": user.id, "ext_id": user.ext_id, "name": user.name,
            "profile": Personalization.profile_of(user)}


@router.get("/users/{ext_id}/profile", summary="Get a user's learned profile")
def get_profile(ext_id: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.ext_id == ext_id).first()
    if not u:
        raise HTTPException(404, "user not found")
    n = db.query(Interaction).filter(Interaction.user_id == u.id).count()
    fb = db.query(Interaction).filter(Interaction.user_id == u.id,
                                      Interaction.reward.isnot(None)).count()
    memories = [{"id": m.id, "kind": m.kind, "text": m.text, "created_at": m.created_at.isoformat()}
                for m in db.query(Memory).filter(Memory.user_id == u.id)
                .order_by(Memory.id.desc()).limit(50).all()]
    return {"id": u.id, "ext_id": u.ext_id, "name": u.name,
            "interactions": n, "with_feedback": fb,
            "profile": Personalization.profile_of(u), "memories": memories}


@router.get("/users/{ext_id}/history", summary="A user's interactions")
def user_history(ext_id: str, limit: int = 50, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.ext_id == ext_id).first()
    if not u:
        raise HTTPException(404, "user not found")
    rows = (db.query(Interaction).filter(Interaction.user_id == u.id)
            .order_by(Interaction.id.desc()).limit(min(limit, 500)).all())
    return [{"id": i.id, "input": i.input_text[:200], "answer": i.output_text[:300],
             "confidence": i.confidence, "reward": i.reward, "topic": i.topic,
             "flagged": i.flagged, "created_at": i.created_at.isoformat()} for i in rows]
