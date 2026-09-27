"""Meta endpoints: health, config snapshot, landing."""
from __future__ import annotations

from fastapi import APIRouter, Request

from synapseos.core.config import get_settings

router = APIRouter(tags=["meta"])


@router.get("/health", summary="Liveness + storage health")
def health(request: Request):
    engine = request.app.state.engine
    return {
        "status": "ok",
        "version": "0.1.0",
        "model": engine.llm.name,
        "model_provider": engine.llm.provider if hasattr(engine.llm, "provider") else "local",
        "vector_collections": engine.store.stats(),
    }


@router.get("/meta/config", summary="Sanitized configuration snapshot")
def config():
    return get_settings().safe_summary()
