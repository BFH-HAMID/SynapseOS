"""Unified multi-modal embedding pipeline.

Every input — text, image or voice — becomes an `EmbeddedItem` with:
  - a text-space vector (derived caption drives cross-modal retrieval), and
  - optional native modality features (pixel grid / spectral bands) + metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from synapseos.core.config import Settings
from synapseos.embeddings.media import (audio_caption, audio_fingerprint,
                                        image_caption, image_pixel_vector)
from synapseos.embeddings.text_embedder import HashingTextEmbedder, build_text_embedder


@dataclass
class EmbeddedItem:
    modality: str                 # text | image | audio
    text_repr: str                # unified textual representation
    vector: np.ndarray            # text-space vector (cross-modal)
    meta: dict = field(default_factory=dict)
    native_vector: np.ndarray | None = None   # modality-native features (pixel/spectral)


class UnifiedEmbedder:
    def __init__(self, settings: Settings, text_embedder=None):
        self.settings = settings
        self.text = text_embedder or build_text_embedder(settings)
        self._hasher = self.text if isinstance(self.text, HashingTextEmbedder) else HashingTextEmbedder(384)

    @property
    def dim(self) -> int:
        return getattr(self.text, "dim", 384)

    def embed_text(self, text: str) -> EmbeddedItem:
        return EmbeddedItem(modality="text", text_repr=text, vector=self.text.embed(text))

    def embed_image(self, data: bytes, filename: str = "", caption_hint: str = "") -> EmbeddedItem:
        caption, meta = image_caption(data, filename)
        if caption_hint:
            caption = f"{caption_hint} ({caption})"
            meta["caption_hint"] = caption_hint
        return EmbeddedItem(
            modality="image",
            text_repr=caption,
            vector=self.text.embed(caption),
            meta=meta,
            native_vector=image_pixel_vector(data),
        )

    def embed_audio(self, data: bytes, filename: str = "", transcript: str = "") -> EmbeddedItem:
        caption, meta = audio_caption(data, filename, transcript)
        return EmbeddedItem(
            modality="audio",
            text_repr=caption,
            vector=self.text.embed(caption),
            meta=meta,
            native_vector=audio_fingerprint(data),
        )

    def embed_any(self, modality: str, *, text: str = "", data: bytes | None = None,
                  filename: str = "", caption_hint: str = "", transcript: str = "") -> EmbeddedItem:
        if modality == "image" and data:
            return self.embed_image(data, filename, caption_hint)
        if modality == "audio" and data:
            return self.embed_audio(data, filename, transcript)
        return self.embed_text(text or caption_hint)
