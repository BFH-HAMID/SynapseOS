"""Text embedding.

Two providers:
- HashingTextEmbedder: deterministic, dependency-free hashing embedder (word unigrams
  + char trigrams -> fixed-dim signed feature vector). Runs fully offline; good enough
  for lexical-semantic retrieval and makes the whole learning loop testable anywhere.
- OpenAIEmbedder: real semantic embeddings via the OpenAI embeddings API when a key
  is configured. Falls back to hashing on any error so the system never hard-fails.
"""
from __future__ import annotations

import math
import re
from hashlib import blake2b

import numpy as np

from synapseos.core.config import Settings

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


class HashingTextEmbedder:
    name = "synapse-hash-384"

    def __init__(self, dim: int = 384):
        self.dim = dim

    @staticmethod
    def _hash(token: str) -> int:
        return int.from_bytes(blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        words = _tokens(text)
        if not words:
            return vec
        feats: dict[int, float] = {}
        for w in words:  # word unigrams, weight 1.0
            h = self._hash(w)
            feats[h % self.dim] = feats.get(h % self.dim, 0.0) + (1.0 if (h >> 63) & 1 else -1.0)
        joined = "".join(words)
        for i in range(len(joined) - 2):  # char trigrams, weight 0.35 — tolerates typos/inflection
            t = joined[i : i + 3]
            h = self._hash("g:" + t)
            feats[h % self.dim] = feats.get(h % self.dim, 0.0) + 0.35 * (1.0 if (h >> 63) & 1 else -1.0)
        for idx, v in feats.items():
            if v == 0:  # sign collisions cancel out — nothing to add
                continue
            vec[idx] += math.copysign(1.0 + math.log(abs(v)), v)  # sublinear tf
        n = float(np.linalg.norm(vec))
        if n > 0:
            vec /= n
        return vec


class OpenAIEmbedder:
    name = "text-embedding-3-small"

    def __init__(self, settings: Settings, dim: int = 1536):
        import httpx  # lazy: httpx is a core dep but keeps import graph light

        self._http = httpx
        self.settings = settings
        self.dim = dim
        self._fallback = HashingTextEmbedder(384)
        self._degraded = False

    def embed(self, text: str) -> np.ndarray:
        if not self._degraded:
            try:
                r = self._http.post(
                    f"{self.settings.llm_base_url.rstrip('/')}/embeddings"
                    if self.settings.embed_provider != "openai"
                    else "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    json={"model": self.name, "input": text[:8000]},
                    timeout=30,
                )
                r.raise_for_status()
                data = np.asarray(r.json()["data"][0]["embedding"], dtype=np.float32)
                data /= max(float(np.linalg.norm(data)), 1e-9)
                self.dim = int(data.shape[0])
                return data
            except Exception:
                self._degraded = True  # degrade gracefully to the offline embedder
        return self._fallback.embed(text)


def build_text_embedder(settings: Settings):
    if settings.embed_provider == "openai" and settings.llm_api_key:
        return OpenAIEmbedder(settings)
    return HashingTextEmbedder(settings.embed_dim)
