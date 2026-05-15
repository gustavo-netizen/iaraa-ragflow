"""Aggregation of per-chunk ``.validation.yaml`` files in ``merge_document``.

Covers the Fase 1 (Bug 3) entry of PLANO_BUGFIXES_QUALITY_GATE.md: every
chunked PDF must produce a merged ``<pdf>.validation.yaml`` so the Step 5.5
KQI gate and ``MarcoChecker`` strict mode see chunked PDFs instead of only
direct ones.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "conversao"))
sys.path.insert(0, str(REPO_ROOT / "conversao" / "scripts"))

from docmind.document import (  # noqa: E402
    Chunk,
    Document,
    aggregate_chunk_validations,
)
from merge_results_full import merge_document  # noqa: E402


# --------------------------------------------------------- helpers


def _make_chunk_validation(
    pdf_name: str,
    *,
    total_pages: int,
    successful_pages: int,
    yaml_insertion_rate: float = 1.0,
    average_confidence: float = 0.9,
    failed_pages_detail: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    failed = total_pages - successful_pages
    psr = successful_pages / total_pages if total_pages else 0
    overall = (
        yaml_insertion_rate >= 0.95
        and average_confidence >= 0.85
        and psr >= 0.95
    )
    return {
        "document_info": {
            "filename": f"{pdf_name}.pdf",
            "total_pages": total_pages,
            "processed_pages": total_pages,
        },
        "kqi_metrics": {
            "yaml_insertion_rate": yaml_insertion_rate,
            "yaml_insertion_pass": yaml_insertion_rate >= 0.95,
            "average_confidence": average_confidence,
            "confidence_pass": average_confidence >= 0.85,
            "page_success_rate": psr,
            "overall_quality_pass": overall,
        },
        "validation_metrics": {
            "total_figures_detected": 0,
            "total_tables_detected": 0,
            "total_formulas_detected": 0,
            "pages_with_figures": 0,
            "pages_with_tables": 0,
            "pages_with_formulas": 0,
            "high_confidence_figures": 0,
            "medium_confidence_figures": 0,
            "low_confidence_figures": 0,
        },
        "page_statistics": {
            "total_pages": total_pages,
            "successful_pages": successful_pages,
            "failed_pages": failed,
            "skipped_pages": 0,
            "success_rate": psr,
        },
        "quality_indicators": {
            "all_figures_have_yaml": True,
            "zero_hallucination": True,
            "proper_markdown_format": True,
            "complete_data_extraction": True,
            "no_page_failures": failed == 0,
        },
        "failed_pages_detail": failed_pages_detail or [],
        "page_by_page_results": [],
    }


def _seed_chunk_dir(
    chunks_root: Path,
    chunk_name: str,
    *,
    md_content: str,
    validation: Dict[str, Any] | None,
) -> None:
    chunk_dir = chunks_root / chunk_name
    chunk_dir.mkdir(parents=True, exist_ok=True)
    (chunk_dir / f"{chunk_name}.md").write_text(md_content, encoding="utf-8")
    if validation is not None:
        (chunk_dir / f"{chunk_name}.validation.yaml").write_text(
            yaml.dump(validation, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def _build_document(tmp_path: Path, original: str, chunk_pages: List[int]) -> Document:
    chunks_root = tmp_path / "output" / "chunks"
    chunks_root.mkdir(parents=True, exist_ok=True)
    output_dir = tmp_path / "output" / original
    chunks: List[Chunk] = []
    for idx, pages in enumerate(chunk_pages, start=1):
        name = f"{original}_chunk_{idx:03d}"
        chunks.append(
            Chunk(
                path=tmp_path / "split_pdfs" / f"{name}.pdf",
                pages=pages,
                chunk_idx=idx,
                total_chunks=len(chunk_pages),
                original_pdf=f"{original}.pdf",
            )
        )
    return Document(
        pdf_path=tmp_path / f"{original}.pdf",
        original_name=original,
        chunks=chunks,
        output_dir=output_dir,
    )


# --------------------------------------------------------- aggregate_chunk_validations (pure)


def test_aggregate_weights_kqi_by_chunk_total_pages():
    """avg_confidence weighted by chunk size, not arithmetic mean of chunks."""
    chunks = [
        _make_chunk_validation("a_001", total_pages=10, successful_pages=10, average_confidence=0.95),
        _make_chunk_validation("a_002", total_pages=2, successful_pages=2, average_confidence=0.50),
    ]
    out = aggregate_chunk_validations(chunks, [0, 10])
    expected_conf = (0.95 * 10 + 0.50 * 2) / 12
    assert out["kqi_metrics"]["average_confidence"] == pytest.approx(expected_conf, abs=1e-4)
    assert out["page_statistics"]["total_pages"] == 12


def test_aggregate_applies_offset_to_failed_pages_detail():
    chunks = [
        _make_chunk_validation("a_001", total_pages=3, successful_pages=3),
        _make_chunk_validation(
            "a_002",
            total_pages=2,
            successful_pages=1,
            failed_pages_detail=[{"page": 1, "error": "throttle"}],
        ),
    ]
    out = aggregate_chunk_validations(chunks, [0, 3])
    assert [fp["page"] for fp in out["failed_pages_detail"]] == [4]
    assert out["failed_pages_detail"][0]["error"] == "throttle"


def test_aggregate_overall_fails_when_one_chunk_fails():
    chunks = [
        _make_chunk_validation("a_001", total_pages=10, successful_pages=10),  # psr 1.0
        _make_chunk_validation("a_002", total_pages=10, successful_pages=5),  # psr 0.5
    ]
    out = aggregate_chunk_validations(chunks, [0, 10])
    assert out["kqi_metrics"]["overall_quality_pass"] is False
    assert out["kqi_metrics"]["page_success_rate"] == pytest.approx(0.75, abs=1e-4)


def test_aggregate_raises_on_length_mismatch():
    chunks = [_make_chunk_validation("a_001", total_pages=3, successful_pages=3)]
    with pytest.raises(ValueError):
        aggregate_chunk_validations(chunks, [0, 3])


# --------------------------------------------------------- merge_document integration


def test_merge_emits_aggregated_validation_yaml(tmp_path: Path):
    """2 chunks (3+2 pages) all passing → merged validation.yaml with total=5, overall_pass=True."""
    document = _build_document(tmp_path, "MyBook", [3, 2])
    chunks_root = tmp_path / "output" / "chunks"
    for chunk in document.chunks:
        _seed_chunk_dir(
            chunks_root,
            chunk.name,
            md_content=("body line " * 20),
            validation=_make_chunk_validation(
                chunk.name,
                total_pages=chunk.pages,
                successful_pages=chunk.pages,
            ),
        )

    result = merge_document(document, chunks_root)

    assert result["success"]
    assert document.validation_path.exists()
    data = yaml.safe_load(document.validation_path.read_text(encoding="utf-8"))
    assert data["page_statistics"]["total_pages"] == 5
    assert data["page_statistics"]["successful_pages"] == 5
    assert data["kqi_metrics"]["overall_quality_pass"] is True
    assert data["document_info"]["filename"] == "MyBook.pdf"


def test_merge_aggregated_validation_applies_page_offset_to_failed_pages(tmp_path: Path):
    """Chunk 2 (offset=3) fails page 1 → aggregated failed_pages_detail[0].page == 4."""
    document = _build_document(tmp_path, "OffsetBook", [3, 2])
    chunks_root = tmp_path / "output" / "chunks"
    chunk1, chunk2 = document.chunks
    _seed_chunk_dir(
        chunks_root,
        chunk1.name,
        md_content=("body line " * 20),
        validation=_make_chunk_validation(
            chunk1.name, total_pages=3, successful_pages=3
        ),
    )
    _seed_chunk_dir(
        chunks_root,
        chunk2.name,
        md_content=("body line " * 20),
        validation=_make_chunk_validation(
            chunk2.name,
            total_pages=2,
            successful_pages=1,
            failed_pages_detail=[{"page": 1, "error": "rate_limit"}],
        ),
    )

    merge_document(document, chunks_root)

    data = yaml.safe_load(document.validation_path.read_text(encoding="utf-8"))
    assert [fp["page"] for fp in data["failed_pages_detail"]] == [4]


def test_merge_aggregated_validation_marks_failed_when_one_chunk_fails(tmp_path: Path):
    """psr_1=1.0 + psr_2=0.5 → overall_quality_pass=False."""
    document = _build_document(tmp_path, "MixedBook", [10, 10])
    chunks_root = tmp_path / "output" / "chunks"
    chunk1, chunk2 = document.chunks
    _seed_chunk_dir(
        chunks_root,
        chunk1.name,
        md_content=("body line " * 20),
        validation=_make_chunk_validation(
            chunk1.name, total_pages=10, successful_pages=10
        ),
    )
    _seed_chunk_dir(
        chunks_root,
        chunk2.name,
        md_content=("body line " * 20),
        validation=_make_chunk_validation(
            chunk2.name, total_pages=10, successful_pages=5
        ),
    )

    merge_document(document, chunks_root)

    data = yaml.safe_load(document.validation_path.read_text(encoding="utf-8"))
    assert data["kqi_metrics"]["overall_quality_pass"] is False
    assert data["kqi_metrics"]["page_success_rate"] == pytest.approx(0.75, abs=1e-4)


def test_merge_skips_aggregation_when_chunk_validation_missing(tmp_path: Path):
    """Chunk lacking .validation.yaml → no aggregated file emitted, merge still succeeds."""
    document = _build_document(tmp_path, "SilentBook", [3, 2])
    chunks_root = tmp_path / "output" / "chunks"
    chunk1, chunk2 = document.chunks
    _seed_chunk_dir(
        chunks_root,
        chunk1.name,
        md_content=("body line " * 20),
        validation=_make_chunk_validation(
            chunk1.name, total_pages=3, successful_pages=3
        ),
    )
    # Chunk 2: MD present, validation.yaml missing
    _seed_chunk_dir(
        chunks_root,
        chunk2.name,
        md_content=("body line " * 20),
        validation=None,
    )

    result = merge_document(document, chunks_root)

    assert result["success"] is True
    assert not document.validation_path.exists()
