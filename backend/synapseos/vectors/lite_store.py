"""Vector store abstraction + embedded SQLite/numpy implementation ("LiteStore").

Collections used by SynapseOS:
  kb          — document chunks (kind=doc_chunk) and approved learned facts (kind=fact)
  memory      — long-term memories (user-scoped or global)
  interactions— past queries (kind=chat) with reward metadata -> reinforcement exemplars
  media       — native image/audio feature vectors (search-by-image)
  queries     — rolling query embeddings for drift detection (PSI)
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Protocol

import numpy as np


class VectorStore(Protocol):
    def upsert(self, collection: str, id: str, vector: np.ndarray, meta: dict) -> None: ...
    def delete(self, collection: str, id: str) -> None: ...
    def delete_collection(self, collection: str) -> None: ...
    def search(self, collection: str, query: np.ndarray, top_k: int = 5,
               where: dict | None = None) -> list[dict]: ...
    def count(self, collection: str) -> int: ...
    def stats(self) -> dict: ...


def _match(meta: dict, where: dict | None) -> bool:
    if not where:
        return True
    return all(meta.get(k) == v for k, v in where.items())


class LiteVectorStore:
    """Embedded vector DB: SQLite persistence + brute-force cosine search.

    Exact search, zero external services. Comfortable up to low hundreds of
    thousands of vectors; switch SYNAPSE_VECTOR_BACKEND=qdrant for scale.
    """

    def __init__(self, path: str):
        self.path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS vectors (
                collection TEXT NOT NULL,
                id TEXT NOT NULL,
                dim INTEGER NOT NULL,
                vec BLOB NOT NULL,
                meta TEXT NOT NULL,
                PRIMARY KEY (collection, id)
            )"""
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_vec_col ON vectors(collection)")
        self._conn.commit()
        self._cache: dict[str, tuple[np.ndarray, list[dict]]] = {}

    # ── writes ────────────────────────────────────────────────────────────
    def upsert(self, collection: str, id: str, vector: np.ndarray, meta: dict) -> None:
        v = np.asarray(vector, dtype=np.float32)
        n = float(np.linalg.norm(v))
        if n > 0:
            v = v / n
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO vectors (collection, id, dim, vec, meta) VALUES (?,?,?,?,?)",
                (collection, str(id), int(v.shape[0]), v.tobytes(), json.dumps(meta, default=str)),
            )
            self._conn.commit()
        self._cache.pop(collection, None)

    def update_meta(self, collection: str, id: str, **changes) -> None:
        rows = self._load(collection)
        for r in rows:
            if r["id"] == str(id):
                r["meta"].update(changes)
                with self._lock:
                    self._conn.execute(
                        "UPDATE vectors SET meta=? WHERE collection=? AND id=?",
                        (json.dumps(r["meta"], default=str), collection, str(id)),
                    )
                    self._conn.commit()
                self._cache.pop(collection, None)
                return

    def delete(self, collection: str, id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM vectors WHERE collection=? AND id=?", (collection, str(id)))
            self._conn.commit()
        self._cache.pop(collection, None)

    def delete_collection(self, collection: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM vectors WHERE collection=?", (collection,))
            self._conn.commit()
        self._cache.pop(collection, None)

    def clear(self, collection: str, kind: str | None = None) -> int:
        rows = self._load(collection)
        removed = 0
        for r in rows:
            if kind is None or r["meta"].get("kind") == kind:
                self.delete(collection, r["id"])
                removed += 1
        return removed

    # ── reads ─────────────────────────────────────────────────────────────
    def _load(self, collection: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, dim, vec, meta FROM vectors WHERE collection=?", (collection,)
            ).fetchall()
        out = []
        for rid, dim, blob, meta in rows:
            out.append({
                "id": rid,
                "vector": np.frombuffer(blob, dtype=np.float32),
                "meta": json.loads(meta),
            })
        return out

    def _matrix(self, collection: str):
        cached = self._cache.get(collection)
        if cached is not None:
            return cached
        rows = self._load(collection)
        if not rows:
            return np.zeros((0, 1), dtype=np.float32), []
        mat = np.vstack([r["vector"] for r in rows])
        self._cache[collection] = (mat, rows)
        return mat, rows

    def search(self, collection: str, query: np.ndarray, top_k: int = 5,
               where: dict | None = None, min_score: float | None = None) -> list[dict]:
        q = np.asarray(query, dtype=np.float32)
        n = float(np.linalg.norm(q))
        if n > 0:
            q = q / n
        mat, rows = self._matrix(collection)
        if mat.size == 0 or not rows:
            return []
        scores = mat @ q
        order = np.argsort(-scores)
        results = []
        for i in order[: max(top_k * 4, top_k)]:
            r = rows[int(i)]
            if not _match(r["meta"], where):
                continue
            s = float(scores[int(i)])
            if min_score is not None and s < min_score:
                continue
            results.append({"id": r["id"], "score": s, "meta": r["meta"]})
            if len(results) >= top_k:
                break
        return results

    def count(self, collection: str) -> int:
        with self._lock:
            (n,) = self._conn.execute(
                "SELECT COUNT(*) FROM vectors WHERE collection=?", (collection,)
            ).fetchone()
        return int(n)

    def stats(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT collection, COUNT(*) FROM vectors GROUP BY collection"
            ).fetchall()
        return {c: int(n) for c, n in rows}


class QdrantVectorStore:
    """Qdrant adapter (optional). Same interface; install `qdrant-client` and set
    SYNAPSE_VECTOR_BACKEND=qdrant + SYNAPSE_QDRANT_URL."""

    def __init__(self, url: str):
        from qdrant_client import QdrantClient  # type: ignore

        self.client = QdrantClient(url=url, timeout=10)

    def upsert(self, collection: str, id: str, vector: np.ndarray, meta: dict) -> None:
        from qdrant_client.models import PointStruct  # type: ignore

        self.client.upsert(collection_name=f"synapse_{collection}",
                           points=[PointStruct(id=str(id), vector=vector.tolist(), payload=meta)])

    def delete(self, collection: str, id: str) -> None:
        from qdrant_client.models import PointSelectors  # type: ignore

        self.client.delete(collection_name=f"synapse_{collection}",
                           points_selector=PointSelectors(point_ids=[str(id)]))

    def delete_collection(self, collection: str) -> None:
        self.client.delete_collection(collection_name=f"synapse_{collection}")

    def search(self, collection: str, query: np.ndarray, top_k: int = 5,
               where: dict | None = None) -> list[dict]:
        res = self.client.search(collection_name=f"synapse_{collection}",
                                 query_vector=np.asarray(query).tolist(), limit=top_k,
                                 query_filter=where or None)
        return [{"id": str(h.id), "score": h.score, "meta": h.payload or {}} for h in res]

    def count(self, collection: str) -> int:
        return self.client.count(collection_name=f"synapse_{collection}").count

    def stats(self) -> dict[str, int]:
        return {}


def build_store(settings) -> VectorStore:
    if settings.vector_backend == "qdrant":
        try:
            store = QdrantVectorStore(settings.qdrant_url)
            store.count("kb")
            return store  # type: ignore[return-value]
        except Exception as e:  # noqa: BLE001 — degrade to embedded store
            import logging

            logging.getLogger("synapseos").warning(
                "Qdrant unavailable (%s) — falling back to LiteVectorStore", e)
    return LiteVectorStore(settings.vector_path)
