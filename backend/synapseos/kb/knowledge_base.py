"""Versioned knowledge base with human-in-the-loop fact approval and rollback.

- Documents are chunked + embedded into the vector store on ingest.
- Facts proposed from user corrections land in a *pending* state.
- Approving a fact snapshots the KB (new immutable version) and embeds the fact,
  making it live for retrieval.
- Rollback restores any previous snapshot: facts/docs are reactivated or retired
  and the vector store is re-synced. Bad "learned" updates are undoable.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from synapseos.db.models import Document, KBVersion, LearnedFact, ReviewItem
from synapseos.rag.retriever import KB_COLLECTION
from synapseos.vectors.lite_store import VectorStore

CHUNK_SIZE = 700
CHUNK_OVERLAP = 120


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = re.sub(r"\s+\n", "\n", text.strip())
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(". ", start + size // 2, end)
            if cut == -1:
                cut = text.rfind(" ", start + size // 2, end)
            if cut != -1:
                end = cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


class KnowledgeBase:
    def __init__(self, store: VectorStore, embedder):
        self.store = store
        self.embedder = embedder

    # ── documents ─────────────────────────────────────────────────────────
    def add_document(self, db: Session, title: str, text: str, source: str = "",
                     modality: str = "text", mime: str = "text/plain", meta: dict | None = None,
                     created_by: str = "") -> Document:
        doc = Document(title=title, source=source, modality=modality, mime=mime,
                       content_text=text, meta=meta or {})
        db.add(doc)
        db.flush()
        for i, chunk in enumerate(chunk_text(text)):
            self.store.upsert(KB_COLLECTION, f"doc-{doc.id}-{i}", self.embedder.embed(chunk),
                              {"kind": "doc_chunk", "doc_id": doc.id, "chunk": i,
                               "title": title, "text": chunk, "modality": modality})
        db.commit()
        self._snapshot(db, label=f"document #{doc.id} added: {title}",
                       note=f"added by {created_by or 'api'}")
        return doc

    def deactivate_document(self, db: Session, doc_id: int) -> bool:
        doc = db.get(Document, doc_id)
        if not doc:
            return False
        doc.active = False
        self._remove_doc_vectors(doc_id)
        db.commit()
        self._snapshot(db, label=f"document #{doc_id} deactivated: {doc.title}")
        return True

    def _remove_doc_vectors(self, doc_id: int) -> None:
        mat, rows = self.store._matrix(KB_COLLECTION)  # type: ignore[attr-defined]
        for r in rows or []:
            if r["meta"].get("doc_id") == doc_id:
                self.store.delete(KB_COLLECTION, r["id"])

    # ── learned facts ─────────────────────────────────────────────────────
    def propose_fact(self, db: Session, statement: str, source_interaction_id: int | None = None,
                     evidence: dict | None = None, proposed_by: str = "system") -> LearnedFact:
        fact = LearnedFact(statement=statement.strip(), source_interaction_id=source_interaction_id,
                           evidence=evidence or {}, proposed_by=proposed_by, status="pending")
        db.add(fact)
        db.flush()
        db.add(ReviewItem(kind="fact", ref_id=fact.id,
                          reason="learned fact proposed from feedback",
                          payload={"statement": fact.statement, "evidence": fact.evidence,
                                   "source_interaction_id": source_interaction_id}))
        db.commit()
        return fact

    def decide_fact(self, db: Session, fact_id: int, approve: bool, decided_by: str = "admin") -> LearnedFact | None:
        fact = db.get(LearnedFact, fact_id)
        if not fact:
            return None
        from synapseos.db.models import utcnow

        if approve:
            fact.status = "active"
            fact.version = self._next_version(db)
            self.store.upsert(KB_COLLECTION, f"fact-{fact.id}", self.embedder.embed(fact.statement),
                              {"kind": "fact", "fact_id": fact.id, "text": fact.statement,
                               "version": fact.version})
            label = f"fact #{fact.id} approved → v{fact.version}"
        else:
            fact.status = "rejected"
            self.store.delete(KB_COLLECTION, f"fact-{fact.id}")
            label = f"fact #{fact.id} rejected"
        fact.decided_by = decided_by
        fact.decided_at = utcnow()
        # close the matching review item
        for item in db.query(ReviewItem).filter_by(kind="fact", ref_id=fact.id,
                                                   status="open").all():
            item.status = "resolved"
        db.commit()
        self._snapshot(db, label=label, note=f"decision by {decided_by}")
        return fact

    def _next_version(self, db: Session) -> int:
        row = db.query(KBVersion).order_by(KBVersion.id.desc()).first()
        return (row.id + 1) if row else 1

    # ── snapshots & rollback ──────────────────────────────────────────────
    def _snapshot(self, db: Session, label: str = "", note: str = "", created_by: str = "system") -> KBVersion:
        fact_ids = [f.id for f in db.query(LearnedFact).filter_by(status="active").all()]
        doc_ids = [d.id for d in db.query(Document).filter_by(active=True).all()]
        v = KBVersion(label=label, note=note, created_by=created_by,
                      payload={"fact_ids": fact_ids, "doc_ids": doc_ids})
        db.add(v)
        db.commit()
        return v

    def rollback(self, db: Session, version_id: int, by: str = "admin") -> KBVersion | None:
        target = db.get(KBVersion, version_id)
        if not target:
            return None
        fact_ids = set(target.payload.get("fact_ids", []))
        doc_ids = set(target.payload.get("doc_ids", []))
        for f in db.query(LearnedFact).filter(LearnedFact.status.in_(["active", "retired"])).all():
            should = f.id in fact_ids
            if should and f.status != "active":
                f.status = "active"
                self.store.upsert(KB_COLLECTION, f"fact-{f.id}", self.embedder.embed(f.statement),
                                  {"kind": "fact", "fact_id": f.id, "text": f.statement,
                                   "version": f.version})
            elif not should and f.status == "active":
                f.status = "retired"
                self.store.delete(KB_COLLECTION, f"fact-{f.id}")
        for d in db.query(Document).all():
            should = d.id in doc_ids
            if should and not d.active:
                d.active = True
                for i, chunk in enumerate(chunk_text(d.content_text)):
                    self.store.upsert(KB_COLLECTION, f"doc-{d.id}-{i}", self.embedder.embed(chunk),
                                      {"kind": "doc_chunk", "doc_id": d.id, "chunk": i,
                                       "title": d.title, "text": chunk, "modality": d.modality})
            elif not should and d.active:
                d.active = False
                self._remove_doc_vectors(d.id)
        db.commit()
        return self._snapshot(db, label=f"rollback to version {version_id}",
                              note=f"rolled back by {by}", created_by=by)

    def resync(self, db: Session) -> int:
        """Rebuild the kb vector collection from relational truth (docs + active facts)."""
        self.store.delete_collection(KB_COLLECTION)
        n = 0
        for d in db.query(Document).filter_by(active=True).all():
            for i, chunk in enumerate(chunk_text(d.content_text)):
                self.store.upsert(KB_COLLECTION, f"doc-{d.id}-{i}", self.embedder.embed(chunk),
                                  {"kind": "doc_chunk", "doc_id": d.id, "chunk": i,
                                   "title": d.title, "text": chunk, "modality": d.modality})
                n += 1
        for f in db.query(LearnedFact).filter_by(status="active").all():
            self.store.upsert(KB_COLLECTION, f"fact-{f.id}", self.embedder.embed(f.statement),
                              {"kind": "fact", "fact_id": f.id, "text": f.statement,
                               "version": f.version})
            n += 1
        return n
