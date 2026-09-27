"""Anomaly / drift detection.

Three detectors:
  - psi:    population-stability index between the baseline query-embedding
            distribution and the recent window (input drift / new topics).
  - reward: sustained drop in the reward EMA (performance degradation).
  - volume: interaction-volume z-score anomaly (spikes, outages, abuse).

Events land in `drift_events` (+ review queue for critical ones) and power the
dashboard alerts. Checks run on a background timer and on demand via the API.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from synapseos.db.models import DriftEvent, Interaction, ReviewItem, SystemState
from synapseos.vectors.lite_store import LiteVectorStore

QUERY_COLLECTION = "queries"
_DEDUP_HOURS = 6
_RNG = np.random.default_rng(42)
_PROJ_CACHE: dict[int, np.ndarray] = {}


def _projections(dim: int) -> np.ndarray:
    if dim not in _PROJ_CACHE:
        p = _RNG.normal(size=(4, dim))
        _PROJ_CACHE[dim] = p / np.linalg.norm(p, axis=1, keepdims=True)
    return _PROJ_CACHE[dim]


def _psi(a: np.ndarray, b: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index between two 1-D samples."""
    lo = min(a.min(), b.min())
    hi = max(a.max(), b.max())
    if hi - lo < 1e-9:
        return 0.0
    edges = np.linspace(lo, hi, bins + 1)
    pa = np.histogram(a, bins=edges)[0] / max(len(a), 1)
    pb = np.histogram(b, bins=edges)[0] / max(len(b), 1)
    pa = np.clip(pa, 1e-4, None)
    pb = np.clip(pb, 1e-4, None)
    return float(np.sum((pa - pb) * np.log(pa / pb)))


class DriftMonitor:
    def __init__(self, store: LiteVectorStore, psi_threshold: float = 0.25,
                 reward_drop: float = 0.15):
        self.store = store
        self.psi_threshold = psi_threshold
        self.reward_drop = reward_drop

    # ── input distribution drift (PSI on query embeddings) ───────────────
    def check_psi(self, db: Session) -> dict:
        rows = self.store.search(QUERY_COLLECTION, np.zeros(384, dtype=np.float32),
                                 top_k=100000) if False else None
        # direct load (search needs a real query vector; PSI wants the raw set)
        mat, items = self.store._matrix(QUERY_COLLECTION)  # type: ignore[attr-defined]
        if mat.size == 0 or len(items) < 40:
            return {"status": "insufficient_data", "psi": None,
                    "n_queries": 0 if mat.size == 0 else len(items)}
        # newest last (ids are sequential ints); baseline = older half, recent = latest 60
        def _ts(it: dict) -> float:
            return float(it["meta"].get("ts", 0))
        items_sorted = sorted(items, key=_ts)
        vecs = np.vstack([it["vector"] for it in items_sorted])
        split = max(len(vecs) - 60, 1)
        baseline, recent = vecs[: split], vecs[split:]
        if len(baseline) < 15:
            return {"status": "insufficient_data", "psi": None, "n_queries": len(vecs)}
        proj = _projections(vecs.shape[1])
        psis = [_psi(baseline @ proj[d], recent @ proj[d]) for d in range(proj.shape[0])]
        psi = round(float(np.mean(psis)), 4)
        status = "ok" if psi < self.psi_threshold else "drift"
        if status == "drift":
            self._emit(db, "psi", "warning" if psi < self.psi_threshold * 2 else "critical",
                       {"psi": psi, "threshold": self.psi_threshold,
                        "baseline_n": len(baseline), "recent_n": len(recent),
                        "message": "New queries are shifting away from the known "
                                   "distribution — new topics or users arriving."})
        return {"status": status, "psi": psi, "n_queries": len(vecs)}

    # ── reward EMA degradation ───────────────────────────────────────────
    def check_reward(self, db: Session) -> dict:
        row = db.get(SystemState, "reward_emas")
        emas = dict(row.value) if row else {}
        now_ema = emas.get("global")
        if now_ema is None:
            return {"status": "insufficient_data"}
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        week = db.query(Interaction).filter(Interaction.created_at >= cutoff,
                                            Interaction.reward.isnot(None)).all()
        if len(week) < 10:
            return {"status": "insufficient_data", "global_ema": now_ema}
        baseline = sum(i.reward for i in week) / len(week)
        drop = round(baseline - now_ema, 4)
        status = "ok" if drop < self.reward_drop else "degrading"
        if status == "degrading":
            self._emit(db, "reward", "warning" if drop < 2 * self.reward_drop else "critical",
                       {"drop": drop, "baseline_7d": round(baseline, 4),
                        "current_ema": now_ema, "threshold": self.reward_drop,
                        "message": "Feedback reward is trending down — answers degrading."})
        return {"status": status, "drop": drop, "global_ema": now_ema,
                "baseline_7d": round(baseline, 4)}

    # ── volume anomaly ───────────────────────────────────────────────────
    def check_volume(self, db: Session) -> dict:
        now = datetime.now(timezone.utc)
        bucket = func.strftime("%Y-%m-%dT%H:00:00", Interaction.created_at)
        counts = (db.query(bucket, func.count(Interaction.id))
                  .filter(Interaction.created_at >= now - timedelta(hours=48))
                  .group_by(bucket).all())
        buckets = {c: n for c, n in counts}
        series = [buckets.get((now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:00:00"), 0)
                  for h in range(48)]
        recent, rest = series[-3:], series[:-3] or [0]
        mean = sum(rest) / len(rest)
        var = sum((x - mean) ** 2 for x in rest) / len(rest)
        std = math.sqrt(var)
        z = ((sum(recent) / len(recent)) - mean) / std if std > 1e-9 else 0.0
        status = "ok" if abs(z) < 3 else "anomaly"
        if status == "anomaly":
            self._emit(db, "volume", "warning",
                       {"z_score": round(z, 3), "mean_hourly": round(mean, 2),
                        "message": "Interaction volume anomaly (z>=3) — spike or outage."})
        return {"status": status, "z_score": round(z, 3)}

    def run_all(self, db: Session) -> dict:
        return {"psi": self.check_psi(db), "reward": self.check_reward(db),
                "volume": self.check_volume(db)}

    # ── event emission with dedupe ───────────────────────────────────────
    def _emit(self, db: Session, kind: str, severity: str, details: dict) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_DEDUP_HOURS)
        recent = (db.query(DriftEvent)
                  .filter(DriftEvent.kind == kind, DriftEvent.created_at >= cutoff)
                  .first())
        if recent:
            return
        ev = DriftEvent(kind=kind, severity=severity, details=details)
        db.add(ev)
        if severity == "critical":
            db.add(ReviewItem(kind="drift", reason=f"critical {kind} drift",
                              payload=details))
        db.commit()
