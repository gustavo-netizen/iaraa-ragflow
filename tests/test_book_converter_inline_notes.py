"""
J.3 — `convert_book_with_llm` consome sidecar via flag `inline_notes`.

Cobre os 5 casos do plano:
- `none` (default) → sem `## Notas` mesmo com sidecar válido.
- `all` → renderiza todos os items, ruído incluído.
- `useful` → filtra via `is_substantive_footnote` (J.0).
- `footnotes_yaml_path` apontando pra arquivo inexistente → no-op gracioso.
- Livro legacy com `**Footnotes:**` no body + sem sidecar → cleanup de J.0
  elimina o label, sem `## Notas` adicionada.

Reusa as fixtures do snapshot (`livro_fixture.md` + `livro_llm_response.json`)
para exercitar o pipeline real, e adiciona um sidecar sintético em `tmp_path`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from processamento.book_converter.llm_pipeline import (
    _render_notes_section,
    convert_book_with_llm,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = Path(__file__).resolve().parent / "golden"


# ───────────────────── fixtures ─────────────────────


@pytest.fixture
def livro_content() -> str:
    return (FIXTURES / "livro_fixture.md").read_text(encoding="utf-8")


@pytest.fixture
def llm_response() -> str:
    return (GOLDEN / "livro_llm_response.json").read_text(encoding="utf-8")


@pytest.fixture
def sidecar_yaml(tmp_path: Path) -> Path:
    """Sidecar com mix: 1 nota ruidosa (¹ órfão) + 2 substantivas."""
    path = tmp_path / "livro.footnotes.yaml"
    doc = {
        "version": "1.0",
        "pdf_name": "livro_fixture",
        "total_pages": 7,
        "notes": [
            {"page": 3, "id": 1, "text": "¹"},
            {"page": 5, "id": 1, "text": "*Tournois refere-se à livre tournois.*"},
            {"page": 6, "id": 1, "text": "DOI: https://dx.doi.org/10.1234/example"},
        ],
    }
    path.write_text(
        yaml.dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


# ───────────────────── full-pipeline tests ─────────────────────


def test_inline_notes_none_skips_section(
    livro_content: str, llm_response: str, sidecar_yaml: Path
) -> None:
    """Default `none`: body limpo mesmo com sidecar válido na mão."""
    out, _ = convert_book_with_llm(
        content=livro_content,
        filename="livro_fixture.md",
        llm_response=llm_response,
        footnotes_yaml_path=sidecar_yaml,
        inline_notes="none",
    )
    assert "## Notas" not in out


def test_inline_notes_all_renders_full_list(
    livro_content: str, llm_response: str, sidecar_yaml: Path
) -> None:
    """Modo `all`: todos os 3 items renderizados com (p. N) e superscript."""
    out, _ = convert_book_with_llm(
        content=livro_content,
        filename="livro_fixture.md",
        llm_response=llm_response,
        footnotes_yaml_path=sidecar_yaml,
        inline_notes="all",
    )
    assert "## Notas" in out
    notas = out[out.index("## Notas"):]
    assert "(p. 3)" in notas  # ruído incluído
    assert "(p. 5)" in notas
    assert "(p. 6)" in notas
    assert "Tournois" in notas
    assert "DOI" in notas
    assert "**¹ (p. 3)**" in notas


def test_inline_notes_useful_filters_noise(
    livro_content: str, llm_response: str, sidecar_yaml: Path
) -> None:
    """Modo `useful`: nota com text=`¹` (alpha=0) dropada; substantivas mantidas."""
    out, _ = convert_book_with_llm(
        content=livro_content,
        filename="livro_fixture.md",
        llm_response=llm_response,
        footnotes_yaml_path=sidecar_yaml,
        inline_notes="useful",
    )
    assert "## Notas" in out
    notas = out[out.index("## Notas"):]
    assert "Tournois" in notas
    assert "DOI" in notas
    # nota ruidosa (page 3) eliminada — só p. 5 e p. 6 sobrevivem
    assert "(p. 3)" not in notas
    assert "(p. 5)" in notas
    assert "(p. 6)" in notas


def test_missing_sidecar_is_no_op(
    livro_content: str, llm_response: str, tmp_path: Path
) -> None:
    """Path aponta pra arquivo inexistente: sem erro, sem `## Notas`."""
    nonexistent = tmp_path / "missing.footnotes.yaml"
    out, _ = convert_book_with_llm(
        content=livro_content,
        filename="livro_fixture.md",
        llm_response=llm_response,
        footnotes_yaml_path=nonexistent,
        inline_notes="useful",
    )
    assert "## Notas" not in out


def test_legacy_body_without_sidecar_uses_j0_cleanup() -> None:
    """Livro pré-J.2 com `**Footnotes:**` no body + sem sidecar.

    O cleanup de J.0 elimina o label órfão; `inline_notes="useful"` é no-op
    porque `footnotes_yaml_path=None`. Validate que o fallback funciona sem
    quebrar nem adicionar seção espúria.
    """
    legacy_content = (
        "# livro-legacy\n\n"
        "*Processed with Marco-Compliant Converter v2.0*\n"
        "*Model: qwen-vl-plus*\n\n"
        "## Page 1\n\n"
        "Texto introdutório do livro com referência³⁵.\n\n"
        "## Page 2\n\n"
        "CAPÍTULO 1 - INTRODUÇÃO\n\n"
        "Conteúdo do capítulo.\n\n"
        "---\n\n"
        "**Footnotes:**\n\n"
        "[^1]: ¹\n"
        "[^2]: *Translator note: Tournois refere-se à...*\n"
    )
    minimal_response = (
        '{"metadados": {"titulo": "Legacy Test", "autores": [], '
        '"editora": [], "ano": null, "isbn": null}, '
        '"capitulos": [], '
        '"remover": {"figuras": [], "toc": [], "frontmatter": [], "referencias": []}}'
    )
    out, _ = convert_book_with_llm(
        content=legacy_content,
        filename="legacy.md",
        llm_response=minimal_response,
        footnotes_yaml_path=None,
        inline_notes="useful",
    )
    assert "**Footnotes:**" not in out  # J.0 eliminou
    assert "## Notas" not in out         # J.3 no-op (sem sidecar)


# ───────────────────── _render_notes_section unit tests ─────────────────────


def test_render_returns_none_when_mode_is_none(sidecar_yaml: Path) -> None:
    assert _render_notes_section(sidecar_yaml, "none") is None


def test_render_returns_none_when_path_is_none() -> None:
    assert _render_notes_section(None, "useful") is None


def test_render_returns_none_when_sidecar_has_empty_notes(tmp_path: Path) -> None:
    path = tmp_path / "empty.footnotes.yaml"
    path.write_text(
        yaml.dump(
            {"version": "1.0", "pdf_name": "x", "total_pages": 1, "notes": []},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    assert _render_notes_section(path, "all") is None


def test_render_returns_none_when_useful_filters_everything(tmp_path: Path) -> None:
    """Sidecar só com ruído + mode=useful → tudo dropa → None (sem seção vazia)."""
    path = tmp_path / "noise.footnotes.yaml"
    path.write_text(
        yaml.dump(
            {
                "version": "1.0",
                "pdf_name": "x",
                "total_pages": 5,
                "notes": [
                    {"page": 1, "id": 1, "text": "¹"},
                    {"page": 2, "id": 1, "text": "4."},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    assert _render_notes_section(path, "useful") is None


def test_render_uses_global_counter_for_superscript(tmp_path: Path) -> None:
    """Counter renumera 1, 2, 3... independente do `id` por-página do sidecar."""
    path = tmp_path / "multi.footnotes.yaml"
    path.write_text(
        yaml.dump(
            {
                "version": "1.0",
                "pdf_name": "x",
                "total_pages": 10,
                "notes": [
                    {"page": 3, "id": 1, "text": "primeira nota substantiva"},
                    {"page": 3, "id": 2, "text": "segunda nota substantiva"},
                    {"page": 8, "id": 1, "text": "terceira nota substantiva"},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    rendered = _render_notes_section(path, "all")
    assert rendered is not None
    assert "**¹ (p. 3)** primeira" in rendered
    assert "**² (p. 3)** segunda" in rendered
    assert "**³ (p. 8)** terceira" in rendered
