"""
Testes do filtro heurístico de footnote items (J.0).

Cobre:
- Heurística por linha (`is_footnote_noise` / `is_substantive_footnote`).
- Pattern do label `**Footnotes:**` em `CLEANUP_PATTERNS` (com e sem `---`
  precedente, dado que o separador genérico costuma ser comido antes).
"""

from __future__ import annotations

from processamento.shared.footnote_filter import (
    filter_footnote_items,
    is_footnote_noise,
    is_substantive_footnote,
)
from processamento.shared.ocr_patterns import CLEANUP_PATTERNS, remove_artifacts


def test_drops_orphan_superscript() -> None:
    assert is_footnote_noise("[^1]: ¹") is True


def test_drops_short_numeric() -> None:
    assert is_footnote_noise("[^1]: 4.") is True


def test_keeps_translator_note() -> None:
    line = "[^1]: *Tournois refere-se à livre tournois, moeda francesa."
    assert is_footnote_noise(line) is False
    assert is_substantive_footnote(line.split(":", 1)[1]) is True


def test_keeps_definition() -> None:
    line = "[^1]: 4. Ao longo do artigo, a palavra máquinas se refere ao conjunto."
    assert is_footnote_noise(line) is False


def test_keeps_doi() -> None:
    line = "[^1]: 1. DOI: https://dx.doi.org/10.1234/example"
    assert is_footnote_noise(line) is False


def test_non_footnote_line_passes_through() -> None:
    assert is_footnote_noise("Parágrafo qualquer com referência³⁵.") is False
    assert is_footnote_noise("## Capítulo") is False


def test_filter_drops_noise_keeps_substantive() -> None:
    content = (
        "[^1]: ¹\n"
        "[^2]: 4.\n"
        "[^3]: *Tournois refere-se à livre tournois.\n"
        "[^4]: 1. DOI: https://dx.doi.org/10.1234/example\n"
    )
    result = filter_footnote_items(content)
    assert "[^1]:" not in result
    assert "[^2]:" not in result
    assert "[^3]: *Tournois" in result
    assert "[^4]: 1. DOI" in result


def test_label_pattern_removes_orphan() -> None:
    """Quando `---` já foi comido pelo pattern de SEPARADORES, o label fica órfão."""
    content = "Texto antes.\n\n**Footnotes:**\n\nMais texto.\n"
    result = remove_artifacts(content, CLEANUP_PATTERNS)
    assert "**Footnotes:**" not in result


def test_label_pattern_removes_dashed_block() -> None:
    """Bloco completo `---\\n\\n**Footnotes:**\\n\\n` é eliminado."""
    content = "Texto antes.\n\n---\n\n**Footnotes:**\n\nMais texto.\n"
    result = remove_artifacts(content, CLEANUP_PATTERNS)
    assert "**Footnotes:**" not in result
    assert "---" not in result
