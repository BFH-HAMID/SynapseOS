"""Semantic search — pure retrieval over the growing vector store, no generation.

Designed for plugging SynapseOS's knowledge into other apps: search documents,
approved learned facts and (optionally user-scoped) long-term memories.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from synapseos.api.deps import get_db, get_engine, require_api_key
from synapseos.db.models import User
from synapseos.engine import SynapseEngine
from synapseos.rag.retriever import KB_COLLECTION
from synapseos.schemas import SearchRequest

router = APIRouter(tags=["search"], dependencies=[Depends(require_api_key)])


@router.post("/search", summary="Semantic search over documents, facts and memories")
def search(req: SearchRequest, db: Session = Depends(get_db),
           engine: SynapseEngine = Depends(get_engine)):
    if not req.text.strip():
        from fastapi import HTTPException

        raise HTTPException(422, "text required")
    vec = engine.embedder.embed_text(req.text).vector
    results: list[dict] = []

    if "document" in req.kinds or "fact" in req.kinds:
        for h in engine.store.search(KB_COLLECTION, vec, top_k=req.top_k * 4):
            m = h["meta"]
            kind = "fact" if m.get("kind") == "fact" else "document"
            if kind not in req.kinds:
                continue
            results.append({
                "kind": kind,
                "title": m.get("title") if kind == "document" else "Learned fact",
                "text": m.get("text", ""),
                "score": round(h["score"], 4),
                "ref": m.get("doc_id") or m.get("fact_id"),
                "modality": m.get("modality", "text"),
            })

    if "memory" in req.kinds:
        uid = None
        if req.user_id:
            u = db.query(User).filter(User.ext_id == req.user_id).first()
            uid = u.id if u else -1  # unknown user -> global memories only
        for mem in engine.long_term.recall(vec, uid, k=req.top_k):
            results.append({
                "kind": "memory",
                "title": f"{mem['scope']} memory ({mem['kind']})",
                "text": mem["text"],
                "score": mem.get("score", 0.0),
                "ref": mem.get("id"),
                "modality": "text",
            })

    results.sort(key=lambda r: -r["score"])
    return {"query": req.text, "results": results[: req.top_k]}
