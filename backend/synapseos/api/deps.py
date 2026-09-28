"""Shared API dependencies: DB session + auth guards."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from synapseos.core.config import get_settings
from synapseos.db.session import make_session_factory
from synapseos.engine import SynapseEngine


def get_engine(request: Request) -> SynapseEngine:
    return request.app.state.engine


def get_db(request: Request):
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def _extract_key(request: Request, x_api_key: str | None, authorization: str | None) -> str | None:
    return x_api_key or (authorization.removeprefix("Bearer ").strip()
                         if authorization else None)


def require_api_key(request: Request,
                    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
                    authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.auth_enabled:
        return  # dev mode: open
    key = _extract_key(request, x_api_key, authorization)
    # the admin key is also a master API key
    if not key or (key not in settings.api_keys and key != settings.admin_key):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def require_admin(request: Request,
                  x_api_key: str | None = Header(default=None, alias="X-API-Key"),
                  authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.admin_auth_enabled:
        return  # dev mode: open — the security audit flags this
    key = _extract_key(request, x_api_key, authorization)
    if not key or key != settings.admin_key:
        raise HTTPException(status_code=403, detail="admin key required")


def admin_actor() -> str:
    """Identity recorded in the audit trail for privileged actions.
    (The key itself is a secret — never logged.)"""
    settings = get_settings()
    return "admin" if settings.admin_auth_enabled else "dev-admin"
