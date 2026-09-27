"""Knowledge-base endpoints: learned facts, versions, rollback."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from synapseos.api.deps import get_db, get_engine, require_api_key, require_admin
from synapseos.db.models import KBVersion, LearnedFact
from synapseos.engine import SynapseEngine
from synapseos.schemas import FactIn

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


@router.get("/facts", summary="List learned facts", dependencies=[Depends(require_api_key)])
def list_facts(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(LearnedFact)
    if status:
        q = q.filter(LearnedFact.status == status)
    facts = q.order_by(LearnedFact.id.desc()).limit(500).all()
    return [{
        "id": f.id, "statement": f.statement, "status": f.status, "version": f.version,
        "evidence": f.evidence, "proposed_by": f.proposed_by, "decided_by": f.decided_by,
        "decided_at": f.decided_at.isoformat() if f.decided_at else None,
        "source_interaction_id": f.source_interaction_id,
        "created_at": f.created_at.isoformat(),
    } for f in facts]


@router.post("/facts", summary="Propose a learned fact (or make it live with auto_active, admin)")
def propose_fact(req: FactIn, db: Session = Depends(get_db),
                 engine: SynapseEngine = Depends(get_engine)):
    if not req.statement.strip():
        raise HTTPException(422, "statement required")
    fact = engine.kb.propose_fact(db, req.statement, req.source_interaction_id,
                                  req.evidence, proposed_by="api")
    if req.auto_active:
        engine.kb.decide_fact(db, fact.id, approve=True, decided_by="api-admin")
        fact = db.get(LearnedFact, fact.id)
    return {"id": fact.id, "status": fact.status, "statement": fact.statement,
            "note": None if req.auto_active else
            "pending — approve via POST /kb/facts/{id}/approve"}


@router.post("/facts/{fact_id}/approve", summary="Approve a learned fact (goes live)",
             dependencies=[Depends(require_admin)])
def approve_fact(fact_id: int, db: Session = Depends(get_db),
                 engine: SynapseEngine = Depends(get_engine)):
    fact = engine.kb.decide_fact(db, fact_id, approve=True)
    if not fact:
        raise HTTPException(404, "not found")
    return {"id": fact.id, "status": fact.status, "version": fact.version}


@router.post("/facts/{fact_id}/reject", summary="Reject a learned fact",
             dependencies=[Depends(require_admin)])
def reject_fact(fact_id: int, db: Session = Depends(get_db),
                engine: SynapseEngine = Depends(get_engine)):
    fact = engine.kb.decide_fact(db, fact_id, approve=False)
    if not fact:
        raise HTTPException(404, "not found")
    return {"id": fact.id, "status": fact.status}


@router.get("/versions", summary="Knowledge-base version history",
            dependencies=[Depends(require_api_key)])
def versions(db: Session = Depends(get_db)):
    vs = db.query(KBVersion).order_by(KBVersion.id.desc()).limit(100).all()
    return [{"id": v.id, "label": v.label, "note": v.note, "created_by": v.created_by,
             "facts": len(v.payload.get("fact_ids", [])),
             "documents": len(v.payload.get("doc_ids", [])),
             "created_at": v.created_at.isoformat()} for v in vs]


@router.post("/versions/{version_id}/rollback", summary="Roll back the KB to a version",
             dependencies=[Depends(require_admin)])
def rollback(version_id: int, db: Session = Depends(get_db),
             engine: SynapseEngine = Depends(get_engine)):
    v = engine.kb.rollback(db, version_id)
    if not v:
        raise HTTPException(404, "version not found")
    return {"rolled_back_to": version_id, "new_version": v.id, "label": v.label}


@router.post("/resync", summary="Rebuild KB vectors from relational truth",
             dependencies=[Depends(require_admin)])
def resync(db: Session = Depends(get_db), engine: SynapseEngine = Depends(get_engine)):
    n = engine.kb.resync(db)
    return {"reindexed": n}
