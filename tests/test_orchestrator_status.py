"""Fase G.1 — Pipeline.status() and PipelineStatus rendering.

Builds synthetic ``conversao/`` roots in ``tmp_path`` to exercise:

- progress.json absent vs present (legacy "no progress" message)
- split_mapping.json discovery (chunked vs direct PDFs)
- per-document is_complete / failed_pages flags
- VALIDATION_REPORT.json folding
- as_text() preserves legacy bash-output keywords
- as_json() round-trip

No live filesystem dependency on ``conversao/`` — tests can run in CI
without API keys or actual PDFs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "conversao"))

from orchestrator import (  # noqa: E402
    DocumentStatus,
    Pipeline,
    PipelineStatus,
    _load_validation_summary,
)


# --------------------------------------------------------------- fixtures


@pytest.fixture
def empty_root(tmp_path: Path) -> Path:
    """A conversao/-shaped root with no progress, no mapping, no output."""
    root = tmp_path / "conversao"
    (root / "input" / "split_pdfs").mkdir(parents=True)
    (root / "output").mkdir()
    (root / "final-delivery").mkdir()
    return root


@pytest.fixture
def synthetic_root(empty_root: Path) -> Path:
    """A populated conversao/ root.

    Layout:
      progress.json     — in_progress, 1/2 PDFs done, 50/100 pages.
      split_mapping     — chunked PDF "a" (2 chunks) + direct PDF "b".
      output/b/b.md     — direct PDF complete (merged MD exists).
      output/a/         — absent → "a" reports incomplete.
    """
    root = empty_root

    progress = {
        "version": "0.8",
        "started_at": "2026-05-04T10:00:00",
        "updated_at": "2026-05-04T10:30:00",
        "status": "in_progress",
        "steps": {
            "split": {"status": "completed"},
            "process_chunks": {
                "status": "in_progress",
                "completed": ["a-chunk1"],
                "failed": [],
                "pending": ["a-chunk2"],
            },
            "process_direct": {
                "status": "completed",
                "completed": ["b"],
                "failed": [],
                "pending": [],
            },
            "merge": {"status": "pending"},
        },
        "pdf_progress": {},
        "statistics": {
            "total_pdfs": 2,
            "completed_pdfs": 1,
            "total_pages": 100,
            "completed_pages": 50,
            "failed_pages": 0,
        },
    }
    (root / "progress.json").write_text(json.dumps(progress), encoding="utf-8")

    mapping = {
        "stats": {},
        "chunks": [
            {
                "path": "/somewhere/a-chunk1.pdf",
                "pages": 50,
                "chunk_idx": 0,
                "total_chunks": 2,
                "original_pdf": "a.pdf",
            },
            {
                "path": "/somewhere/a-chunk2.pdf",
                "pages": 50,
                "chunk_idx": 1,
                "total_chunks": 2,
                "original_pdf": "a.pdf",
            },
        ],
        "direct": [{"pdf_path": "/somewhere/b.pdf", "pdf_name": "b.pdf"}],
    }
    (root / "input" / "split_pdfs" / "split_mapping.json").write_text(
        json.dumps(mapping), encoding="utf-8"
    )

    (root / "output" / "b").mkdir()
    (root / "output" / "b" / "b.md").write_text("# Body\n", encoding="utf-8")

    return root


# --------------------------------------------------------------- Pipeline


def test_from_env_defaults_to_orchestrator_dir():
    pipeline = Pipeline.from_env()
    assert pipeline.root.name == "conversao"


def test_from_env_accepts_custom_root(tmp_path: Path):
    pipeline = Pipeline.from_env(tmp_path)
    assert pipeline.root == tmp_path


def test_from_env_loads_app_config():
    pipeline = Pipeline.from_env()
    assert pipeline.config.ocr_model
    assert pipeline.config.llm_model


def test_run_not_yet_implemented(empty_root: Path):
    pipeline = Pipeline.from_env(empty_root)
    with pytest.raises(NotImplementedError):
        pipeline.run()


# -------------------------------------------------------- Pipeline.status


def test_status_empty_root_returns_default(empty_root: Path):
    pipeline = Pipeline.from_env(empty_root)
    status = pipeline.status()
    assert status.progress_present is False
    assert status.overall_status == "not_started"
    assert status.documents == []
    assert status.validation is None


def test_status_reads_progress_summary(synthetic_root: Path):
    pipeline = Pipeline.from_env(synthetic_root)
    status = pipeline.status()
    assert status.progress_present is True
    assert status.overall_status == "in_progress"
    assert status.statistics["total_pdfs"] == 2
    assert status.statistics["completed_pages"] == 50
    assert status.steps["split"]["status"] == "completed"
    assert status.steps["process_chunks"]["status"] == "in_progress"


def test_status_lists_documents_from_mapping(synthetic_root: Path):
    pipeline = Pipeline.from_env(synthetic_root)
    status = pipeline.status()
    by_name = {d.name: d for d in status.documents}
    assert set(by_name) == {"a", "b"}

    # b is direct + merged MD exists → complete
    assert by_name["b"].is_chunked is False
    assert by_name["b"].is_complete is True
    assert by_name["b"].chunks_total == 0

    # a is chunked + no merged MD → incomplete
    assert by_name["a"].is_chunked is True
    assert by_name["a"].is_complete is False
    assert by_name["a"].chunks_total == 2


def test_status_picks_up_validation_report(synthetic_root: Path):
    report = {
        "summary": {"passed": False},
        "results": [
            {
                "name": "Structure",
                "passed": False,
                "issues": [{"target": "x", "message": "bad"}],
                "warnings": [],
            },
            {
                "name": "Syntax",
                "passed": True,
                "issues": [],
                "warnings": [{"target": "y", "message": "advisory"}],
            },
        ],
    }
    (synthetic_root / "final-delivery" / "VALIDATION_REPORT.json").write_text(
        json.dumps(report), encoding="utf-8"
    )

    pipeline = Pipeline.from_env(synthetic_root)
    status = pipeline.status()
    assert status.validation == {"passed": False, "issues": 1, "warnings": 1}


def test_status_handles_corrupt_validation_report(synthetic_root: Path):
    (synthetic_root / "final-delivery" / "VALIDATION_REPORT.json").write_text(
        "{not json", encoding="utf-8"
    )
    pipeline = Pipeline.from_env(synthetic_root)
    status = pipeline.status()
    assert status.validation is None


def test_status_handles_corrupt_split_mapping(empty_root: Path):
    (empty_root / "input" / "split_pdfs" / "split_mapping.json").write_text(
        "garbage", encoding="utf-8"
    )
    pipeline = Pipeline.from_env(empty_root)
    status = pipeline.status()
    assert status.documents == []


# -------------------------------------------------- PipelineStatus.as_text


def test_as_text_no_progress_returns_legacy_message():
    status = PipelineStatus()
    assert status.as_text() == "没有找到进度文件，尚未开始处理"


def test_as_text_preserves_legacy_keywords(synthetic_root: Path):
    pipeline = Pipeline.from_env(synthetic_root)
    text = pipeline.status().as_text()

    assert "📊 DocMind 处理进度" in text
    assert "状态: in_progress" in text
    assert "步骤状态:" in text
    assert "✅ split: completed" in text
    assert "🔄 process_chunks: in_progress" in text
    assert "✅ process_direct: completed" in text
    assert "⏳ merge: pending" in text
    assert "统计:" in text
    assert "PDF: 1/2" in text
    assert "页面: 50/100" in text
    assert "失败: 0" in text
    assert "总进度: 50.0%" in text


def test_as_text_appends_documents_section(synthetic_root: Path):
    pipeline = Pipeline.from_env(synthetic_root)
    text = pipeline.status().as_text()

    assert "文档:" in text
    assert "✅ b [direct]" in text
    assert "⏳ a [chunked]" in text


def test_as_text_appends_validation_section_when_present(synthetic_root: Path):
    (synthetic_root / "final-delivery" / "VALIDATION_REPORT.json").write_text(
        json.dumps(
            {"summary": {"passed": True}, "results": []}
        ),
        encoding="utf-8",
    )
    pipeline = Pipeline.from_env(synthetic_root)
    text = pipeline.status().as_text()
    assert "验证:" in text
    assert "✅ 0 问题, 0 警告" in text


# -------------------------------------------------- PipelineStatus.as_json


def test_as_json_serializable(synthetic_root: Path):
    pipeline = Pipeline.from_env(synthetic_root)
    serialized = json.dumps(pipeline.status().as_json(), ensure_ascii=False)
    parsed = json.loads(serialized)
    assert parsed["overall_status"] == "in_progress"
    assert parsed["progress_present"] is True
    assert {d["name"] for d in parsed["documents"]} == {"a", "b"}
    by_name = {d["name"]: d for d in parsed["documents"]}
    assert by_name["b"]["is_complete"] is True
    assert by_name["a"]["is_complete"] is False


def test_as_json_empty_root(empty_root: Path):
    pipeline = Pipeline.from_env(empty_root)
    parsed = pipeline.status().as_json()
    assert parsed["progress_present"] is False
    assert parsed["overall_status"] == "not_started"
    assert parsed["documents"] == []
    assert parsed["validation"] is None


# ------------------------------------------- _load_validation_summary edges


def test_load_validation_infers_passed_from_results(tmp_path: Path):
    path = tmp_path / "v.json"
    path.write_text(
        json.dumps(
            {
                "results": [
                    {"name": "X", "passed": True, "issues": [], "warnings": []},
                    {"name": "Y", "passed": True, "issues": [], "warnings": []},
                ]
            }
        )
    )
    summary = _load_validation_summary(path)
    assert summary == {"passed": True, "issues": 0, "warnings": 0}


def test_load_validation_returns_none_for_invalid(tmp_path: Path):
    path = tmp_path / "v.json"
    path.write_text("not json at all")
    assert _load_validation_summary(path) is None


# ------------------------------------------------- DocumentStatus as_dict


def test_document_status_as_dict_round_trip():
    ds = DocumentStatus(
        name="x", is_chunked=True, is_complete=False, chunks_total=3, failed_pages=[2, 5]
    )
    d = ds.as_dict()
    assert d == {
        "name": "x",
        "is_chunked": True,
        "is_complete": False,
        "chunks_total": 3,
        "failed_pages": [2, 5],
    }
