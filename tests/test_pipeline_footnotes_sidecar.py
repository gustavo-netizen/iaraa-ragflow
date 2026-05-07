"""
J.2 — Stage 1 emite `<name>.footnotes.yaml`; body MD sem `**Footnotes:**`.

Três camadas de cobertura:

1. **Helper puro** — `_build_footnotes_sidecar` testado em isolação. Schema
   por ADR-0004: `notes: []` quando vazio (incondicional), pages ordenadas
   asc, `id` reinicia em 1 por página, unicode preservado.
2. **Source-guards** — greps em pipeline.py garantem que o pattern legacy
   inline foi removido e o write do sidecar permanece junto ao
   `_all_figures.yaml`. Trava regressão se alguém re-introduzir o append
   de `**Footnotes:**` ao body.
3. **Integração** — drive `process_pdf_async` via `asyncio.run` + mocks
   leves de `pdf2image.convert_from_path`, `process_single_page_with_context`
   e cliente Qwen. Cobre os 5 asserts do plano (a-e) + caso de PDF sem
   footnotes (sidecar com `notes: []`).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "conversao"))
sys.path.insert(0, str(REPO_ROOT / "conversao" / "scripts"))

from docmind.pipeline import (  # noqa: E402
    _build_footnotes_sidecar,
    process_pdf_async,
)


PIPELINE_PY = REPO_ROOT / "conversao" / "docmind" / "pipeline.py"


# ────────────────────────── Layer 1: helper unit tests ──────────────────────


def test_build_sidecar_empty_yields_empty_notes_list() -> None:
    """Emissão incondicional: PDF sem footnotes ainda emite `notes: []`."""
    doc = _build_footnotes_sidecar("livro_x", 10, {})
    assert doc == {
        "version": "1.0",
        "pdf_name": "livro_x",
        "total_pages": 10,
        "notes": [],
    }


def test_build_sidecar_assigns_id_per_page_starting_at_one() -> None:
    """`id` reinicia em 1 a cada página (não global)."""
    doc = _build_footnotes_sidecar(
        "livro_y",
        20,
        {3: ["a", "b"], 8: ["c"]},
    )
    ids_per_page = {(n["page"], n["id"]) for n in doc["notes"]}
    assert ids_per_page == {(3, 1), (3, 2), (8, 1)}


def test_build_sidecar_orders_pages_ascending() -> None:
    """Sort por `page` mesmo quando dict de input é fora de ordem."""
    doc = _build_footnotes_sidecar(
        "livro_z",
        50,
        {42: ["last"], 1: ["first"], 17: ["middle"]},
    )
    pages = [n["page"] for n in doc["notes"]]
    assert pages == [1, 17, 42]


def test_build_sidecar_preserves_unicode_text() -> None:
    """Glifos OCR (³⁵, ¹) e acentos passam intactos pro YAML."""
    doc = _build_footnotes_sidecar(
        "livro_w",
        5,
        {3: ["³⁵", "*Tournois refere-se à livre tournois*"]},
    )
    assert doc["notes"][0]["text"] == "³⁵"
    assert doc["notes"][1]["text"] == "*Tournois refere-se à livre tournois*"


def test_build_sidecar_top_level_schema_matches_adr() -> None:
    """ADR-0004 schema: version="1.0" + pdf_name + total_pages + notes."""
    doc = _build_footnotes_sidecar("any", 1, {})
    assert set(doc.keys()) == {"version", "pdf_name", "total_pages", "notes"}
    assert doc["version"] == "1.0"


# ────────────────────────── Layer 2: source-guards ──────────────────────────


def test_pipeline_no_longer_appends_footnotes_label_to_page_content() -> None:
    """Garante que o append legacy de `**Footnotes:**` ao body sumiu."""
    src = PIPELINE_PY.read_text(encoding="utf-8")
    assert '"---\\n\\n**Footnotes:**\\n\\n"' not in src
    assert "page_content += " not in src.split("# Validation report")[0].rsplit(
        "if footnotes :=", 1
    )[-1] or "Footnotes" not in src.split("if footnotes :=")[1].split(
        "markdown_sections.append"
    )[0]


def test_pipeline_no_longer_appends_footnote_items_to_page_content() -> None:
    """O bloco que escrevia `[^N]: <text>\\n` ao body foi removido."""
    src = PIPELINE_PY.read_text(encoding="utf-8")
    assert 'page_content += f"[^{i}]: {fn}' not in src


def test_pipeline_still_emits_all_figures_yaml() -> None:
    """Regressão: J.2 não pode quebrar a emissão do sidecar de figuras."""
    src = PIPELINE_PY.read_text(encoding="utf-8")
    assert '_all_figures.yaml' in src
    assert '"figures": all_figures_metadata' in src


def test_pipeline_writes_footnotes_sidecar_yaml() -> None:
    """O write do `<name>.footnotes.yaml` está presente."""
    src = PIPELINE_PY.read_text(encoding="utf-8")
    assert '.footnotes.yaml' in src
    assert '_build_footnotes_sidecar(' in src


# ────────────────────────── Layer 3: integration ────────────────────────────


class _FakeClient:
    """Substitui QwenClient durante o teste — só precisa de simple_ocr_sync."""

    def simple_ocr_sync(self, image: Any) -> str:
        return "fake ocr text"


def _make_fake_process(footnotes_per_page: Dict[int, List[str]]):
    """Constrói um substituto async para `process_single_page_with_context`."""

    async def fake_process(*, page_num: int, image: Any, **kwargs: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "success": True,
            "page": page_num,
            "body_text": f"Body of page {page_num}.",
            "tokens": {"input": 100, "output": 200},
            "figure_count": 0,
            "table_count": 0,
            "formula_count": 0,
            "tables": [],
            "formulas": [],
            "figures": [],
            "figures_metadata": [],
        }
        if page_num in footnotes_per_page:
            result["footnotes"] = footnotes_per_page[page_num]
        return result

    return fake_process


def _drive_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    n_pages: int,
    footnotes_per_page: Dict[int, List[str]],
) -> Dict[str, Path]:
    """Roda `process_pdf_async` com mocks; retorna paths dos arquivos escritos."""
    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%fake\n%%EOF\n")
    output_base = tmp_path / "output"
    output_base.mkdir()

    fake_images = [object()] * n_pages
    monkeypatch.setattr("pdf2image.convert_from_path", lambda *a, **kw: fake_images)
    monkeypatch.setattr(
        "docmind.pipeline.process_single_page_with_context",
        _make_fake_process(footnotes_per_page),
    )

    result = asyncio.run(
        process_pdf_async(
            pdf_path=pdf,
            api_key="fake-key",
            output_base=output_base,
            progress_manager=None,
            resume=False,
            client=_FakeClient(),
        )
    )
    assert result.get("success") is True, f"pipeline failed: {result}"

    output_dir = output_base / "fake"
    return {
        "md": output_dir / "fake.md",
        "footnotes": output_dir / "fake.footnotes.yaml",
        "figures": output_dir / "fake_all_figures.yaml",
    }


def test_process_pdf_async_writes_sidecar_with_correct_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan asserts (a)-(e): body limpo, sidecar correto, figures preservado."""
    paths = _drive_pipeline(
        tmp_path,
        monkeypatch,
        n_pages=3,
        footnotes_per_page={
            2: ["¹", "*Tournois refere-se à livre tournois.*"],
            3: ["⁴⁵"],
        },
    )

    md = paths["md"].read_text(encoding="utf-8")
    sidecar = yaml.safe_load(paths["footnotes"].read_text(encoding="utf-8"))

    # (a) body MD tem zero `**Footnotes:**`
    assert "**Footnotes:**" not in md
    # (b) body MD tem zero `[^N]:` lines
    assert "[^1]:" not in md
    assert "[^2]:" not in md
    # (c) sidecar existe (read sem exceção já valida)
    assert paths["footnotes"].exists()
    # (d) shape do sidecar
    assert sidecar["version"] == "1.0"
    assert sidecar["pdf_name"] == "fake"
    assert sidecar["total_pages"] == 3
    assert sidecar["notes"] == [
        {"page": 2, "id": 1, "text": "¹"},
        {"page": 2, "id": 2, "text": "*Tournois refere-se à livre tournois.*"},
        {"page": 3, "id": 1, "text": "⁴⁵"},
    ]
    # (e) `_all_figures.yaml` continua sendo emitido
    assert paths["figures"].exists()
    # marker redundante no metadata header (signal duplicado da existência do sidecar)
    assert "*Footnotes: sidecar*" in md


def test_process_pdf_async_emits_empty_sidecar_when_no_footnotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sidecar emitido com `notes: []` mesmo sem footnotes (incondicional)."""
    paths = _drive_pipeline(
        tmp_path,
        monkeypatch,
        n_pages=2,
        footnotes_per_page={},
    )

    md = paths["md"].read_text(encoding="utf-8")
    sidecar = yaml.safe_load(paths["footnotes"].read_text(encoding="utf-8"))

    assert paths["footnotes"].exists()
    assert sidecar["notes"] == []
    assert sidecar["total_pages"] == 2
    # marker NÃO aparece quando não há footnotes
    assert "*Footnotes: sidecar*" not in md
    # body limpo independentemente
    assert "**Footnotes:**" not in md
