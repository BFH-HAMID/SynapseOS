"""Reward model / reinforcement signal.

Every piece of feedback is normalized to a reward in [-1, +1] and folded into:
  - the interaction record (per-example reward),
  - exponentially-weighted moving averages per topic and globally,
  - policy parameters (verbosity, citation density) that bias future generation,
  - exemplar metadata in the vector store, so high-reward past answers are
    retrieved as style/content guidance for similar future questions.

This is the "improve without full retraining" mechanism: feedback reshapes the
retrieval distribution and generation policy online.
"""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

from synapseos.db.models import Interaction, SystemState

EMA_ALPHA = 0.2
POLICY_KEY = "policy"
REWARD_KEY = "reward_emas"

POSITIVE_WORDS = {"good", "great", "perfect", "excellent", "helpful", "thanks", "thank",
                  "correct", "right", "exactly", "awesome", "nice", "clear"}
NEGATIVE_WORDS = {"bad", "wrong", "terrible", "useless", "incorrect", "nope", "confusing",
                  "unclear", "garbage", "off", "missing", "irrelevant"}
SHORTEN_WORDS = {"shorter", "brief", "concise", "verbose", "terse", "less detail", "tl;dr", "tldr"}
EXPAND_WORDS = {"longer", "detail", "detailed", "more", "elaborate", "expand", "thorough"}


class RewardModel:
    # ── normalization ─────────────────────────────────────────────────────
    @staticmethod
    def normalize(kind: str, value, text: str = "") -> float:
        """Map any feedback kind onto a [-1, +1] reward."""
        if kind == "thumb":
            return 1.0 if str(value).lower() in ("up", "1", "true", "+1") else -1.0
        if kind == "rating":
            try:
                r = float(value)
            except (TypeError, ValueError):
                return 0.0
            return max(-1.0, min(1.0, (r - 3.0) / 2.0))  # 1..5 stars -> [-1, +1]
        if kind == "correction":
            # the previous answer was wrong (negative reward), but the correction
            # itself is valuable signal — handled separately by the memory layer.
            return -0.6
        if kind == "text":
            t = set((text or "").lower().split())
            pos, neg = len(t & POSITIVE_WORDS), len(t & NEGATIVE_WORDS)
            if pos > neg:
                return 0.5
            if neg > pos:
                return -0.5
            return 0.0
        return 0.0

    # ── state helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _get_state(db: Session, key: str) -> dict:
        row = db.get(SystemState, key)
        return dict(row.value) if row else {}

    @staticmethod
    def _set_state(db: Session, key: str, value: dict) -> None:
        row = db.get(SystemState, key)
        if row:
            row.value = value
        else:
            db.add(SystemState(key=key, value=value))

    # ── main hook ─────────────────────────────────────────────────────────
    def register(self, db: Session, interaction: Interaction, kind: str, value,
                 text: str = "") -> float:
        reward = self.normalize(kind, value, text)

        # per-example reward (average of all feedback for this interaction)
        rewards = [f.value for f in interaction.feedback] + [reward]
        interaction.reward = sum(rewards) / len(rewards)

        # EMAs: global + per-topic
        emas = self._get_state(db, REWARD_KEY)
        g = emas.get("global", 0.0)
        emas["global"] = round(EMA_ALPHA * reward + (1 - EMA_ALPHA) * g, 4)
        topic = interaction.topic or "general"
        t = emas.get(topic, 0.0)
        emas[topic] = round(EMA_ALPHA * reward + (1 - EMA_ALPHA) * t, 4)
        self._set_state(db, REWARD_KEY, emas)

        # policy parameters — text heuristics nudge generation style
        policy = self._get_state(db, POLICY_KEY)
        cur = policy.get("verbosity", 1.0)
        joined = " ".join([text or "", ""]).lower()
        if any(w in joined for w in SHORTEN_WORDS):
            policy["verbosity"] = round(max(0.4, cur - 0.1), 3)
        elif any(w in joined for w in EXPAND_WORDS):
            policy["verbosity"] = round(min(2.0, cur + 0.1), 3)
        if kind == "thumb" and reward < 0:
            policy["citation_density"] = round(min(1.5, policy.get("citation_density", 1.0) + 0.1), 3)
        if kind == "correction":
            policy["corrections_seen"] = policy.get("corrections_seen", 0) + 1
        policy["feedback_count"] = policy.get("feedback_count", 0) + 1
        self._set_state(db, POLICY_KEY, policy)
        return reward

    # ── policy consumed at generation time ────────────────────────────────
    def bias(self, db: Session, user_profile: dict, topic: str) -> dict:
        policy = self._get_state(db, POLICY_KEY)
        emas = self._get_state(db, REWARD_KEY)
        verbosity = policy.get("verbosity", 1.0)
        # per-topic reward below zero -> try tighter, more cautious answers
        if emas.get(topic, 0.0) < 0:
            verbosity = max(0.4, verbosity - 0.2)
        # user-level preference overrides (personalization)
        verbosity *= float(user_profile.get("verbosity_pref", 1.0))
        return {
            "verbosity": round(min(2.0, max(0.4, verbosity)), 3),
            "citation_density": policy.get("citation_density", 1.0),
            "topic_reward_ema": emas.get(topic, 0.0),
            "global_reward_ema": emas.get("global", 0.0),
        }

    def snapshot(self, db: Session) -> dict:
        return {"emas": self._get_state(db, REWARD_KEY), "policy": self._get_state(db, POLICY_KEY)}

    @staticmethod
    def sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))
