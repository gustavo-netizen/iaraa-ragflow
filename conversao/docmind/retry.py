"""Retry policy for dashscope calls.

Pure module: no I/O, no globals beyond ``DEFAULT_RETRY_CONFIG``. Defaults
read once from ``AppConfig.from_env()`` so env vars (``DOCMIND_RETRY_*``)
override at import time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from config import AppConfig

_APP_CONFIG = AppConfig.from_env()


@dataclass
class RetryConfig:
    """Exponential-backoff retry policy."""

    max_retries: int = _APP_CONFIG.retry_max_attempts
    initial_delay: float = _APP_CONFIG.retry_base_delay
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = _APP_CONFIG.retry_jitter

    retry_on_status_codes: tuple = (429, 500, 502, 503, 504)
    retry_on_exceptions: tuple = (
        "SSLError",
        "ConnectionError",
        "TimeoutError",
        "NameResolutionError",
        "UNEXPECTED_EOF",
    )


DEFAULT_RETRY_CONFIG = RetryConfig()


def should_retry(error: Exception, config: RetryConfig) -> bool:
    """Decide retry by matching error string against ``retry_on_exceptions``."""
    error_str = str(error)
    for exc_pattern in config.retry_on_exceptions:
        if exc_pattern in error_str:
            return True
    return False


def calculate_retry_delay(attempt: int, config: RetryConfig) -> float:
    """Exponential backoff with optional ±25% jitter. Floors at 0.1s."""
    delay = min(
        config.initial_delay * (config.exponential_base ** attempt),
        config.max_delay,
    )
    if config.jitter:
        jitter_range = delay * 0.25
        delay += random.uniform(-jitter_range, jitter_range)
    return max(0.1, delay)
