"""User-specific personalization profiles.

Each user gets a learned profile: topic affinities (EMA of rewards per topic),
verbosity preference (adjusted when corrections mention length), liked/disliked
topics, and counts. The profile feeds both retrieval weighting and generation
style, so two users can get differently-shaped answers from the same engine.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from synapseos.db.models import Interaction, User

DEFAULT_PROFILE: dict = {
    "verbosity_pref": 1.0,
    "topic_affinity": {},     # topic -> EMA of rewards
    "liked_topics": {},       # topic -> count of positive feedback
    "disliked_topics": {},    # topic -> count of negative feedback
    "feedback_count": 0,
    "corrections_received": 0,
}

SHORTEN = {"shorter", "brief", "concise", "verbose", "terse", "tldr", "tl;dr"}
EXPAND = {"longer", "detailed", "detail", "elaborate", "expand", "thorough", "more"}


class Personalization:
    @staticmethod
    def ensure_user(db: Session, ext_id: str, name: str = "") -> User:
        user = db.query(User).filter(User.ext_id == ext_id).first()
        if not user:
            profile = dict(DEFAULT_PROFILE)
            user = User(ext_id=ext_id, name=name or ext_id, profile=profile)
            db.add(user)
            db.flush()
        elif name and name != user.name:
            user.name = name
        return user

    @staticmethod
    def profile_of(user: User) -> dict:
        p = dict(DEFAULT_PROFILE)
        p.update(user.profile or {})
        return p

    @classmethod
    def update_on_feedback(cls, db: Session, user: User, interaction: Interaction,
                           reward: float, feedback_text: str = "") -> dict:
        p = cls.profile_of(user)
        topic = interaction.topic or "general"
        aff = p["topic_affinity"]
        aff[topic] = round(0.25 * reward + 0.75 * aff.get(topic, 0.0), 4)
        if reward > 0.3:
            p["liked_topics"][topic] = p["liked_topics"].get(topic, 0) + 1
        elif reward < -0.3:
            p["disliked_topics"][topic] = p["disliked_topics"].get(topic, 0) + 1
        toks = set((feedback_text or "").lower().replace(";", " ").split())
        if toks & SHORTEN:
            p["verbosity_pref"] = round(max(0.5, p["verbosity_pref"] - 0.1), 3)
        elif toks & EXPAND:
            p["verbosity_pref"] = round(min(1.8, p["verbosity_pref"] + 0.1), 3)
        p["feedback_count"] += 1
        if abs(reward + 0.6) < 1e-6:  # correction penalty marker
            p["corrections_received"] += 1
        user.profile = p
        db.flush()
        return p
