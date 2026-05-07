"""Pluggable validation checkers.

Each checker has a ``name`` and a ``run(target)`` method that returns a
``CheckResult``. The target is a directory path (typically ``final-delivery/``).
Checkers don't share state; the ``ValidationPipeline`` runs them and
aggregates results.

Mapping to F.1 inventory IDs is in each docstring (e.g. "A1-A2", "B1-B3").
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# --------------------------------------------------------------- Result type


@dataclass
class CheckResult:
    """Outcome of one ``Checker.run`` invocation.

    ``passed`` mirrors the legacy boolean from ``final_delivery_check.py``:
    True when no blocking issue was found. Issues are blocking failures,
    warnings are advisory, ``stats`` carries arbitrary numeric/structural
    data the report layer consumes.
    """

    name: str
    passed: bool = True
    issues: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[Dict[str, str]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def add_issue(self, target: str, message: str) -> None:
        self.issues.append({"target": target, "message": message})
        self.passed = False

    def add_warning(self, target: str, message: str) -> None:
        self.warnings.append({"target": target, "message": message})


class Checker(ABC):
    """Base class for pluggable validators.

    Subclasses set ``name`` (used in reports) and implement ``run(target)``.
    """

    name: str = ""

    @abstractmethod
    def run(self, target: Path) -> CheckResult:
        """Validate ``target`` and return a structured result."""
        raise NotImplementedError


# ---------------------------------------------------------- helper utilities


def _md_files_in(target: Path) -> List[Path]:
    """All ``*.md`` files in ``target``, sorted, excluding ``QUALITY_REPORT*``."""
    return sorted(
        f
        for f in target.glob("*.md")
        if not f.name.startswith("QUALITY_REPORT")
    )


def _yaml_files_in(target: Path) -> List[Path]:
    """All ``*.yaml`` files in ``target``, sorted, excluding ``VALIDATION_REPORT*``."""
    return sorted(
        f
        for f in target.glob("*.yaml")
        if not f.name.startswith("VALIDATION_REPORT")
    )


# =========================================================== StructureChecker


class StructureChecker(Checker):
    """File-count and md/yaml pairing checks. Maps F.1 inventory A1, A2.

    Optionally enforces ``expected_count`` (default off). Pairs every ``*.md``
    against ``{stem}.yaml`` in the same directory.

    J.5: também valida pareamento ``{stem}.md`` ↔ ``{stem}.footnotes.yaml``
    (sidecar emitido por Stage 1 pós-J.2) e flagga body-leaks de
    ``**Footnotes:**`` literal — deveria ter sido removido pelo cleanup
    de J.0.
    """

    name = "structure"

    def __init__(self, expected_count: Optional[int] = None):
        self.expected_count = expected_count

    def run(self, target: Path) -> CheckResult:
        result = CheckResult(name=self.name)

        if not target.exists():
            result.add_issue("", f"Delivery directory does not exist: {target}")
            result.stats["md_count"] = 0
            return result

        md_files = _md_files_in(target)
        result.stats["md_count"] = len(md_files)

        # A1: file count vs expected
        if self.expected_count is not None and len(md_files) != self.expected_count:
            result.add_issue(
                "",
                f"Expected {self.expected_count} MD files, found {len(md_files)}",
            )

        # A2: md/yaml pairs
        missing_yaml = 0
        for md_file in md_files:
            yaml_file = target / f"{md_file.stem}.yaml"
            if not yaml_file.exists():
                result.add_issue(md_file.stem, "Missing corresponding YAML file")
                missing_yaml += 1

        result.stats["missing_yaml"] = missing_yaml
        result.stats["yaml_count"] = len(md_files) - missing_yaml

        # J.5: footnote sidecar pairing + body-leak detection
        footnote_sidecars = 0
        body_leaks = 0
        for md_file in md_files:
            sidecar = target / f"{md_file.stem}.footnotes.yaml"
            if sidecar.exists():
                footnote_sidecars += 1
                self._validate_footnote_sidecar(sidecar, md_file.stem, result)

            try:
                body = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            if "**Footnotes:**" in body:
                body_leaks += 1
                result.add_warning(
                    md_file.stem,
                    f"Body contains literal **Footnotes:** label "
                    f"(legacy leak — re-run Stage 2 cleanup post-J.0)",
                )

        result.stats["footnote_sidecars"] = footnote_sidecars
        result.stats["body_leaks"] = body_leaks
        return result

    @staticmethod
    def _validate_footnote_sidecar(
        sidecar: Path, stem: str, result: CheckResult
    ) -> None:
        """Schema canônico ADR-0004: dict com `version`, `pdf_name`, `notes: list`."""
        try:
            data = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            result.add_issue(stem, f"{sidecar.name}: invalid YAML — {e}")
            return
        except Exception as e:
            result.add_issue(stem, f"{sidecar.name}: cannot read — {e}")
            return

        if not isinstance(data, dict):
            result.add_issue(stem, f"{sidecar.name}: not a YAML mapping")
            return
        if "version" not in data:
            result.add_issue(stem, f"{sidecar.name}: missing 'version' field")
        if "pdf_name" not in data:
            result.add_issue(stem, f"{sidecar.name}: missing 'pdf_name' field")
        if not isinstance(data.get("notes"), list):
            result.add_issue(stem, f"{sidecar.name}: 'notes' is not a list")


# ===================================================== ContentSyntaxChecker


_JSON_FENCE_RE = re.compile(r"```json", re.IGNORECASE)
_LATEX_DISPLAY_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
_LATEX_INLINE_RE = re.compile(r"\$[^$]+\$")
_LATEX_BRACKET_RE = re.compile(r"\\\[.*?\\\]", re.DOTALL)
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


class ContentSyntaxChecker(Checker):
    """Per-file content syntax integrity. Maps F.1 inventory B1, B2, B3.

    - B1 (json remnants): ``\\`\\`\\`json`` blocks, raw JSON keys (``"body_text":``,
      ``"chart_type":``) leaking into the MD.
    - B2 (literal newlines): ``\\n`` literals outside LaTeX/code contexts.
    - B3 (yaml syntax): every ``*.yaml`` parses without ``YAMLError``.
    """

    name = "content_syntax"

    def run(self, target: Path) -> CheckResult:
        result = CheckResult(name=self.name)

        if not target.exists():
            result.add_issue("", f"Target does not exist: {target}")
            return result

        # B1 + B2 over MD files
        for md_file in _md_files_in(target):
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception as e:
                result.add_issue(md_file.stem, f"Cannot read {md_file.name}: {e}")
                continue

            # B1: ```json fences
            json_blocks = len(_JSON_FENCE_RE.findall(content))
            if json_blocks > 0:
                result.add_issue(
                    md_file.stem,
                    f"Found {json_blocks} JSON code blocks in {md_file.name}",
                )

            # B1: leaked JSON keys
            body_text_refs = content.count('"body_text":')
            if body_text_refs > 0:
                result.add_issue(
                    md_file.stem,
                    f"Found {body_text_refs} 'body_text' references in {md_file.name}",
                )
            chart_type_refs = content.count('"chart_type":')
            if chart_type_refs > 0:
                result.add_warning(
                    md_file.stem,
                    f"Found {chart_type_refs} 'chart_type' references in {md_file.name}",
                )

            # B2: literal \n outside LaTeX
            literal_n_count = self._count_literal_newlines(content)
            if literal_n_count > 0:
                # Mirror legacy threshold: warn when count exceeds 10× the number of
                # code blocks (some legitimately contain ``\n``).
                code_blocks = len(_CODE_BLOCK_RE.findall(content))
                if literal_n_count > code_blocks * 10:
                    result.add_warning(
                        md_file.stem,
                        f"Found {literal_n_count} literal \\n in {md_file.name} (may need review)",
                    )

        # B3: yaml syntax
        for yaml_file in _yaml_files_in(target):
            try:
                content = yaml_file.read_text(encoding="utf-8")
                data = yaml.safe_load(content)
                if data is None and yaml_file.stat().st_size > 10:
                    result.add_warning(
                        yaml_file.stem,
                        f"YAML file parses to None: {yaml_file.name}",
                    )
            except yaml.YAMLError as e:
                result.add_issue(
                    yaml_file.stem,
                    f"Invalid YAML in {yaml_file.name}: {e}",
                )
            except Exception as e:
                result.add_issue(
                    yaml_file.stem,
                    f"Cannot read {yaml_file.name}: {e}",
                )

        return result

    @staticmethod
    def _count_literal_newlines(content: str) -> int:
        """Count ``\\n`` literals outside ``$..$``/``$$..$$``/``\\[..\\]`` blocks."""
        stripped = _LATEX_DISPLAY_RE.sub("", content)
        stripped = _LATEX_INLINE_RE.sub("", stripped)
        stripped = _LATEX_BRACKET_RE.sub("", stripped)
        return stripped.count("\\n")


# -------------------------------------------------------- Page-split utility


_PAGE_HEADER_RE = re.compile(r"^## Page \d+", re.MULTILINE)


def split_into_pages(content: str) -> List[str]:
    """Split MD by ``^## Page N`` headers, drop preamble and empty entries.

    Mirrors the splitting logic in ``generate_quality_report.py:analyze_pdf``.
    Used by ``MarkdownChecker``, ``QualityChecker`` and ``ElementChecker``.
    """
    pages = _PAGE_HEADER_RE.split(content)
    pages = [p.strip() for p in pages if p.strip()]
    if pages and pages[0].startswith("#"):
        pages = pages[1:]
    return pages


# ============================================================== MarkdownChecker


_FIG_HEADER_RE = re.compile(r"### Fig \d+:")


class MarkdownChecker(Checker):
    """Markdown structural counts. Maps F.1 inventory C1, C2, C3.

    - C1 page header count (``## Page N``)
    - C2 figure ref count (``### Fig N:`` — note: only matches ``Fig`` not
      ``Figure``; legacy regex preserved for byte-equivalence)
    - C3 file size warning when ``< 1000`` chars
    """

    name = "markdown_structure"

    SMALL_FILE_THRESHOLD = 1000

    def run(self, target: Path) -> CheckResult:
        result = CheckResult(name=self.name)
        result.stats["per_file"] = {}
        result.stats["total_pages"] = 0
        result.stats["total_figures_via_fig_regex"] = 0
        result.stats["total_chars"] = 0

        for md_file in _md_files_in(target):
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception as e:
                result.add_issue(md_file.stem, f"Cannot read {md_file.name}: {e}")
                continue

            pages = len(_PAGE_HEADER_RE.findall(content))
            figures = len(_FIG_HEADER_RE.findall(content))
            file_size = len(content)

            if pages == 0:
                result.add_warning(md_file.stem, f"No page headers found in {md_file.name}")
            if file_size < self.SMALL_FILE_THRESHOLD:
                result.add_warning(
                    md_file.stem,
                    f"Very small file ({file_size} chars): {md_file.name}",
                )

            result.stats["per_file"][md_file.stem] = {
                "pages": pages,
                "figures": figures,
                "file_size": file_size,
            }
            result.stats["total_pages"] += pages
            result.stats["total_figures_via_fig_regex"] += figures
            result.stats["total_chars"] += file_size

        return result


# =============================================================== QualityChecker


_GARBLED_RE = re.compile(r"[�]")
_REPEATED_RE = re.compile(r"(.)\1{10,}")


class QualityChecker(Checker):
    """Page-level semantic quality metrics. Maps F.1 inventory D1-D5.

    Per-page:
    - D1 distribution buckets (empty <10, short <100, medium <500, long ≥500)
    - D2 garbled-char ratio > 5%
    - D3 ≥10 consecutive identical chars
    Per-file:
    - D4 quality_score = (medium + long) / total × 100
    - D5 needs_review when empty>20% or issues>10% of pages
    """

    name = "quality"

    def run(self, target: Path) -> CheckResult:
        result = CheckResult(name=self.name)
        result.stats.update(
            {
                "empty_pages": 0,
                "short_pages": 0,
                "medium_pages": 0,
                "long_pages": 0,
                "total_pages": 0,
                "review_needed": [],
                "per_file": {},
                "overall_quality_score": 0.0,
            }
        )

        for md_file in _md_files_in(target):
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception as e:
                result.add_issue(md_file.stem, f"Cannot read {md_file.name}: {e}")
                continue

            pages = split_into_pages(content)
            file_stats: Dict[str, Any] = {
                "total_pages": len(pages),
                "empty_pages": 0,
                "short_pages": 0,
                "medium_pages": 0,
                "long_pages": 0,
                "issues": [],
            }

            for page_idx, page in enumerate(pages, 1):
                char_len = len(page)

                if char_len < 10:
                    file_stats["empty_pages"] += 1
                    file_stats["issues"].append(f"Page {page_idx}: 空白页或内容极少")
                elif char_len < 100:
                    file_stats["short_pages"] += 1
                    if char_len < 50:
                        file_stats["issues"].append(
                            f"Page {page_idx}: 内容过短，可能识别失败"
                        )
                elif char_len < 500:
                    file_stats["medium_pages"] += 1
                else:
                    file_stats["long_pages"] += 1

                garbled_ratio = len(_GARBLED_RE.findall(page)) / max(char_len, 1)
                if garbled_ratio > 0.05:
                    file_stats["issues"].append(
                        f"Page {page_idx}: 可能存在乱码 ({garbled_ratio:.1%})"
                    )

                if _REPEATED_RE.search(page):
                    file_stats["issues"].append(f"Page {page_idx}: 存在异常重复字符")

            total = file_stats["total_pages"]
            valid_ratio = (
                (file_stats["medium_pages"] + file_stats["long_pages"]) / total
                if total > 0
                else 0
            )
            file_stats["quality_score"] = round(valid_ratio * 100, 1)

            needs_review = total > 0 and (
                file_stats["empty_pages"] / total > 0.2
                or len(file_stats["issues"]) > total * 0.1
            )
            file_stats["needs_review"] = needs_review
            if needs_review:
                result.stats["review_needed"].append(md_file.stem)

            result.stats["per_file"][md_file.stem] = file_stats
            result.stats["empty_pages"] += file_stats["empty_pages"]
            result.stats["short_pages"] += file_stats["short_pages"]
            result.stats["medium_pages"] += file_stats["medium_pages"]
            result.stats["long_pages"] += file_stats["long_pages"]

        total = (
            result.stats["empty_pages"]
            + result.stats["short_pages"]
            + result.stats["medium_pages"]
            + result.stats["long_pages"]
        )
        result.stats["total_pages"] = total
        if total > 0:
            valid_ratio = (
                result.stats["medium_pages"] + result.stats["long_pages"]
            ) / total
            result.stats["overall_quality_score"] = round(valid_ratio * 100, 1)

        return result


# =============================================================== ElementChecker


_TABLE_PIPE_RE = re.compile(r"\|.*\|.*\|")
_TABLE_RULE_RE = re.compile(r"\|-+\|")
_FORMULA_DISPLAY_RE = re.compile(r"\$\$.+?\$\$", re.DOTALL)
_FORMULA_INLINE_RE = re.compile(r"\$[^$]+\$")
_IMAGE_REF_RE = re.compile(r"!\[.*?\]\(.*?\)")
_FIGURE_TAG_RE = re.compile(r"<figure>", re.IGNORECASE)


class ElementChecker(Checker):
    """Per-page element detection. Maps F.1 inventory E1-E4.

    Counts pages that contain at least one of: Markdown table, LaTeX formula,
    image reference, fenced code block. Aggregated per-file and overall.
    """

    name = "elements"

    def run(self, target: Path) -> CheckResult:
        result = CheckResult(name=self.name)
        result.stats.update(
            {
                "total_tables": 0,
                "total_formulas": 0,
                "total_images": 0,
                "total_code_blocks": 0,
                "per_file": {},
            }
        )

        for md_file in _md_files_in(target):
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception as e:
                result.add_issue(md_file.stem, f"Cannot read {md_file.name}: {e}")
                continue

            pages = split_into_pages(content)
            file_stats = {"tables": 0, "formulas": 0, "images": 0, "code_blocks": 0}

            for page in pages:
                if _TABLE_PIPE_RE.search(page) and _TABLE_RULE_RE.search(page):
                    file_stats["tables"] += 1
                if _FORMULA_DISPLAY_RE.search(page) or _FORMULA_INLINE_RE.search(page):
                    file_stats["formulas"] += 1
                if _IMAGE_REF_RE.search(page) or _FIGURE_TAG_RE.search(page):
                    file_stats["images"] += 1
                if _CODE_BLOCK_RE.search(page):
                    file_stats["code_blocks"] += 1

            result.stats["per_file"][md_file.stem] = file_stats
            result.stats["total_tables"] += file_stats["tables"]
            result.stats["total_formulas"] += file_stats["formulas"]
            result.stats["total_images"] += file_stats["images"]
            result.stats["total_code_blocks"] += file_stats["code_blocks"]

        return result


# ================================================================= MarcoChecker


_TITLE_RE = re.compile(r"^# ", re.MULTILINE)


class MarcoChecker(Checker):
    """Composite MARCO compliance per file. Maps F.1 inventory F1.

    A file is compliant if all three hold:
    - Has a sibling YAML file (``{stem}.yaml``)
    - Has at least one ``# title`` header
    - Has at least one ``## Page N`` header
    """

    name = "marco_compliance"

    def run(self, target: Path) -> CheckResult:
        result = CheckResult(name=self.name)
        result.stats.update(
            {
                "compliant": [],
                "non_compliant": [],
                "compliance_rate": 0.0,
            }
        )

        md_files = _md_files_in(target)
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception as e:
                result.add_issue(md_file.stem, f"Cannot read {md_file.name}: {e}")
                continue

            yaml_file = target / f"{md_file.stem}.yaml"
            checks = {
                "has_yaml": yaml_file.exists(),
                "has_title": bool(_TITLE_RE.search(content)),
                "has_page_headers": bool(_PAGE_HEADER_RE.search(content)),
            }

            if all(checks.values()):
                result.stats["compliant"].append(md_file.stem)
            else:
                result.stats["non_compliant"].append(
                    {
                        "name": md_file.stem,
                        "missing": [k for k, v in checks.items() if not v],
                    }
                )

        if md_files:
            result.stats["compliance_rate"] = round(
                len(result.stats["compliant"]) / len(md_files) * 100,
                1,
            )

        return result
