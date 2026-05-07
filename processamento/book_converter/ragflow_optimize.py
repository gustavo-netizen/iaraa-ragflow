"""
Otimização para RAGFlow — wrapper sobre `processamento.shared.ragflow`.

Mantido como módulo separado para preservar imports públicos
(`from processamento.book_converter.ragflow_optimize import ...`).
A formatação de relatório `format_optimize_summary` é específica do
pipeline de livros (conta partes/capítulos/seções) e fica aqui.
"""

import re

from processamento.shared.ragflow import (
    join_paragraph_lines,
    format_bullets,
    normalize_spacing,
    optimize_for_ragflow,
)


__all__ = [
    "join_paragraph_lines",
    "format_bullets",
    "normalize_spacing",
    "optimize_for_ragflow",
    "format_optimize_summary",
]


def format_optimize_summary(content: str, original_size: int) -> str:
    """Formata resumo da otimização (estatísticas de headers e tamanho)."""
    final_size = len(content)
    reduction = (1 - final_size / original_size) * 100 if original_size > 0 else 0

    h1_count = len(re.findall(r'^# [^#]', content, re.MULTILINE))
    h2_count = len(re.findall(r'^## [^#]', content, re.MULTILINE))
    h3_count = len(re.findall(r'^### [^#]', content, re.MULTILINE))
    bullet_count = len(re.findall(r'^\s*\* ', content, re.MULTILINE))
    paragraph_count = len(re.findall(r'\n\n[A-Z]', content))

    lines = [
        "Otimização RAGFlow concluída:",
        "",
        "Headers (delimitadores nativos do RAGFlow):",
        f"  - Partes (#): {h1_count}",
        f"  - Capítulos (##): {h2_count}",
        f"  - Seções (###): {h3_count}",
        "",
        "Estatísticas do documento:",
        f"  - Bullets padronizados: {bullet_count}",
        f"  - Parágrafos: ~{paragraph_count}",
        "",
        "Tamanho:",
        f"  - Original: {original_size:,} caracteres",
        f"  - Final: {final_size:,} caracteres",
        f"  - Redução: {reduction:.1f}%",
    ]

    return '\n'.join(lines)
