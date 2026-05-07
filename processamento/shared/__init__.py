"""
processamento.shared — funções e constantes compartilhadas entre os
converters de Ficha Agroecológica e Livro Técnico.

Existe para que `generate_id`, `join_paragraph_lines`, `format_authors_display`
e `CLEANUP_PATTERNS` tenham uma única implementação canônica. Decisões
de schema e vocabulário em docs/adr/ e processamento/CONTEXT.md.
"""

from .yaml_writer import (
    ACCENT_MAP,
    transliterate,
    generate_id,
    format_yaml_value,
    format_yaml_list,
    format_authors_display,
)
from .ragflow import (
    join_paragraph_lines,
    format_bullets,
    normalize_spacing,
    optimize_for_ragflow,
)
from .ocr_patterns import (
    CLEANUP_PATTERNS,
    FICHA_EXTRA_PATTERNS,
    remove_artifacts,
)
from .footnote_filter import (
    is_footnote_noise,
    is_substantive_footnote,
    filter_footnote_items,
)

__all__ = [
    "ACCENT_MAP",
    "transliterate",
    "generate_id",
    "format_yaml_value",
    "format_yaml_list",
    "format_authors_display",
    "join_paragraph_lines",
    "format_bullets",
    "normalize_spacing",
    "optimize_for_ragflow",
    "CLEANUP_PATTERNS",
    "FICHA_EXTRA_PATTERNS",
    "remove_artifacts",
    "is_footnote_noise",
    "is_substantive_footnote",
    "filter_footnote_items",
]
