"""
ficha_converter - Conversor de Fichas Agroecológicas para RAGFlow.

Converte arquivos Markdown de Fichas Agroecológicas (gerados por OCR)
para formato otimizado para ingestão no RAGFlow.

Uso:
    python -m ficha_converter input.md -o output.md [opções]

Módulos:
    cleanup: Limpeza de artefatos OCR e otimização RAGFlow (Fases 1, 5)
    extraction: Extração de metadados (Fase 2)
    frontmatter: Geração de YAML frontmatter (Fase 3)
    restructure: Reestruturação markdown (Fase 4)
"""

__version__ = "1.0.0"

# Cleanup (Fases 1, 5)
from .cleanup import (
    remove_artifacts,
    clean_empty_lines,
    clean_all,
    join_paragraph_lines,
    normalize_punctuation,
    optimize_for_ragflow,
)

# Extraction (Fase 2)
from .extraction import (
    extract_title,
    extract_authors,
    extract_ficha_number,
    extract_resumo,
    extract_all,
    format_extraction_summary,
)

# Frontmatter (Fase 3)
from .frontmatter import (
    normalize_tag,
    generate_id,
    generate_tags,
    generate_frontmatter,
    test_frontmatter,
)

# Restructure (Fase 4)
from .restructure import (
    restructure_sections,
    format_steps,
    format_bullets,
    extract_body,
    format_authors_display,
    assemble_document,
)

# CLI
from .cli import (
    convert_full,
    process_file,
    process_directory,
)

# Table Injector (Fase 4.5)
from .table_injector import (
    find_yaml_file,
    load_tables_from_yaml,
    format_table_section,
    inject_tables_in_body,
)

__all__ = [
    # Cleanup
    "remove_artifacts",
    "clean_empty_lines",
    "clean_all",
    "join_paragraph_lines",
    "normalize_punctuation",
    "optimize_for_ragflow",
    # Extraction
    "extract_title",
    "extract_authors",
    "extract_ficha_number",
    "extract_resumo",
    "extract_all",
    "format_extraction_summary",
    # Frontmatter
    "normalize_tag",
    "generate_id",
    "generate_tags",
    "generate_frontmatter",
    "test_frontmatter",
    # Restructure
    "restructure_sections",
    "format_steps",
    "format_bullets",
    "extract_body",
    "format_authors_display",
    "assemble_document",
    # CLI
    "convert_full",
    "process_file",
    "process_directory",
    # Table Injector
    "find_yaml_file",
    "load_tables_from_yaml",
    "format_table_section",
    "inject_tables_in_body",
]
