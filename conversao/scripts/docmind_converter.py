#!/usr/bin/env python3
"""DocMind PDF→Markdown — backwards-compatible shim.

The implementation lives in ``conversao/docmind/`` since Fase D of
PLANO_REFATORACAO.md (2026-05). This file:

1. Adds ``conversao/`` to ``sys.path`` so ``import docmind.pipeline`` works.
2. Re-exports the symbols ``retry_failed_pages.py`` imports.
3. Forwards CLI invocation to ``docmind.pipeline.main``.

``run.sh`` continues to call ``python3 scripts/docmind_converter.py …`` and
``monitor_daemon.py`` continues to ``pgrep -f docmind_converter.py`` — both
work unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_CONVERSAO_DIR = _SCRIPT_DIR.parent

if str(_CONVERSAO_DIR) not in sys.path:
    sys.path.insert(0, str(_CONVERSAO_DIR))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from docmind.api_key_pool import (  # noqa: E402
    API_KEYS,
    APIKeyHealth,
    APIKeyHealthMonitor,
    _api_key_monitor,
    get_next_api_key,
    get_next_api_key_sync,
    load_api_keys_from_env,
)
from docmind.page_processor import (  # noqa: E402
    CHART_EXTRACTION_PROMPT,
    CHART_INDICATORS,
    DEFAULT_CONTEXT_MODE,
    DEFAULT_PROMPT_MODE,
    ContextMode,
    PromptMode,
    build_context_window,
    build_prompt,
    generate_figure_yaml,
    has_chart_indicators,
    process_single_page_with_context,
)
from docmind.pipeline import (  # noqa: E402
    APP_CONFIG,
    DEFAULT_MODEL,
    check_dependencies,
    get_api_key,
    main,
    process_all_pdfs_parallel,
    process_pdf_async,
)
from docmind.qwen_client import (  # noqa: E402
    QwenClient,
    safe_get_text_from_response,
)
from docmind.retry import (  # noqa: E402
    DEFAULT_RETRY_CONFIG,
    RetryConfig,
    calculate_retry_delay,
    should_retry,
)

__all__ = [
    "API_KEYS",
    "APIKeyHealth",
    "APIKeyHealthMonitor",
    "APP_CONFIG",
    "CHART_EXTRACTION_PROMPT",
    "CHART_INDICATORS",
    "ContextMode",
    "DEFAULT_CONTEXT_MODE",
    "DEFAULT_MODEL",
    "DEFAULT_PROMPT_MODE",
    "DEFAULT_RETRY_CONFIG",
    "PromptMode",
    "QwenClient",
    "RetryConfig",
    "_api_key_monitor",
    "build_context_window",
    "build_prompt",
    "calculate_retry_delay",
    "check_dependencies",
    "generate_figure_yaml",
    "get_api_key",
    "get_next_api_key",
    "get_next_api_key_sync",
    "has_chart_indicators",
    "load_api_keys_from_env",
    "main",
    "process_all_pdfs_parallel",
    "process_pdf_async",
    "process_single_page_with_context",
    "safe_get_text_from_response",
    "should_retry",
]


if __name__ == "__main__":
    sys.exit(main())
