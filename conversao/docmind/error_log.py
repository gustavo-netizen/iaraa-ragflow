"""JSON Lines sidecar for DashScope API failures.

Each attempted call that doesn't return 200 (including intermediate retries)
appends one line to ``logs/api_errors.jsonl`` with enough context to triage:
HTTP status, DashScope error code, request_id, model alias, masked key and
the surrounding PDF / chunk / page identifiers.

The writer is deliberately defensive: it never raises into the OCR / VLM hot
loop, falls back to silent drop on disk errors, and uses FileLock so multiple
concurrent workers can append safely.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

from filelock import FileLock, Timeout


def _default_log_path() -> Path:
    return Path(os.environ.get("DOCMIND_ERROR_LOG", "logs/api_errors.jsonl"))


def _key_short(key: Optional[str]) -> str:
    if not key:
        return "-"
    if len(key) <= 12:
        return f"{key[:3]}…"
    return f"{key[:6]}…{key[-4:]}"


def classify(
    status_code: Optional[int],
    dashscope_code: Optional[str],
    exception: Optional[BaseException],
    message: Optional[str] = None,
) -> str:
    """Bucket the failure into a coarse category so JSONL is greppable."""
    msg_blob = " ".join(filter(None, [message or "", dashscope_code or ""]))

    if exception is not None:
        exc_name = type(exception).__name__
        exc_str = str(exception).lower()
        if "Timeout" in exc_name or "timeout" in exc_str:
            return "timeout"
        if "Connection" in exc_name or "socket" in exc_str:
            return "network"

    if status_code == 429 or (dashscope_code or "").startswith("Throttling"):
        return "throttle"
    if "DataInspectionFailed" in msg_blob:
        return "moderation"
    if isinstance(status_code, int):
        if status_code >= 500:
            return "server_error"
        if status_code in (401, 403):
            return "auth"
        if status_code == 400:
            return "bad_request"

    if exception is not None:
        return "exception"
    return "other"


def log_api_error(
    *,
    phase: str,
    attempt: int,
    max_attempts: int,
    model: str,
    api_key: Optional[str],
    context: Optional[Mapping[str, Any]] = None,
    status_code: Optional[int] = None,
    dashscope_code: Optional[str] = None,
    request_id: Optional[str] = None,
    latency_s: Optional[float] = None,
    exception: Optional[BaseException] = None,
    message: Optional[str] = None,
    path: Optional[Path] = None,
) -> None:
    """Append one JSON Lines record describing an attempted API call that failed.

    ``phase`` is ``"ocr"`` (Phase 2, sync) or ``"vlm"`` (Phase 3, async).
    ``context`` may carry ``pdf_name``, ``chunk``, ``page``, ``prompt_mode``,
    etc. Any disk / serialization error is swallowed — we don't want logging
    to break a production run.
    """
    target = path or _default_log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    record: dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "phase": phase,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "model": model,
        "key_short": _key_short(api_key),
        "http_status": status_code,
        "dashscope_code": dashscope_code,
        "request_id": request_id,
        "latency_s": round(latency_s, 3) if isinstance(latency_s, (int, float)) else None,
        "category": classify(status_code, dashscope_code, exception, message),
        "message": (message or "")[:500],
    }
    if exception is not None:
        record["exception_class"] = type(exception).__name__

    if context:
        for key, value in context.items():
            record.setdefault(key, value)

    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
    except Exception:
        return

    lock_path = str(target) + ".lock"
    try:
        with FileLock(lock_path, timeout=5):
            with open(target, "a", encoding="utf-8") as fp:
                fp.write(line + "\n")
    except (OSError, Timeout):
        return
