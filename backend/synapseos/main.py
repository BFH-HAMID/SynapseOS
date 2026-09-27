"""SynapseOS FastAPI application.

Run:  uvicorn synapseos.main:app --host 0.0.0.0 --port 8000
      (or `synapseos serve`)
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from synapseos import __version__
from synapseos.api import admin as admin_api
from synapseos.api import chat as chat_api
from synapseos.api import documents as docs_api
from synapseos.api import kb as kb_api
from synapseos.api import meta as meta_api
from synapseos.api import users as users_api
from synapseos.core.config import get_settings
from synapseos.core.ratelimit import TokenBucketLimiter
from synapseos.engine import build_engine

log = logging.getLogger("synapseos")

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    engine = build_engine(settings)
    limiter = TokenBucketLimiter(settings.rate_limit_capacity, settings.rate_limit_refill)

    app = FastAPI(
        title="SynapseOS",
        version=__version__,
        description=(
            "Self-learning AI system: continuous feedback loop, short/long-term memory, "
            "adaptive RAG, reinforcement signal, self-evaluation, drift detection, "
            "personalization, explainability, human-in-the-loop approvals, "
            "versioned knowledge base with rollback."
        ),
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
    )
    app.state.engine = engine
    app.state.settings = settings
    app.state.limiter = limiter
    app.state.session_factory = engine.db

    # ── middleware (order matters: outermost runs first) ──────────────────
    @app.middleware("http")
    async def rate_limit_and_security_headers(request: Request, call_next):
        def _secure(resp: JSONResponse) -> JSONResponse:
            resp.headers.setdefault("X-Content-Type-Options", "nosniff")
            resp.headers.setdefault("X-Frame-Options", "DENY")
            resp.headers.setdefault("Referrer-Policy", "no-referrer")
            return resp

        # body size guard
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > settings.max_body_bytes:
            return _secure(JSONResponse({"error": "payload too large"}, status_code=413))
        # rate limit
        key = request.headers.get("x-api-key") or (
            request.headers.get("authorization") or
            (request.client.host if request.client else "anon"))
        allowed, retry = limiter.check(f"{key}")
        if not allowed:
            return _secure(JSONResponse({"error": "rate limit exceeded"},
                                        status_code=429,
                                        headers={"Retry-After": str(int(retry) + 1)}))
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-RateLimit-Limit", str(settings.rate_limit_capacity))
        return response

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": "internal error",
                             "detail": str(exc) if settings.docs_enabled else "see server logs"},
                            status_code=500)

    # ── routers ───────────────────────────────────────────────────────────
    app.include_router(meta_api.router, prefix=API_PREFIX)
    app.include_router(chat_api.router, prefix=API_PREFIX)
    app.include_router(docs_api.router, prefix=API_PREFIX)
    app.include_router(kb_api.router, prefix=API_PREFIX)
    app.include_router(users_api.router, prefix=API_PREFIX)
    app.include_router(admin_api.router, prefix=API_PREFIX)

    @app.get("/", tags=["meta"], include_in_schema=False)
    def landing():
        return {"system": "SynapseOS", "version": __version__,
                "docs": "/docs" if settings.docs_enabled else "disabled",
                "api": f"{API_PREFIX}/health"}

    # ── background drift monitor ──────────────────────────────────────────
    async def drift_loop():
        while True:
            try:
                await asyncio.sleep(settings.drift_check_interval_s)
                db = engine.db()
                try:
                    engine.drift.run_all(db)
                finally:
                    db.close()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                log.exception("drift loop iteration failed")

    @app.on_event("startup")
    async def _start():  # pragma: no cover
        app.state.drift_task = asyncio.create_task(drift_loop())

    @app.on_event("shutdown")
    async def _stop():  # pragma: no cover
        task = getattr(app.state, "drift_task", None)
        if task:
            task.cancel()

    return app


app = create_app()
