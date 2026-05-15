# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in `conversao/`.

## Project Overview

DocMind is **Stage 1** of the iaraa-ragflow pipeline. It converts PDFs to Markdown + YAML metadata using Alibaba's Qwen-VL API (OCR + VLM) with concurrent processing, multi-key load balancing, and page-level checkpoint/resume.

After Fase G, the pipeline is orchestrated in Python (`conversao/orchestrator.py`). `run.sh` is a thin wrapper (~207 lines) that loads API keys, spawns the monitor daemon, handles `--history`/`--no-quality-gate`, then delegates to `python orchestrator.py run [...]`. Operators see no behavior change; the CLI surface is preserved.

## System Dependencies

Two C libraries are required alongside the Python packages in `requirements.txt`:

- **poppler** — consumed by `pdf2image` (PDF → PNG rasterization). `brew install poppler` (macOS) / `apt install poppler-utils` (Linux).
- **libqpdf** — consumed by `pikepdf` (PDF splitting in `scripts/split_large_pdfs_smart.py`). `brew install qpdf` (macOS) / `apt install libqpdf-dev` (Linux). pikepdf replaced PyPDF2 in Fase 3 of `PLANO_BUGFIXES_QUALITY_GATE.md` because libqpdf's C parser silently recovers from minor PDF damage (truncated trailers, off-spec headers) that PyPDF2's pure-Python parser rejects.

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

# Skip the Step 5.5 KQI gate (proceed even if PDFs fail MARCO thresholds)
./run.sh --no-quality-gate

# Direct orchestrator invocation (bypass run.sh — useful for tooling/JSON status)
python orchestrator.py status [--json]
python orchestrator.py run [--restart] [--retry-failed] [--no-quality-gate] [-t TASK_NAME]
```

### Environment Variables for Tuning

`AppConfig` (Fase C, `scripts/config.py`) is the single source of truth for runtime knobs. Defaults preserve current production behavior; override via env vars:

```bash
DOCMIND_OCR_MODEL=qwen3-vl-plus              # default (alias — habilita prompt caching)
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
├── run.sh                     # Thin shell wrapper: env + monitor + tee run log + --history/--no-quality-gate
│
├── docmind/                   # Fase D: Stage-1 core (split from monolithic docmind_converter.py)
│   ├── retry.py               # RetryConfig + exponential backoff with jitter
│   ├── api_key_pool.py        # APIKeyHealthMonitor + load balancing
│   ├── qwen_client.py         # QwenClient (OCR + VLM dashscope wrapper) + CallResult
│   ├── error_log.py           # JSON Lines sidecar: log_api_error() + classify() (logs/api_errors.jsonl)
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

Step 5.5: KQI Quality Gate (MARCO) — orchestrator-native, post-fix
    └── Reads output/*/{name}.validation.yaml; aborts (rc=1) if any
        overall_quality_pass=false (yaml_insertion ≥ 95% / avg_confidence
        ≥ 0.85 / page_success ≥ 95%). progress.json stays in_progress and
        Steps 6-9 do not run. Skip with --no-quality-gate.

Step 6: postprocess.py
    └── Fixes tables, headings, LaTeX validation

Step 7: generate_quality_report.py → validation/ (Fase F)
    └── KQI metrics and quality grades

Step 8: final_delivery_check.py → validation/ (Fase F)
    └── Validates output completeness via pluggable Checkers
        (includes MarcoChecker strict mode — flags KQI violations as issues
        even when --no-quality-gate let the run reach this point)
```

### Key Design Patterns

**3-Page Context Window** (`docmind/page_processor.py`): each page is processed with prev/current/next OCR text to identify cross-page figure references.

**Two-Phase VLM Processing** (`docmind/pipeline.py`):
1. **OCR phase** — simple text extraction (`qwen3-vl-plus`, alias bare — habilita prompt caching)
2. **LLM phase** — structured extraction with chain-of-thought prompt (`qwen-vl-max-latest`)

**Prompt Modes**:
- `ENHANCED` — full 2500-char prompt with chain-of-thought for data extraction
- `SIMPLE` — short 500-char prompt for text-heavy pages or sensitive content

**API Key Pool** (`docmind/api_key_pool.py`): `APIKeyHealthMonitor` tracks per-key health; auto-disables a key for `DOCMIND_HEALTH_DISABLE_DURATION` seconds (default 5 min) after `DOCMIND_HEALTH_DISABLE_AFTER` consecutive failures (default 5).

**Retry** (`docmind/retry.py`): `RetryConfig` exponential backoff with jitter, `max_attempts=4`, base delay `1.0s`.

**Structured Error Log** (`docmind/error_log.py`): every OCR / VLM attempt that doesn't return 200 (including intermediate retries) appends one JSON Lines record to `logs/api_errors.jsonl`. Fields: `ts`, `phase` (`ocr` | `vlm`), `attempt`/`max_attempts`, `model`, `key_short` (masked), `http_status`, `dashscope_code`, `request_id`, `latency_s`, `category` (`throttle` | `moderation` | `timeout` | `network` | `server_error` | `auth` | `bad_request` | `exception` | `other`), `message`, plus per-call context (`pdf_name`, `page`, `prompt_mode`). Override the path via `DOCMIND_ERROR_LOG`. FileLock-guarded so concurrent workers append safely; writer is no-raise. In parallel, `run.sh` `tee`s stdout/stderr of the orchestrator into `logs/run_<timestamp>_<task>.log` for human review.

**Document dataclass** (`docmind/document.py`, Fase E): per-PDF state — `discover()`, `is_complete()`, `failed_pages()`, `apply_page_offset()`. Used by merge + retry scripts.

**Validation** (`validation/`, Fase F): `Checker` base class with pluggable subclasses (`StructureChecker`, `ContentSyntaxChecker`, `MarkdownChecker`, `QualityChecker`, `ElementChecker`, `MarcoChecker`). Consumed by `final_delivery_check.py` and `generate_quality_report.py` shims. `MarcoChecker` has two modes: **strict** (reads `output/*/.validation.yaml` and enforces the three MARCO thresholds — same data the Step 5.5 quality gate uses) and **structural** fallback (yaml + title + page-header sanity check when no `.validation.yaml` is available).

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

### Mapping Schema (`split_mapping.json`)

Escrito pelo Step 1 (`split_large_pdfs_smart.py`) e consumido por todos os steps abaixo. **Três campos top-level com leitores diferentes** — não tratar como um schema único:

```json
{
  "stats": {
    "total_pdfs": 10,
    "split_pdfs": 7,
    "skipped_pdfs": 3,
    "error_pdfs": 0,
    "total_chunks": 42,
    "pdfs": {
      "Foo.pdf":     {"pages": 120, "size_mb": 18.4, "chunks": 3, "status": "split"},
      "Bar.pdf":     {"pages":  30, "size_mb":  4.2, "chunks": 0, "status": "skip"},
      "Broken.pdf":  {"error": "Invalid Elementary Object", "status": "error"}
    }
  },
  "chunks": [
    {"path": "...", "chunk_idx": 1, "total_chunks": 3, "pages": 50,
     "start_page": 1, "end_page": 50, "size_mb": 7.1, "original_pdf": "Foo.pdf"}
  ],
  "direct": [
    {"pdf_path": "/abs/path/Bar.pdf", "pdf_name": "Bar.pdf"}
  ]
}
```

- **`stats.pdfs[name].status`** ∈ `{split, skip, error}`. Consumido por `orchestrator._validate_split_mapping_or_abort` (pre-Step-2 guard, ADR-0005) — qualquer `status == 'error'` aborta o pipeline antes do Step 2. Bloco humanamente legível: cada PDF que entrou em `input/` aparece aqui, com diagnóstico.
- **`stats.error_pdfs`** (Fase 2 do `PLANO_BUGFIXES_QUALITY_GATE.md`): contador agregado usado pelo `main()` para decidir `set_step_status('split', 'failed')` e rc=1.
- **`chunks[]` / `direct[]`** são os campos canônicos consumidos por `Document.discover` (`docmind/document.py`). Apenas PDFs que tiveram split bem-sucedido aparecem em `chunks[]`; PDFs abaixo do threshold em `direct[]`. **PDFs com `status='error'` não aparecem em nenhum dos dois** — por isso o guard precisa ler `stats.pdfs` para detectá-los.

Regra: para enumerar PDFs **que vão ser processados** use `Document.discover`. Para enumerar PDFs **que o operador submeteu**, ou para detectar erros do splitter, leia `stats.pdfs`.

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

See `docs/MARCO_QUALITY_SPECIFICATION.md` for the full schema. Enforced in two places:

1. **Step 5.5 KQI Quality Gate** (`orchestrator._step4_5_quality_gate`) — reads `output/*/{name}.validation.yaml` between merge and final-delivery copy; aborts the pipeline (`rc=1`, `progress.json` stays `in_progress`) if any PDF has `kqi_metrics.overall_quality_pass=false`. The per-PDF `.validation.yaml` is written by `docmind/pipeline.py`. Bypass with `--no-quality-gate`.
2. **Step 8 `MarcoChecker`** (strict mode) — same thresholds, runs as part of `final_delivery_check.py` after the delivery package is built. Acts as a second line of defense and as the only KQI check when `--no-quality-gate` was used.

## Tests

Tests live at the repo root in `tests/` (not in `conversao/`).

```bash
pytest tests/                          # Full suite (202 passed, 0 xfail)
pytest tests/test_orchestrator_run.py  # Pipeline.run() unit tests
pytest tests/test_orchestrator_status.py
pytest tests/test_document.py          # Document dataclass (Fase E)
pytest tests/test_retry.py             # RetryConfig
pytest tests/test_validation_*.py      # Checkers (Fase F)
```

After every structural change in Fases B–G, `pytest tests/` must pass before commit.
