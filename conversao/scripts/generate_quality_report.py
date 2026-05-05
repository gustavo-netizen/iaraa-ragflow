#!/usr/bin/env python3
"""Quality report generator — thin shim invoking the validation/ pipeline.

Refactored in Fase F.2 of PLANO_REFATORACAO.md. Real implementation lives in
``conversao/validation/``. This script preserves the legacy CLI for ``run.sh``:

    generate_quality_report.py --input <dir> [--output <md>] \
                               [--progress <progress.json>] [--json]

Runs all 6 checkers (full inventory) and renders the unified Markdown report.
Cost is intentionally not computed here (per F.1 recommendation: cost analysis
belongs in ``admin/generate_report.py`` which has access to ``batch_report*.json``;
this script only sees the ``final-delivery/`` flat directory).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_CONVERSAO_DIR = _SCRIPT_DIR.parent
if str(_CONVERSAO_DIR) not in sys.path:
    sys.path.insert(0, str(_CONVERSAO_DIR))

from validation.checkers import (  # noqa: E402
    ContentSyntaxChecker,
    ElementChecker,
    MarcoChecker,
    MarkdownChecker,
    QualityChecker,
    StructureChecker,
)
from validation.pipeline import ValidationPipeline  # noqa: E402
from validation.report import (  # noqa: E402
    load_retry_failures,
    render_quality_report,
)


def _load_progress_info(progress_file: Optional[Path]) -> Dict[str, Any]:
    if not progress_file or not progress_file.exists():
        return {}
    try:
        with open(progress_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _processing_time_from_progress(progress: Dict[str, Any]) -> int:
    started = progress.get("started_at", "")
    completed = progress.get("completed_at", progress.get("updated_at", ""))
    if not (started and completed):
        return 0
    try:
        start_t = datetime.fromisoformat(started)
        end_t = datetime.fromisoformat(completed)
        return max(0, int((end_t - start_t).total_seconds()))
    except Exception:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DocMind 质量报告生成器")
    parser.add_argument("--input", "-i", required=True, help="final-delivery 目录路径")
    parser.add_argument("--output", "-o", help="报告输出路径 (默认: <input>/QUALITY_REPORT.md)")
    parser.add_argument("--progress", "-p", help="progress.json 文件路径")
    parser.add_argument("--json", action="store_true", help="同时输出 JSON 格式报告")
    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"❌ 输入目录不存在: {input_dir}")
        return 1

    output_path = Path(args.output) if args.output else input_dir / "QUALITY_REPORT.md"
    progress_path = Path(args.progress) if args.progress else None

    print(f"📊 分析目录: {input_dir}")

    pipeline = ValidationPipeline(checkers=[
        StructureChecker(),
        ContentSyntaxChecker(),
        MarkdownChecker(),
        QualityChecker(),
        ElementChecker(),
        MarcoChecker(),
    ])
    report = pipeline.run(input_dir)

    # Auxiliary data: retry failures (from output/chunks/retry_failures.yaml)
    chunks_dir = input_dir.parent / "output" / "chunks"
    retry_failures = load_retry_failures(chunks_dir)

    # Auxiliary data: progress info (processing time + resource usage)
    progress = _load_progress_info(progress_path)
    processing_time = _processing_time_from_progress(progress)
    resource_usage = progress.get("resource_usage")

    # Render
    md = render_quality_report(
        report,
        retry_failures=retry_failures,
        resource_usage=resource_usage,
        processing_time_sec=processing_time,
        target_label=str(input_dir),
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✅ 报告已保存: {output_path}")

    # Terminal summary
    quality = report.stats("quality")
    structure = report.stats("structure")
    marco = report.stats("marco_compliance")
    overall = quality.get("overall_quality_score", 0.0)
    review_count = len(quality.get("review_needed", []))

    print("\n" + "=" * 60)
    print("📊 质量报告摘要")
    print("=" * 60)
    md_count = structure.get("md_count", 0)
    print(f"  总 PDF: {md_count}")
    print(f"  总页数: {quality.get('total_pages', 0):,}")
    print(f"  质量评分: {overall:.1f}/100")
    print(f"  MARCO符合: {marco.get('compliance_rate', 0.0):.1f}%")
    if review_count:
        print(f"  需复核: {review_count} 个 PDF")
    print("=" * 60)

    if args.json:
        json_path = output_path.with_suffix(".json")
        payload: Dict[str, Any] = {
            "total_pdfs": md_count,
            "total_pages": quality.get("total_pages", 0),
            "overall_quality_score": overall,
            "marco_compliance_rate": marco.get("compliance_rate", 0.0),
            "content_distribution": {
                "empty": quality.get("empty_pages", 0),
                "short": quality.get("short_pages", 0),
                "medium": quality.get("medium_pages", 0),
                "long": quality.get("long_pages", 0),
            },
            "elements": {
                "tables": report.stats("elements").get("total_tables", 0),
                "formulas": report.stats("elements").get("total_formulas", 0),
                "images": report.stats("elements").get("total_images", 0),
                "code_blocks": report.stats("elements").get("total_code_blocks", 0),
            },
            "resource_usage": resource_usage or {},
            "review_needed": quality.get("review_needed", []),
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"📄 JSON 报告: {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
