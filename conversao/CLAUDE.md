# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in `conversao/`.

## Project Overview

DocMind is **Stage 1** of the iaraa-ragflow pipeline. It converts PDFs to Markdown + YAML metadata using Alibaba's Qwen-VL API (OCR + VLM) with concurrent processing, multi-key load balancing, and page-level checkpoint/resume.

After Fase G, the pipeline is orchestrated in Python (`conversao/orchestrator.py`). `run.sh` is a thin wrapper (~198 lines) that loads API keys, spawns the monitor daemon, handles `--history`, then delegates to `python orchestrator.py run [...]`. Operators see no behavior change; the CLI surface is preserved.

## Essential Commands

```bash
# Run the main processing pipeline
./run.sh

# Check processing progress (delegates to orchestrator.py status)
./run.sh --status

# Force restart from beginning (archives old progress)
./run.sh --restart

# Retry only failed pages
./run.sh --retry-failed

# Run with resource monitoring
./run.sh --monitor --task-name my_task

# View task history
./run.sh --history

# Direct orchestrator invocation (bypass run.sh — useful for tooling/JSON status)
python orchestrator.py status [--json]
python orchestrator.py run [--restart] [--retry-failed] [-t TASK_NAME]
```

### Environment Variables for Tuning

`AppConfig` (Fase C, `scripts/config.py`) is the single source of truth for runtime knobs. Defaults preserve current production behavior; override via env vars:

```bash
DOCMIND_OCR_MODEL=qwen3-vl-plus-2025-12-19   # default
DOCMIND_LLM_MODEL=qwen-vl-max-latest         # default

DOCMIND_RETRY_MAX_ATTEMPTS=4
DOCMIND_RETRY_BASE_DELAY=1.0
DOCMIND_RETRY_JITTER=true

DOCMIND_HEALTH_DISABLE_AFTER=5
DOCMIND_HEALTH_DISABLE_DURATION=300

DOCMIND_REQUEST_TIMEOUT=120
```

Concurrency knobs (consumed by `orchestrator.py` / `scripts/docmind_converter.py`):

```bash
MAX_PAGES=50      # Pages per chunk (default: 50)
MAX_SIZE=50       # MB per chunk (default: 50)
SEMAPHORE=30      # Concurrent PDFs (default: 30)
LLM_CONCURRENT=10 # LLM calls per PDF (default: 10)
```

### Running Individual Scripts

```bash
# Core converter (processes a directory of PDFs)
python3 scripts/docmind_converter.py --input input/ --output output/ \
    --semaphore-limit 10 --pdf-concurrency 30 --progress-file progress.json

# Split large PDFs
python3 scripts/split_large_pdfs_smart.py --input-dir input/ --output-dir input/split_pdfs \
    --chunk-size 50 --max-chunk-size-mb 50

# Merge split results
python3 scripts/merge_results_full.py --mapping-file split_mapping.json \
    --results-dir output/chunks --output-dir output/

# Post-process markdown
python3 scripts/postprocess.py --input final-delivery/ --fix-tables --fix-headings

# Generate quality report
python3 scripts/generate_quality_report.py --input final-delivery/ --progress progress.json

# Final delivery check
python3 scripts/final_delivery_check.py --input final-delivery/

# Check progress status
python3 scripts/progress_manager.py --status --progress-file progress.json
```

## Architecture

### Module Layout (post-refactor)

```
conversao/
├── orchestrator.py            # Fase G: Pipeline.status() / Pipeline.run() — Python entry-point
├── run.sh                     # Thin shell wrapper (~198 lines): env + monitor + --history
│
├── docmind/                   # Fase D: Stage-1 core (split from monolithic docmind_converter.py)
│   ├── retry.py               # RetryConfig + exponential backoff with jitter
│   ├── api_key_pool.py        # APIKeyHealthMonitor + load balancing
│   ├── qwen_client.py         # QwenClient (OCR + VLM dashscope wrapper) + CallResult
│   ├── page_processor.py      # process_single_page_with_context (3-page window)
│   ├── pipeline.py            # process_pdf_async + process_all_pdfs_parallel
│   └── document.py            # Fase E: Document dataclass (per PDF + chunks),
│                              #   discover() / is_complete() / failed_pages() / apply_page_offset()
│
├── scripts/                   # Pipeline scripts (Steps 1–9)
│   ├── config.py              # AppConfig (Fase C) — frozen dataclass + from_env()
│   ├── docmind_converter.py   # Thin shim re-exporting docmind.*
│   ├── split_large_pdfs_smart.py
│   ├── merge_results_full.py
│   ├── retry_failed_pages.py
│   ├── postprocess.py
│   ├── progress_manager.py
│   ├── generate_quality_report.py # Shim — delegates to validation/
│   ├── final_delivery_check.py    # Shim — delegates to validation/
│   └── admin/                 # Utilities (monitor, archive, key tests, …)
│
└── validation/                # Fase F: pluggable Checkers + cost + report
    ├── pipeline.py            # Validation pipeline runner
    ├── checkers.py            # StructureChecker, ContentSyntaxChecker, MarkdownChecker,
    │                          #   QualityChecker, ElementChecker, MarcoChecker
    ├── cost.py                # Token / call cost estimation
    └── report.py              # Quality + delivery report rendering
```

### Processing Pipeline (orchestrator.py runs Steps 1–9)

```
Step 1: split_large_pdfs_smart.py
    └── Splits PDFs >50 pages or >50MB into chunks

Step 2: docmind_converter.py (for chunks) → delegates to docmind/pipeline.py
    ├── Phase 1: PDF → PNG images (pdf2image, 150 DPI)
    ├── Phase 2: OCR extraction (qwen3-vl-plus-2025-12-19, 20 concurrent)
    └── Phase 3: LLM processing (qwen-vl-max-latest, 10 concurrent per PDF)

Step 3: retry_failed_pages.py
    └── Retries pages that failed in Step 2

Step 4: docmind_converter.py (for small PDFs)
    └── Same 3-phase processing

Step 5: merge_results_full.py
    └── Combines chunks, adjusts page numbers (uses Document.apply_page_offset)

Step 6: postprocess.py
    └── Fixes tables, headings, LaTeX validation

Step 7: generate_quality_report.py → validation/ (Fase F)
    └── KQI metrics and quality grades

Step 8: final_delivery_check.py → validation/ (Fase F)
    └── Validates output completeness via pluggable Checkers
```

### Key Design Patterns

**3-Page Context Window** (`docmind/page_processor.py`): each page is processed with prev/current/next OCR text to identify cross-page figure references.

**Two-Phase VLM Processing** (`docmind/pipeline.py`):
1. **OCR phase** — simple text extraction (`qwen3-vl-plus-2025-12-19`)
2. **LLM phase** — structured extraction with chain-of-thought prompt (`qwen-vl-max-latest`)

**Prompt Modes**:
- `ENHANCED` — full 2500-char prompt with chain-of-thought for data extraction
- `SIMPLE` — short 500-char prompt for text-heavy pages or sensitive content

**API Key Pool** (`docmind/api_key_pool.py`): `APIKeyHealthMonitor` tracks per-key health; auto-disables a key for `DOCMIND_HEALTH_DISABLE_DURATION` seconds (default 5 min) after `DOCMIND_HEALTH_DISABLE_AFTER` consecutive failures (default 5).

**Retry** (`docmind/retry.py`): `RetryConfig` exponential backoff with jitter, `max_attempts=4`, base delay `1.0s`.

**Document dataclass** (`docmind/document.py`, Fase E): per-PDF state — `discover()`, `is_complete()`, `failed_pages()`, `apply_page_offset()`. Used by merge + retry scripts.

**Validation** (`validation/`, Fase F): `Checker` base class with pluggable subclasses (`StructureChecker`, `ContentSyntaxChecker`, `MarkdownChecker`, `QualityChecker`, `ElementChecker`, `MarcoChecker`). Consumed by `final_delivery_check.py` and `generate_quality_report.py` shims.

### Output Structure

```
output/{pdf_name}/
├── {pdf_name}.md              # Main markdown output (sem `**Footnotes:**` pós-J.2)
├── {pdf_name}_all_figures.yaml # Combined figure metadata (consumed by ficha_converter Phase 4.5)
├── {pdf_name}.footnotes.yaml   # Footnotes sidecar (Fase J/ADR-0004); incondicional (notes: [] quando vazio)
├── {pdf_name}.validation.yaml  # Quality metrics
├── images/                     # Page PNGs
└── yaml_metadata/              # Per-figure YAML files
```

`<pdf_name>.footnotes.yaml` schema flat (espelha `_all_figures.yaml:figures`):

```yaml
version: "1.0"
pdf_name: <name>
total_pages: 10
notes:
  - {page: 3, id: 1, text: "³⁵"}
  - {page: 8, id: 1, text: "*Tournois refere-se à livre tournois*"}
```

Quando o sidecar existe e tem notes, o metadata header do MD ganha um marker `*Footnotes: sidecar*` (signal redundante caso o `.md` se separe do `.yaml`).

### API Configuration

Priority: `api/keys.txt` > `.env` > environment variables.

**How keys are loaded:**
- `api/keys.txt` — one key per line. `run.sh` reads this file and exports each key as `DASHSCOPE_API_KEY_1`, `DASHSCOPE_API_KEY_2`, etc.
- `.env` — define keys as `DASHSCOPE_API_KEY_1=sk-xxx`, `DASHSCOPE_API_KEY_2=sk-yyy`, etc.
- Environment variables — export `DASHSCOPE_API_KEY` or `DASHSCOPE_API_KEY_N` directly.

**Important:** the Python scripts only read from environment variables. `run.sh` handles the conversion from `api/keys.txt` to environment variables automatically.

Keys are load-balanced with health monitoring; failing keys are auto-disabled per the thresholds above.

## Quality Standards (MARCO Specification)

- YAML insertion rate: ≥ 95%
- Average confidence: ≥ 0.85
- Page success rate: ≥ 95%

See `docs/MARCO_QUALITY_SPECIFICATION.md` for the full schema. The `MarcoChecker` in `validation/checkers.py` enforces these thresholds.

## Tests

Tests live at the repo root in `tests/` (not in `conversao/`).

```bash
pytest tests/                          # Full suite (194 passed, 0 xfail)
pytest tests/test_orchestrator_run.py  # Pipeline.run() unit tests
pytest tests/test_orchestrator_status.py
pytest tests/test_document.py          # Document dataclass (Fase E)
pytest tests/test_retry.py             # RetryConfig
pytest tests/test_validation_*.py      # Checkers (Fase F)
```

After every structural change in Fases B–G, `pytest tests/` must pass before commit.
