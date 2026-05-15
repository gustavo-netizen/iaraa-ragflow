"""Tests for ``conversao/scripts/split_large_pdfs_smart.py``.

Covers Fase 2 (Bug 1) of PLANO_BUGFIXES_QUALITY_GATE.md:
* Splitter returns rc=1 when any PDF errors (was rc=0 silently)
* ``progress.json`` records ``steps.split.status == 'failed'``
* ``split_pdf`` cleans up ``.pdf.tmp`` files on failure — no partial chunks

Uses ``PdfWriter.add_blank_page`` to fabricate minimal valid PDFs so the tests
run without external fixtures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pikepdf
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "conversao"))
sys.path.insert(0, str(REPO_ROOT / "conversao" / "scripts"))

import split_large_pdfs_smart as splitter  # noqa: E402


# ----------------------------------------------------------- fixtures


def _write_valid_pdf(path: Path, pages: int = 60) -> None:
    """Write a minimal valid PDF with ``pages`` blank US-letter pages."""
    with pikepdf.Pdf.new() as pdf:
        for _ in range(pages):
            pdf.add_blank_page(page_size=(612, 792))
        pdf.save(path)


def _write_corrupt_pdf(path: Path) -> None:
    """Write bytes neither PyPDF2 nor pikepdf can parse."""
    path.write_bytes(b"not a pdf at all")


@pytest.fixture
def split_args(tmp_path: Path):
    """Argv builder + paths for invoking ``splitter.main()``."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "split_pdfs"
    mapping = tmp_path / "split_mapping.json"
    input_dir.mkdir()
    return input_dir, output_dir, mapping


def _argv(input_dir: Path, output_dir: Path, mapping: Path) -> list[str]:
    return [
        "split_large_pdfs_smart.py",
        "--input-dir", str(input_dir),
        "--output-dir", str(output_dir),
        "--mapping-file", str(mapping),
        "--threshold", "5",
        "--chunk-size", "10",
        "--max-chunk-size-mb", "50",
        "--no-resume",  # ignore progress_manager state; we test rc + mapping
    ]


# ----------------------------------------------------------- rc + mapping


def test_split_pdf_returns_nonzero_when_any_pdf_errors(
    split_args, monkeypatch: pytest.MonkeyPatch
):
    """1 valid PDF + 1 corrupt → rc=1, mapping has the bad PDF as status=error."""
    input_dir, output_dir, mapping = split_args
    _write_valid_pdf(input_dir / "good.pdf", pages=60)
    _write_corrupt_pdf(input_dir / "bad.pdf")

    monkeypatch.setattr(sys, "argv", _argv(input_dir, output_dir, mapping))
    rc = splitter.main()

    assert rc == 1
    data = json.loads(mapping.read_text())
    assert data["stats"]["error_pdfs"] == 1
    assert data["stats"]["pdfs"]["bad.pdf"]["status"] == "error"
    assert data["stats"]["pdfs"]["good.pdf"]["status"] == "split"


def test_split_returns_zero_when_no_errors(
    split_args, monkeypatch: pytest.MonkeyPatch
):
    """Baseline: a clean run still returns rc=0 (no regression for happy path)."""
    input_dir, output_dir, mapping = split_args
    _write_valid_pdf(input_dir / "good.pdf", pages=60)

    monkeypatch.setattr(sys, "argv", _argv(input_dir, output_dir, mapping))
    rc = splitter.main()

    assert rc == 0
    data = json.loads(mapping.read_text())
    assert data["stats"]["error_pdfs"] == 0


# ----------------------------------------------------------- progress_manager


def test_split_step_status_set_to_failed_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """progress.json records steps.split.status == 'failed' when any PDF errors."""
    # progress_manager looks two levels up for base_dir (Path(__file__).parent.parent).
    # We mimic that layout: conversao/scripts/, conversao/progress.json.
    conversao = tmp_path / "conversao"
    scripts_dir = conversao / "scripts"
    scripts_dir.mkdir(parents=True)
    input_dir = conversao / "input"
    output_dir = conversao / "split_pdfs"
    mapping = conversao / "split_mapping.json"
    input_dir.mkdir()
    _write_valid_pdf(input_dir / "good.pdf", pages=60)
    _write_corrupt_pdf(input_dir / "bad.pdf")

    # Force splitter.__file__ to resolve to conversao/scripts/ so the progress
    # manager seeds progress.json inside our tmp_path tree.
    fake_module_file = scripts_dir / "split_large_pdfs_smart.py"
    fake_module_file.write_text("# placeholder")
    monkeypatch.setattr(splitter, "__file__", str(fake_module_file))

    monkeypatch.setattr(
        sys, "argv",
        [
            "split_large_pdfs_smart.py",
            "--input-dir", str(input_dir),
            "--output-dir", str(output_dir),
            "--mapping-file", str(mapping),
            "--threshold", "5",
            "--chunk-size", "10",
            "--max-chunk-size-mb", "50",
        ],
    )

    rc = splitter.main()
    assert rc == 1

    progress_file = conversao / "progress.json"
    assert progress_file.exists()
    progress = json.loads(progress_file.read_text())
    assert progress["steps"]["split"]["status"] == "failed"


# ----------------------------------------------------------- tmp cleanup


def test_split_pdf_does_not_leave_partial_chunks_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When Pdf.save raises on chunk 2/3, no .pdf.tmp remains in output_dir."""
    pdf_path = tmp_path / "big.pdf"
    _write_valid_pdf(pdf_path, pages=30)  # → 3 chunks at chunk_size=10
    output_dir = tmp_path / "out"

    real_save = pikepdf.Pdf.save
    state = {"calls": 0}

    def failing_save(self: pikepdf.Pdf, *args: Any, **kwargs: Any) -> Any:
        state["calls"] += 1
        if state["calls"] == 2:
            raise RuntimeError("simulated mid-split failure")
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(splitter.pikepdf.Pdf, "save", failing_save)

    with pytest.raises(RuntimeError, match="simulated mid-split failure"):
        splitter.split_pdf(
            pdf_path,
            output_dir,
            max_pages_per_chunk=10,
            max_size_mb_per_chunk=50,
        )

    remaining = sorted(p.name for p in output_dir.iterdir())
    tmp_files = [n for n in remaining if n.endswith(".tmp")]
    assert tmp_files == [], f"orphan .tmp files: {tmp_files}"


# ----------------------------------------------------------- pikepdf recovery


def test_split_pdf_handles_minor_corruption_via_pikepdf(
    split_args, monkeypatch: pytest.MonkeyPatch
):
    """PDF with truncated trailer/xref must still split — that was the failure
    mode we hit manually with Dissertação_Carvalho.pdf. PyPDF2 rejects it;
    pikepdf (libqpdf) recovers the cross-reference silently."""
    input_dir, output_dir, mapping = split_args
    pdf = input_dir / "truncated.pdf"
    _write_valid_pdf(pdf, pages=60)
    # Lop off the trailer + xref tail. pikepdf reconstructs from the body.
    raw = pdf.read_bytes()
    pdf.write_bytes(raw[:-50])

    monkeypatch.setattr(sys, "argv", _argv(input_dir, output_dir, mapping))
    rc = splitter.main()

    assert rc == 0
    data = json.loads(mapping.read_text())
    assert data["stats"]["pdfs"]["truncated.pdf"]["status"] == "split"
    assert data["stats"]["error_pdfs"] == 0


def test_split_pdf_still_errors_on_total_garbage(
    split_args, monkeypatch: pytest.MonkeyPatch
):
    """Migrating to pikepdf must not silently 'recover' arbitrary bytes — Bug 1
    regression: garbage must still be flagged as status=error and exit 1."""
    input_dir, output_dir, mapping = split_args
    (input_dir / "garbage.pdf").write_bytes(b"not a pdf at all")

    monkeypatch.setattr(sys, "argv", _argv(input_dir, output_dir, mapping))
    rc = splitter.main()

    assert rc == 1
    data = json.loads(mapping.read_text())
    assert data["stats"]["pdfs"]["garbage.pdf"]["status"] == "error"
    assert data["stats"]["error_pdfs"] == 1
