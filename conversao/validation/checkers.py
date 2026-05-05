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
        return result


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
