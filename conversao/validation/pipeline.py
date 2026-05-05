"""Run an ordered list of checkers and aggregate the results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from .checkers import CheckResult, Checker


@dataclass
class ValidationReport:
    """Composite result of a ``ValidationPipeline.run``."""

    target: Path
    results: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True only if every checker passed."""
        return all(r.passed for r in self.results)

    @property
    def total_issues(self) -> int:
        return sum(len(r.issues) for r in self.results)

    @property
    def total_warnings(self) -> int:
        return sum(len(r.warnings) for r in self.results)

    def stats(self, name: str) -> Dict[str, Any]:
        """Convenience accessor: stats from the checker named ``name``."""
        for r in self.results:
            if r.name == name:
                return r.stats
        return {}


@dataclass
class ValidationPipeline:
    """Orders a list of checkers and runs them sequentially against a target.

    Stateless beyond the configured checker list — safe to reuse across runs.
    """

    checkers: List[Checker]

    def run(self, target: Path) -> ValidationReport:
        report = ValidationReport(target=target)
        for checker in self.checkers:
            report.results.append(checker.run(target))
        return report
