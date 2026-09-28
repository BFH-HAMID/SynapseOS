"""Memory consolidation — the system's "sleep cycle".

Runs periodically (and on demand):
  1. dedupe   — near-duplicate long-term memories (cosine > 0.92, same scope+kind)
                are merged, keeping the more important one
  2. decay    — memory importance decays exponentially with age (corrections
                decay slower); stale low-importance memories are dropped
  3. summarize— users with enough memories get a compact profile summary memory
                (replaces the previous summary)
  4. prune    — the drift-baseline query collection is capped so PSI stays fast
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from synapseos.db.models import Memory, SystemState, User
from synapseos.learning.drift import QUERY_COLLECTION
from synapseos.memory.long_term import LongTermMemory, MEM_COLLECTION
from synapseos.security.trail import record_action

QUERY_CAP = 2000
DEDUPE_COSINE = 0.92
LAST_RUN_KEY = "last_consolidation"


def _age_days(dt: datetime, now: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max((now - dt).total_seconds() / 86400.0, 0.0)


class MemoryConsolidator:
    def __init__(self, store, embedder):
        self.store = store
        self.long_term = LongTermMemory(store, embedder)

    def consolidate(self, db: Session, actor: str = "system") -> dict:
        now = datetime.now(timezone.utc)
        report = {"inspected": 0, "deduped": 0, "decayed": 0, "dropped": 0,
                  "summaries": 0, "queries_pruned": 0}

        memories = db.query(Memory).all()
        report["inspected"] = len(memories)

        # ── 1. dedupe near-duplicates ────────────────────────────────────
        mat, rows = self.store._matrix(MEM_COLLECTION)  # type: ignore[attr-defined]
        groups: dict[tuple, list[dict]] = {}
        for r in rows or []:
            m = r["meta"]
            groups.setdefault((m.get("user_id"), m.get("kind")), []).append(r)
        for (_uid, kind), grp in groups.items():
            if len(grp) < 2 or kind == "summary":
                continue
            removed: set[str] = set()
            for i in range(len(grp)):
                if grp[i]["id"] in removed:
                    continue
                for j in range(i + 1, len(grp)):
                    if grp[j]["id"] in removed:
                        continue
                    cos = float(np.dot(grp[i]["vector"], grp[j]["vector"]))
                    if cos > DEDUPE_COSINE:
                        keep_i = (grp[i]["meta"].get("importance", 1.0)
                                  >= grp[j]["meta"].get("importance", 1.0))
                        victim = grp[j] if keep_i else grp[i]
                        removed.add(victim["id"])
                        mid = victim["meta"].get("memory_id")
                        if mid:
                            row = db.get(Memory, mid)
                            if row:
                                db.delete(row)
                        self.store.delete(MEM_COLLECTION, victim["id"])
                        report["deduped"] += 1

        # ── 2. importance decay ──────────────────────────────────────────
        for mem in db.query(Memory).all():
            age = _age_days(mem.created_at, now)
            half_life = 60.0 if mem.kind == "correction" else 30.0
            new_imp = round(mem.importance * math.exp(-age * math.log(2) / half_life), 4)
            if new_imp < 0.25 and age > 14:
                db.delete(mem)
                self.store.delete(MEM_COLLECTION, f"mem-{mem.id}")
                report["dropped"] += 1
            elif abs(new_imp - mem.importance) > 1e-4:
                mem.importance = new_imp
                self.store.update_meta(MEM_COLLECTION, f"mem-{mem.id}", importance=new_imp)
                report["decayed"] += 1

        # ── 3. per-user summary memories ─────────────────────────────────
        for user in db.query(User).all():
            n = db.query(Memory).filter(Memory.user_id == user.id).count()
            if n < 5:
                continue
            for s in (db.query(Memory)
                      .filter(Memory.user_id == user.id, Memory.kind == "summary").all()):
                db.delete(s)
                self.store.delete(MEM_COLLECTION, f"mem-{s.id}")
            p = user.profile or {}
            liked = ", ".join(sorted((p.get("liked_topics") or {}).keys())) or "none yet"
            text = (f"User summary: {user.name} ({user.ext_id}) — {n} long-term memories, "
                    f"{p.get('feedback_count', 0)} feedback events, "
                    f"{p.get('corrections_received', 0)} corrections received; "
                    f"liked topics: {liked}; verbosity preference {p.get('verbosity_pref', 1.0)}.")
            self.long_term.remember(db, text, kind="summary", user_id=user.id, importance=1.2)
            report["summaries"] += 1

        # ── 4. cap the drift-baseline query collection ───────────────────
        mat, rows = self.store._matrix(QUERY_COLLECTION)  # type: ignore[attr-defined]
        if rows and len(rows) > QUERY_CAP:
            for r in sorted(rows, key=lambda r: float(r["meta"].get("ts", 0)))[:-QUERY_CAP]:
                self.store.delete(QUERY_COLLECTION, r["id"])
                report["queries_pruned"] += 1

        record_action(db, actor, "memory.consolidate", "memory", dict(report))
        row = db.get(SystemState, LAST_RUN_KEY)
        payload = {"ts": now.isoformat(), "report": report}
        if row:
            row.value = payload
        else:
            db.add(SystemState(key=LAST_RUN_KEY, value=payload))
        db.commit()
        return report

    def stats(self, db: Session) -> dict:
        by_kind: dict[str, int] = {}
        for m in db.query(Memory).all():
            by_kind[m.kind] = by_kind.get(m.kind, 0) + 1
        row = db.get(SystemState, LAST_RUN_KEY)
        last = dict(row.value) if row else None
        return {"total": sum(by_kind.values()), "by_kind": by_kind,
                "last_consolidation": last}
