"""SynapseEngine — the continuous learning loop orchestrator.

chat() pipeline (no retraining required):
  1. unify multi-modal input (text/image/voice -> text space + native features)
  2. adaptive retrieval: docs + approved facts + long-term memories + high-reward exemplars
  3. personalization profile + reward-model policy -> generation style bias
  4. generate (remote LLM or local synthesizer, with automatic fallback)
  5. self-evaluation second pass -> confidence, verdict, review-queue flagging
  6. structured logging of the full interaction (input, output, retrieval, critique, trace)
  7. embed the query into the reinforcement index (reward updated on feedback)
  8. drift monitor records the query embedding

feedback() pipeline:
  normalize reward -> update interaction + EMAs + policy + user profile
  -> corrections become long-term memories and propose learned facts (pending review)
  -> exemplar metadata updated so future similar queries retrieve the good examples
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from synapseos.core.config import Settings
from synapseos.db.models import (Feedback, Interaction, ReviewItem, User, utcnow)
from synapseos.embeddings.unified import UnifiedEmbedder
from synapseos.kb.knowledge_base import KnowledgeBase
from synapseos.learning.drift import DriftMonitor, QUERY_COLLECTION
from synapseos.learning.personalization import Personalization
from synapseos.learning.reward import RewardModel
from synapseos.learning.selfeval import SelfCritic
from synapseos.learning.topics import classify
from synapseos.memory.long_term import LongTermMemory
from synapseos.memory.short_term import build_session_cache
from synapseos.models.base import GenRequest
from synapseos.models.local_synth import words, STOP
from synapseos.rag.retriever import INTERACTIONS_COLLECTION, Retriever
from synapseos.vectors.lite_store import VectorStore

REMEMBER_PREFIX = "remember that "
REMEMBER_PREFIX2 = "remember: "


class SynapseEngine:
    def __init__(self, settings: Settings, session_factory, store: VectorStore,
                 embedder: UnifiedEmbedder, llm, retriever: Retriever,
                 long_term: LongTermMemory, kb: KnowledgeBase, reward: RewardModel,
                 critic: SelfCritic, drift: DriftMonitor):
        self.settings = settings
        self.sessions = build_session_cache(settings)
        self.db = session_factory
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.retriever = retriever
        self.long_term = long_term
        self.kb = kb
        self.reward = reward
        self.critic = critic
        self.drift = drift

    # ───────────────────────────── chat ───────────────────────────────────
    def chat(self, user_ext_id: str, session_id: str, text: str,
             attachments: list[dict] | None = None, source: str = "api",
             inject_ts: datetime | None = None) -> dict:
        t0 = time.perf_counter()
        db: Session = self.db()
        try:
            user = Personalization.ensure_user(db, user_ext_id)
            profile = Personalization.profile_of(user)
            attachments = attachments or []
            modality = "text"
            if attachments:
                kinds = {a.get("kind") for a in attachments}
                modality = "multimodal" if "text" in kinds or text else next(iter(kinds), "text")

            # 1) unified embedding of all modalities
            embedded = self.embedder.embed_text(text or "")
            caption_parts = [text or ""]
            att_meta = []
            for a in attachments:
                item = self.embedder.embed_any(
                    a.get("kind", "text"), text=a.get("text", ""),
                    data=a.get("data"), filename=a.get("filename", ""),
                    caption_hint=a.get("caption", ""), transcript=a.get("transcript", ""))
                caption_parts.append(item.text_repr)
                m = dict(item.meta)
                m["kind"] = a.get("kind", "text")
                att_meta.append(m)
                if item.native_vector is not None:
                    self.store.upsert("media", f"att-{user.id}-{int(time.time()*1000)}",
                                      item.native_vector, {"modality": item.modality,
                                                          "text_repr": item.text_repr[:200]})
            effective_query = " ".join(p for p in caption_parts if p).strip()

            # 2) adaptive retrieval
            topic = classify(effective_query)
            retrieval = self.retriever.retrieve(db, embedded.vector, user.id, topic)

            # 3) policy: reward-model bias + personalization
            bias = self.reward.bias(db, profile, topic)
            style = {"verbosity": bias["verbosity"], "citation_density": bias["citation_density"]}

            # explicit memory instructions ("remember that X")
            if text.lower().startswith((REMEMBER_PREFIX, REMEMBER_PREFIX2)):
                fact_text = text.split(":", 1)[-1].strip() if ":" in text[:12] else text
                fact_text = fact_text.removeprefix("that").strip()
                self.long_term.remember(db, fact_text, kind="preference", user_id=user.id,
                                        importance=1.5)

            # 4) generation
            req = GenRequest(
                system=("You are SynapseOS, a self-learning assistant. Ground every claim "
                        "in the CONTEXT and cite sources as [n]. Use APPROVED FACTS and "
                        "MEMORIES when relevant. Match the STYLE DIRECTIVES."),
                question=effective_query,
                facts=[f["text"] for f in retrieval.facts],
                context=[{"id": i + 1, "title": d["title"], "text": d["text"],
                          "kind": "document", "score": d["score"]} for i, d in enumerate(retrieval.docs)],
                memories=retrieval.memories,
                exemplars=[{"question": e["question"], "answer": e["answer"]} for e in retrieval.exemplars],
                session_history=self.sessions.history(f"s{user.id}:{session_id}"),
                style=style,
            )
            gen = self.llm.generate(req)

            # 5) self-evaluation second pass
            sources = retrieval.all_sources()
            critique = self.critic.critique(gen.text, effective_query, sources,
                                            retrieval.top_scores)
            flagged = critique["verdict"] == "review"

            # 6) structured logging (the feedback-ingestion ledger row)
            trace = self._build_trace(effective_query, topic, retrieval, style, bias, gen, critique)
            explanation = {
                "confidence": critique["confidence"],
                "verdict": critique["verdict"],
                "sources": [{"type": s["type"], "title": s["title"], "ref": s["ref"],
                             "snippet": s["text"][:240], "score": s["score"]} for s in sources[:8]],
                "trace": trace,
            }
            latency_ms = int((time.perf_counter() - t0) * 1000)
            inter = Interaction(
                user_id=user.id, session_id=session_id, modality=modality,
                input_text=text or "", attachment_meta=att_meta, output_text=gen.text,
                confidence=critique["confidence"], critique=critique, explanation=explanation,
                retrieval={"docs": retrieval.docs, "facts": retrieval.facts,
                           "memories": retrieval.memories,
                           "exemplars": [{k: v for k, v in e.items() if k != "answer"}
                                         for e in retrieval.exemplars]},
                model=gen.model, topic=topic, latency_ms=latency_ms, flagged=flagged,
                created_at=inject_ts or utcnow(),
            )
            db.add(inter)
            db.flush()  # assigns inter.id
            if flagged:
                db.add(ReviewItem(kind="low_confidence", ref_id=inter.id,
                                  reason=f"confidence {critique['confidence']} below threshold",
                                  payload={"question": text, "answer": gen.text,
                                           "critique": critique}))
            db.commit()

            # 7) reinforcement index: embed query for exemplar retrieval
            self.store.upsert(
                INTERACTIONS_COLLECTION, f"chat-{inter.id}", embedded.vector,
                {"kind": "chat", "interaction_id": inter.id, "user_id": user.id,
                 "question": effective_query[:400], "answer": gen.text[:600],
                 "reward": 0.0, "topic": topic, "ts": time.time()},
            )
            # 8) drift monitor records the query distribution
            self.store.upsert(QUERY_COLLECTION, f"q-{inter.id}", embedded.vector,
                              {"ts": time.time(), "topic": topic})

            # short-term memory
            self.sessions.append(f"s{user.id}:{session_id}",
                                 {"role": "user", "content": text or "[attachment]"})
            self.sessions.append(f"s{user.id}:{session_id}",
                                 {"role": "assistant", "content": gen.text[:600]})

            return self._interaction_payload(db, inter, user, extra={
                "degraded": gen.degraded, "usage": gen.usage,
                "exemplars_used": len(retrieval.exemplars),
            })
        finally:
            db.close()

    # ─────────────────────────── feedback ─────────────────────────────────
    def feedback(self, interaction_id: int, kind: str, value=None, text: str = "",
                 user_ext_id: str | None = None, inject_ts: datetime | None = None) -> dict:
        db: Session = self.db()
        try:
            inter = db.get(Interaction, interaction_id)
            if not inter:
                return {"error": "interaction not found"}
            user = db.get(User, inter.user_id)
            if user_ext_id and user and user.ext_id != user_ext_id and user_ext_id != "admin":
                return {"error": "interaction belongs to another user"}

            fb = Feedback(interaction_id=inter.id, user_id=inter.user_id, kind=kind,
                          value=0.0, raw={"value": value, "text": text},
                          correction_text=text if kind == "correction" else "",
                          created_at=inject_ts or utcnow())
            db.add(fb)
            db.flush()
            reward = self.reward.register(db, inter, kind, value, text or "")

            # personalization
            profile = Personalization.update_on_feedback(db, user, inter, reward, text or "")

            # corrections -> long-term memory + proposed learned fact (pending approval)
            proposed = None
            if kind == "correction" and text.strip():
                self.long_term.remember(db, f"Correction: {text.strip()}",
                                        kind="correction", user_id=user.id,
                                        importance=2.0, source_interaction_id=inter.id)
                proposed = self.kb.propose_fact(
                    db, statement=text.strip(),
                    source_interaction_id=inter.id,
                    evidence={"original_question": inter.input_text,
                              "original_answer": inter.output_text[:400],
                              "user": user.ext_id},
                    proposed_by=f"user:{user.ext_id}")

            # reinforcement index update: reward propagates to the exemplar store
            self.store.update_meta(INTERACTIONS_COLLECTION, f"chat-{inter.id}", reward=reward)
            db.commit()

            result = {
                "interaction_id": inter.id,
                "reward": round(reward, 4),
                "interaction_reward": round(inter.reward or reward, 4),
                "policy": self.reward.snapshot(db)["policy"],
                "profile": profile,
                "memory_updated": kind == "correction",
                "proposed_fact_id": proposed.id if proposed else None,
            }
            if proposed:
                result["note"] = ("Correction stored in long-term memory and proposed as a "
                                  "learned fact — pending admin approval before it goes live.")
            return result
        finally:
            db.close()

    # ─────────────────────────── helpers ──────────────────────────────────
    def _build_trace(self, query: str, topic: str, retrieval, style: dict,
                     bias: dict, gen, critique: dict) -> list[dict]:
        q_terms = [w for w in words(query) if w not in STOP][:12]
        return [
            {"step": "input_analysis",
             "detail": {"topic": topic, "key_terms": q_terms,
                        "modality_count": 1 + len(retrieval.exemplars) * 0}},
            {"step": "retrieval",
             "detail": {"documents": len(retrieval.docs), "facts": len(retrieval.facts),
                        "memories": len(retrieval.memories),
                        "exemplars": len(retrieval.exemplars),
                        "top_scores": retrieval.top_scores[:5]}},
            {"step": "policy_bias",
             "detail": {"style_applied": style, "topic_reward_ema": bias["topic_reward_ema"],
                        "global_reward_ema": bias["global_reward_ema"]}},
            {"step": "generation",
             "detail": {"model": gen.model, "provider": gen.provider,
                        "degraded": gen.degraded, "usage": gen.usage}},
            {"step": "self_evaluation",
             "detail": critique},
        ]

    def _interaction_payload(self, db: Session, inter: Interaction, user: User,
                             extra: dict | None = None) -> dict:
        payload = {
            "interaction_id": inter.id,
            "user": {"id": user.id, "ext_id": user.ext_id, "name": user.name},
            "session_id": inter.session_id,
            "modality": inter.modality,
            "input": inter.input_text,
            "attachments": inter.attachment_meta,
            "answer": inter.output_text,
            "confidence": inter.confidence,
            "verdict": inter.critique.get("verdict"),
            "critique": inter.critique,
            "explanation": inter.explanation,
            "model": inter.model,
            "topic": inter.topic,
            "latency_ms": inter.latency_ms,
            "flagged_for_review": inter.flagged,
            "reward": inter.reward,
            "created_at": inter.created_at.isoformat(),
        }
        if extra:
            payload.update(extra)
        return payload


def build_engine(settings: Settings) -> SynapseEngine:
    """Wire the full dependency graph from settings."""
    from synapseos.db.session import build_engine as _db_engine, init_db, make_session_factory
    from synapseos.embeddings.unified import UnifiedEmbedder as _UE
    from synapseos.kb.knowledge_base import KnowledgeBase as _KB
    from synapseos.learning.drift import DriftMonitor as _DM
    from synapseos.learning.reward import RewardModel as _RM
    from synapseos.learning.selfeval import SelfCritic as _SC
    from synapseos.memory.long_term import LongTermMemory as _LTM
    from synapseos.models.providers import build_llm
    from synapseos.rag.retriever import Retriever as _R
    from synapseos.vectors.lite_store import build_store

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db_engine = _db_engine(settings)
    init_db(db_engine)
    session_factory = make_session_factory(db_engine)

    store = build_store(settings)
    unified = _UE(settings)
    long_term = _LTM(store, unified.text)  # text-space embedder for memories
    llm = build_llm(settings)
    retriever = _R(store, long_term, exemplar_min_reward=settings.exemplar_min_reward,
                   top_k=settings.retrieval_top_k, memory_k=settings.memory_top_k)
    kb = _KB(store, unified.text)  # text-space embedder for KB chunks/facts
    reward = _RM()
    critic = _SC(settings.review_confidence_threshold)
    drift = _DM(store, psi_threshold=settings.drift_psi_threshold,
                reward_drop=settings.drift_reward_drop)
    return SynapseEngine(settings, session_factory, store, unified, llm, retriever,
                         long_term, kb, reward, critic, drift)
