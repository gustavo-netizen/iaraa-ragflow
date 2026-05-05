"""Tests for ``conversao/docmind/document.py``.

Pure unit tests using synthetic split_mapping.json + synthetic validation.yaml.
No real PDFs, no API calls. Plan reference: PLANO_REFATORACAO.md Fase E.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "conversao"))
sys.path.insert(0, str(REPO_ROOT / "conversao" / "scripts"))

from docmind.document import Chunk, Document, FailedPage  # noqa: E402


# ---------------------------------------------------------- discover() tests


def _write_mapping(path: Path, chunks: list, direct: list) -> None:
    path.write_text(json.dumps({"stats": {}, "chunks": chunks, "direct": direct}))


def test_discover_chunked_pdf_groups_and_sorts(tmp_path: Path):
    mapping = tmp_path / "split_mapping.json"
    output = tmp_path / "output" / "chunks"
    _write_mapping(
        mapping,
        chunks=[
            {
                "path": str(tmp_path / "split_pdfs" / "MyBook_chunk_002.pdf"),
                "pages": 50,
                "chunk_idx": 2,
                "total_chunks": 3,
                "original_pdf": "MyBook.pdf",
            },
            {
                "path": str(tmp_path / "split_pdfs" / "MyBook_chunk_001.pdf"),
                "pages": 50,
                "chunk_idx": 1,
                "total_chunks": 3,
                "original_pdf": "MyBook.pdf",
            },
            {
                "path": str(tmp_path / "split_pdfs" / "MyBook_chunk_003.pdf"),
                "pages": 30,
                "chunk_idx": 3,
                "total_chunks": 3,
                "original_pdf": "MyBook.pdf",
            },
        ],
        direct=[],
    )

    docs = Document.discover(mapping, output)
    assert len(docs) == 1
    doc = docs[0]
    assert doc.original_name == "MyBook"
    assert doc.is_chunked
    assert [c.chunk_idx for c in doc.chunks] == [1, 2, 3]
    assert doc.total_pages() == 130
    assert doc.output_dir == output / "MyBook"
    assert doc.merged_md_path == output / "MyBook" / "MyBook.md"
    assert doc.validation_path == output / "MyBook" / "MyBook.validation.yaml"
    assert doc.yaml_path == output / "MyBook" / "MyBook_all_figures.yaml"


def test_discover_direct_pdf_emits_chunkless_document(tmp_path: Path):
    mapping = tmp_path / "split_mapping.json"
    output = tmp_path / "output"
    _write_mapping(
        mapping,
        chunks=[],
        direct=[
            {
                "pdf_path": "/abs/path/foo.pdf",
                "pdf_name": "foo.pdf",
            }
        ],
    )

    docs = Document.discover(mapping, output)
    assert len(docs) == 1
    doc = docs[0]
    assert doc.original_name == "foo"
    assert not doc.is_chunked
    assert doc.chunks == []
    assert doc.pdf_path == Path("/abs/path/foo.pdf")
    assert doc.output_dir == output / "foo"


def test_discover_handles_mixed_chunks_and_direct(tmp_path: Path):
    mapping = tmp_path / "split_mapping.json"
    output = tmp_path / "output"
    _write_mapping(
        mapping,
        chunks=[
            {
                "path": str(tmp_path / "split_pdfs" / "Big_chunk_001.pdf"),
                "pages": 100,
                "chunk_idx": 1,
                "total_chunks": 1,
                "original_pdf": "Big.pdf",
            }
        ],
        direct=[{"pdf_path": "/abs/small.pdf", "pdf_name": "small.pdf"}],
    )

    docs = Document.discover(mapping, output)
    by_name = {d.original_name: d for d in docs}
    assert set(by_name) == {"Big", "small"}
    assert by_name["Big"].is_chunked
    assert not by_name["small"].is_chunked


def test_discover_handles_empty_mapping(tmp_path: Path):
    mapping = tmp_path / "split_mapping.json"
    output = tmp_path / "output"
    _write_mapping(mapping, chunks=[], direct=[])
    assert Document.discover(mapping, output) == []


# --------------------------------------------------- apply_page_offset tests


def test_apply_page_offset_zero_is_identity():
    content = "## Page 1\n\n[Page 2] ![alt](images/page_001.png)\n"
    assert Document.apply_page_offset(content, 0) == content


def test_apply_page_offset_shifts_page_headers_and_brackets():
    content = "## Page 1\n\nSee [Page 2] for details.\n## Page 3"
    out = Document.apply_page_offset(content, 50)
    assert "## Page 51" in out
    assert "## Page 53" in out
    assert "[Page 52]" in out
    assert "Page 1" not in out  # original numbers gone
    assert "Page 2" not in out
    assert "Page 3" not in out


def test_apply_page_offset_shifts_image_references():
    content = "![Figure 1](images/page_001.png)\n![Cover](images/page_010.png)"
    out = Document.apply_page_offset(content, 25)
    assert "images/page_026.png" in out
    assert "images/page_035.png" in out
    assert "images/page_001.png" not in out


def test_apply_page_offset_shifts_yaml_references_in_url_position():
    # Standalone occurrence: rewritten correctly.
    content = "ref: yaml_metadata/Figure_1_page1.yaml end"
    out = Document.apply_page_offset(content, 100)
    assert "Figure_1_page101.yaml" in out


@pytest.mark.xfail(
    reason=(
        "Pre-existing greedy-regex bug inherited from merge_results_full.py — when the "
        "same path appears twice on a line (Markdown link `[text](url)` form, which "
        "Stage-1 emits in `assembler.py`), only the URL portion is renumbered; the "
        "link-text portion keeps the original page number. Cosmetic (URL is correct, "
        "displayed text drifts). Documented for Fase H bug fixes."
    ),
    strict=True,
)
def test_apply_page_offset_yaml_refs_in_markdown_link_known_buggy():
    content = (
        "*YAML Metadata: [yaml_metadata/Figure_1_page1.yaml]"
        "(yaml_metadata/Figure_1_page1.yaml)*"
    )
    out = Document.apply_page_offset(content, 100)
    # Both occurrences should renumber — but greedy regex only catches the URL.
    assert out.count("Figure_1_page101.yaml") == 2


def test_apply_page_offset_combines_all_three_transforms():
    content = (
        "## Page 1\n\n"
        "Body text references [Page 2].\n\n"
        "![Fig](images/page_001.png)\n\n"
        "Metadata: yaml_metadata/Figure_1_page1.yaml\n"
    )
    out = Document.apply_page_offset(content, 10)
    assert "## Page 11" in out
    assert "[Page 12]" in out
    assert "images/page_011.png" in out
    assert "Figure_1_page11.yaml" in out


# ----------------------------------------------------- failed_pages() tests


def _make_doc(tmp_path: Path, name: str = "doc") -> Document:
    output_dir = tmp_path / "output" / name
    output_dir.mkdir(parents=True)
    return Document(
        pdf_path=tmp_path / f"{name}.pdf",
        original_name=name,
        chunks=[],
        output_dir=output_dir,
    )


def test_failed_pages_returns_empty_when_validation_yaml_missing(tmp_path: Path):
    doc = _make_doc(tmp_path)
    assert doc.failed_pages() == []


def test_failed_pages_reads_validation_yaml(tmp_path: Path):
    doc = _make_doc(tmp_path)
    payload = {
        "failed_pages_detail": [
            {"page": 7, "error": "DataInspectionFailed: content"},
            {"page": 12, "error": "Timeout after retries"},
        ]
    }
    doc.validation_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    failed = doc.failed_pages()
    assert failed == [
        FailedPage(page=7, error="DataInspectionFailed: content"),
        FailedPage(page=12, error="Timeout after retries"),
    ]


def test_failed_pages_skips_malformed_entries(tmp_path: Path):
    doc = _make_doc(tmp_path)
    payload = {
        "failed_pages_detail": [
            {"page": 5, "error": "ok"},
            {"error": "missing page key"},
            "not even a dict",
            {"page": "not-a-number"},
            {"page": 9},  # missing error → empty string
        ]
    }
    doc.validation_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    failed = doc.failed_pages()
    assert failed == [FailedPage(page=5, error="ok"), FailedPage(page=9, error="")]


def test_failed_pages_handles_corrupt_yaml(tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc.validation_path.write_text("not: valid: yaml: at: all: [", encoding="utf-8")
    assert doc.failed_pages() == []


def test_failed_pages_handles_empty_yaml(tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc.validation_path.write_text("", encoding="utf-8")
    assert doc.failed_pages() == []


# -------------------------------------------------------- is_complete tests


def test_is_complete_no_progress_manager_false_when_md_missing(tmp_path: Path):
    doc = _make_doc(tmp_path)
    assert doc.is_complete() is False


def test_is_complete_no_progress_manager_true_when_md_nonempty(tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc.merged_md_path.write_text("# content", encoding="utf-8")
    assert doc.is_complete() is True


def test_is_complete_no_progress_manager_false_when_md_empty(tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc.merged_md_path.write_text("", encoding="utf-8")
    assert doc.is_complete() is False


def test_is_complete_with_progress_manager_uses_validate(tmp_path: Path):
    doc = _make_doc(tmp_path)

    class FakeProgress:
        def __init__(self, valid: bool):
            self.valid = valid
            self.calls = []

        def validate_pdf_completion(self, step, name, output_dir):
            self.calls.append((step, name, output_dir))
            return {"valid": self.valid, "reason": "stub"}

    pm = FakeProgress(valid=True)
    assert doc.is_complete(progress_manager=pm, step_name="process_direct") is True
    assert pm.calls == [("process_direct", "doc", str(doc.output_dir.parent))]

    pm = FakeProgress(valid=False)
    assert doc.is_complete(progress_manager=pm, step_name="process_direct") is False


def test_is_complete_falls_back_to_is_pdf_completed_when_no_validate(tmp_path: Path):
    doc = _make_doc(tmp_path)

    class MinimalProgress:
        def is_pdf_completed(self, step, name):
            return step == "process_direct" and name == "doc"

    pm = MinimalProgress()
    assert doc.is_complete(progress_manager=pm) is True


def test_infer_step_name_uses_chunks_substring(tmp_path: Path):
    doc_chunks = Document(
        pdf_path=tmp_path / "x.pdf",
        original_name="x",
        chunks=[],
        output_dir=tmp_path / "output" / "chunks" / "x",
    )
    doc_direct = Document(
        pdf_path=tmp_path / "y.pdf",
        original_name="y",
        chunks=[],
        output_dir=tmp_path / "output" / "y",
    )
    assert doc_chunks._infer_step_name() == "process_chunks"
    assert doc_direct._infer_step_name() == "process_direct"
