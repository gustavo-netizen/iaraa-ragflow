"""Tests for ``validation/checkers.py`` — StructureChecker + ContentSyntaxChecker.

Synthetic flat ``final-delivery/``-shaped fixtures. No I/O outside tmp_path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "conversao"))

from validation.checkers import (  # noqa: E402
    CheckResult,
    ContentSyntaxChecker,
    StructureChecker,
)
from validation.pipeline import ValidationPipeline  # noqa: E402


def _seed_delivery(root: Path, names: list[str]) -> None:
    """Create matching .md + .yaml file pairs."""
    for name in names:
        (root / f"{name}.md").write_text(
            f"# {name}\n\n## Page 1\n\nBody text\n",
            encoding="utf-8",
        )
        (root / f"{name}.yaml").write_text(
            f"title: {name}\nauthors:\n  - SOMEONE\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------- StructureChecker


def test_structure_checker_passes_on_clean_directory(tmp_path):
    _seed_delivery(tmp_path, ["A", "B", "C"])
    result = StructureChecker().run(tmp_path)
    assert result.passed
    assert result.stats["md_count"] == 3
    assert result.stats["yaml_count"] == 3
    assert result.stats["missing_yaml"] == 0


def test_structure_checker_flags_missing_yaml(tmp_path):
    _seed_delivery(tmp_path, ["A", "B"])
    (tmp_path / "B.yaml").unlink()  # break pair
    result = StructureChecker().run(tmp_path)
    assert not result.passed
    assert result.stats["missing_yaml"] == 1
    assert any("Missing corresponding YAML" in i["message"] for i in result.issues)


def test_structure_checker_enforces_expected_count(tmp_path):
    _seed_delivery(tmp_path, ["A", "B"])
    result = StructureChecker(expected_count=5).run(tmp_path)
    assert not result.passed
    assert any("Expected 5 MD files, found 2" in i["message"] for i in result.issues)


def test_structure_checker_excludes_quality_report(tmp_path):
    _seed_delivery(tmp_path, ["A"])
    (tmp_path / "QUALITY_REPORT.md").write_text("# report", encoding="utf-8")
    result = StructureChecker().run(tmp_path)
    assert result.stats["md_count"] == 1


def test_structure_checker_handles_missing_directory(tmp_path):
    target = tmp_path / "does-not-exist"
    result = StructureChecker().run(target)
    assert not result.passed


# ---------------- J.5: footnote sidecar pairing + body-leak detection -------


def _write_sidecar(path: Path, **overrides) -> None:
    """Helper: escreve sidecar canônico com overrides opcionais por campo."""
    import yaml as _yaml

    doc = {"version": "1.0", "pdf_name": path.stem.split(".")[0],
           "total_pages": 1, "notes": []}
    doc.update(overrides)
    path.write_text(_yaml.dump(doc, allow_unicode=True), encoding="utf-8")


def test_structure_checker_passes_with_valid_sidecar_pairing(tmp_path: Path) -> None:
    """MD + YAML + footnotes.yaml válido: passa, conta o sidecar, sem leak."""
    _seed_delivery(tmp_path, ["A"])
    _write_sidecar(tmp_path / "A.footnotes.yaml")

    result = StructureChecker().run(tmp_path)
    assert result.passed
    assert result.stats["footnote_sidecars"] == 1
    assert result.stats["body_leaks"] == 0


def test_structure_checker_warns_on_body_leak(tmp_path: Path) -> None:
    """Body com `**Footnotes:**` literal vira warning (legacy não cleaned)."""
    _seed_delivery(tmp_path, ["A"])
    (tmp_path / "A.md").write_text(
        "# A\n\n## Page 1\n\nBody\n\n---\n\n**Footnotes:**\n\n[^1]: x\n",
        encoding="utf-8",
    )

    result = StructureChecker().run(tmp_path)
    # warning, não issue → ainda pode passar
    assert result.stats["body_leaks"] == 1
    assert any("**Footnotes:**" in w["message"] for w in result.warnings)


def test_structure_checker_validates_sidecar_schema_missing_keys(tmp_path: Path) -> None:
    """Sidecar sem `version` ou `pdf_name` vira issue (não warning)."""
    _seed_delivery(tmp_path, ["A"])
    (tmp_path / "A.footnotes.yaml").write_text("notes: []\n", encoding="utf-8")

    result = StructureChecker().run(tmp_path)
    assert not result.passed
    messages = [i["message"] for i in result.issues]
    assert any("missing 'version'" in m for m in messages)
    assert any("missing 'pdf_name'" in m for m in messages)


def test_structure_checker_validates_sidecar_schema_notes_not_list(tmp_path: Path) -> None:
    """`notes` deve ser lista (mesmo vazia); dict ou string vira issue."""
    _seed_delivery(tmp_path, ["A"])
    _write_sidecar(tmp_path / "A.footnotes.yaml", notes={"page1": ["x"]})  # dict, errado

    result = StructureChecker().run(tmp_path)
    assert not result.passed
    assert any("'notes' is not a list" in i["message"] for i in result.issues)


def test_structure_checker_handles_malformed_sidecar_yaml(tmp_path: Path) -> None:
    """YAML inválido vira issue específica."""
    _seed_delivery(tmp_path, ["A"])
    (tmp_path / "A.footnotes.yaml").write_text(
        "version: '1.0'\nnotes:\n  - {page: 1, id:\n", encoding="utf-8"
    )

    result = StructureChecker().run(tmp_path)
    assert not result.passed
    assert any("invalid YAML" in i["message"] for i in result.issues)


def test_structure_checker_no_sidecar_no_op(tmp_path: Path) -> None:
    """Livros legacy sem sidecar: stat=0, sem issue."""
    _seed_delivery(tmp_path, ["A", "B"])

    result = StructureChecker().run(tmp_path)
    assert result.passed
    assert result.stats["footnote_sidecars"] == 0
    assert result.stats["body_leaks"] == 0
    assert result.stats["md_count"] == 2


# -------------------------------------------------------- ContentSyntaxChecker


def test_content_syntax_passes_on_clean_files(tmp_path):
    _seed_delivery(tmp_path, ["A"])
    result = ContentSyntaxChecker().run(tmp_path)
    assert result.passed
    assert result.issues == []


def test_content_syntax_flags_json_fence(tmp_path):
    (tmp_path / "A.md").write_text(
        "# title\n\n```json\n{\"foo\": 1}\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "A.yaml").write_text("title: A\n", encoding="utf-8")
    result = ContentSyntaxChecker().run(tmp_path)
    assert not result.passed
    assert any("JSON code blocks" in i["message"] for i in result.issues)


def test_content_syntax_flags_body_text_leak(tmp_path):
    (tmp_path / "A.md").write_text(
        '# title\n\n"body_text": "leaked"\n',
        encoding="utf-8",
    )
    (tmp_path / "A.yaml").write_text("title: A\n", encoding="utf-8")
    result = ContentSyntaxChecker().run(tmp_path)
    assert not result.passed
    assert any("body_text" in i["message"] for i in result.issues)


def test_content_syntax_warns_on_chart_type_leak(tmp_path):
    (tmp_path / "A.md").write_text(
        '# title\n\n"chart_type": "line"\n',
        encoding="utf-8",
    )
    (tmp_path / "A.yaml").write_text("title: A\n", encoding="utf-8")
    result = ContentSyntaxChecker().run(tmp_path)
    # chart_type is warning-level; doesn't fail the check
    assert result.passed
    assert any("chart_type" in w["message"] for w in result.warnings)


def test_content_syntax_flags_invalid_yaml(tmp_path):
    (tmp_path / "A.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "A.yaml").write_text("title: [unclosed", encoding="utf-8")
    result = ContentSyntaxChecker().run(tmp_path)
    assert not result.passed
    assert any("Invalid YAML" in i["message"] for i in result.issues)


def test_content_syntax_warns_on_yaml_parsing_to_none(tmp_path):
    (tmp_path / "A.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "A.yaml").write_text("# only a comment, nothing else\n", encoding="utf-8")
    result = ContentSyntaxChecker().run(tmp_path)
    assert any("parses to None" in w["message"] for w in result.warnings)


def test_content_syntax_literal_newlines_warn_threshold(tmp_path):
    # Many \n outside LaTeX trigger the warning (10× code-block threshold).
    body = "\\n" * 50
    (tmp_path / "A.md").write_text(f"# A\n\n{body}\n", encoding="utf-8")
    (tmp_path / "A.yaml").write_text("title: A\n", encoding="utf-8")
    result = ContentSyntaxChecker().run(tmp_path)
    assert any("literal \\n" in w["message"] for w in result.warnings)


def test_content_syntax_ignores_literal_n_in_latex(tmp_path):
    # \n inside $$...$$ should be ignored.
    body = r"$$ \\n_{i=1} \\n_{j=1} $$" * 10
    (tmp_path / "A.md").write_text(f"# A\n\n{body}\n", encoding="utf-8")
    (tmp_path / "A.yaml").write_text("title: A\n", encoding="utf-8")
    result = ContentSyntaxChecker().run(tmp_path)
    assert all("literal \\n" not in w["message"] for w in result.warnings)


def test_content_syntax_excludes_validation_report_from_yaml_scan(tmp_path):
    (tmp_path / "A.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "A.yaml").write_text("title: A\n", encoding="utf-8")
    (tmp_path / "VALIDATION_REPORT.yaml").write_text("invalid: [unclosed", encoding="utf-8")
    result = ContentSyntaxChecker().run(tmp_path)
    # invalid VALIDATION_REPORT.yaml shouldn't fail the check (excluded)
    assert result.passed


# ------------------------------------------------------------ ValidationPipeline


def test_pipeline_aggregates_passing_results(tmp_path):
    _seed_delivery(tmp_path, ["A"])
    pipe = ValidationPipeline(checkers=[StructureChecker(), ContentSyntaxChecker()])
    report = pipe.run(tmp_path)
    assert report.passed
    assert len(report.results) == 2
    assert report.total_issues == 0
    assert report.stats("structure")["md_count"] == 1


def test_pipeline_passed_false_when_any_checker_fails(tmp_path):
    _seed_delivery(tmp_path, ["A"])
    (tmp_path / "A.yaml").unlink()
    pipe = ValidationPipeline(checkers=[StructureChecker(), ContentSyntaxChecker()])
    report = pipe.run(tmp_path)
    assert not report.passed
    assert report.total_issues >= 1


def test_pipeline_runs_checkers_in_order(tmp_path):
    _seed_delivery(tmp_path, ["A"])
    pipe = ValidationPipeline(checkers=[ContentSyntaxChecker(), StructureChecker()])
    report = pipe.run(tmp_path)
    assert [r.name for r in report.results] == ["content_syntax", "structure"]
