"""Image & audio feature extraction for the unified multi-modal pipeline.

Design: every item — text, image or audio — is projected into the SAME text
embedding space via a derived textual representation ("caption"), so cross-modal
retrieval works with any text embedder. In addition, raw modality features
(pixel grid / spectral bands) are stored alongside as native vectors + metadata,
so "search by image" also works. Swap in CLIP/Whisper by implementing the same
two functions.
"""
from __future__ import annotations

import io
import struct
import wave
from pathlib import Path

import numpy as np


# ─────────────────────────────── images ───────────────────────────────────

def image_pixel_vector(data: bytes, dim: int = 384) -> np.ndarray:
    """Thumbnail grayscale grid -> normalized vector (native image space)."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        g = im.convert("L").resize((24, max(dim // 24, 1)))  # 24 x 16 grid for dim=384
        vec = np.asarray(g, dtype=np.float32).flatten() / 255.0
    vec = vec[:dim]
    n = float(np.linalg.norm(vec))
    return vec / n if n > 0 else vec


def image_caption(data: bytes, filename: str = "") -> tuple[str, dict]:
    """Derive a textual description of an image (drives cross-modal retrieval)."""
    from PIL import Image

    meta: dict = {"filename": Path(filename).name}
    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
        meta.update({"width": w, "height": h, "format": im.format or "?"})
        small = im.convert("RGB").resize((64, 64))
        arr = np.asarray(small)
        q = (arr // 32 * 32).reshape(-1, 3)
        colors, counts = np.unique(q, axis=0, return_counts=True)
        order = np.argsort(-counts)[:3]
        hexes = ["#%02x%02x%02x" % tuple(int(c) for c in colors[i]) for i in order]
        meta["dominant_colors"] = hexes
        meta["brightness"] = "dark" if arr.mean() < 64 else "bright" if arr.mean() > 192 else "medium"
    caption = (
        f"image {filename or 'attachment'} {w}x{h}, "
        f"colors {' '.join(hexes)}, {meta['brightness']}"
    )
    return caption, meta


def math_ceil(x: float) -> int:
    return int(-(-x // 1))


# ─────────────────────────────── audio ────────────────────────────────────

def audio_fingerprint(data: bytes) -> np.ndarray | None:
    """32-band log-energy spectral fingerprint for WAV input (best-effort)."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            frames = w.getnframes()
            width = w.getsampwidth()
            ch = w.getnchannels()
            rate = w.getframerate()
            if frames == 0 or width != 2:
                return None
            raw = w.readframes(min(frames, rate * 30))
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
            if ch > 1:
                samples = samples.reshape(-1, ch).mean(axis=1)
        spec = np.abs(np.fft.rfft(samples[: 1 << 16])) + 1e-6
        bands = np.array_split(spec, 32)
        energy = np.log10(np.array([b.mean() for b in bands]))
        energy -= energy.mean()
        n = float(np.linalg.norm(energy))
        if n > 0:
            energy /= n
        return energy.astype(np.float32)
    except Exception:
        return None


def audio_caption(data: bytes, filename: str = "", transcript: str = "") -> tuple[str, dict]:
    """Derive a textual description of an audio clip. If a transcript is available
    (client-side speech-to-text, Whisper, etc.) it becomes the primary text."""
    meta: dict = {"filename": Path(filename).name, "bytes": len(data)}
    fingerprint = audio_fingerprint(data)
    if fingerprint is not None:
        meta["spectral_bands"] = [round(float(x), 3) for x in fingerprint]
    if transcript:
        meta["transcript"] = transcript
        return f"audio transcript: {transcript}", meta
    return f"audio clip {Path(filename).name}", meta
