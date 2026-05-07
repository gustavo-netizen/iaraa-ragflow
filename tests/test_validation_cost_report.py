"""Tests for ``validation/cost.py`` and ``validation/report.py``."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "conversao"))

from validation.checkers import (  # noqa: E402
    ContentSyntaxChecker,
    ElementChecker,
    MarcoChecker,
    MarkdownChecker,
    QualityChecker,
    StructureChecker,
)
from validation.cost import (  # noqa: E402
    PRICE_INPUT_PER_1K_CNY,
    PRICE_OUTPUT_PER_1K_CNY,
    CostBreakdown,
    TokenUsage,
    compute_cost,
    from_batch_reports,
)
from validation.pipeline import ValidationPipeline  # noqa: E402
from validation.report import (  # noqa: E402
    RetryFailures,
    format_duration,
    load_retry_failures,
    quality_rating,
    render_quality_report,
)


# ====================================================================== cost


def test_compute_cost_basic_arithmetic():
    cost = compute_cost(input_tokens=100_000, output_tokens=50_000, pages=10, time_sec=120)
    # Both prices 0.02/1k → 100k×0.02/1k = 2.0; 50k×0.02/1k = 1.0
    assert cost.input_cost_cny == 2.0
    assert cost.output_cost_cny == 1.0
    assert cost.total_cost_cny == 3.0
    assert cost.tokens.total == 150_000
    assert cost.cost_per_page == 0.3
    assert cost.tokens_per_page == 15000.0


def test_compute_cost_handles_zero_pages():
    cost = compute_cost(input_tokens=1000, output_tokens=500, pages=0)
    # cost_per_page falls back to dividing by 1, doesn't crash
    assert cost.cost_per_page > 0


def test_compute_cost_default_constants():
    assert PRICE_INPUT_PER_1K_CNY == 0.02
    assert PRICE_OUTPUT_PER_1K_CNY == 0.02


def test_from_batch_reports_uses_explicit_input_output():
    """Post-Fase-D batch_report has tokens_input + tokens_output explicit."""
    reports = [
        {
            "pdfs": [
                {
                    "success": True,
                    "pdf_info": {"pages": 100},
                    "processing": {
                        "tokens_input": 200_000,
                        "tokens_output": 80_000,
                        "tokens": 280_000,  # ignored when explicit fields exist
                        "time": 60,
                    },
                }
            ],
            "summary": {"total_cost_cny": 5.6},
        }
    ]
    cost = from_batch_reports(reports)
    assert cost.tokens.input_tokens == 200_000
    assert cost.tokens.output_tokens == 80_000
    assert cost.pages == 100
    assert cost.recorded_cost_cny == 5.6


def test_from_batch_reports_falls_back_to_estimate_for_legacy_format():
    """Legacy batch_report has only `tokens` total → estimate input as pages × 1500."""
    reports = [
        {
            "pdfs": [
                {
                    "success": True,
                    "pdf_info": {"pages": 100},
                    "processing": {"tokens": 50_000, "time": 60},
                }
            ]
        }
    ]
    cost = from_batch_reports(reports)
    # input estimated = 100 × 1500 = 150k; output = 50k from logged total
    assert cost.tokens.input_tokens == 150_000
    assert cost.tokens.output_tokens == 50_000


def test_from_batch_reports_skips_failed_pdfs():
    reports = [
        {
            "pdfs": [
                {
                    "success": False,
                    "pdf_info": {"pages": 50},
                    "processing": {"tokens_input": 1, "tokens_output": 1},
                },
                {
                    "success": True,
                    "pdf_info": {"pages": 100},
                    "processing": {"tokens_input": 200_000, "tokens_output": 50_000, "time": 60},
                },
            ]
        }
    ]
    cost = from_batch_reports(reports)
    assert cost.pages == 100  # failed PDF's 50 pages excluded
    assert cost.tokens.input_tokens == 200_000


def test_from_batch_reports_aggregates_across_multiple_reports():
    reports = [
        {"pdfs": [{"success": True, "pdf_info": {"pages": 50}, "processing": {"tokens_input": 100_000, "tokens_output": 25_000, "time": 30}}]},
        {"pdfs": [{"success": True, "pdf_info": {"pages": 30}, "processing": {"tokens_input": 60_000, "tokens_output": 15_000, "time": 20}}]},
    ]
    cost = from_batch_reports(reports)
    assert cost.pages == 80
    assert cost.tokens.input_tokens == 160_000
    assert cost.tokens.output_tokens == 40_000
    assert cost.time_sec == 50.0


# ==================================================================== report


def _build_report(tmp_path: Path) -> "ValidationReport":
    """Synthetic delivery dir → run all 6 checkers → return the ValidationReport."""
    body = (
        "## Page 1\n\n" + "lorem ipsum dolor sit amet " * 20 + "\n"
        "## Page 2\n\n" + "consectetur adipiscing elit sed " * 20 + "\n"
        "## Page 3\n\n"
        "| col1 | col2 |\n|------|------|\n| a | b |\n\n"
        "$E=mc^2$\n\n"
        "![alt](images/page_001.png)\n"
    )
    (tmp_path / "Doc.md").write_text(f"# Doc\n\n{body}", encoding="utf-8")
    (tmp_path / "Doc.yaml").write_text("title: Doc\n", encoding="utf-8")

    pipe = ValidationPipeline(checkers=[
        StructureChecker(),
        ContentSyntaxChecker(),
        MarkdownChecker(),
        QualityChecker(),
        ElementChecker(),
        MarcoChecker(),
    ])
    return pipe.run(tmp_path)


def test_render_quality_report_includes_all_sections(tmp_path):
    report = _build_report(tmp_path)
    cost = compute_cost(input_tokens=5000, output_tokens=2000, pages=3, time_sec=45)

    out = render_quality_report(report, cost=cost, processing_time_sec=45)

    # Section anchors
    assert "## 1. 执行摘要" in out
    assert "## 2. 质量评分" in out
    assert "## 3. 内容分布" in out
    assert "## 4. 图表统计" in out
    assert "## 5. 问题列表" in out
    assert "## 6. 详细报告" in out
    assert "## 7. 建议" in out
    assert "## 8. 资源使用统计" in out


def test_render_quality_report_summary_numbers(tmp_path):
    report = _build_report(tmp_path)
    out = render_quality_report(report, processing_time_sec=120)

    assert "| 总 PDF 数 | 1 |" in out
    assert "| 总页数 | 3 |" in out


def test_render_quality_report_marco_full_compliance(tmp_path):
    report = _build_report(tmp_path)
    out = render_quality_report(report)
    # Single doc with yaml + title + page headers → 100% MARCO
    assert "100.0%" in out


def test_render_quality_report_lists_failed_pdfs_when_present(tmp_path):
    # Break the file pair to create a failure.
    (tmp_path / "Doc.md").write_text("# Doc\n\n## Page 1\n\nbody\n", encoding="utf-8")
    # Intentionally no Doc.yaml — StructureChecker will issue an "Missing YAML"

    pipe = ValidationPipeline(checkers=[StructureChecker(), MarcoChecker(), QualityChecker(), ElementChecker(), MarkdownChecker(), ContentSyntaxChecker()])
    report = pipe.run(tmp_path)

    out = render_quality_report(report)
    assert "Missing corresponding YAML file" in out


def test_render_quality_report_empty_resource_section(tmp_path):
    report = _build_report(tmp_path)
    out = render_quality_report(report)
    assert "资源监控: 未启用或无数据" in out


def test_render_quality_report_with_resource_usage(tmp_path):
    report = _build_report(tmp_path)
    ru = {
        "cpu": {"average_percent": 45.5, "peak_percent": 80.1},
        "memory": {"average_process_mb": 1200, "peak_process_mb": 1800, "peak_system_percent": 65.0, "total_system_gb": 32},
        "disk_io": {"average_read_mb_s": 5.0, "average_write_mb_s": 3.5},
        "network_io": {"average_sent_kb_s": 10.2, "average_recv_kb_s": 25.5},
        "sample_count": 100,
        "sample_interval_sec": 10,
    }
    out = render_quality_report(report, resource_usage=ru)
    assert "45.5%" in out
    assert "1800 MB" in out


def test_render_quality_report_with_retry_failures(tmp_path):
    report = _build_report(tmp_path)
    rf = RetryFailures(
        attempted=20,
        successful=18,
        permanent_failures=[{"chunk": "chunk1", "page": 5, "error": "timeout"}],
        skipped_pages=[{"chunk": "chunk2", "page": 3}],
    )
    out = render_quality_report(report, retry_failures=rf)
    assert "### 5.3 页面重试统计" in out
    assert "| 重试尝试 | 20 |" in out
    assert "永久失败页面" in out


# --------------------------------------------------------------- helpers


def test_format_duration_seconds():
    assert format_duration(45) == "45s"


def test_format_duration_minutes():
    assert format_duration(125) == "2m 5s"


def test_format_duration_hours():
    assert format_duration(3725) == "1h 2m"


def test_quality_rating_thresholds():
    assert quality_rating(95)[0] == "优秀"
    assert quality_rating(85)[0] == "良好"
    assert quality_rating(70)[0] == "一般"
    assert quality_rating(50)[0] == "较差"
    assert quality_rating(20)[0] == "很差"


def test_load_retry_failures_missing_file_returns_empty(tmp_path):
    rf = load_retry_failures(tmp_path)
    assert rf.attempted == 0
    assert rf.permanent_failures == []


def test_load_retry_failures_reads_yaml(tmp_path):
    (tmp_path / "retry_failures.yaml").write_text(
        yaml.safe_dump({
            "attempted_retries": 30,
            "successful_retries": 25,
            "permanent_failures": [{"chunk": "a", "page": 1, "error": "x"}],
            "skipped_pages": [{"chunk": "b", "page": 2}],
        }),
        encoding="utf-8",
    )
    rf = load_retry_failures(tmp_path)
    assert rf.attempted == 30
    assert rf.successful == 25
    assert len(rf.permanent_failures) == 1
    assert len(rf.skipped_pages) == 1
