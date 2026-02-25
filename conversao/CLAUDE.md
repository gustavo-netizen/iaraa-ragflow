# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DocMind is a high-performance PDF to Markdown converter using Alibaba's Qwen-VL API. It processes PDFs through OCR and vision-language models to extract text, tables, figures, and charts with structured YAML metadata.

## Essential Commands

```bash
# Run the main processing pipeline
./run.sh

# Check processing progress
./run.sh --status

# Force restart from beginning (archives old progress)
./run.sh --restart

# Retry only failed pages
./run.sh --retry-failed

# Run with resource monitoring
./run.sh --monitor --task-name my_task

# View task history
./run.sh --history
```

### Environment Variables for Tuning

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

# Check progress status
python3 scripts/progress_manager.py --status --progress-file progress.json
```

## Architecture

### Processing Pipeline (run.sh orchestrates)

```
Step 1: split_large_pdfs_smart.py
    └── Splits PDFs >50 pages or >50MB into chunks

Step 2: docmind_converter.py (for chunks)
    ├── Phase 1: PDF → PNG images (pdf2image, 150 DPI)
    ├── Phase 2: OCR extraction (20 concurrent, qwen-vl-plus)
    └── Phase 3: LLM processing (10 concurrent per PDF, qwen-vl-max-latest)

Step 3: retry_failed_pages.py
    └── Retries pages that failed in Step 2

Step 4: docmind_converter.py (for small PDFs)
    └── Same 3-phase processing

Step 5: merge_results_full.py
    └── Combines chunks, adjusts page numbers

Step 6: postprocess.py
    └── Fixes tables, headings, LaTeX validation

Step 7: generate_quality_report.py
    └── KQI metrics and quality grades

Step 8: final_delivery_check.py
    └── Validates output completeness
```

### Core Components

**docmind_converter.py** - Main converter with:
- `APIKeyHealthMonitor`: Tracks API key health, auto-disables failing keys
- `RetryConfig`: Exponential backoff with jitter for API calls
- `process_single_page_with_context()`: Processes one page with 3-page context window
- `process_pdf_async()`: Handles single PDF with all 3 phases
- `process_all_pdfs_parallel()`: PDF-level parallelism coordinator

**progress_manager.py** - Checkpoint/resume system:
- Tracks completion at PDF and page level
- Thread-safe with file locking
- Validates completion before skipping

### Key Design Patterns

**3-Page Context Window**: Each page is processed with prev/current/next OCR text to identify cross-page figure references.

**Two-Phase VLM Processing**:
1. OCR phase: Simple text extraction (qwen3-vl-plus-2025-12-19)
2. LLM phase: Structured extraction with chain-of-thought prompt (qwen3-vl-plus-2025-12-19)

**Prompt Modes**:
- `ENHANCED`: Full 2500-char prompt with chain-of-thought for data extraction
- `SIMPLE`: Short 500-char prompt for text-heavy pages or sensitive content

### Output Structure

```
output/{pdf_name}/
├── {pdf_name}.md              # Main markdown output
├── {pdf_name}_all_figures.yaml # Combined figure metadata
├── {pdf_name}.validation.yaml  # Quality metrics
├── images/                     # Page PNGs
└── yaml_metadata/              # Per-figure YAML files
```

### API Configuration

Priority: `api/keys.txt` > `.env` > environment variables

**How keys are loaded:**
- `api/keys.txt`: One key per line. The `run.sh` script reads this file and exports each key as `DASHSCOPE_API_KEY_1`, `DASHSCOPE_API_KEY_2`, etc.
- `.env`: Define keys as `DASHSCOPE_API_KEY_1=sk-xxx`, `DASHSCOPE_API_KEY_2=sk-yyy`, etc.
- Environment variables: Export `DASHSCOPE_API_KEY` or `DASHSCOPE_API_KEY_N` directly.

**Important:** The Python scripts only read from environment variables. The `run.sh` script handles the conversion from `api/keys.txt` to environment variables automatically.

Keys are load-balanced with health monitoring. Failing keys are auto-disabled for 5 minutes after 5 consecutive failures.

## Quality Standards (MARCO Specification)

- YAML insertion rate: ≥95%
- Average confidence: ≥0.85
- Page success rate: ≥95%

See `docs/MARCO_QUALITY_SPECIFICATION.md` for full schema.
