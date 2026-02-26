# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**iaraa-ragflow** is a two-stage pipeline for converting agricultural PDFs into Markdown optimized for RAGFlow (Retrieval-Augmented Generation). The documents are Brazilian agricultural publications: technical sheets ("Fichas Agroecológicas") and full books ("Livros Técnicos").

**Stage 1 — `conversao/` (DocMind):** Converts raw PDFs to Markdown + YAML metadata using Alibaba's Qwen-VL API with concurrent OCR/VLM processing.

**Stage 2 — `processamento/`:** Post-processes the OCR-generated Markdown to be RAGFlow-ready: cleans artifacts, extracts metadata, generates YAML frontmatter, restructures content with `##`/`###` headers.

## Architecture

```
PDF ──► conversao/ (DocMind)     ──► Raw Markdown + YAML
        Qwen-VL OCR + LLM            per-page extraction

    ──► processamento/           ──► RAGFlow-optimized Markdown
        ficha_converter/              YAML frontmatter + ##/### headers
        book_converter/ (skill)
```

### conversao/ — PDF to Markdown (DocMind)

Orchestrated by `run.sh`. Pipeline: split large PDFs → OCR (qwen-vl-plus) → LLM extraction (qwen-vl-max) → merge chunks → post-process → quality report.

Key design: 3-page context window for cross-page references, multi-API-key load balancing with health monitoring, page-level checkpoint/resume.

See `conversao/CLAUDE.md` for detailed commands and architecture.

### processamento/ — Markdown optimization for RAGFlow

Two converters for two document types:

- **`ficha_converter/`** — Regex-based 6-phase pipeline for Fichas Agroecológicas. Run with `python -m ficha_converter`.
- **`book_converter/`** (at root `.claude/skills/convert-book/`) — LLM-powered 6-phase pipeline for full books. Invoked via `/convert-book` skill.

See `processamento/CLAUDE.md` for detailed commands, pipeline phases, and LLM response format.

### RAGFlow Integration

RAGFlow recognizes Markdown headers (`## `, `### `) natively as chunk delimiters — no custom markers needed. For books, configure the delimiter as `## ` in RAGFlow for chapter-level chunking. Fichas are small enough for RAGFlow's automatic token-based chunking. The `join_paragraph_lines()` function merges OCR line breaks to prevent fragmented chunks.

## Commands

### conversao/

```bash
cd conversao/
./run.sh                    # Full pipeline
./run.sh --status           # Check progress
./run.sh --restart          # Force restart
./run.sh --retry-failed     # Retry failed pages
```

### processamento/

```bash
cd processamento/

# Fichas Agroecológicas — single file
python -m ficha_converter "input.md" -o "output.md" -v

# Fichas Agroecológicas — batch directory
python -m ficha_converter "MD/MD systemRAG/" -o "MD/converted/" --batch -v

# Livros Técnicos — via Claude Code skill
/convert-book <input.md> [-o <output.md>] [-v]
```

## Key Patterns

- **API keys** (conversao): Priority is `api/keys.txt` > `.env` > env vars. Python scripts only read env vars; `run.sh` converts `keys.txt` to env vars automatically.
- **Output format**: Each document gets YAML frontmatter (`---` delimited) + Markdown body with `##`/`###` headers (recognized natively by RAGFlow as chunk delimiters).
- **`join_paragraph_lines()`**: Joins lines starting with lowercase or `(`/`[` (OCR continuation). Preserves blank lines, headers, list items, and lines starting with uppercase.
- **`config.py`** (processamento): Centralizes editable regex patterns (`CLEANUP_PATTERNS`, `SECTION_PATTERNS`, `TAG_KEYWORDS`) for the ficha_converter pipeline.
