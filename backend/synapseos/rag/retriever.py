"""Adaptive retrieval (RAG).

Every retrieval pulls from four growing sources:
  1. document chunks (the ingested corpus),
  2. approved learned facts (human-approved knowledge),
  3. long-term memories (user-scoped + global),
  4. high-reward past interactions (reinforcement exemplars).

The vector store grows with every document, memory, fact and interaction, so
answer quality compounds over time without retraining.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from synapseos.db.models import LearnedFact
from synapseos.memory.long_term import LongTermMemory
from synapseos.vectors.lite_store import VectorStore

KB_COLLECTION = "kb"
INTERACTIONS_COLLECTION = "interactions"


@dataclass
class RetrievalResult:
    docs: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    memories: list[dict] = field(default_factory=list)
    exemplars: list[dict] = field(default_factory=list)

    @property
    def top_scores(self) -> list[float]:
        return [d["score"] for d in self.docs]

    def all_sources(self) -> list[dict]:
        out = []
        for d in self.docs:
            out.append({"type": "document", "ref": d.get("doc_id"), "id": d["id"],
                        "title": d.get("title", ""), "text": d.get("text", ""),
                        "score": d["score"], "modality": d.get("modality", "text")})
        for f in self.facts:
            out.append({"type": "fact", "ref": f.get("fact_id"), "id": f["id"],
                        "title": "Learned fact", "text": f.get("text", ""), "score": f["score"]})
        for m in self.memories:
            out.append({"type": "memory", "ref": m.get("id"), "id": f"mem-{m.get('id')}",
                        "title": f"{m.get('scope')} memory ({m.get('kind')})",
                        "text": m.get("text", ""), "score": m.get("score", 0.0)})
        return out


class Retriever:
    def __init__(self, store: VectorStore, long_term: LongTermMemory,
                 exemplar_min_reward: float = 0.5, top_k: int = 5, memory_k: int = 4):
        self.store = store
        self.long_term = long_term
        self.exemplar_min_reward = exemplar_min_reward
        self.top_k = top_k
        self.memory_k = memory_k

    def retrieve(self, db: Session, query_vec, user_id: int | None,
                 topic: str = "general") -> RetrievalResult:
        res = RetrievalResult()

        kb_hits = self.store.search(KB_COLLECTION, query_vec, top_k=self.top_k * 3)
        for h in kb_hits:
            m = h["meta"]
            if m.get("kind") == "doc_chunk":
                res.docs.append({"id": h["id"], "doc_id": m.get("doc_id"),
                                 "title": m.get("title", ""), "text": m.get("text", ""),
                                 "modality": m.get("modality", "text"),
                                 "score": round(h["score"], 4)})
            elif m.get("kind") == "fact":
                res.facts.append({"id": h["id"], "fact_id": m.get("fact_id"),
                                  "text": m.get("text", ""), "score": round(h["score"], 4)})
            if len(res.docs) >= self.top_k and len(res.facts) >= 3:
                break
        res.docs = res.docs[: self.top_k]
        res.facts = res.facts[:3]

        # user affinity boost: re-rank docs whose topic matches the user's liked topics
        res.memories = self.long_term.recall(query_vec, user_id, k=self.memory_k)

        # reinforcement exemplars — past high-reward answers to similar questions
        inter_hits = self.store.search(INTERACTIONS_COLLECTION, query_vec, top_k=16)
        exemplars = []
        for h in inter_hits:
            m = h["meta"]
            if m.get("kind") != "chat":
                continue
            if m.get("reward", 0) < self.exemplar_min_reward:
                continue
            same_user = m.get("user_id") == user_id
            exemplars.append({"question": m.get("question", ""), "answer": m.get("answer", ""),
                              "reward": m.get("reward", 0), "same_user": same_user,
                              "score": round(h["score"], 4),
                              "interaction_id": m.get("interaction_id")})
        exemplars.sort(key=lambda e: (e["same_user"], e["reward"] * 0.5 + e["score"]))
        res.exemplars = exemplars[-3:][::-1]
        return res
