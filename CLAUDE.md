# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**iaraa-ragflow** is a two-stage pipeline for converting agricultural PDFs into Markdown optimized for RAGFlow (Retrieval-Augmented Generation). The documents are Brazilian agricultural publications: technical sheets ("Fichas Agroecológicas") and full books ("Livros Técnicos").

**Stage 1 — `conversao/` (DocMind):** Converts raw PDFs to Markdown + YAML metadata using Alibaba's Qwen-VL API with concurrent OCR/VLM processing.

**Stage 2 — `processamento/`:** Post-processes the OCR-generated Markdown to be RAGFlow-ready: cleans artifacts, extracts metadata, generates YAML frontmatter, restructures content with `##`/`###` headers.

The codebase is in active refactoring — see `PLANO_REFATORACAO.md` for the current sprint and `docs/adr/` for locked architectural decisions.

## Architecture

```
PDF ──► conversao/ (DocMind)     ──► Raw Markdown + YAML
        Qwen-VL OCR + LLM            per-page extraction

    ──► processamento/           ──► RAGFlow-optimized Markdown
        ficha_converter/  (regex)     YAML frontmatter + ##/### headers
        book_converter/   (LLM)
        shared/                       (canonical generate_id, join_paragraph_lines, …)
```

### conversao/ — PDF to Markdown (DocMind)

Orchestrated by `run.sh`. Pipeline: split large PDFs → OCR (qwen-vl-plus) → LLM extraction (qwen-vl-max) → retry failed pages → merge chunks → post-process → quality report → final delivery check.

Key design: 3-page context window for cross-page references, multi-API-key load balancing with health monitoring, page-level checkpoint/resume in `progress.json` + filelock.

**Module layout** (post-refactor):
- `conversao/orchestrator.py` (Fase G) — single-file Python entry-point with `Pipeline.status()` and `Pipeline.run()` (Steps 1–9 via subprocess + tee streaming). CLI: `python orchestrator.py {status,run} [...]`. `run.sh` is now a thin shell wrapper around it.
- `conversao/docmind/` (Fase D) — `retry.py`, `api_key_pool.py`, `qwen_client.py`, `page_processor.py`, `pipeline.py`, `document.py` (Stage-1 dataclass per PDF + chunks, with `discover()` / `is_complete()` / `failed_pages()` / `apply_page_offset()`).
- `conversao/scripts/` — pipeline scripts at top level (`docmind_converter.py` is now a thin shim re-exporting `docmind.*`); utilities under `scripts/admin/`.
- `conversao/validation/` (Fase F) — pluggable `Checker`s (`StructureChecker`, `ContentSyntaxChecker`, `MarkdownChecker`, `QualityChecker`, `ElementChecker`, `MarcoChecker`) + `cost.py` + `report.py`. Consumed by `final_delivery_check.py` and `generate_quality_report.py` shims.
- `conversao/scripts/config.py` — `AppConfig` (frozen dataclass, `from_env()`); env vars `DOCMIND_OCR_MODEL`, `DOCMIND_LLM_MODEL`, `DOCMIND_RETRY_*`, `DOCMIND_HEALTH_*`, `DOCMIND_REQUEST_TIMEOUT`.

See `conversao/CLAUDE.md` for detailed commands and the legacy architecture description.

### processamento/ — Markdown optimization for RAGFlow

Two converters for two document types, sharing canonical helpers under `processamento/shared/`:

- **`ficha_converter/`** — Regex-based 6-phase pipeline for Fichas Agroecológicas. Run with `python -m ficha_converter`.
- **`book_converter/`** — LLM-powered 6-phase pipeline for full books. Invoked via `/convert-book` skill (the skill is defined at `.claude/skills/convert-book/SKILL.md` but the package itself lives at `processamento/book_converter/` and is imported as `from processamento.book_converter import ...`). LLM-agnostic by ADR-0002 — the package never imports an LLM SDK; it receives `llm_response: str` from the skill driver.
- **`shared/`** (Fase B) — `yaml_writer.py` (canonical `generate_id`, `transliterate`, `format_authors_display`, YAML formatters), `ragflow.py` (`join_paragraph_lines`, `format_bullets`, `optimize_for_ragflow`), `ocr_patterns.py` (`CLEANUP_PATTERNS` superset + `remove_artifacts`).

See `processamento/CLAUDE.md` for detailed commands, pipeline phases, and LLM response format. See `processamento/CONTEXT.md` for the domain vocabulary (chunk sense 1 = PDF slice vs sense 2 = RAGFlow chunk; Stage 1 vs Marco Converter; PT/EN naming convention).

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

### Tests (root)

```bash
pytest tests/                       # Full suite (202 passed, 0 xfail)
pytest tests/test_snapshot.py       # Stage-2 goldens (ficha + livro)
UPDATE_GOLDENS=1 pytest tests/test_snapshot.py   # Re-baseline after intentional changes
```

After every structural change in Fases B–G, `pytest tests/` must pass before commit. Goldens are re-baselined only with an explicit justification in the commit message.

## Key Patterns

- **API keys** (conversao): Priority is `api/keys.txt` > `.env` > env vars. Python scripts only read env vars; `run.sh` converts `keys.txt` to env vars automatically.
- **Output format**: Each document gets YAML frontmatter (`---` delimited) + Markdown body with `##`/`###` headers. Frontmatter carries `tipo: ficha_agroecologica | livro_tecnico` (closed vocabulary, ADR-0001) and `id` as a pure ASCII slug — no `tipo_` prefix.
- **`generate_id`**: single canonical implementation in `processamento/shared/yaml_writer.py`. Transliterates accents via `ACCENT_MAP` (`café → cafe`). Imported by both ficha and book converters — never re-implement locally.
- **`join_paragraph_lines()`**: Joins lines starting with lowercase or `(`/`[` (OCR continuation). Preserves blank lines, headers, list items, and lines starting with uppercase. Canonical implementation in `processamento/shared/ragflow.py`.
- **`config.py`** (`processamento/ficha_converter/`): only ficha-specific patterns (`SECTION_PATTERNS`, `SUBSECTION_PATTERNS`, `TAG_KEYWORDS`). `CLEANUP_PATTERNS` and `ACCENT_MAP` live in `processamento/shared/` and are used by both converters.
- **ADRs** in `docs/adr/`: ADR-0001 (id schema + `tipo`), ADR-0002 (book_converter LLM-agnostic), ADR-0003 (progress storage stays JSON+FileLock), ADR-0004 (footnotes em sidecar YAML). Don't reopen without registering a new ADR.
- **Footnotes sidecar** (Fase J, ADR-0004): Stage 1 emite `<pdf_name>.footnotes.yaml` ao lado do `<pdf_name>_all_figures.yaml`. Schema flat `notes: [{page, id, text}]`, emissão incondicional. `book_converter.convert_book_with_llm` aceita `footnotes_yaml_path: Path | None` + `inline_notes: Literal["none","useful","all"]` (default `"none"` — body limpo). `processamento/shared/footnote_filter.py:is_substantive_footnote` é a fonte única da heurística "<5 chars alfabéticos = ruído", reusada por J.0 cleanup e J.3 render.
- **MARCO Quality Gate** (post-J fix, 2026-05-12): Step 5.5 in `orchestrator.py` (`_step4_5_quality_gate`) reads `output/*/{name}.validation.yaml` after merge; aborts pipeline (`rc=1`, `progress.json` stays `in_progress`) if any PDF has `kqi_metrics.overall_quality_pass=false` (thresholds: `yaml_insertion ≥ 95%`, `avg_confidence ≥ 0.85`, `page_success ≥ 95%`). Bypass with `./run.sh --no-quality-gate`. `MarcoChecker` (Step 8) has a strict mode that reads the same data and reports KQI violations even when the gate was bypassed. Reason: silent failure where 27/78 pages failed throttling but pipeline marked `completed` and propagated incomplete MD to `final-delivery/`.
- **Refactor status**: `PLANO_REFATORACAO.md` tracks phases. **Fases 0–J all done** on branch `refactor/fase-d-split-docmind` (suite 202 passed, zero xfail). `conversao/orchestrator.py` is the Python entry-point; `run.sh` (~207 lines) handles only env loading, monitor daemon, and the `--history`/`--no-quality-gate` shortcuts, then delegates to `python orchestrator.py run [...]`. Live end-to-end smoke (`./run.sh --restart` with real PDFs + API keys) is the only remaining pre-merge gate — especially after J.2 (única fase a tocar Stage 1 sem snapshot estabelecido).
