"""Self-evaluation module — a second pass before any answer is returned.

The critic scores the draft answer on:
  - grounding: fraction of content words covered by the retrieved sources
  - retrieval confidence: strength of the top retrieval scores
  - citation presence and length/repetition sanity

producing a confidence in [0, 1] and a verdict. Low-confidence answers are
logged to the human review queue (never silently shipped) and feed the drift
monitor as an early-warning signal.
"""
from __future__ import annotations

import re
from collections import Counter

from synapseos.models.local_synth import STOP, words

_HEDGES = re.compile(r"\b(i don't have|i'm not sure|cannot|unknown|flagged)\b", re.I)


class SelfCritic:
    def __init__(self, threshold: float = 0.45):
        self.threshold = threshold

    def critique(self, answer: str, question: str, sources: list[dict],
                 retrieval_scores: list[float]) -> dict:
        answer_words = [w for w in words(answer) if w not in STOP]
        if not answer_words:
            grounding, answer_coverage = 0.0, 0.0
        else:
            src_terms = set()
            for s in sources:
                src_terms |= {w for w in words(s.get("text", "")) if w not in STOP}
            covered = sum(1 for w in answer_words if w in src_terms)
            grounding = covered / len(answer_words)
            q_terms = {w for w in words(question) if w not in STOP}
            answer_terms = set(answer_words)
            answer_coverage = (len(q_terms & answer_terms) / len(q_terms)) if q_terms else 1.0

        retrieval_conf = (sum(retrieval_scores) / len(retrieval_scores)) if retrieval_scores else 0.0
        top_conf = max(retrieval_scores) if retrieval_scores else 0.0
        has_citation = bool(re.search(r"\[\d+\]", answer))
        hedged = bool(_HEDGES.search(answer))
        wc = len(answer_words)
        length_ok = 0.6 if wc < 4 else 1.0 if wc <= 350 else 0.7
        rep = Counter(answer_words)
        repetition = 1.0
        if rep:
            worst = rep.most_common(1)[0][1]
            repetition = max(0.2, 1.0 - max(0, worst - 5) * 0.15)

        confidence = (
            0.40 * grounding
            + 0.25 * min(1.0, retrieval_conf * 1.6)
            + 0.10 * top_conf
            + 0.10 * (1.0 if has_citation else 0.4)
            + 0.05 * length_ok
            + 0.05 * repetition
            + 0.05 * answer_coverage
        )
        if hedged:
            confidence = min(confidence, 0.35)
        confidence = round(min(1.0, max(0.0, confidence)), 4)
        verdict = "ok" if confidence >= self.threshold else "review"

        notes = []
        if grounding < 0.5:
            notes.append("answer poorly grounded in retrieved sources")
        if retrieval_conf < 0.15:
            notes.append("weak retrieval scores")
        if hedged:
            notes.append("model explicitly declined / low knowledge")
        if repetition < 0.8:
            notes.append("repetitive phrasing detected")
        return {
            "confidence": confidence,
            "grounding": round(grounding, 4),
            "retrieval_confidence": round(retrieval_conf, 4),
            "top_source_score": round(top_conf, 4),
            "citations": has_citation,
            "length_penalty": round(1 - length_ok, 4),
            "repetition_penalty": round(1 - repetition, 4),
            "question_coverage": round(answer_coverage, 4),
            "verdict": verdict,
            "notes": notes,
            "threshold": self.threshold,
        }
