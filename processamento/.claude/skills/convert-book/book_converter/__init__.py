"""
book_converter - Conversor de livros para RAGFlow (pipeline LLM).

Converte livros técnicos em Markdown (gerados por OCR) para formato
otimizado para ingestão no RAGFlow usando análise LLM.

Módulos:
    models: Dataclasses (TocEntry, ChapterBoundary, BookMetadata)
    ocr_cleanup: Limpeza de artefatos OCR
    ragflow_optimize: Otimização para RAGFlow
    assembler: Montagem final do documento
    llm_analyzer: Prompt LLM + parsing JSON
    structure_applier: Aplicar estrutura identificada pelo LLM
    llm_pipeline: Pipeline de conversão LLM
"""

__version__ = "2.0.0"

from .models import TocEntry, ChapterBoundary, BookMetadata
from .ocr_cleanup import clean_all, remove_artifacts, clean_page_headers, fix_hyphenation
from .ragflow_optimize import (
    join_paragraph_lines,
    format_bullets,
    normalize_spacing,
    optimize_for_ragflow,
    format_optimize_summary,
)
from .assembler import (
    generate_id,
    generate_book_frontmatter,
    assemble_book_document,
    format_assembly_summary,
    get_output_filename,
)
from .llm_analyzer import (
    build_analysis_prompt,
    parse_llm_response,
)
from .llm_pipeline import convert_book_with_llm
from .structure_applier import apply_structure, format_structure_summary, remove_sections

__all__ = [
    # Modelos
    "TocEntry",
    "ChapterBoundary",
    "BookMetadata",
    # Limpeza OCR
    "clean_all",
    "remove_artifacts",
    "clean_page_headers",
    "fix_hyphenation",
    # Otimização RAGFlow
    "join_paragraph_lines",
    "format_bullets",
    "normalize_spacing",
    "optimize_for_ragflow",
    "format_optimize_summary",
    # Montagem final
    "generate_id",
    "generate_book_frontmatter",
    "assemble_book_document",
    "format_assembly_summary",
    "get_output_filename",
    # LLM analyzer
    "build_analysis_prompt",
    "parse_llm_response",
    # LLM pipeline
    "convert_book_with_llm",
    # Structure applier
    "apply_structure",
    "format_structure_summary",
    "remove_sections",
]
