"""
Limpeza OCR e otimização RAGFlow para Fichas Agroecológicas.

Fases 1 e 5 do pipeline. Funções comuns vêm de `processamento.shared`;
este módulo só guarda o que é específico da estrutura de fichas
(`normalize_punctuation` para itens de lista terminando em `;`).
"""

import re

from processamento.shared.ocr_patterns import (
    CLEANUP_PATTERNS,
    FICHA_EXTRA_PATTERNS,
    remove_artifacts as _remove_artifacts_shared,
)
from processamento.shared.footnote_filter import filter_footnote_items
from processamento.shared.ragflow import join_paragraph_lines


_FICHA_PATTERNS = CLEANUP_PATTERNS + FICHA_EXTRA_PATTERNS


def remove_artifacts(content: str) -> str:
    """Remove artefatos OCR (Marco/DocMind + 2 patterns específicos de ficha)."""
    return _remove_artifacts_shared(content, _FICHA_PATTERNS)


def clean_empty_lines(content: str) -> str:
    """Colapsa 3+ linhas em branco consecutivas em 2."""
    return re.sub(r'\n{3,}', '\n\n', content)


def normalize_punctuation(content: str) -> str:
    """
    Substitui `;` final por `.` em itens de lista que não têm continuação.

    RAGFlow usa `\\n!?。；！？` como delimiters; itens com `;` final viram
    chunks tortos. Só toca em linhas iniciadas por `* ` (bullets já
    padronizados pela fase de restructure).
    """
    lines = content.split('\n')
    result = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        if not stripped or stripped.startswith(('#', '>', '**', '![')):
            result.append(line)
            continue

        if stripped.startswith('* '):
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
            is_continuation = next_line and next_line[0].islower()

            if not is_continuation:
                if stripped.endswith(';'):
                    line = line.rstrip()[:-1] + '.'
                elif stripped[-1] not in '.!?:)':
                    line = line.rstrip() + '.'

            result.append(line)
            continue

        result.append(line)

    return '\n'.join(result)


def clean_all(content: str) -> str:
    """Fase 1 completa: remove artefatos OCR + filtra footnote items."""
    content = remove_artifacts(content)
    content = filter_footnote_items(content)
    return content


def optimize_for_ragflow(content: str) -> str:
    """Fase 5: junta linhas de parágrafo quebradas pelo OCR."""
    return join_paragraph_lines(content)
