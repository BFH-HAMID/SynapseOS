"""Central configuration, loaded from environment variables (prefix: SYNAPSE_)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/synapseos/core/config.py -> repo root
BACKEND_ROOT = REPO_ROOT / "backend"


def _env(key: str, default: str | None = None) -> str | None:
    v = os.environ.get(key)
    if v is None or v.strip() == "":
        return default
    return v.strip()


def _bool_env(key: str, default: bool) -> bool:
    v = _env(key)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


def _int_env(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _float_env(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # storage
    data_dir: Path = field(default_factory=lambda: BACKEND_ROOT / "data")
    db_url: str = ""
    vector_backend: str = "lite"
    vector_path: Path = None  # type: ignore[assignment]
    qdrant_url: str = "http://localhost:6333"
    redis_url: str | None = None

    # model layer
    model_provider: str = "local"          # local | openai | anthropic | openai_compatible
    model_name: str = "synapse-local-synth-1"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_timeout: float = 60.0
    embed_provider: str = "local"          # local | openai
    embed_dim: int = 384

    # security
    admin_key: str | None = None
    api_keys: list[str] = field(default_factory=list)
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    rate_limit_capacity: int = 240
    rate_limit_refill: float = 4.0
    max_body_bytes: int = 8 * 1024 * 1024
    docs_enabled: bool = True
    guard_mode: str = "monitor"          # off | monitor | strict
    public_url: str = "http://127.0.0.1:8000"

    # learning engine knobs
    session_ttl_s: int = 6 * 3600
    review_confidence_threshold: float = 0.45
    exemplar_min_reward: float = 0.5
    retrieval_top_k: int = 5
    memory_top_k: int = 4
    drift_psi_threshold: float = 0.25
    drift_reward_drop: float = 0.15
    drift_check_interval_s: int = 60

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(_env("SYNAPSE_DATA_DIR", str(BACKEND_ROOT / "data"))).expanduser()
        if not data_dir.is_absolute():
            data_dir = (Path.cwd() / data_dir).resolve()
        db_url = _env("SYNAPSE_DB_URL", f"sqlite:///{data_dir / 'synapseos.db'}")
        api_keys = [k.strip() for k in (_env("SYNAPSE_API_KEYS") or "").split(",") if k.strip()]
        cors = [o.strip() for o in (_env("SYNAPSE_CORS_ORIGINS", "*") or "").split(",") if o.strip()]
        return cls(
            data_dir=data_dir,
            db_url=db_url,
            vector_backend=(_env("SYNAPSE_VECTOR_BACKEND", "lite") or "lite").lower(),
            vector_path=data_dir / "vectors.db",
            qdrant_url=_env("SYNAPSE_QDRANT_URL", "http://localhost:6333"),
            redis_url=_env("SYNAPSE_REDIS_URL"),
            model_provider=(_env("SYNAPSE_MODEL_PROVIDER", "local") or "local").lower(),
            model_name=_env("SYNAPSE_MODEL_NAME", "") or "",
            llm_base_url=_env("SYNAPSE_LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_api_key=_env("SYNAPSE_LLM_API_KEY") or _env("OPENAI_API_KEY") or _env("ANTHROPIC_API_KEY"),
            llm_timeout=_float_env("SYNAPSE_LLM_TIMEOUT", 60.0),
            embed_provider=(_env("SYNAPSE_EMBED_PROVIDER", "local") or "local").lower(),
            admin_key=_env("SYNAPSE_ADMIN_KEY"),
            api_keys=api_keys,
            cors_origins=cors,
            rate_limit_capacity=_int_env("SYNAPSE_RATE_LIMIT_CAPACITY", 240),
            rate_limit_refill=_float_env("SYNAPSE_RATE_LIMIT_REFILL", 4.0),
            max_body_bytes=_int_env("SYNAPSE_MAX_BODY_MB", 8) * 1024 * 1024,
            docs_enabled=_bool_env("SYNAPSE_DOCS", True),
            guard_mode=(_env("SYNAPSE_GUARD_MODE", "monitor") or "monitor").lower(),
            public_url=_env("SYNAPSE_PUBLIC_URL", "http://127.0.0.1:8000"),
            session_ttl_s=_int_env("SYNAPSE_SESSION_TTL_S", 6 * 3600),
            review_confidence_threshold=_float_env("SYNAPSE_REVIEW_CONFIDENCE", 0.45),
            exemplar_min_reward=_float_env("SYNAPSE_EXEMPLAR_MIN_REWARD", 0.5),
            retrieval_top_k=_int_env("SYNAPSE_RETRIEVAL_TOP_K", 5),
            memory_top_k=_int_env("SYNAPSE_MEMORY_TOP_K", 4),
            drift_psi_threshold=_float_env("SYNAPSE_DRIFT_PSI_THRESHOLD", 0.25),
            drift_reward_drop=_float_env("SYNAPSE_DRIFT_REWARD_DROP", 0.15),
            drift_check_interval_s=_int_env("SYNAPSE_DRIFT_CHECK_INTERVAL_S", 60),
        )

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)

    @property
    def admin_auth_enabled(self) -> bool:
        return bool(self.admin_key)

    def safe_summary(self) -> dict:
        """Config snapshot safe to expose via /meta/config (no secrets)."""
        return {
            "version": "0.1.0",
            "db_url_kind": self.db_url.split("://", 1)[0],
            "vector_backend": self.vector_backend,
            "redis_enabled": bool(self.redis_url),
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "embed_provider": self.embed_provider,
            "embed_dim": self.embed_dim,
            "auth_enabled": self.auth_enabled,
            "admin_auth_enabled": self.admin_auth_enabled,
            "cors_origins": self.cors_origins,
            "rate_limit": {"capacity": self.rate_limit_capacity, "refill_per_s": self.rate_limit_refill},
            "max_body_mb": self.max_body_bytes // (1024 * 1024),
            "docs_enabled": self.docs_enabled,
            "guard_mode": self.guard_mode,
            "review_confidence_threshold": self.review_confidence_threshold,
        }


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
