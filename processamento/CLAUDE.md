# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project optimizes Markdown files from "systemRAG" (OCR-generated via DocMind/Marco Converter) for ingestion into RAGFlow. There are two types of documents:

1. **Fichas Agroecológicas** - Technical agricultural sheets from the Brazilian Ministry of Agriculture (use `ficha_converter/`)
2. **Livros técnicos** - Full technical books in PDF converted to Markdown (use `/convert-book` skill)

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

### Livros Técnicos (/convert-book)

Livros técnicos são processados exclusivamente via skill `/convert-book`, que usa análise LLM para extrair metadados, identificar capítulos e remover seções irrelevantes.

```
/convert-book <input.md> [-o <output.md>] [-v]
```

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
│  └─ normalize_spacing()                                     │
├─────────────────────────────────────────────────────────────┤
│  FASE 6 (Código) - Assembly                                 │
│  ├─ Gerar YAML frontmatter + documento final                │
│  └─ get_output_filename() - sugerir nome baseado no título  │
└─────────────────────────────────────────────────────────────┘
```

**Correções Automáticas:**

| Função | Descrição |
|--------|-----------|
| `remove_figure_descriptions()` | Remove blocos `**Type:**`...`*Confidence:*` gerados pelo OCR |
| `_fix_chapter_headers_fallback()` | Detecta CAPÍTULO/PARTE/APRESENTAÇÃO/PREFÁCIO e adiciona `##` |
| `get_output_filename()` | Sugere nome de arquivo baseado no título extraído |

**Uso programático:**
```python
from book_converter.llm_pipeline import convert_book_with_llm
from book_converter.llm_analyzer import build_analysis_prompt, parse_llm_response

# 1. Gerar prompt para análise
prompt = build_analysis_prompt(content, max_lines=500)

# 2. Obter resposta do LLM (JSON com metadados, capítulos, seções)
llm_response = "..."  # JSON do LLM

# 3. Executar pipeline
document, log = convert_book_with_llm(
    content=content,
    filename="livro.md",
    llm_response=llm_response,
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

Modular Python package for converting Fichas Agroecológicas. Six-phase pipeline organized in 5 modules:

**Module structure:**
```
ficha_converter/
├── __init__.py       # Public exports (v1.1.0)
├── __main__.py       # Entry point
├── cli.py            # Command-line interface
├── config.py         # Editable constants (patterns, keywords)
├── cleanup.py        # Phases 1, 5: OCR cleanup + RAGFlow optimization
├── extraction.py     # Phase 2: Metadata extraction
├── frontmatter.py    # Phase 3: YAML frontmatter generation
├── restructure.py    # Phase 4: Markdown restructuring + assembly
└── table_injector.py # Phase 4.5: Table injection from YAML
```

**6-Phase Pipeline:**
1. **Phase 1 - Cleanup**: Removes OCR artifacts (processing metadata, page divisions, figure references)
2. **Phase 2 - Extraction**: Extracts title (ALL CAPS line), authors (SURNAME, I. I. format), sheet number, summary
3. **Phase 3 - YAML Frontmatter**: Generates id, titulo, autores, tags, resumo
4. **Phase 4 - Restructuring**: Converts sections to markdown headers (##, ###), formats numbered steps, standardizes bullets
4.5. **Phase 4.5 - Table Injection**: Extracts tables from `*_all_figures.yaml` and injects into body (see below)
5. **Phase 5 - RAGFlow Optimization**: `join_paragraph_lines()` merges OCR line breaks to prevent small chunks

**Table Injector (Phase 4.5):**
Extracts tables from YAML files generated by Marco Converter and injects them into the document body.

- `find_yaml_file()` - Locates `[name]_all_figures.yaml` in same directory as MD
- `load_tables_from_yaml()` - Loads entries with `image_type: table`, sorted by page number
- `format_table_section()` - Converts table to RAG-optimized markdown format
- `inject_tables_in_body()` - Inserts formatted tables before "Referências bibliográficas"
- `translate_to_portuguese()` - Translates English descriptions to Portuguese

Output format for each table:
```markdown
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

### book_converter/ - Livros Técnicos (LLM pipeline)

LLM-powered package for converting full books. Uses Claude for adaptive structure analysis instead of regex.

**Module structure:**
```
.claude/skills/convert-book/
├── SKILL.md                 # Skill definition for /convert-book
└── book_converter/          # Package for Livros Técnicos (v2.0.0)
    ├── __init__.py          # Public exports
    ├── models.py            # Dataclasses (TocEntry, ChapterBoundary, BookMetadata)
    ├── ocr_cleanup.py       # OCR artifact removal + figure descriptions
    ├── ragflow_optimize.py  # RAGFlow optimization (join lines, bullets, spacing)
    ├── assembler.py         # Final document assembly + get_output_filename()
    ├── llm_analyzer.py      # LLM prompt generation + JSON parsing
    ├── structure_applier.py # Apply LLM-identified structure
    └── llm_pipeline.py      # LLM pipeline + _fix_chapter_headers_fallback()
```

### RAGFlow Integration

RAGFlow recognizes Markdown headers (`## `, `### `) natively as chunk delimiters — no custom markers needed.

**Delimiter configuration:**
- **Fichas**: No delimiter needed — fichas are small enough for RAGFlow's automatic token-based chunking
- **Books**: Configure delimiter as `## ` for chapter-level chunking, or `### ` for section-level

Key implications:
- Internal `---` separators removed (only YAML frontmatter keeps them)
- Line breaks from PDF page width cause fragmented chunks — solved by `join_paragraph_lines()`
- Headers `##` and `###` serve as natural chunk boundaries recognized by RAGFlow

### Directory Structure

```
.
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
├── .claude/
│   └── skills/
│       └── convert-book/        # Skill: /convert-book
│           ├── SKILL.md         # Skill definition
│           └── book_converter/  # Package for Livros Técnicos (v2.0.0)
│               ├── __init__.py
│               ├── models.py
│               ├── ocr_cleanup.py       # + remove_figure_descriptions()
│               ├── ragflow_optimize.py
│               ├── assembler.py         # + get_output_filename()
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

RAGFlow natively recognizes Markdown headers as chunk delimiters:
- Configure `## ` as delimiter for chapter-level chunks (books)
- Configure `### ` for finer section-level chunks
- Fichas are small enough for automatic token-based chunking
