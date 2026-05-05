"""Tests for ``conversao/docmind/retry.py``.

Pure-logic coverage: backoff math, jitter bounds, retry-decision predicate.
No network. Plan reference: PLANO_REFATORACAO.md Fase D, l.250.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "conversao"))
sys.path.insert(0, str(REPO_ROOT / "conversao" / "scripts"))

from docmind.retry import (  # noqa: E402
    DEFAULT_RETRY_CONFIG,
    RetryConfig,
    calculate_retry_delay,
    should_retry,
)


def test_should_retry_matches_known_transients():
    cfg = RetryConfig()
    assert should_retry(Exception("SSLError: handshake failed"), cfg) is True
    assert should_retry(Exception("ConnectionError: refused"), cfg) is True
    assert should_retry(Exception("UNEXPECTED_EOF mid-stream"), cfg) is True


def test_should_retry_rejects_unknown_errors():
    cfg = RetryConfig()
    assert should_retry(ValueError("bad input"), cfg) is False
    assert should_retry(Exception("DataInspectionFailed: content"), cfg) is False


def test_calculate_retry_delay_no_jitter_doubles():
    cfg = RetryConfig(initial_delay=1.0, exponential_base=2.0, max_delay=30.0, jitter=False)
    assert calculate_retry_delay(0, cfg) == 1.0
    assert calculate_retry_delay(1, cfg) == 2.0
    assert calculate_retry_delay(2, cfg) == 4.0
    assert calculate_retry_delay(3, cfg) == 8.0


def test_calculate_retry_delay_caps_at_max_delay():
    cfg = RetryConfig(initial_delay=1.0, exponential_base=2.0, max_delay=10.0, jitter=False)
    assert calculate_retry_delay(10, cfg) == 10.0
    assert calculate_retry_delay(20, cfg) == 10.0


def test_calculate_retry_delay_jitter_within_25_percent_band():
    cfg = RetryConfig(initial_delay=4.0, exponential_base=2.0, max_delay=60.0, jitter=True)
    base = 4.0  # attempt=0
    for _ in range(50):
        delay = calculate_retry_delay(0, cfg)
        # ±25% of base, with a 0.1s floor
        assert 0.1 <= delay <= base * 1.25 + 1e-9
        assert delay >= base * 0.75 - 1e-9 or delay == 0.1


def test_calculate_retry_delay_floor_is_0_1():
    cfg = RetryConfig(initial_delay=0.001, exponential_base=2.0, max_delay=30.0, jitter=False)
    assert calculate_retry_delay(0, cfg) == pytest.approx(0.1)


def test_default_retry_config_reads_app_config_defaults():
    # Production defaults — see config.py and ADR-0001/Fase C decisions.
    assert DEFAULT_RETRY_CONFIG.max_retries == 4
    assert DEFAULT_RETRY_CONFIG.initial_delay == 1.0
    assert DEFAULT_RETRY_CONFIG.jitter is True
    assert DEFAULT_RETRY_CONFIG.max_delay == 30.0
    assert DEFAULT_RETRY_CONFIG.exponential_base == 2.0


def test_retry_on_status_codes_covers_429_and_5xx():
    cfg = RetryConfig()
    for code in (429, 500, 502, 503, 504):
        assert code in cfg.retry_on_status_codes


def test_replace_does_not_share_state():
    cfg_a = RetryConfig(max_retries=2)
    cfg_b = replace(cfg_a, max_retries=5)
    assert cfg_a.max_retries == 2
    assert cfg_b.max_retries == 5
