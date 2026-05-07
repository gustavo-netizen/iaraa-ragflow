# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in `processamento/`.

## Project Overview

`processamento/` is **Stage 2** of the iaraa-ragflow pipeline. It post-processes Markdown produced by Stage 1 (DocMind, in `conversao/`) so it is ready for RAGFlow ingestion. Two converters share a canonical helper layer:

1. **Fichas Agroecológicas** — `ficha_converter/` (regex-based, 6 phases)
2. **Livros Técnicos** — `book_converter/` (LLM-powered, 6 phases — invoked via `/convert-book` skill)
3. **Shared helpers** — `shared/` (Fase B: canonical `generate_id`, `join_paragraph_lines`, `CLEANUP_PATTERNS`)

See `processamento/CONTEXT.md` for the domain vocabulary (chunk sense 1 = PDF slice vs sense 2 = RAGFlow chunk; Stage 1 vs Marco Converter; PT/EN naming convention).

## Architecture

```
processamento/
├── ficha_converter/       # Fichas Agroecológicas (regex, v1.1.0)
├── book_converter/        # Livros Técnicos (LLM-agnostic, v2.0.0)
└── shared/                # Canonical helpers (Fase B)
```

### `ficha_converter/` — Fichas Agroecológicas

Regex-based 6-phase pipeline. Run with `python -m ficha_converter`.

**Module layout:**
```
ficha_converter/
├── __init__.py        # Public exports (v1.1.0)
├── __main__.py        # Entry point (python -m ficha_converter)
├── cli.py             # Command-line interface + orchestration
├── config.py          # Ficha-specific patterns (SECTION_PATTERNS, SUBSECTION_PATTERNS, TAG_KEYWORDS)
├── cleanup.py         # Phase 1: OCR cleanup (delegates to shared/ocr_patterns.py)
├── extraction.py      # Phase 2: Metadata extraction
├── frontmatter.py     # Phase 3: YAML frontmatter (uses shared/yaml_writer.py)
├── restructure.py     # Phase 4: Markdown restructuring + assembly
└── table_injector.py  # Phase 4.5: Table injection from *_all_figures.yaml
```

**6-Phase Pipeline:**
1. **Cleanup** — removes OCR artifacts (processing metadata, page divisions, figure references)
2. **Extraction** — title (ALL CAPS), authors (`SURNAME, I. I.`), sheet number, summary
3. **YAML Frontmatter** — `id`, `tipo: ficha_agroecologica`, `titulo`, `autores`, `tags`, `resumo`
4. **Restructuring** — sections to `##`/`###` headers, numbered steps, standardized bullets
4.5. **Table Injection** — extracts tables from `<name>_all_figures.yaml` (Stage 1 sidecar) and injects them before "Referências bibliográficas"
5. **RAGFlow Optimization** — `join_paragraph_lines()` merges OCR line breaks

**Key CLI flags:**
- `--dry-run` — preview without writing
- `--clean-only` — only Phase 1
- `--test-extract` / `--test-yaml` — debug Phases 2 / 3
- `--batch` — process a directory

### `book_converter/` — Livros Técnicos (LLM-agnostic)

LLM-powered package for full books. **Locked by ADR-0002:** the package never imports an LLM SDK — it receives `llm_response: str` from a driver (the `/convert-book` skill in production).

The skill itself is defined at `.claude/skills/convert-book/SKILL.md` (prompt + driver logic). The Python package lives at `processamento/book_converter/` and is imported as `from processamento.book_converter import ...`.

**Module layout:**
```
book_converter/
├── __init__.py            # Public exports (v2.0.0)
├── models.py              # Dataclasses (TocEntry, ChapterBoundary, BookMetadata)
├── llm_analyzer.py        # Phase 1: build_analysis_prompt() + parse_llm_response()
├── structure_applier.py   # Phase 2: apply LLM-identified structure
├── ocr_cleanup.py         # Phase 3: OCR artifact removal + figure descriptions
├── llm_pipeline.py        # Phase 4: insert ## headers + _fix_chapter_headers_fallback()
├── ragflow_optimize.py    # Phase 5: join lines, bullets, spacing
└── assembler.py           # Phase 6: final assembly + get_output_filename()
```

**6-Phase Pipeline:**
```
┌─────────────────────────────────────────────────────────────┐
│  Phase 1 (LLM, via driver) — Adaptive Analysis              │
│  ├─ Extract metadata (title, authors, ISBN, year, publisher)│
│  ├─ Identify chapter structure with line positions          │
│  └─ Detect sections to remove (figures, TOC, refs, frontmtr)│
├─────────────────────────────────────────────────────────────┤
│  Phase 2 (Code) — Section Removal                           │
│  └─ Remove frontmatter, TOC, references (line-based)        │
├─────────────────────────────────────────────────────────────┤
│  Phase 3 (Code) — OCR Cleanup                               │
│  ├─ Remove Marco/DocMind artifacts (ocr_cleanup.py)         │
│  ├─ remove_figure_descriptions() — **Type:**...*Confidence:*│
│  └─ Remove headers/footers with book title                  │
├─────────────────────────────────────────────────────────────┤
│  Phase 4 (Code) — Insert Headers                            │
│  ├─ Insert ## headers at chapter titles (text search)       │
│  └─ _fix_chapter_headers_fallback() — CAPÍTULO/PARTE/etc.   │
├─────────────────────────────────────────────────────────────┤
│  Phase 5 (Code) — RAGFlow Optimization                      │
│  └─ join_paragraph_lines(), format_bullets(), spacing       │
├─────────────────────────────────────────────────────────────┤
│  Phase 6 (Code) — Assembly                                  │
│  ├─ YAML frontmatter (tipo: livro_tecnico) + final document │
│  └─ get_output_filename() — suggest filename from title     │
└─────────────────────────────────────────────────────────────┘
```

**Programmatic use** (driver responsibility — Stage 2 never calls an LLM directly):

```python
from processamento.book_converter import (
    build_analysis_prompt,
    parse_llm_response,
    convert_book_with_llm,
)

# 1. Driver builds the prompt
prompt = build_analysis_prompt(content, max_lines=500)

# 2. Driver calls its own LLM (Claude, GPT, etc.) — out of scope here
llm_response = "..."  # JSON string

# 3. Driver invokes the pipeline
document, log = convert_book_with_llm(
    content=content,
    filename="livro.md",
    llm_response=llm_response,
)
```

**LLM response schema** (driver must produce this JSON):
```json
{
  "metadados": {
    "titulo": "Título do Livro",
    "autores": ["Autor 1"],
    "editora": ["Editora"],
    "ano": 2020,
    "isbn": "978-85-0000-000-0"
  },
  "capitulos": [
    {"titulo": "INTRODUÇÃO", "linha_inicio": 45, "nivel": "chapter"}
  ],
  "remover": {
    "figuras": [[10, 15]],
    "toc": [30, 44],
    "frontmatter": [1, 29],
    "referencias": [[200, 250]]
  }
}
```

Notes on `remover`:
- `frontmatter`: `[start, end]` — credits, ficha catalográfica, license (before Prefácio)
- `toc`: `[start, end]` — Sumário/Índice
- `figuras`: `[[start, end], ...]` — figure blocks
- `referencias`: `[[start, end], ...]` — references sections (multiple allowed)

Full skill documentation: `.claude/skills/convert-book/SKILL.md`.

### `shared/` — Canonical helpers (Fase B)

Single source of truth for cross-converter logic. Both `ficha_converter` and `book_converter` import from here — never re-implement locally.

```
shared/
├── yaml_writer.py     # generate_id, transliterate, ACCENT_MAP, format_authors_display, YAML formatters
├── ragflow.py         # join_paragraph_lines, format_bullets, optimize_for_ragflow
└── ocr_patterns.py    # CLEANUP_PATTERNS (superset) + remove_artifacts
```

Key functions:
- **`generate_id(title)`** — pure ASCII slug, transliterates accents via `ACCENT_MAP` (`café → cafe`). Schema locked by ADR-0001 — no `tipo_` prefix.
- **`join_paragraph_lines(text)`** — merges lines that start with lowercase or `(`/`[` (OCR continuation). Preserves blank lines, headers, list items, and lines starting with uppercase.
- **`CLEANUP_PATTERNS`** — superset of regex patterns shared by both converters; `remove_artifacts()` applies them.

## Commands

```bash
cd processamento/

# Fichas — single file
python -m ficha_converter "input.md" -o "output.md" -v

# Fichas — batch directory
python -m ficha_converter "MD/MD systemRAG/" -o "MD/converted/" --batch -v

# Fichas — clean only (Phase 1)
python -m ficha_converter "input.md" -o "output.md" --clean-only

# Fichas — preview (dry-run)
python -m ficha_converter "input.md" -o "output.md" --dry-run -v

# Fichas — test metadata extraction (Phase 2)
python -m ficha_converter "MD/MD systemRAG/" --test-extract

# Fichas — test YAML generation (Phase 3)
python -m ficha_converter "MD/MD systemRAG/" --test-yaml

# Livros — via Claude Code skill (driver lives at .claude/skills/convert-book/)
/convert-book <input.md> [-o <output.md>] [-v]
```

## Architecture Decision Records

Locked decisions in `../docs/adr/`. Don't reopen without registering a new ADR.

- **[ADR-0001](../docs/adr/0001-id-schema-frontmatter.md)** — `id` schema (pure ASCII slug, no `tipo_` prefix) + `tipo` as closed vocabulary (`ficha_agroecologica | livro_tecnico`).
- **[ADR-0002](../docs/adr/0002-book-converter-llm-agnostic.md)** — `book_converter` is LLM-agnostic; never imports an LLM SDK.
- **[ADR-0003](../docs/adr/0003-progress-storage-json-filelock.md)** — Stage 1 progress storage stays JSON + FileLock.

## RAGFlow Integration

RAGFlow recognizes Markdown headers (`## `, `### `) natively as chunk delimiters — no custom markers needed.

| Document type | Delimiter | Reason |
|--------------|-----------|--------|
| Fichas | *(none)* | Small enough for automatic token-based chunking |
| Livros | `## ` | Chapter-level chunking |

`join_paragraph_lines()` merges OCR line breaks (caused by PDF page width) to prevent fragmented chunks. Internal `---` separators are removed; only the YAML frontmatter delimiter remains.

## Output Format

Both converters produce Markdown with YAML frontmatter (schema locked by ADR-0001) and `##`/`###` headers in the body:

```yaml
---
id: biofertilizante_vairo
tipo: ficha_agroecologica         # closed vocabulary
titulo: Biofertilizante Vairo
autores: [C. D. Leite, A. L. Meira]
tags: [agroecologia, biofertilizante]
resumo: Técnica de produção...
---
```

```markdown
# Título do Documento

> Autores: C. D. Leite e A. L. Meira

## Ingredientes

* Esterco bovino fresco (2 kg)

## Como Preparar

### 1º passo

Misturar os ingredientes...
```

## Tests

Tests live at the repo root in `tests/`:

```bash
pytest tests/                                   # Full suite (155 passed, 0 xfail)
pytest tests/test_snapshot.py                   # Stage-2 goldens (ficha + livro)
UPDATE_GOLDENS=1 pytest tests/test_snapshot.py  # Re-baseline (commit message must justify)
```
