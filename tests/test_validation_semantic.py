"""Tests for the semantic checkers — Markdown, Quality, Element, Marco."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "conversao"))

from validation.checkers import (  # noqa: E402
    ElementChecker,
    MarcoChecker,
    MarkdownChecker,
    QualityChecker,
    split_into_pages,
)


# ============================================================== split_into_pages


def test_split_into_pages_drops_preamble_and_empties():
    md = (
        "# Title\n\n*Some metadata*\n\n## Page 1\n\nFirst page body\n\n"
        "## Page 2\n\nSecond page body\n"
    )
    pages = split_into_pages(md)
    assert pages == ["First page body", "Second page body"]


def test_split_into_pages_handles_no_pages():
    assert split_into_pages("# Just a title\n\nBody only.\n") == []


def test_split_into_pages_handles_empty():
    assert split_into_pages("") == []


# ============================================================ MarkdownChecker


def _seed(target: Path, name: str, body: str = "## Page 1\n\nbody\n") -> None:
    (target / f"{name}.md").write_text(f"# {name}\n\n{body}", encoding="utf-8")
    (target / f"{name}.yaml").write_text(f"title: {name}\n", encoding="utf-8")


def test_markdown_checker_counts_pages_and_figs(tmp_path):
    body = (
        "## Page 1\n\nbody\n\n### Fig 1: caption\n\n"
        "## Page 2\n\nbody\n\n### Fig 2: caption\n"
    )
    _seed(tmp_path, "A", body)
    result = MarkdownChecker().run(tmp_path)
    per_file = result.stats["per_file"]["A"]
    assert per_file["pages"] == 2
    assert per_file["figures"] == 2
    assert result.stats["total_pages"] == 2
    assert result.stats["total_figures_via_fig_regex"] == 2


def test_markdown_checker_warns_on_no_pages(tmp_path):
    _seed(tmp_path, "A", body="just body, no page headers " * 100)
    result = MarkdownChecker().run(tmp_path)
    assert any("No page headers" in w["message"] for w in result.warnings)


def test_markdown_checker_warns_on_small_file(tmp_path):
    _seed(tmp_path, "tiny", body="x")
    result = MarkdownChecker().run(tmp_path)
    assert any("Very small file" in w["message"] for w in result.warnings)


def test_markdown_checker_doesnt_warn_above_threshold(tmp_path):
    body = "## Page 1\n\n" + ("x" * 1500) + "\n"
    _seed(tmp_path, "big", body)
    result = MarkdownChecker().run(tmp_path)
    assert all("Very small file" not in w["message"] for w in result.warnings)


# =============================================================== QualityChecker


_LOREM = "lorem ipsum dolor sit amet consectetur adipiscing elit "  # 55 chars, varied


def test_quality_checker_distribution_buckets(tmp_path):
    # Note: pages that are empty *between* `## Page N` headers are dropped by
    # split_into_pages (legacy behavior, matches GQR). To populate the empty
    # bucket we need 1-9 chars after strip.
    body = (
        "## Page 1\n\nshort\n"  # 5 chars → empty (<10)
        "## Page 2\n\n" + _LOREM + "\n"  # 55 chars → short
        "## Page 3\n\n" + _LOREM * 6 + "\n"  # 330 chars → medium
        "## Page 4\n\n" + _LOREM * 20 + "\n"  # 1100 chars → long
    )
    _seed(tmp_path, "A", body)
    result = QualityChecker().run(tmp_path)
    file_stats = result.stats["per_file"]["A"]
    assert file_stats["empty_pages"] == 1
    assert file_stats["short_pages"] == 1
    assert file_stats["medium_pages"] == 1
    assert file_stats["long_pages"] == 1


def test_quality_checker_overall_score(tmp_path):
    body = (
        "## Page 1\n\n" + _LOREM + "\n"  # short
        "## Page 2\n\n" + _LOREM + "\n"  # short
        "## Page 3\n\n" + _LOREM * 6 + "\n"  # medium
        "## Page 4\n\n" + _LOREM * 6 + "\n"  # medium
    )
    _seed(tmp_path, "A", body)
    result = QualityChecker().run(tmp_path)
    # 2 medium / 4 total = 50% valid
    assert result.stats["overall_quality_score"] == 50.0


def test_quality_checker_flags_garbled_chars(tmp_path):
    # Pure U+FFFD replacement character: ratio > 5%.
    body = "## Page 1\n\n" + "�" * 20 + (_LOREM * 2) + "\n"
    _seed(tmp_path, "A", body)
    result = QualityChecker().run(tmp_path)
    issues = result.stats["per_file"]["A"]["issues"]
    assert any("可能存在乱码" in issue for issue in issues)


def test_quality_checker_flags_repeated_chars(tmp_path):
    body = "## Page 1\n\n" + _LOREM * 4 + "aaaaaaaaaaaaaa" + " end\n"
    _seed(tmp_path, "A", body)
    result = QualityChecker().run(tmp_path)
    issues = result.stats["per_file"]["A"]["issues"]
    assert any("异常重复字符" in issue for issue in issues)


def test_quality_checker_marks_review_needed_on_high_empty_ratio(tmp_path):
    # 3 empty + 2 long: empty/total = 0.6 > 0.2 → needs_review
    body = (
        "## Page 1\n\nshort\n"
        "## Page 2\n\nshort\n"
        "## Page 3\n\nshort\n"
        "## Page 4\n\n" + _LOREM * 20 + "\n"
        "## Page 5\n\n" + _LOREM * 20 + "\n"
    )
    _seed(tmp_path, "A", body)
    result = QualityChecker().run(tmp_path)
    assert "A" in result.stats["review_needed"]
    assert result.stats["per_file"]["A"]["needs_review"]


def test_quality_checker_no_review_when_clean(tmp_path):
    body = (
        "## Page 1\n\n" + _LOREM * 20 + "\n"
        "## Page 2\n\n" + _LOREM * 20 + "\n"
    )
    _seed(tmp_path, "A", body)
    result = QualityChecker().run(tmp_path)
    assert "A" not in result.stats["review_needed"]
    assert result.stats["per_file"]["A"]["needs_review"] is False


# =============================================================== ElementChecker


def test_element_checker_counts_tables(tmp_path):
    body = (
        "## Page 1\n\n"
        "| col1 | col2 |\n|------|------|\n| a | b |\n\n"
        "## Page 2\n\n"
        "no table here\n"
    )
    _seed(tmp_path, "A", body)
    result = ElementChecker().run(tmp_path)
    assert result.stats["per_file"]["A"]["tables"] == 1


def test_element_checker_counts_formulas_inline_and_display(tmp_path):
    body = (
        "## Page 1\n\nFormula: $E=mc^2$\n\n"
        "## Page 2\n\n$$\\int_0^1 x dx$$\n\n"
        "## Page 3\n\nplain text\n"
    )
    _seed(tmp_path, "A", body)
    result = ElementChecker().run(tmp_path)
    assert result.stats["per_file"]["A"]["formulas"] == 2


def test_element_checker_counts_images(tmp_path):
    body = (
        "## Page 1\n\n![alt](images/page_001.png)\n\n"
        "## Page 2\n\n<figure>x</figure>\n\n"
        "## Page 3\n\nno image\n"
    )
    _seed(tmp_path, "A", body)
    result = ElementChecker().run(tmp_path)
    assert result.stats["per_file"]["A"]["images"] == 2


def test_element_checker_counts_code_blocks(tmp_path):
    body = "## Page 1\n\n```python\nprint('x')\n```\n\n## Page 2\n\nplain\n"
    _seed(tmp_path, "A", body)
    result = ElementChecker().run(tmp_path)
    assert result.stats["per_file"]["A"]["code_blocks"] == 1


def test_element_checker_aggregates_across_files(tmp_path):
    _seed(tmp_path, "A", "## Page 1\n\n$E=mc^2$\n")
    _seed(tmp_path, "B", "## Page 1\n\n$F=ma$\n## Page 2\n\n$x=y$\n")
    result = ElementChecker().run(tmp_path)
    assert result.stats["total_formulas"] == 3


# ================================================================= MarcoChecker


def test_marco_checker_passes_when_all_three_present(tmp_path):
    _seed(tmp_path, "A", "## Page 1\n\nbody\n")
    result = MarcoChecker().run(tmp_path)
    assert "A" in result.stats["compliant"]
    assert result.stats["compliance_rate"] == 100.0


def test_marco_checker_fails_when_yaml_missing(tmp_path):
    (tmp_path / "A.md").write_text("# A\n\n## Page 1\n\nbody\n", encoding="utf-8")
    # no yaml file
    result = MarcoChecker().run(tmp_path)
    assert any(item["name"] == "A" for item in result.stats["non_compliant"])
    assert "has_yaml" in result.stats["non_compliant"][0]["missing"]


def test_marco_checker_fails_when_title_missing(tmp_path):
    (tmp_path / "A.md").write_text("## Page 1\n\nbody\n", encoding="utf-8")
    (tmp_path / "A.yaml").write_text("title: A\n", encoding="utf-8")
    result = MarcoChecker().run(tmp_path)
    assert "A" in [item["name"] for item in result.stats["non_compliant"]]


def test_marco_checker_fails_when_page_headers_missing(tmp_path):
    _seed(tmp_path, "A", "just body, no page headers\n")
    result = MarcoChecker().run(tmp_path)
    assert "A" in [item["name"] for item in result.stats["non_compliant"]]


def test_marco_checker_compliance_rate_partial(tmp_path):
    _seed(tmp_path, "A", "## Page 1\n\nbody\n")
    (tmp_path / "B.md").write_text("# B\n\nno page headers\n", encoding="utf-8")
    (tmp_path / "B.yaml").write_text("title: B\n", encoding="utf-8")
    result = MarcoChecker().run(tmp_path)
    assert result.stats["compliance_rate"] == 50.0
