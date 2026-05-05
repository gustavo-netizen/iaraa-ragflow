"""DocMind — Stage-1 PDF→Markdown converter.

Split from ``conversao/scripts/docmind_converter.py`` during Fase D of
PLANO_REFATORACAO.md (2026-05). Modules:

- ``retry``        — RetryConfig, calculate_retry_delay, should_retry
- ``api_key_pool`` — APIKeyHealth, APIKeyHealthMonitor, env loading, default monitor
- ``qwen_client``  — QwenClient (OCR + VLM dashscope wrapper) and CallResult
- ``page_processor``— ContextMode/PromptMode, prompts, per-page orchestration
- ``pipeline``     — PDF-level orchestration, CLI entry-point

The package depends on ``conversao/scripts/config.py`` (AppConfig) and
``conversao/scripts/progress_manager.py``. We add ``scripts/`` to sys.path
once here so callers can ``from docmind.X import Y`` without first
adjusting paths themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
