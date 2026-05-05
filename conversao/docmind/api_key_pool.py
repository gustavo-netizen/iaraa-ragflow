"""API key rotation + health monitoring for dashscope calls.

Loads ``DASHSCOPE_API_KEY_1..8`` and ``DASHSCOPE_API_KEY`` from env, tracks
per-key success/failure, and auto-disables a key after consecutive failures.
Both async and sync code paths are needed because Phase 2 (OCR) runs sync
inside ``run_in_executor`` while Phase 3 (VLM) is fully async.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config import AppConfig

_APP_CONFIG = AppConfig.from_env()


@dataclass
class APIKeyHealth:
    """Health state for a single API key."""

    key: str
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    total_latency: float = 0.0
    last_success_time: Optional[float] = None
    last_failure_time: Optional[float] = None
    is_disabled: bool = False
    disabled_until: Optional[float] = None

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 1.0

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.success_count if self.success_count > 0 else 0.0

    def record_success(self, latency: float) -> None:
        self.success_count += 1
        self.consecutive_failures = 0
        self.total_latency += latency
        self.last_success_time = time.time()
        if self.is_disabled:
            self.is_disabled = False
            self.disabled_until = None

    def record_failure(self, disable_threshold: int = 5, disable_duration: float = 300.0) -> None:
        self.failure_count += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        if self.consecutive_failures >= disable_threshold:
            self.is_disabled = True
            self.disabled_until = time.time() + disable_duration

    def is_available(self) -> bool:
        if not self.is_disabled:
            return True
        if self.disabled_until and time.time() > self.disabled_until:
            self.is_disabled = False
            self.disabled_until = None
            self.consecutive_failures = 0
            return True
        return False


class APIKeyHealthMonitor:
    """Smart load-balanced rotation across a list of API keys."""

    def __init__(
        self,
        api_keys: List[str],
        disable_threshold: int = 5,
        disable_duration: float = 300.0,
    ):
        self.health_data: Dict[str, APIKeyHealth] = {
            key: APIKeyHealth(key=key) for key in api_keys
        }
        self.disable_threshold = disable_threshold
        self.disable_duration = disable_duration
        self._lock = asyncio.Lock()
        self._current_index = 0

    async def get_healthy_key(self) -> Optional[str]:
        async with self._lock:
            return self._pick_key()

    def get_healthy_key_sync(self) -> Optional[str]:
        return self._pick_key(jitter=False)

    def _pick_key(self, jitter: bool = True) -> Optional[str]:
        available = [k for k, h in self.health_data.items() if h.is_available()]
        if not available:
            earliest = min(
                self.health_data.keys(),
                key=lambda k: self.health_data[k].disabled_until or float("inf"),
            )
            self.health_data[earliest].is_disabled = False
            return earliest

        if jitter:
            sorted_keys = sorted(
                available,
                key=lambda k: (
                    -self.health_data[k].success_rate,
                    self.health_data[k].consecutive_failures,
                    random.random() * 0.1,
                ),
            )
        else:
            sorted_keys = sorted(
                available,
                key=lambda k: (
                    -self.health_data[k].success_rate,
                    self.health_data[k].consecutive_failures,
                ),
            )
        return sorted_keys[0]

    async def record_success(self, key: str, latency: float) -> None:
        async with self._lock:
            if key in self.health_data:
                self.health_data[key].record_success(latency)

    async def record_failure(self, key: str) -> None:
        async with self._lock:
            if key in self.health_data:
                self.health_data[key].record_failure(
                    self.disable_threshold,
                    self.disable_duration,
                )

    def record_success_sync(self, key: str, latency: float) -> None:
        if key in self.health_data:
            self.health_data[key].record_success(latency)

    def record_failure_sync(self, key: str) -> None:
        if key in self.health_data:
            self.health_data[key].record_failure(
                self.disable_threshold,
                self.disable_duration,
            )

    def get_stats(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {
            "total_keys": len(self.health_data),
            "active_keys": sum(1 for h in self.health_data.values() if h.is_available()),
            "disabled_keys": sum(1 for h in self.health_data.values() if h.is_disabled),
            "keys": {},
        }
        for key, health in self.health_data.items():
            masked_key = f"{key[:8]}...{key[-4:]}"
            stats["keys"][masked_key] = {
                "success_rate": f"{health.success_rate:.1%}",
                "success_count": health.success_count,
                "failure_count": health.failure_count,
                "consecutive_failures": health.consecutive_failures,
                "avg_latency": f"{health.avg_latency:.2f}s",
                "is_disabled": health.is_disabled,
            }
        return stats

    def print_stats(self) -> None:
        stats = self.get_stats()
        print(f"\n📊 API Key 健康状态:")
        print(f"   活跃: {stats['active_keys']}/{stats['total_keys']} | 禁用: {stats['disabled_keys']}")
        for key, info in stats["keys"].items():
            status = "🔴" if info["is_disabled"] else "🟢"
            print(
                f"   {status} {key}: 成功率 {info['success_rate']}, "
                f"调用 {info['success_count']}/{info['success_count'] + info['failure_count']}, "
                f"延迟 {info['avg_latency']}"
            )


def load_api_keys_from_env() -> List[str]:
    """Load DASHSCOPE_API_KEY_1..8 + DASHSCOPE_API_KEY, filtering placeholders."""
    keys = [os.environ.get(f"DASHSCOPE_API_KEY_{i}") for i in range(1, 9)]
    keys.append(os.environ.get("DASHSCOPE_API_KEY"))
    return [k for k in keys if k and k != "YOUR_API_KEY_HERE"]


# Module-level default monitor — initialized on import to preserve the behavior
# of the pre-Fase-D monolith (docmind_converter.py l.541-547). Reads env once.
API_KEYS: List[str] = load_api_keys_from_env()

_api_key_monitor: Optional[APIKeyHealthMonitor] = None
if API_KEYS:
    _api_key_monitor = APIKeyHealthMonitor(
        API_KEYS,
        disable_threshold=_APP_CONFIG.health_disable_after,
        disable_duration=float(_APP_CONFIG.health_disable_duration),
    )


async def get_next_api_key() -> Optional[str]:
    """Async: pick next healthy key from the default monitor, fallback to env."""
    if _api_key_monitor:
        return await _api_key_monitor.get_healthy_key()
    return os.environ.get("DASHSCOPE_API_KEY")


def get_next_api_key_sync() -> Optional[str]:
    """Sync version for use in ``run_in_executor`` callbacks."""
    if _api_key_monitor:
        return _api_key_monitor.get_healthy_key_sync()
    return os.environ.get("DASHSCOPE_API_KEY")
