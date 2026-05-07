#!/usr/bin/env python3
"""Final delivery validation — thin shim invoking the validation/ pipeline.

Refactored in Fase F.2 of PLANO_REFATORACAO.md. Real implementation lives in
``conversao/validation/``. This script preserves the legacy CLI for ``run.sh``:

    final_delivery_check.py --delivery-dir <dir> [--expected-count N] \
                            [--output-report <json>] [--verbose]

Maps to the F.1 inventory subset (A, B, C):
    StructureChecker        — A1 file count, A2 md/yaml pairs
    ContentSyntaxChecker    — B1 json remnants, B2 literal newlines, B3 yaml syntax
    MarkdownChecker         — C1 page headers, C2 figure refs, C3 file size
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

_SCRIPT_DIR = Path(__file__).resolve().parent
_CONVERSAO_DIR = _SCRIPT_DIR.parent
if str(_CONVERSAO_DIR) not in sys.path:
    sys.path.insert(0, str(_CONVERSAO_DIR))

from validation.checkers import (  # noqa: E402
    ContentSyntaxChecker,
    MarkdownChecker,
    StructureChecker,
)
from validation.pipeline import ValidationPipeline, ValidationReport  # noqa: E402


def _print_summary(report: ValidationReport, expected_count: int | None) -> bool:
    """Mirror legacy CLI output: per-check pass/fail then issues + warnings."""
    print("=" * 70)
    print("🔍 Final Delivery Validation")
    print("=" * 70)
    print(f"Directory: {report.target}")
    if expected_count is not None:
        print(f"Expected MD files: {expected_count}")
    print()

    timestamp = datetime.now().strftime("%H:%M:%S")
    for r in report.results:
        icon = "✅" if r.passed else "❌"
        status = "PASS" if r.passed else "FAIL"
        print(f"[{timestamp}] {icon} {r.name}: {status}")

    print()
    print("=" * 70)
    print("📊 Validation Summary")
    print("=" * 70)

    # Stats
    structure_stats = report.stats("structure")
    md_count = structure_stats.get("md_count", 0)
    yaml_count = structure_stats.get("yaml_count", 0)
    md_stats = report.stats("markdown_structure")
    print(f"  MD files checked: {md_count}")
    print(f"  YAML files checked: {yaml_count}")
    print(f"  Total pages: {md_stats.get('total_pages', 0):,}")
    print(f"  Total characters: {md_stats.get('total_chars', 0):,}")

    if report.total_issues:
        print()
        print("❌ Issues Found:")
        for r in report.results:
            for issue in r.issues:
                target = f"[{issue['target']}] " if issue.get("target") else ""
                print(f"  {target}{r.name}: {issue['message']}")

    if report.total_warnings:
        print()
        print("⚠️  Warnings:")
        warnings: list[Dict[str, str]] = []
        for r in report.results:
            for w in r.warnings:
                warnings.append({"check": r.name, **w})
        for w in warnings[:10]:
            target = f"[{w['target']}] " if w.get("target") else ""
            print(f"  {target}{w['check']}: {w['message']}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more warnings")

    print()
    if report.passed:
        print("✅ All checks passed!")
    else:
        print(f"❌ Validation failed with {report.total_issues} issues")

    return report.passed


def _save_report(report: ValidationReport, output_path: str, expected_count: int | None) -> None:
    payload: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "delivery_dir": str(report.target),
        "expected_count": expected_count,
        "passed": report.passed,
        "results": [
            {
                "name": r.name,
                "passed": r.passed,
                "issues": r.issues,
                "warnings": r.warnings,
                "stats": r.stats,
            }
            for r in report.results
        ],
        "total_issues": report.total_issues,
        "total_warnings": report.total_warnings,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Report saved to {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Final Delivery Validation Script")
    parser.add_argument("--delivery-dir", required=True, help="Path to final-delivery directory")
    parser.add_argument("--expected-count", type=int, help="Expected number of MD files")
    parser.add_argument("--output-report", help="Save validation report to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    target = Path(args.delivery_dir)
    pipeline = ValidationPipeline(checkers=[
        StructureChecker(expected_count=args.expected_count),
        ContentSyntaxChecker(),
        MarkdownChecker(),
    ])
    report = pipeline.run(target)

    passed = _print_summary(report, args.expected_count)

    if args.output_report:
        _save_report(report, args.output_report, args.expected_count)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
