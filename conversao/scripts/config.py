"""Centralized configuration for DocMind (Stage 1).

Single source of truth for model names, retry policy, API key health thresholds
and request timeout. Defaults preserve current production behavior; values can
be overridden via environment variables consumed by ``AppConfig.from_env``.

Phase C of PLANO_REFATORACAO.md. ``AppConfig`` is not a singleton — modules
that need it should call ``AppConfig.from_env()`` once at startup and pass the
instance through. Phase D will plumb it explicitly across the split modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class AppConfig:
    """Stage-1 runtime configuration.

    Defaults match current production hardcodes (see ``docmind_converter.py``
    l.287, l.693, l.540-541 and ``retry_failed_pages.py`` l.42 before Phase C).
    """

    ocr_model: str = "qwen3-vl-plus-2025-12-19"
    llm_model: str = "qwen-vl-max-latest"

    retry_max_attempts: int = 4
    retry_base_delay: float = 1.0
    retry_jitter: bool = True

    health_disable_after: int = 5
    health_disable_duration: int = 300

    request_timeout: int = 120

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            ocr_model=_env_str("DOCMIND_OCR_MODEL", cls.ocr_model),
            llm_model=_env_str("DOCMIND_LLM_MODEL", cls.llm_model),
            retry_max_attempts=_env_int("DOCMIND_RETRY_MAX_ATTEMPTS", cls.retry_max_attempts),
            retry_base_delay=_env_float("DOCMIND_RETRY_BASE_DELAY", cls.retry_base_delay),
            retry_jitter=_env_bool("DOCMIND_RETRY_JITTER", cls.retry_jitter),
            health_disable_after=_env_int("DOCMIND_HEALTH_DISABLE_AFTER", cls.health_disable_after),
            health_disable_duration=_env_int("DOCMIND_HEALTH_DISABLE_DURATION", cls.health_disable_duration),
            request_timeout=_env_int("DOCMIND_REQUEST_TIMEOUT", cls.request_timeout),
        )
