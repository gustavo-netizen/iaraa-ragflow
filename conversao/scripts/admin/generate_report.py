#!/usr/bin/env python3
"""
生成任务报告

用法:
    python3 generate_report.py --task-name "RedMarx-Lenin-Vol11-20"
    python3 generate_report.py --task-name "RedMarx-Lenin-Vol11-20" --from-batch /path/to/batch_report.json

功能:
    - 统一收集任务产出的所有报告
    - 生成质量报告、成本明细、验证结果
    - 所有报告保存到 reports/{task_name}/ 目录
"""

import os
import sys
import json
import argparse
import glob
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# Make ``conversao/`` importable so we can pull cost computation from the
# unified ``validation/cost.py`` (Fase F.2.c).
_SCRIPT_DIR = Path(__file__).resolve().parent
_CONVERSAO_DIR = _SCRIPT_DIR.parent.parent
if str(_CONVERSAO_DIR) not in sys.path:
    sys.path.insert(0, str(_CONVERSAO_DIR))

from validation.cost import from_batch_reports  # noqa: E402


class TaskReportGenerator:
    """任务报告生成器"""

    def __init__(self, base_dir: str, task_name: str):
        self.base_dir = Path(base_dir)
        self.task_name = task_name
        self.reports_dir = self.base_dir / "reports" / task_name
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def collect_batch_reports(self) -> List[Dict]:
        """收集所有 batch_report JSON 文件"""
        reports = []

        # 搜索 output/chunks 目录
        chunks_dir = self.base_dir / "output" / "chunks"
        if chunks_dir.exists():
            for f in chunks_dir.glob("batch_report_*.json"):
                try:
                    with open(f) as fp:
                        reports.append(json.load(fp))
                except Exception as e:
                    print(f"  警告: 无法读取 {f}: {e}")

        # 搜索其他可能的位置
        for pattern in ["**/batch_report_*.json", "**/chunks/batch_report_*.json"]:
            for f in self.base_dir.glob(pattern):
                if str(Path("output") / "chunks") not in str(f):  # 避免重复
                    try:
                        with open(f) as fp:
                            data = json.load(fp)
                            if data not in reports:
                                reports.append(data)
                    except Exception:
                        pass

        return reports

    def collect_progress_data(self) -> Optional[Dict]:
        """收集 progress.json 数据"""
        progress_file = self.base_dir / "progress.json"
        if progress_file.exists():
            try:
                with open(progress_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def collect_monitor_data(self) -> List[Dict]:
        """收集监控数据"""
        monitor_dir = self.base_dir / "monitor"
        data = []

        if monitor_dir.exists():
            # 查找与任务名匹配的文件
            for f in monitor_dir.glob(f"{self.task_name}*_summary.json"):
                try:
                    with open(f) as fp:
                        data.append(json.load(fp))
                except Exception:
                    pass

            # 如果没找到，取最新的
            if not data:
                summaries = sorted(monitor_dir.glob("*_summary.json"), reverse=True)
                if summaries:
                    try:
                        with open(summaries[0]) as fp:
                            data.append(json.load(fp))
                    except Exception:
                        pass

        return data

    def calculate_costs(self, batch_reports: List[Dict]) -> Dict:
        """计算成本明细 — uses ``validation.cost.from_batch_reports`` (Fase F.2.c).

        Returns the legacy dict shape that ``main()`` writes to ``cost_summary.json``;
        the actual aggregation (token resolution, fallback estimation, recorded
        cost) lives in ``validation/cost.py``.
        """
        cost = from_batch_reports(batch_reports)

        # Per-PDF detail list — not part of CostBreakdown, extract here.
        pdf_details: List[Dict[str, Any]] = []
        total_figures = 0
        for r in batch_reports:
            for pdf in r.get("pdfs", []):
                if not pdf.get("success"):
                    continue
                info = pdf.get("pdf_info", {})
                proc = pdf.get("processing", {})
                pages = info.get("pages", 0)
                figures = info.get("figures", 0)
                total_figures += figures
                pdf_details.append({
                    "name": info.get("name", "unknown"),
                    "pages": pages,
                    "figures": figures,
                    "input_tokens_est": proc.get("tokens_input", pages * 1500),
                    "output_tokens": proc.get("tokens_output", proc.get("tokens", 0)),
                    "time_sec": round(proc.get("time", 0), 1),
                })

        return {
            "task_name": self.task_name,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_pages": cost.pages,
                "total_figures": total_figures,
                "total_time_sec": cost.time_sec,
                "total_time_formatted": self._format_duration(cost.time_sec),
            },
            "tokens": {
                "input_tokens_estimated": cost.tokens.input_tokens,
                "output_tokens": cost.tokens.output_tokens,
                "total_tokens": cost.tokens.total,
            },
            "cost_analysis": {
                "pricing": {
                    "input_per_1k": cost.pricing_input_per_1k,
                    "output_per_1k": cost.pricing_output_per_1k,
                    "model": cost.model,
                },
                "calculated": {
                    "input_cost_cny": cost.input_cost_cny,
                    "output_cost_cny": cost.output_cost_cny,
                    "total_cost_cny": cost.total_cost_cny,
                },
                "recorded_in_code": cost.recorded_cost_cny,
                "note": "calculated 基于官方定价估算，recorded_in_code 是代码记录值，实际账单可能因优惠而不同",
            },
            "per_page_metrics": {
                "cost_per_page": cost.cost_per_page,
                "tokens_per_page": cost.tokens_per_page,
                "time_per_page_sec": cost.time_per_page_sec,
            },
            "pdf_details": pdf_details[:50],
        }

    def generate_validation_result(self, batch_reports: List[Dict]) -> Dict:
        """生成验证结果 JSON"""
        results = {
            "task_name": self.task_name,
            "generated_at": datetime.now().isoformat(),
            "pdfs": [],
        }

        for report in batch_reports:
            for pdf in report.get("pdfs", []):
                results["pdfs"].append({
                    "name": pdf.get("pdf_info", {}).get("name", "unknown"),
                    "success": pdf.get("success", False),
                    "validation": pdf.get("validation", {}),
                })

        # 汇总统计
        total = len(results["pdfs"])
        success = sum(1 for p in results["pdfs"] if p["success"])

        results["summary"] = {
            "total_pdfs": total,
            "successful": success,
            "failed": total - success,
            "success_rate": round(success / max(total, 1) * 100, 1),
        }

        return results

    def copy_processing_log(self):
        """复制处理日志到报告目录"""
        log_sources = [
            self.base_dir / "logs" / "chunks_processing.log",
            self.base_dir / "logs" / "direct_processing.log",
        ]

        combined_log = self.reports_dir / "processing.log"

        with open(combined_log, 'w') as out:
            out.write(f"# Processing Log for {self.task_name}\n")
            out.write(f"# Generated: {datetime.now().isoformat()}\n\n")

            for log_file in log_sources:
                if log_file.exists():
                    out.write(f"\n{'='*60}\n")
                    out.write(f"# Source: {log_file.name}\n")
                    out.write(f"{'='*60}\n\n")
                    try:
                        # 只读取最后 1000 行
                        with open(log_file) as f:
                            lines = f.readlines()
                            out.writelines(lines[-1000:])
                    except Exception as e:
                        out.write(f"Error reading log: {e}\n")

    def generate_all(self) -> Dict[str, str]:
        """生成所有报告，返回文件路径"""
        print(f"\n📊 生成任务报告: {self.task_name}")
        print(f"   输出目录: {self.reports_dir}")

        # 收集数据
        print("   收集 batch reports...")
        batch_reports = self.collect_batch_reports()
        print(f"   找到 {len(batch_reports)} 个 batch report")

        print("   收集 progress 数据...")
        progress = self.collect_progress_data()

        print("   收集监控数据...")
        monitor_data = self.collect_monitor_data()

        generated_files = {}

        # 1. 成本明细
        print("   生成成本明细...")
        cost_data = self.calculate_costs(batch_reports)
        cost_file = self.reports_dir / "cost_summary.json"
        with open(cost_file, 'w') as f:
            json.dump(cost_data, f, indent=2, ensure_ascii=False)
        generated_files["cost_summary"] = str(cost_file)
        print(f"      ✅ {cost_file.name}")

        # 2. (Quality report removido na Fase F.2 — duplicava generate_quality_report.py
        #     com formatação inferior; este dossiê per-task agora foca em cost+validation+log.
        #     QUALITY_REPORT.md é gerado por scripts/generate_quality_report.py em final-delivery/.)

        # 3. 验证结果
        print("   生成验证结果...")
        validation = self.generate_validation_result(batch_reports)
        validation_file = self.reports_dir / "validation_result.json"
        with open(validation_file, 'w') as f:
            json.dump(validation, f, indent=2, ensure_ascii=False)
        generated_files["validation_result"] = str(validation_file)
        print(f"      ✅ {validation_file.name}")

        # 4. 处理日志
        print("   复制处理日志...")
        self.copy_processing_log()
        generated_files["processing_log"] = str(self.reports_dir / "processing.log")
        print(f"      ✅ processing.log")

        # 打印摘要
        print(f"\n{'='*60}")
        print(f"📈 成本摘要")
        print(f"{'='*60}")
        print(f"   总页数: {cost_data['summary']['total_pages']:,}")
        print(f"   处理时间: {cost_data['summary']['total_time_formatted']}")
        print(f"   估算成本: ¥{cost_data['cost_analysis']['calculated']['total_cost_cny']:.2f}")
        print(f"   代码记录: ¥{cost_data['cost_analysis']['recorded_in_code']:.2f}")
        print(f"   单页成本: ¥{cost_data['per_page_metrics']['cost_per_page']:.4f}")
        print(f"{'='*60}\n")

        return generated_files

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """格式化时长"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"


def main():
    parser = argparse.ArgumentParser(description="生成任务报告")
    parser.add_argument("--base-dir", "-d",
                       default=str(Path(__file__).parent.parent.parent),
                       help="DocMind 根目录")
    parser.add_argument("--task-name", "-t", required=True,
                       help="任务名称 (如: RedMarx-Lenin-Vol11-20)")
    parser.add_argument("--from-batch", "-b",
                       help="指定 batch_report.json 文件路径")

    args = parser.parse_args()

    generator = TaskReportGenerator(args.base_dir, args.task_name)
    files = generator.generate_all()

    print("✅ 报告生成完成!")
    print("   文件列表:")
    for name, path in files.items():
        print(f"   - {name}: {path}")


if __name__ == "__main__":
    main()
