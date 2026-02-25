# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project optimizes Markdown files from "systemRAG" (OCR-generated via Marco Converter) for ingestion into RAGFlow. There are two types of documents:

1. **Fichas Agroecológicas** - Technical agricultural sheets from the Brazilian Ministry of Agriculture (use `ficha_converter/`)
2. **Livros técnicos** - Full technical books in PDF converted to Markdown (use `book_converter/`)

## Key Commands

### Fichas Agroecológicas (ficha_converter/)

```bash
# Convert single file (full pipeline)
python -m ficha_converter "MD/MD systemRAG/10-biofertilizante-vairo-1.md" -o "output.md" -v

# Batch convert directory
python -m ficha_converter "MD/MD systemRAG/" -o "MD/converted/" --batch -v

# Clean only (Phase 1, no restructuring)
python -m ficha_converter "arquivo.md" -o "saida.md" --clean-only

# Preview without writing (dry-run)
python -m ficha_converter "arquivo.md" -o "saida.md" --dry-run -v

# Test metadata extraction (Phase 2)
python -m ficha_converter "MD/MD systemRAG/" --test-extract

# Test YAML frontmatter generation (Phase 3)
python -m ficha_converter "MD/MD systemRAG/" --test-yaml
```

### Livros Técnicos (book_converter/)

```bash
# Using wrapper script (recommended)
python book_converter.py "Teste/Teste SystemRAG/AGROECOLOGIABASES_2019.md" -o "output.md" -v

# Or with PYTHONPATH (module is in .claude/skills/convert-book/)
PYTHONPATH=.claude/skills/convert-book python -m book_converter "Teste/Teste SystemRAG/AGROECOLOGIABASES_2019.md" -o "output.md" -v

# Clean OCR artifacts only (Phase 1)
python -m book_converter "input.md" -o "output.md" --clean-only -v

# Extract and display TOC (Phase 2)
python -m book_converter "input.md" --extract-only

# Test metadata extraction (Phase 3)
python -m book_converter "input.md" --test-metadata

# Test chapter detection (Phase 4)
python -m book_converter "input.md" --test-chapters

# Test restructuring (Phase 5)
python -m book_converter "input.md" --test-restructure -v

# Test RAGFlow optimization (Phase 6)
python -m book_converter "input.md" --test-optimize -v

# Full pipeline with options
python -m book_converter "input.md" -o "output.md" --chunk-level 3 -v
python -m book_converter "input.md" -o "output.md" --no-frontmatter -v

# Batch process directory
python -m book_converter "input_dir/" -o "output_dir/" --batch -v
```

### Post-Processing Scripts

Scripts for cleaning processed books before RAGFlow ingestion:

```bash
# Remove SUMÁRIO/ÍNDICE sections from processed books
python remove_sumario.py "/path/to/Livros_Processados/"

# Remove REFERÊNCIAS/BIBLIOGRAFIA sections from processed books
python remove_referencias.py "/path/to/Livros_Processados/"
```

**`remove_sumario.py`** - Removes table of contents/index sections:
- Detects: `SUMÁRIO`, `ÍNDICE`, `## SUMÁRIO`, `## ÍNDICE`, `ÍNDICE ONOMÁSTICO`
- Preserves: `SUMÁRIO EXECUTIVO` (legitimate content, not navigation)
- Uses line-by-line processing to avoid regex backtracking

**`remove_referencias.py`** - Removes bibliography/references sections:
- Detects: `## Referências`, `## Bibliografia`, `## Referências bibliográficas`
- Handles variants like `## Referências: Quer saber mais?`
- Ignores TOC entries (lines ending with `...`)
- Removes orphan `§` markers left after removal

**Execution history:** See `PLANO_REMOVER_SUMARIO_REFERENCIAS.md` for detailed results.

### Skill: /convert-book (LLM-powered)

Skill que usa LLM para análise adaptativa de estrutura de livros, substituindo a detecção baseada em regex do `book_converter` tradicional.

```
/convert-book <input.md> [-o <output.md>] [-v]
```

**Vantagens sobre book_converter (regex):**
| Aspecto | book_converter | /convert-book |
|---------|----------------|---------------|
| Detecção de metadados | ~60% (regex) | ~95% (LLM) |
| Detecção de capítulos | Depende de TOC | Independente |
| Novos formatos | Requer código | Automático |
| Manutenção | Alta | Baixa |

**Pipeline (6 fases):**
```
┌─────────────────────────────────────────────────────────────┐
│  FASE 1 (LLM) - Análise Adaptativa                          │
│  ├─ Extrair metadados (título, autores, ISBN, ano, editora) │
│  ├─ Identificar estrutura de capítulos com posições         │
│  └─ Detectar seções para remover (figuras, TOC, refs, front)│
├─────────────────────────────────────────────────────────────┤
│  FASE 2 (Código) - Remover Seções                           │
│  └─ Remover frontmatter, TOC, refs (linhas do original)     │
├─────────────────────────────────────────────────────────────┤
│  FASE 3 (Código) - Limpeza OCR                              │
│  ├─ Remover artefatos Marco/DocMind (ocr_cleanup.py)        │
│  ├─ remove_figure_descriptions() - blocos **Type:**...*Conf*│
│  └─ Remover headers/footers com título do livro             │
├─────────────────────────────────────────────────────────────┤
│  FASE 4 (Código) - Inserir Headers                          │
│  ├─ Inserir ## headers nos capítulos por busca de título    │
│  └─ _fix_chapter_headers_fallback() - CAPÍTULO/PARTE/etc.   │
├─────────────────────────────────────────────────────────────┤
│  FASE 5 (Código) - RAGFlow Optimization                     │
│  ├─ join_paragraph_lines(), format_bullets()                │
│  └─ insert_section_markers() (§)                            │
├─────────────────────────────────────────────────────────────┤
│  FASE 6 (Código) - Assembly                                 │
│  ├─ Gerar YAML frontmatter + documento final                │
│  └─ get_output_filename() - sugerir nome baseado no título  │
└─────────────────────────────────────────────────────────────┘
```

**Correções Automáticas (v1.0.3):**

O pipeline inclui correções que não requerem intervenção manual:

| Função | Descrição |
|--------|-----------|
| `remove_figure_descriptions()` | Remove blocos `**Type:**`...`*Confidence:*` gerados pelo OCR |
| `_fix_chapter_headers_fallback()` | Detecta CAPÍTULO/PARTE/APRESENTAÇÃO/PREFÁCIO e adiciona `##` |
| `get_output_filename()` | Sugere nome de arquivo baseado no título extraído |

**Módulos LLM (novos):**
```
.claude/skills/convert-book/book_converter/
├── llm_analyzer.py      # Prompt LLM + parsing JSON
├── structure_applier.py # Aplicar estrutura do LLM
└── llm_pipeline.py      # Pipeline integrado
```

**Uso programático:**
```python
from book_converter.llm_pipeline import convert_book_with_llm, get_analysis_prompt

# 1. Gerar prompt para análise
prompt = get_analysis_prompt(content, max_lines=500)

# 2. Obter resposta do LLM (JSON com metadados, capítulos, seções)
llm_response = "..."  # JSON do LLM

# 3. Executar pipeline
document, log = convert_book_with_llm(
    content=content,
    filename="livro.md",
    llm_response=llm_response,
    chunk_level=2
)
```

**Formato da resposta LLM:**
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

**Notas sobre `remover`:**
- `frontmatter`: [inicio, fim] - Créditos, ficha catalográfica, licença (antes do Prefácio)
- `toc`: [inicio, fim] - Sumário/Índice
- `figuras`: [[inicio, fim], ...] - Blocos de figuras
- `referencias`: [[inicio, fim], ...] - Seções de referências (pode haver múltiplas)

**Documentação completa:** `.claude/skills/convert-book/SKILL.md`

## Architecture

### ficha_converter/ - Fichas Agroecológicas

Modular Python package for converting Fichas Agroecológicas. Seven-phase pipeline organized in 5 modules:

**Module structure:**
```
ficha_converter/
├── __init__.py       # Public exports (v1.1.0)
├── __main__.py       # Entry point
├── cli.py            # Command-line interface
├── config.py         # Editable constants (patterns, keywords)
├── cleanup.py        # Phases 1, 5, 6: OCR cleanup + RAGFlow optimization
├── extraction.py     # Phase 2: Metadata extraction
├── frontmatter.py    # Phase 3: YAML frontmatter generation
├── restructure.py    # Phase 4: Markdown restructuring + assembly
└── table_injector.py # Phase 4.5: Table injection from YAML
```

**7-Phase Pipeline:**
1. **Phase 1 - Cleanup**: Removes OCR artifacts (processing metadata, page divisions, figure references)
2. **Phase 2 - Extraction**: Extracts title (ALL CAPS line), authors (SURNAME, I. I. format), sheet number, summary
3. **Phase 3 - YAML Frontmatter**: Generates id, titulo, autores, tags, resumo
4. **Phase 4 - Restructuring**: Converts sections to markdown headers (##, ###), formats numbered steps, standardizes bullets
4.5. **Phase 4.5 - Table Injection**: Extracts tables from `*_all_figures.yaml` and injects into body (see below)
5. **Phase 5 - RAGFlow Optimization**: `join_paragraph_lines()` merges OCR line breaks to prevent small chunks
6. **Phase 6 - Section Markers**: `insert_section_markers()` adds `§` before each `##` header for chunk delimiting

**Table Injector (Phase 4.5):**
Extracts tables from YAML files generated by Marco Converter and injects them into the document body.

- `find_yaml_file()` - Locates `[name]_all_figures.yaml` in same directory as MD
- `load_tables_from_yaml()` - Loads entries with `image_type: table`, sorted by page number
- `format_table_section()` - Converts table to RAG-optimized markdown format
- `inject_tables_in_body()` - Inserts formatted tables before "Referências bibliográficas"
- `translate_to_portuguese()` - Translates English descriptions to Portuguese

Output format for each table:
```markdown
§
### [Table Title]

[Description translated to Portuguese]

**Itens:**
* item1
* item2

**Insight:** [Key insight translated to Portuguese]
```

Development history: See `PLANO_TABLE_INJECTOR.md` for implementation details.

**Key CLI flags:**
- `--dry-run` - Preview without writing files
- `--clean-only` - Only Phase 1 cleanup
- `--test-extract` - Test metadata extraction
- `--test-yaml` - Test YAML frontmatter generation

**Editable config:** `config.py` contains `CLEANUP_PATTERNS`, `TAG_KEYWORDS`, `SECTION_PATTERNS` for easy customization.

### book_converter/ - Livros Técnicos

Modular Python package for converting full books. **Complete implementation** with 7-phase pipeline.

**Module structure:**
```
.claude/skills/convert-book/
├── SKILL.md                 # Skill definition for /convert-book
└── book_converter/          # Package for Livros Técnicos (v1.0.3)
    ├── __init__.py          # Public exports
    ├── __main__.py          # Entry point
    ├── cli.py               # Command-line interface
    ├── models.py            # Dataclasses (TocEntry, ChapterBoundary, BookMetadata)
    ├── ocr_cleanup.py       # Phase 1: OCR artifact removal + figure descriptions
    ├── toc_parser.py        # Phase 2: TOC extraction
    ├── metadata.py          # Phase 3: Book metadata extraction
    ├── chapter_detection.py # Phase 4: Chapter boundary detection
    ├── restructure.py       # Phase 5: Markdown header insertion
    ├── ragflow_optimize.py  # Phase 6: RAGFlow optimization
    ├── assembler.py         # Phase 7: Final document assembly + get_output_filename()
    ├── pipeline.py          # Full pipeline orchestration
    │
    │   # LLM-powered modules (for /convert-book skill)
    ├── llm_analyzer.py      # LLM prompt generation + JSON parsing
    ├── structure_applier.py # Apply LLM-identified structure
    └── llm_pipeline.py      # LLM pipeline + _fix_chapter_headers_fallback()
```

**7-Phase Pipeline:**
1. **Phase 1 - OCR Cleanup**: Removes Marco Converter metadata, `## Page X` markers, spaced headers
2. **Phase 2 - TOC Extraction**: Parses table of contents, removes from body
3. **Phase 3 - Metadata**: Extracts title, authors, ISBN, publisher, year from CIP block
4. **Phase 4 - Chapter Detection**: Locates chapter boundaries using TOC entries
5. **Phase 5 - Restructuring**: Inserts `#` for parts, `##` for chapters, converts ALL CAPS to Title Case
6. **Phase 6 - RAGFlow Optimization**: Joins paragraph lines, standardizes bullets, inserts `§` markers
7. **Phase 7 - Assembly**: Generates YAML frontmatter, assembles final document

**Key CLI flags:**
- `--chunk-level {1,2,3}` - Chunking granularity (1=parts, 2=chapters, 3=sections)
- `--no-frontmatter` - Skip YAML frontmatter generation
- `--keep-toc` - Keep table of contents in output (not recommended)

**Development history:** See `PLANO_BOOK_CONVERTER.md` for completed 7-sprint roadmap.

**Bugfixes (v1.0.1):** See `PLANO_BUGFIX_BOOK_CONVERTER.md` for details on 4 critical fixes:
1. Content loss fix in `metadata.py:locate_frontmatter_end()` - limited search to first 10k chars
2. Page footer removal in `ocr_cleanup.py:remove_page_footers()` - removes "TITLE    123" patterns
3. Title extraction fix in `metadata.py:_is_likely_author_name()` - filters author names from title candidates
4. Header position fix in `restructure.py:remove_frontmatter_from_body()` - correct offset calculation

**Bugfixes (v1.0.2):** TOC parsing and footer removal improvements:
5. TOC isolated chapter numbers in `toc_parser.py:_preprocess_toc_text()` - joins chapter numbers on separate lines (e.g., "1\nCONTEXTUALIZAÇÃO...17" -> "1 CONTEXTUALIZAÇÃO...17")
6. Footer regex fix in `ocr_cleanup.py:remove_page_footers()` - changed `\s` to `[ \t]` to prevent matching across newlines (was removing "ÍNDICE" along with footers)

**Enhancements (v1.0.3):** Automatic corrections for LLM pipeline:
7. `remove_figure_descriptions()` in `ocr_cleanup.py` - removes `**Type:**`...`*Confidence:*` blocks from Marco Converter
8. `_fix_chapter_headers_fallback()` in `llm_pipeline.py` - detects CAPÍTULO/PARTE/APRESENTAÇÃO/PREFÁCIO patterns and adds `##` headers
9. `get_output_filename()` in `assembler.py` - suggests output filename based on extracted title
10. Improved `_insert_chapter_headers_by_title()` - stricter matching to avoid false positives on credit lines

### RAGFlow Integration

**Delimiter configuration:** Use `` `§` `` (with backticks) in RAGFlow's delimiter field.

The backticks make RAGFlow treat `§` as a literal multi-character delimiter (see `naive_merge` in `__init__.py` lines 1092-1110). Each `§` creates a chunk boundary, and the marker is removed from the final chunks.

Key implications:
- Internal `---` separators removed (only YAML frontmatter keeps them)
- Line breaks from PDF page width cause fragmented chunks - solved by `join_paragraph_lines()`
- Section markers (`§`) create one chunk per `##` section
- Headers `###` (subsections) stay within parent `##` chunk

### Reference Files

- `naive.py`, `parser.py`, `chunker.txt` - RAGFlow source code for analysis
- `PLANO_BOOK_CONVERTER.md` - Implementation plan for book_converter (Livros)
- `PLANO_TABLE_INJECTOR.md` - Implementation plan for table_injector (Fichas)
- `PLANO_REMOVER_SUMARIO_REFERENCIAS.md` - Plan and results for post-processing scripts
- `PLANO_SKILL_CONVERT_BOOK.md` - Implementation plan for /convert-book skill (LLM)
- `book_conversion_analysis.json` - Analysis of book conversion challenges and requirements

### Directory Structure

```
.
├── converter.py          # DEPRECATED - use ficha_converter instead
├── remove_sumario.py     # Post-processing: remove TOC/index sections
├── remove_referencias.py # Post-processing: remove bibliography sections
├── ficha_converter/      # Package for Fichas Agroecológicas (v1.1.0)
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── cleanup.py
│   ├── extraction.py
│   ├── frontmatter.py
│   ├── restructure.py
│   └── table_injector.py # Phase 4.5: Table injection from YAML
├── book_converter.py     # Wrapper script for book_converter package
├── .claude/
│   └── skills/
│       └── convert-book/        # Skill: /convert-book
│           ├── SKILL.md         # Skill definition
│           └── book_converter/  # Package for Livros Técnicos (v1.0.3)
│               ├── __init__.py
│               ├── __main__.py
│               ├── cli.py
│               ├── models.py
│               ├── ocr_cleanup.py       # + remove_figure_descriptions()
│               ├── toc_parser.py
│               ├── metadata.py
│               ├── chapter_detection.py
│               ├── restructure.py
│               ├── ragflow_optimize.py
│               ├── assembler.py         # + get_output_filename()
│               ├── pipeline.py
│               ├── llm_analyzer.py      # LLM: prompt + parsing
│               ├── structure_applier.py # LLM: apply structure
│               └── llm_pipeline.py      # LLM: pipeline + fallback headers
├── MD/
│   ├── MD systemRAG/     # Input: OCR-generated Fichas (raw)
│   ├── MD Maria/         # Reference: manually formatted Fichas
│   └── converted/        # Output: processed Fichas for RAGFlow
└── Teste/
    ├── Teste SystemRAG/  # Input: OCR-generated books (raw)
    └── Teste RAGFlow/    # Output: processed books for RAGFlow
```

### External Directories

**Livros Processados (batch processed):**
```
/home/gustavo/Downloads/results_md_yaml/Livros/
├── [68 folders with original + processed books]
└── Livros_Processados/   # 76 processed books (Lote 1)
    └── Processado_*.md   # Ready for RAGFlow ingestion

/home/gustavo/Downloads/results_md_yaml/Livros_2/
└── Livros_Processados_2.1/  # 20 processed books (Lote 2)
    └── *.md                  # Ready for RAGFlow ingestion
```

**Batch Processing Stats (2026-01-15):**

| Lote | Arquivos | Tamanho Original |
|------|----------|------------------|
| Livros_Processados | 76 | ~29 MB |
| Livros_Processados_2.1 | 20 | ~9.5 MB |
| **Total** | **96** | **~38.5 MB** |

**Post-Processing (Sumário + Referências removal):**
- Sumário/Índice removido: ~76 KB
- Referências removidas: ~10.8 MB (97 seções)
- **Total removido: ~10.9 MB**

## Important Patterns

The `join_paragraph_lines()` function joins continuation lines that:
- Start with lowercase letter (sentence continuation)
- Start with `(` or `[` (parenthetical complement)

It preserves:
- Blank lines (paragraph separators)
- Headers (#, ##, ###)
- List items (*, -, •)
- Lines starting with uppercase (new paragraph)

The `insert_section_markers()` function:
- Adds `§` marker before each `##` header (not `###`)
- Enables RAGFlow to chunk by section when using `` `§` `` as delimiter
- Subsections (`###`) remain in the same chunk as their parent `##`
