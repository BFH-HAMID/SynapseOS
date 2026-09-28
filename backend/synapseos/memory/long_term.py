"""Long-term memory: persistent, embedding-indexed, user-scoped or global."""
from __future__ import annotations

from sqlalchemy.orm import Session

from synapseos.db.models import Memory
from synapseos.vectors.lite_store import VectorStore

MEM_COLLECTION = "memory"


class LongTermMemory:
    def __init__(self, store: VectorStore, embedder):
        self.store = store
        self.embedder = embedder

    def remember(self, db: Session, text: str, kind: str = "fact", user_id: int | None = None,
                 importance: float = 1.0, source_interaction_id: int | None = None):
        row = Memory(kind=kind, text=text, user_id=user_id, importance=importance,
                     source_interaction_id=source_interaction_id)
        db.add(row)
        db.flush()
        self.store.upsert(
            MEM_COLLECTION, f"mem-{row.id}", self.embedder.embed(text),
            {"kind": kind, "user_id": user_id, "text": text,
             "importance": importance, "memory_id": row.id},
        )
        return row

    def recall(self, query_vec, user_id: int | None, k: int = 4) -> list[dict]:
        """User-scoped memories first, global memories as fallback — both scored."""
        hits = self.store.search(MEM_COLLECTION, query_vec, top_k=max(k * 4, 12))
        mine = [h for h in hits if h["meta"].get("user_id") == user_id]
        glob = [h for h in hits if h["meta"].get("user_id") is None]
        out: list[dict] = []
        for h in mine + glob:
            if h not in out:
                out.append(h)
        return [
            {"id": h["meta"].get("memory_id"), "kind": h["meta"].get("kind"),
             "text": h["meta"].get("text", ""), "score": round(h["score"], 4),
             "scope": "user" if h["meta"].get("user_id") is not None else "global",
             "importance": h["meta"].get("importance", 1.0)}
            for h in out[:k]
        ]

    def list(self, db: Session, user_id: int | None = None, limit: int = 100) -> list[Memory]:
        q = db.query(Memory)
        if user_id is not None:
            q = q.filter(Memory.user_id == user_id)
        return q.order_by(Memory.id.desc()).limit(limit).all()
