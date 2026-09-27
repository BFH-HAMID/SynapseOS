"""SQLAlchemy models — the structured feedback / learning ledger."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ext_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    profile: Mapped[dict] = mapped_column(JSON, default=dict)  # learned personalization profile
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Interaction(Base):
    __tablename__ = "interactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(128), default="default", index=True)
    modality: Mapped[str] = mapped_column(String(16), default="text")  # text|image|voice|multimodal
    input_text: Mapped[str] = mapped_column(Text, default="")
    attachment_meta: Mapped[list] = mapped_column(JSON, default=list)
    output_text: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    critique: Mapped[dict] = mapped_column(JSON, default=dict)     # self-evaluation second pass
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)  # sources, trace, reasoning
    retrieval: Mapped[dict] = mapped_column(JSON, default=dict)    # raw retrieval payload (audit)
    model: Mapped[str] = mapped_column(String(128), default="")
    topic: Mapped[str] = mapped_column(String(64), default="general", index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    reward: Mapped[float | None] = mapped_column(Float, nullable=True)  # set when feedback arrives
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    feedback: Mapped[list["Feedback"]] = relationship(back_populates="interaction")


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    interaction_id: Mapped[int] = mapped_column(ForeignKey("interactions.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # thumb | rating | correction | text
    value: Mapped[float] = mapped_column(Float, default=0.0)  # normalized reward in [-1, 1]
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    correction_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    interaction: Mapped[Interaction] = relationship(back_populates="feedback")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    source: Mapped[str] = mapped_column(String(512), default="")
    modality: Mapped[str] = mapped_column(String(16), default="text")  # text | image | audio
    mime: Mapped[str] = mapped_column(String(128), default="text/plain")
    content_text: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Memory(Base):
    """Long-term memory entries (preferences, facts, corrections, summaries)."""
    __tablename__ = "memories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # None = global
    kind: Mapped[str] = mapped_column(String(32), default="fact")  # fact|preference|correction|summary
    text: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, default=1.0)
    source_interaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class LearnedFact(Base):
    """Facts proposed by the learning loop — human-in-the-loop approval required."""
    __tablename__ = "learned_facts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement: Mapped[str] = mapped_column(Text)
    source_interaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|active|rejected|retired
    version: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    proposed_by: Mapped[str] = mapped_column(String(128), default="system")
    decided_by: Mapped[str] = mapped_column(String(128), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class KBVersion(Base):
    """Immutable snapshots of the active knowledge base — enables rollback."""
    __tablename__ = "kb_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(256), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # {fact_ids: [], doc_ids: []}
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DriftEvent(Base):
    __tablename__ = "drift_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))       # psi | reward | volume
    severity: Mapped[str] = mapped_column(String(16), default="warning")  # info|warning|critical
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ReviewItem(Base):
    """Human-review queue: low-confidence answers + proposed learned facts."""
    __tablename__ = "review_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), default="low_confidence")  # low_confidence|fact|drift
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)       # interaction id / fact id
    reason: Mapped[str] = mapped_column(String(512), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|resolved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SystemState(Base):
    """Key/value store for reward-model EMAs and policy parameters."""
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
