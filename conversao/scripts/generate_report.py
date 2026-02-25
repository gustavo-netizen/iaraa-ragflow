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


class TaskReportGenerator:
    """任务报告生成器"""

    # Qwen-VL-Max 定价 (2024年价格)
    # 注意: 这是官方价格，实际可能有折扣
    PRICE_INPUT_PER_1K = 0.02   # ¥0.02/1000 input tokens
    PRICE_OUTPUT_PER_1K = 0.02  # ¥0.02/1000 output tokens

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
        """计算成本明细"""
        total_input_tokens = 0
        total_output_tokens = 0
        total_pages = 0
        total_figures = 0
        total_time = 0

        pdf_details = []

        for report in batch_reports:
            if "pdfs" in report:
                for pdf in report["pdfs"]:
                    if pdf.get("success"):
                        proc = pdf.get("processing", {})
                        info = pdf.get("pdf_info", {})

                        tokens = proc.get("tokens", 0)
                        pages = info.get("pages", 0)
                        figures = info.get("figures", 0)
                        time_sec = proc.get("time", 0)

                        # 估算输入tokens (图片为主)
                        # 每页图片约 1500 tokens (150 DPI, A4)
                        est_input_tokens = pages * 1500
                        # 记录的 tokens 视为输出 tokens
                        output_tokens = tokens

                        total_input_tokens += est_input_tokens
                        total_output_tokens += output_tokens
                        total_pages += pages
                        total_figures += figures
                        total_time += time_sec

                        pdf_details.append({
                            "name": info.get("name", "unknown"),
                            "pages": pages,
                            "figures": figures,
                            "input_tokens_est": est_input_tokens,
                            "output_tokens": output_tokens,
                            "time_sec": round(time_sec, 1),
                        })

            # 也检查 summary
            if "summary" in report:
                summary = report["summary"]
                if total_pages == 0:
                    total_pages = summary.get("total_pages", 0)
                    total_figures = summary.get("total_figures", 0)
                    total_time = summary.get("total_time", 0)

        # 计算成本
        input_cost = total_input_tokens * self.PRICE_INPUT_PER_1K / 1000
        output_cost = total_output_tokens * self.PRICE_OUTPUT_PER_1K / 1000
        total_cost = input_cost + output_cost

        # 代码中记录的成本 (可能偏低)
        recorded_cost = sum(
            r.get("summary", {}).get("total_cost_cny", 0)
            for r in batch_reports
        )

        return {
            "task_name": self.task_name,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_pages": total_pages,
                "total_figures": total_figures,
                "total_time_sec": round(total_time, 1),
                "total_time_formatted": self._format_duration(total_time),
            },
            "tokens": {
                "input_tokens_estimated": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
            },
            "cost_analysis": {
                "pricing": {
                    "input_per_1k": self.PRICE_INPUT_PER_1K,
                    "output_per_1k": self.PRICE_OUTPUT_PER_1K,
                    "model": "qwen-vl-max-latest",
                },
                "calculated": {
                    "input_cost_cny": round(input_cost, 2),
                    "output_cost_cny": round(output_cost, 2),
                    "total_cost_cny": round(total_cost, 2),
                },
                "recorded_in_code": round(recorded_cost, 2),
                "note": "calculated 基于官方定价估算，recorded_in_code 是代码记录值，实际账单可能因优惠而不同",
            },
            "per_page_metrics": {
                "cost_per_page": round(total_cost / max(total_pages, 1), 4),
                "tokens_per_page": round((total_input_tokens + total_output_tokens) / max(total_pages, 1), 0),
                "time_per_page_sec": round(total_time / max(total_pages, 1), 2),
            },
            "pdf_details": pdf_details[:50],  # 只保留前50个，避免文件过大
        }

    def generate_quality_report(self, batch_reports: List[Dict], progress: Optional[Dict]) -> str:
        """生成质量报告 Markdown"""

        # 收集统计数据
        total_pages = 0
        total_figures = 0
        total_chars = 0
        failed_pages = 0
        validation_stats = {
            "total_tables": 0,
            "total_formulas": 0,
        }

        for report in batch_reports:
            if "summary" in report:
                s = report["summary"]
                total_pages += s.get("total_pages", 0)
                total_figures += s.get("total_figures", 0)

            if "pdfs" in report:
                for pdf in report["pdfs"]:
                    val = pdf.get("validation", {})
                    validation_stats["total_tables"] += val.get("total_tables_detected", 0)
                    validation_stats["total_formulas"] += val.get("total_formulas_detected", 0)

        # 从 progress 获取失败信息
        if progress:
            pdfs_data = progress.get("pdfs", {})
            for pdf_name, pdf_info in pdfs_data.items():
                failed_pages += len(pdf_info.get("failed_pages", []))

        # 生成报告
        report = f"""# 质量报告: {self.task_name}

生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 处理概要

| 指标 | 数值 |
|------|------|
| 总页数 | {total_pages:,} |
| 总图表 | {total_figures:,} |
| 表格数 | {validation_stats['total_tables']:,} |
| 公式数 | {validation_stats['total_formulas']:,} |
| 失败页 | {failed_pages} |
| 成功率 | {((total_pages - failed_pages) / max(total_pages, 1) * 100):.1f}% |

## 验证结果

"""

        # 添加 PDF 验证详情
        if batch_reports:
            report += "### PDF 处理状态\n\n"
            report += "| PDF | 页数 | 图表 | 状态 |\n"
            report += "|-----|------|------|------|\n"

            count = 0
            for br in batch_reports:
                for pdf in br.get("pdfs", []):
                    if count >= 30:  # 限制行数
                        report += "| ... | ... | ... | ... |\n"
                        break
                    info = pdf.get("pdf_info", {})
                    status = "✅" if pdf.get("success") else "❌"
                    report += f"| {info.get('name', 'unknown')[:40]} | {info.get('pages', 0)} | {info.get('figures', 0)} | {status} |\n"
                    count += 1

        report += """
## 备注

- 此报告由 `generate_report.py` 自动生成
- 详细成本数据见 `cost_summary.json`
- 验证数据见 `validation_result.json`
"""

        return report

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

        # 2. 质量报告
        print("   生成质量报告...")
        quality_md = self.generate_quality_report(batch_reports, progress)
        quality_file = self.reports_dir / "quality_report.md"
        with open(quality_file, 'w') as f:
            f.write(quality_md)
        generated_files["quality_report"] = str(quality_file)
        print(f"      ✅ {quality_file.name}")

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
                       default=str(Path(__file__).parent.parent),
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
