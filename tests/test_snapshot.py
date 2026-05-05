"""
Snapshot tests — Fase 0.1 do PLANO_REFATORACAO.md.

Captura comportamento de saída atual de ambos os pipelines (`ficha_converter`
e `book_converter`) e falha se uma refatoração futura mudar o output sem
atualização explícita do golden.

Inputs em `tests/fixtures/`, goldens em `tests/golden/`.

Quando uma mudança intencional alterar o output (ex: ADR-0001 unificando
`generate_id`), atualizar o golden em commit separado com `--update-goldens`
e justificativa no commit message.
"""

from __future__ import annotations

import os
import sys
import json
import difflib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = Path(__file__).resolve().parent / "golden"

# book_converter ainda vive em .claude/skills/convert-book/ (B.1 move pra processamento/).
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "convert-book"))


def _diff(actual: str, expected: str, label: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=f"{label} (golden)",
            tofile=f"{label} (actual)",
            lineterm="",
            n=3,
        )
    )


def _assert_or_update(actual: str, golden_path: Path, label: str) -> None:
    """Compara contra golden ou regrava se UPDATE_GOLDENS=1."""
    if os.environ.get("UPDATE_GOLDENS") == "1":
        golden_path.write_text(actual, encoding="utf-8")
        return
    expected = golden_path.read_text(encoding="utf-8")
    if actual != expected:
        pytest.fail(
            f"{label} divergiu do golden ({golden_path.relative_to(ROOT)}).\n"
            f"Re-run com UPDATE_GOLDENS=1 se a mudança for intencional.\n\n"
            + _diff(actual, expected, label)
        )


def test_ficha_pipeline_matches_golden() -> None:
    from processamento.ficha_converter.cli import convert_full

    fixture = FIXTURES / "99-biofertilizante-fixture-1.md"
    content = fixture.read_text(encoding="utf-8")

    actual = convert_full(content, fixture.name, verbose=False)

    _assert_or_update(actual, GOLDEN / "ficha.md", "ficha")


def test_livro_pipeline_matches_golden() -> None:
    from book_converter.llm_pipeline import convert_book_with_llm

    fixture = FIXTURES / "livro_fixture.md"
    content = fixture.read_text(encoding="utf-8")
    llm_response = (GOLDEN / "livro_llm_response.json").read_text(encoding="utf-8")

    actual, _log = convert_book_with_llm(
        content=content,
        filename=fixture.name,
        llm_response=llm_response,
        include_frontmatter=True,
        verbose=False,
    )

    _assert_or_update(actual, GOLDEN / "livro.md", "livro")


def test_llm_response_fixture_is_valid_json() -> None:
    """Sanity: a fixture LLM precisa ser JSON válido com schema esperado."""
    data = json.loads((GOLDEN / "livro_llm_response.json").read_text(encoding="utf-8"))
    assert "metadados" in data
    assert "capitulos" in data
    assert "remover" in data
    assert isinstance(data["capitulos"], list) and len(data["capitulos"]) >= 1
