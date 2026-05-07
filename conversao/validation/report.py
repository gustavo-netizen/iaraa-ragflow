"""Render a unified Markdown quality report from a ``ValidationReport``.

Replaces the bespoke ``QualityReportGenerator.render_report`` (200+ lines of
inline f-strings) with a function that consumes structured inputs:

    render_quality_report(
        validation_report=...,        # ValidationPipeline output
        cost=...,                     # CostBreakdown (optional)
        retry_failures=...,           # RetryFailures (optional)
        resource_usage=...,           # dict from progress.json (optional)
        processing_time_sec=...,      # int (optional)
        target_label=...,             # str — directory name for header
    ) -> str

The output keeps GQR's 8-section structure but removes ASCII-art bars and
emoji density. The downstream consumer is a human reading the report; we no
longer try byte-equivalence with the legacy version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .cost import CostBreakdown
from .pipeline import ValidationReport


@dataclass(frozen=True)
class RetryFailures:
    """Page-level retry stats loaded from ``retry_failures.yaml``."""

    attempted: int = 0
    successful: int = 0
    permanent_failures: List[Dict[str, Any]] = field(default_factory=list)
    skipped_pages: List[Dict[str, Any]] = field(default_factory=list)


def load_retry_failures(chunks_dir: Path) -> RetryFailures:
    """Read ``{chunks_dir}/retry_failures.yaml`` if it exists."""
    retry_file = Path(chunks_dir) / "retry_failures.yaml"
    if not retry_file.exists():
        return RetryFailures()

    try:
        with open(retry_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return RetryFailures()

    return RetryFailures(
        attempted=int(data.get("attempted_retries", 0) or 0),
        successful=int(data.get("successful_retries", 0) or 0),
        permanent_failures=list(data.get("permanent_failures", []) or []),
        skipped_pages=list(data.get("skipped_pages", []) or []),
    )


def format_duration(seconds: int) -> str:
    """``HHh MMm`` for ≥1h, ``MMm SSs`` for ≥1min, ``SSs`` otherwise."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def quality_rating(score: float) -> Tuple[str, str]:
    """Map 0-100 score to ``(label, emoji)``. Mirrors GQR thresholds."""
    if score >= 90:
        return "优秀", "🌟"
    if score >= 80:
        return "良好", "✅"
    if score >= 60:
        return "一般", "⚠️"
    if score >= 40:
        return "较差", "❌"
    return "很差", "🚫"


def render_quality_report(
    validation_report: ValidationReport,
    *,
    cost: Optional[CostBreakdown] = None,
    retry_failures: Optional[RetryFailures] = None,
    resource_usage: Optional[Dict[str, Any]] = None,
    processing_time_sec: int = 0,
    target_label: Optional[str] = None,
) -> str:
    """Render the full Markdown quality report."""
    target_label = target_label or str(validation_report.target)
    structure = validation_report.stats("structure")
    quality = validation_report.stats("quality")
    elements = validation_report.stats("elements")
    marco = validation_report.stats("marco_compliance")
    markdown_stats = validation_report.stats("markdown_structure")

    total_pdfs = structure.get("md_count", 0)
    successful_pdfs = total_pdfs - len(_failed_from_issues(validation_report))
    failed_list = _failed_from_issues(validation_report)
    review_needed = quality.get("review_needed", []) or []

    total_pages = quality.get("total_pages", 0) or markdown_stats.get("total_pages", 0)
    total_chars = markdown_stats.get("total_chars", 0)

    overall_score = quality.get("overall_quality_score", 0.0)
    rating, emoji = quality_rating(overall_score)
    marco_rate = marco.get("compliance_rate", 0.0)

    lines: List[str] = []
    lines.append("# DocMind 质量报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f">")
    lines.append(f"> 输入目录: `{target_label}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. Executive summary
    lines.extend([
        "## 1. 执行摘要",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 总 PDF 数 | {total_pdfs} |",
        f"| 成功处理 | {successful_pdfs} ({successful_pdfs * 100 / max(total_pdfs, 1):.1f}%) |",
        f"| 处理失败 | {len(failed_list)} |",
        f"| 总页数 | {total_pages:,} |",
        f"| 总字符数 | {total_chars:,} |",
        f"| 处理耗时 | {format_duration(processing_time_sec) if processing_time_sec else '未知'} |",
    ])
    if cost is not None:
        lines.append(f"| 预估费用 | ¥{cost.total_cost_cny:.2f} |")
    footnote_sidecars = structure.get("footnote_sidecars", 0)
    body_leaks = structure.get("body_leaks", 0)
    if footnote_sidecars or body_leaks:
        lines.append(f"| Footnote sidecars | {footnote_sidecars} |")
        lines.append(f"| Body leaks (legacy) | {body_leaks} |")
    lines.extend(["", "---", ""])

    # 2. Quality score
    lines.extend([
        "## 2. 质量评分",
        "",
        f"### 整体评分: {overall_score:.1f}/100 {emoji} ({rating})",
        "",
        "| 评分项 | 得分 | 说明 |",
        "|--------|------|------|",
        f"| 有效内容率 | {overall_score:.1f}% | 100字符以上页面占比 |",
        f"| MARCO规范符合 | {marco_rate:.1f}% | 符合 MARCO 格式规范 |",
        "",
        "#### 评分标准:",
        "- 90-100: 优秀 🌟",
        "- 80-89: 良好 ✅",
        "- 60-79: 一般 ⚠️",
        "- 40-59: 较差 ❌",
        "- 0-39: 很差 🚫",
        "",
        "---",
        "",
    ])

    # 3. Content distribution
    empty = quality.get("empty_pages", 0)
    short = quality.get("short_pages", 0)
    medium = quality.get("medium_pages", 0)
    long = quality.get("long_pages", 0)
    lines.extend([
        "## 3. 内容分布",
        "",
        "| 类别 | 页数 | 占比 | 说明 |",
        "|------|------|------|------|",
        f"| 空白/极少 | {empty} | {empty * 100 / max(total_pages, 1):.1f}% | <10 字符 |",
        f"| 短内容 | {short} | {short * 100 / max(total_pages, 1):.1f}% | 10-99 字符 |",
        f"| 中等内容 | {medium} | {medium * 100 / max(total_pages, 1):.1f}% | 100-499 字符 |",
        f"| 长内容 | {long} | {long * 100 / max(total_pages, 1):.1f}% | ≥500 字符 |",
        "",
        "---",
        "",
    ])

    # 4. Element counts
    lines.extend([
        "## 4. 图表统计",
        "",
        "| 类型 | 检测数量 |",
        "|------|----------|",
        f"| 表格 | {elements.get('total_tables', 0)} |",
        f"| 公式 (LaTeX) | {elements.get('total_formulas', 0)} |",
        f"| 图片引用 | {elements.get('total_images', 0)} |",
        f"| 代码块 | {elements.get('total_code_blocks', 0)} |",
        "",
        "---",
        "",
    ])

    # 5. Issues
    lines.append("## 5. 问题列表")
    lines.append("")
    lines.append(f"### 5.1 处理失败的 PDF ({len(failed_list)})")
    if failed_list:
        lines.append("")
        lines.append("| PDF 名称 | 失败原因 |")
        lines.append("|----------|----------|")
        for item in failed_list:
            name = item["name"][:50]
            reason = item["reason"]
            lines.append(f"| {name} | {reason} |")
    else:
        lines.extend(["", "✅ 无处理失败的 PDF"])
    lines.append("")

    lines.append(f"### 5.2 需要人工复核 ({len(review_needed)})")
    if review_needed:
        lines.extend(["", "以下 PDF 存在较多空白页或质量问题，建议人工复核:", ""])
        for name in review_needed[:20]:
            lines.append(f"- {name}")
        if len(review_needed) > 20:
            lines.append(f"\n... 共 {len(review_needed)} 个需要复核")
    else:
        lines.extend(["", "✅ 无需人工复核的 PDF"])
    lines.append("")

    if retry_failures is not None:
        lines.extend(_render_retry_section(retry_failures))

    lines.extend(["---", ""])

    # 6. Per-PDF detail (sorted by quality score)
    per_file = quality.get("per_file", {}) or {}
    marco_compliant_set = set(marco.get("compliant", []) or [])
    if per_file:
        lines.extend([
            "## 6. 详细报告 (按质量评分排序)",
            "",
            "| PDF 名称 | 页数 | 质量分 | 空白页 | 表格 | 公式 | MARCO |",
            "|----------|------|--------|--------|------|------|-------|",
        ])
        sorted_names = sorted(
            per_file.keys(),
            key=lambda n: per_file[n].get("quality_score", 0),
            reverse=True,
        )
        for name in sorted_names:
            stats = per_file[name]
            elem_stats = elements.get("per_file", {}).get(name, {})
            display = name[:40] + "..." if len(name) > 40 else name
            marco_mark = "✅" if name in marco_compliant_set else "❌"
            lines.append(
                f"| {display} | {stats.get('total_pages', 0)} | "
                f"{stats.get('quality_score', 0):.0f} | "
                f"{stats.get('empty_pages', 0)} | "
                f"{elem_stats.get('tables', 0)} | "
                f"{elem_stats.get('formulas', 0)} | "
                f"{marco_mark} |"
            )
        lines.extend(["", "---", ""])

    # 7. Suggestions
    lines.append("## 7. 建议")
    lines.append("")
    suggestions = _build_suggestions(
        overall_score=overall_score,
        empty_pages=empty,
        total_pages=total_pages,
        failed_count=len(failed_list),
        marco_rate=marco_rate,
        review_count=len(review_needed),
    )
    for s in suggestions:
        lines.append(f"- {s}")
    lines.extend(["", "---", ""])

    # 8. Resource usage (if provided)
    lines.extend(_render_resource_section(resource_usage))

    lines.extend(["---", "", "*报告由 DocMind 0.8 质量报告生成器自动生成*"])

    return "\n".join(lines) + "\n"


# --------------------------------------------------------- internal helpers


def _failed_from_issues(report: ValidationReport) -> List[Dict[str, str]]:
    """Aggregate every blocking issue raised by any checker into a flat list."""
    failed: List[Dict[str, str]] = []
    for r in report.results:
        for issue in r.issues:
            target = issue.get("target") or "(global)"
            failed.append({"name": target, "reason": issue["message"]})
    return failed


def _render_retry_section(rf: RetryFailures) -> List[str]:
    lines: List[str] = []
    lines.extend([
        "### 5.3 页面重试统计",
        "",
        "| 指标 | 数量 |",
        "|------|------|",
        f"| 重试尝试 | {rf.attempted} |",
        f"| 重试成功 | {rf.successful} |",
        f"| 永久失败 | {len(rf.permanent_failures)} |",
        f"| 跳过 (内容审核) | {len(rf.skipped_pages)} |",
        "",
    ])

    if rf.permanent_failures:
        lines.extend([
            "#### 永久失败页面 (需人工处理)",
            "",
            "| 文件 | 页码 | 错误原因 |",
            "|------|------|----------|",
        ])
        for failure in rf.permanent_failures[:30]:
            chunk = str(failure.get("chunk", "Unknown"))[:40]
            page = failure.get("page", "?")
            error = str(failure.get("error", "Unknown"))[:50]
            lines.append(f"| {chunk}... | {page} | {error}... |")
        if len(rf.permanent_failures) > 30:
            lines.append(f"\n... 共 {len(rf.permanent_failures)} 个永久失败")
        lines.append("")

    if rf.skipped_pages:
        lines.extend([
            "#### 跳过页面 (内容审核无法处理)",
            "",
            "以下页面因内容审核被阻止，无法通过重试恢复:",
            "",
            "| 文件 | 页码 |",
            "|------|------|",
        ])
        for skip in rf.skipped_pages[:20]:
            chunk = str(skip.get("chunk", "Unknown"))[:40]
            page = skip.get("page", "?")
            lines.append(f"| {chunk}... | {page} |")
        if len(rf.skipped_pages) > 20:
            lines.append(f"\n... 共 {len(rf.skipped_pages)} 个被跳过")
        lines.append("")

    if not rf.permanent_failures and not rf.skipped_pages and rf.attempted == 0:
        lines.append("✅ 无需重试的失败页面")
        lines.append("")

    return lines


def _render_resource_section(ru: Optional[Dict[str, Any]]) -> List[str]:
    if not ru:
        return [
            "## 8. 资源使用统计",
            "",
            "> 资源监控: 未启用或无数据",
            "",
        ]

    cpu = ru.get("cpu", {}) or {}
    mem = ru.get("memory", {}) or {}
    disk = ru.get("disk_io", {}) or {}
    net = ru.get("network_io", {}) or {}
    sample_count = ru.get("sample_count", 0)
    interval = ru.get("sample_interval_sec", 0)

    return [
        "## 8. 资源使用统计",
        "",
        f"> 采样次数: {sample_count} | 采样间隔: {interval}秒 | "
        f"总监控时长: {format_duration(sample_count * interval)}",
        "",
        "| 指标 | 平均值 | 峰值 |",
        "|------|--------|------|",
        f"| CPU 使用率 | {cpu.get('average_percent', '-')}% | {cpu.get('peak_percent', '-')}% |",
        f"| 进程内存 | {mem.get('average_process_mb', '-')} MB | {mem.get('peak_process_mb', '-')} MB |",
        f"| 系统内存 | - | {mem.get('peak_system_percent', '-')}% (共 {mem.get('total_system_gb', '-')} GB) |",
        f"| 磁盘读取 | {disk.get('average_read_mb_s', '-')} MB/s | - |",
        f"| 磁盘写入 | {disk.get('average_write_mb_s', '-')} MB/s | - |",
        f"| 网络上传 | {net.get('average_sent_kb_s', '-')} KB/s | - |",
        f"| 网络下载 | {net.get('average_recv_kb_s', '-')} KB/s | - |",
        "",
    ]


def _build_suggestions(
    *,
    overall_score: float,
    empty_pages: int,
    total_pages: int,
    failed_count: int,
    marco_rate: float,
    review_count: int,
) -> List[str]:
    suggestions: List[str] = []

    if overall_score < 60:
        suggestions.append("⚠️ 整体质量评分较低，建议检查 OCR/LLM 处理是否正常")

    empty_ratio = empty_pages / max(total_pages, 1)
    if empty_ratio > 0.1:
        suggestions.append(
            f"⚠️ 空白页比例较高 ({empty_ratio * 100:.1f}%)，"
            "可能存在扫描质量问题或识别失败"
        )

    if failed_count > 0:
        suggestions.append(
            f"❌ 有 {failed_count} 个 PDF 处理失败，建议检查日志排查原因"
        )

    if marco_rate < 100:
        suggestions.append(
            f"📝 MARCO 规范符合率 {marco_rate:.0f}%，部分文件缺少必要的元数据"
        )

    if review_count > 0:
        suggestions.append(f"👀 有 {review_count} 个 PDF 需要人工复核")

    if not suggestions:
        suggestions.append("✅ 处理质量良好，无特殊建议")

    return suggestions
