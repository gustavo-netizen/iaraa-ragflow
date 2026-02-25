#!/usr/bin/env python3
"""
质量报告生成器 - DocMind 0.8
生成 QUALITY_REPORT.md，包含处理结果的全面质量评估

功能:
- 执行摘要（成功率/失败率/耗时/费用估算）
- 质量评分（0-100分）
- 内容分析（空页/短内容/长内容分布）
- 图表统计（表格/公式/图片数量）
- 问题列表（失败原因/需人工复核）
- MARCO规范符合度检查
"""

import argparse
import json
import os
import re
import statistics
import sys
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class PageStats:
    """单页统计"""
    page_num: int
    char_count: int
    has_table: bool = False
    has_formula: bool = False
    has_image: bool = False
    has_code: bool = False
    quality_issues: List[str] = field(default_factory=list)


@dataclass
class PDFStats:
    """单个PDF统计"""
    name: str
    md_path: str
    total_pages: int = 0
    char_count: int = 0
    page_stats: List[PageStats] = field(default_factory=list)

    # 内容分布
    empty_pages: int = 0      # <10 字符
    short_pages: int = 0      # 10-99 字符
    medium_pages: int = 0     # 100-499 字符
    long_pages: int = 0       # >=500 字符

    # 图表统计
    table_count: int = 0
    formula_count: int = 0
    image_count: int = 0
    code_block_count: int = 0

    # 质量评分
    quality_score: float = 0.0

    # 问题
    issues: List[str] = field(default_factory=list)
    needs_review: bool = False

    # MARCO规范
    has_yaml: bool = False
    marco_compliant: bool = False


@dataclass
class OverallStats:
    """总体统计"""
    total_pdfs: int = 0
    successful_pdfs: int = 0
    failed_pdfs: int = 0

    total_pages: int = 0
    successful_pages: int = 0

    total_chars: int = 0

    # 内容分布
    empty_pages: int = 0
    short_pages: int = 0
    medium_pages: int = 0
    long_pages: int = 0

    # 图表统计
    total_tables: int = 0
    total_formulas: int = 0
    total_images: int = 0
    total_code_blocks: int = 0

    # 时间和成本
    processing_time_seconds: int = 0
    estimated_cost_rmb: float = 0.0

    # 资源使用
    resource_usage: Dict = field(default_factory=dict)

    # 质量评分
    overall_quality_score: float = 0.0
    marco_compliance_rate: float = 0.0

    # PDF详情
    pdf_stats: List[PDFStats] = field(default_factory=list)
    failed_list: List[Dict] = field(default_factory=list)
    review_needed: List[str] = field(default_factory=list)

    # 重试统计 (from retry_failures.yaml)
    retry_attempted: int = 0
    retry_successful: int = 0
    permanent_failures: List[Dict] = field(default_factory=list)
    skipped_pages: List[Dict] = field(default_factory=list)


class QualityReportGenerator:
    """质量报告生成器"""

    def __init__(self, input_dir: str, output_path: str = None, progress_file: str = None):
        """
        初始化

        Args:
            input_dir: final-delivery 目录
            output_path: 报告输出路径
            progress_file: progress.json 路径（可选，用于获取时间等信息）
        """
        self.input_dir = Path(input_dir)
        self.output_path = Path(output_path) if output_path else self.input_dir / "QUALITY_REPORT.md"
        self.progress_file = Path(progress_file) if progress_file else None
        self.stats = OverallStats()

    def analyze_page_content(self, content: str, page_num: int) -> PageStats:
        """分析单页内容"""
        stats = PageStats(page_num=page_num, char_count=len(content))

        # 检测表格 (Markdown 表格语法)
        if re.search(r'\|.*\|.*\|', content) and re.search(r'\|-+\|', content):
            stats.has_table = True

        # 检测公式 (LaTeX)
        if re.search(r'\$\$.+?\$\$', content, re.DOTALL) or re.search(r'\$[^$]+\$', content):
            stats.has_formula = True

        # 检测图片引用
        if re.search(r'!\[.*?\]\(.*?\)', content) or re.search(r'<figure>', content, re.IGNORECASE):
            stats.has_image = True

        # 检测代码块
        if re.search(r'```[\s\S]*?```', content):
            stats.has_code = True

        # 质量问题检测
        if len(content.strip()) < 10:
            stats.quality_issues.append("空白页或内容极少")
        elif len(content.strip()) < 50:
            stats.quality_issues.append("内容过短，可能识别失败")

        # 检测可能的乱码
        garbled_ratio = len(re.findall(r'[�\ufffd]', content)) / max(len(content), 1)
        if garbled_ratio > 0.05:
            stats.quality_issues.append(f"可能存在乱码 ({garbled_ratio:.1%})")

        # 检测连续重复字符（可能的识别错误）
        if re.search(r'(.)\1{10,}', content):
            stats.quality_issues.append("存在异常重复字符")

        return stats

    def analyze_pdf(self, md_file: Path) -> Optional[PDFStats]:
        """分析单个PDF的输出（平面结构：直接传入 .md 文件路径）"""
        pdf_name = md_file.stem  # 从文件名获取 PDF 名称

        stats = PDFStats(name=pdf_name, md_path=str(md_file))

        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            stats.issues.append(f"无法读取文件: {e}")
            return stats

        stats.char_count = len(content)

        # 按页面分割
        pages = re.split(r'^## Page \d+', content, flags=re.MULTILINE)
        pages = [p.strip() for p in pages if p.strip()]

        # 跳过标题部分
        if pages and pages[0].startswith('#'):
            pages = pages[1:]

        stats.total_pages = len(pages)

        # 分析每一页
        for i, page_content in enumerate(pages, 1):
            page_stats = self.analyze_page_content(page_content, i)
            stats.page_stats.append(page_stats)

            # 累计统计
            char_len = page_stats.char_count
            if char_len < 10:
                stats.empty_pages += 1
            elif char_len < 100:
                stats.short_pages += 1
            elif char_len < 500:
                stats.medium_pages += 1
            else:
                stats.long_pages += 1

            if page_stats.has_table:
                stats.table_count += 1
            if page_stats.has_formula:
                stats.formula_count += 1
            if page_stats.has_image:
                stats.image_count += 1
            if page_stats.has_code:
                stats.code_block_count += 1

            if page_stats.quality_issues:
                stats.issues.extend([f"Page {i}: {issue}" for issue in page_stats.quality_issues])

        # 检查 YAML 文件（平面结构：同目录下同名的 .yaml 文件）
        yaml_file = md_file.parent / f"{md_file.stem}.yaml"
        stats.has_yaml = yaml_file.exists()

        # MARCO 规范检查
        stats.marco_compliant = self._check_marco_compliance(content, stats.has_yaml)

        # 计算质量评分
        if stats.total_pages > 0:
            # 有效内容比例 (>=100字符)
            valid_ratio = (stats.medium_pages + stats.long_pages) / stats.total_pages
            stats.quality_score = valid_ratio * 100

            # 如果有太多空白页或质量问题，标记为需要审核
            if stats.empty_pages / stats.total_pages > 0.2 or len(stats.issues) > stats.total_pages * 0.1:
                stats.needs_review = True

        return stats

    def _check_marco_compliance(self, content: str, has_yaml: bool) -> bool:
        """检查 MARCO 规范符合度"""
        checks = [
            has_yaml,  # 有 YAML 文件
            bool(re.search(r'^# ', content, re.MULTILINE)),  # 有标题
            bool(re.search(r'^## Page \d+', content, re.MULTILINE)),  # 有页码标记
        ]
        return all(checks)

    def load_progress_info(self) -> Dict:
        """从 progress.json 加载处理信息"""
        if not self.progress_file or not self.progress_file.exists():
            return {}

        try:
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    def calculate_estimated_cost(self, total_pages: int) -> float:
        """估算处理成本（基于 qwen-vl-plus 定价）"""
        # qwen-vl-plus: 约 0.008 元/千token
        # 估算每页约 2000 tokens (输入图片 + 输出文本)
        tokens_per_page = 2000
        price_per_1k_tokens = 0.008

        total_tokens = total_pages * tokens_per_page
        cost = (total_tokens / 1000) * price_per_1k_tokens
        return round(cost, 2)

    def generate(self) -> OverallStats:
        """生成质量报告"""
        print(f"📊 分析目录: {self.input_dir}")

        # 平面结构：直接查找所有 .md 文件（排除 QUALITY_REPORT.md）
        md_files = [f for f in self.input_dir.glob("*.md")
                    if not f.name.startswith('QUALITY_REPORT')]

        self.stats.total_pdfs = len(md_files)

        for md_file in sorted(md_files):
            pdf_stats = self.analyze_pdf(md_file)
            if pdf_stats:
                if pdf_stats.total_pages > 0:
                    self.stats.successful_pdfs += 1
                    self.stats.pdf_stats.append(pdf_stats)

                    # 累计统计
                    self.stats.total_pages += pdf_stats.total_pages
                    self.stats.total_chars += pdf_stats.char_count
                    self.stats.empty_pages += pdf_stats.empty_pages
                    self.stats.short_pages += pdf_stats.short_pages
                    self.stats.medium_pages += pdf_stats.medium_pages
                    self.stats.long_pages += pdf_stats.long_pages
                    self.stats.total_tables += pdf_stats.table_count
                    self.stats.total_formulas += pdf_stats.formula_count
                    self.stats.total_images += pdf_stats.image_count
                    self.stats.total_code_blocks += pdf_stats.code_block_count

                    if pdf_stats.needs_review:
                        self.stats.review_needed.append(pdf_stats.name)
                else:
                    self.stats.failed_pdfs += 1
                    self.stats.failed_list.append({
                        'name': pdf_stats.name,
                        'reason': '输出为空或无法解析'
                    })
            else:
                self.stats.failed_pdfs += 1
                self.stats.failed_list.append({
                    'name': md_file.stem,
                    'reason': '无法解析 .md 文件'
                })

        # 计算总体质量评分
        if self.stats.total_pages > 0:
            valid_ratio = (self.stats.medium_pages + self.stats.long_pages) / self.stats.total_pages
            self.stats.overall_quality_score = round(valid_ratio * 100, 1)

        # MARCO 符合率
        marco_count = sum(1 for p in self.stats.pdf_stats if p.marco_compliant)
        if self.stats.successful_pdfs > 0:
            self.stats.marco_compliance_rate = round(marco_count / self.stats.successful_pdfs * 100, 1)

        # 加载处理时间
        progress_info = self.load_progress_info()
        if progress_info:
            started = progress_info.get('started_at', '')
            completed = progress_info.get('completed_at', progress_info.get('updated_at', ''))
            if started and completed:
                try:
                    start_time = datetime.fromisoformat(started)
                    end_time = datetime.fromisoformat(completed)
                    self.stats.processing_time_seconds = int((end_time - start_time).total_seconds())
                except:
                    pass

        # 估算成本
        self.stats.estimated_cost_rmb = self.calculate_estimated_cost(self.stats.total_pages)

        # 加载资源使用数据
        if progress_info and 'resource_usage' in progress_info:
            self.stats.resource_usage = progress_info['resource_usage']

        # 加载重试失败统计
        self.load_retry_failures()

        return self.stats

    def load_retry_failures(self):
        """加载重试失败统计 (from retry_failures.yaml)"""
        # Try to find retry_failures.yaml in chunks directory
        chunks_dir = self.input_dir.parent / "output" / "chunks"
        retry_file = chunks_dir / "retry_failures.yaml"

        if not retry_file.exists():
            # Also check in input_dir parent
            retry_file = self.input_dir.parent / "output" / "chunks" / "retry_failures.yaml"

        if not retry_file.exists():
            return

        try:
            with open(retry_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not data:
                return

            self.stats.retry_attempted = data.get('attempted_retries', 0)
            self.stats.retry_successful = data.get('successful_retries', 0)
            self.stats.permanent_failures = data.get('permanent_failures', [])
            self.stats.skipped_pages = data.get('skipped_pages', [])

        except Exception as e:
            print(f"  Warning: Could not load retry failures: {e}")

    def format_time(self, seconds: int) -> str:
        """格式化时间"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            return f"{seconds // 60}分{seconds % 60}秒"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}小时{minutes}分"

    def get_quality_rating(self, score: float) -> Tuple[str, str]:
        """获取质量等级"""
        if score >= 90:
            return "优秀", "🌟"
        elif score >= 80:
            return "良好", "✅"
        elif score >= 60:
            return "一般", "⚠️"
        elif score >= 40:
            return "较差", "❌"
        else:
            return "很差", "🚫"

    def format_resource_section(self) -> str:
        """格式化资源使用部分"""
        ru = self.stats.resource_usage
        if not ru:
            return """
## 8. 资源使用统计

> 资源监控: 未启用或无数据

"""

        cpu = ru.get('cpu', {})
        mem = ru.get('memory', {})
        disk = ru.get('disk_io', {})
        net = ru.get('network_io', {})
        sample_count = ru.get('sample_count', 0)
        interval = ru.get('sample_interval_sec', 0)

        return f"""
## 8. 资源使用统计

> 采样次数: {sample_count} | 采样间隔: {interval}秒 | 总监控时长: {self.format_time(sample_count * interval)}

| 指标 | 平均值 | 峰值 |
|------|--------|------|
| CPU 使用率 | {cpu.get('average_percent', '-')}% | {cpu.get('peak_percent', '-')}% |
| 进程内存 | {mem.get('average_process_mb', '-')} MB | {mem.get('peak_process_mb', '-')} MB |
| 系统内存 | - | {mem.get('peak_system_percent', '-')}% (共 {mem.get('total_system_gb', '-')} GB) |
| 磁盘读取 | {disk.get('average_read_mb_s', '-')} MB/s | - |
| 磁盘写入 | {disk.get('average_write_mb_s', '-')} MB/s | - |
| 网络上传 | {net.get('average_sent_kb_s', '-')} KB/s | - |
| 网络下载 | {net.get('average_recv_kb_s', '-')} KB/s | - |

"""

    def render_report(self) -> str:
        """渲染 Markdown 报告"""
        s = self.stats
        rating, emoji = self.get_quality_rating(s.overall_quality_score)

        report = f"""# DocMind 质量报告

> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
>
> 输入目录: `{self.input_dir}`

---

## 1. 执行摘要

| 指标 | 数值 |
|------|------|
| 总 PDF 数 | {s.total_pdfs} |
| 成功处理 | {s.successful_pdfs} ({s.successful_pdfs * 100 / max(s.total_pdfs, 1):.1f}%) |
| 处理失败 | {s.failed_pdfs} |
| 总页数 | {s.total_pages:,} |
| 总字符数 | {s.total_chars:,} |
| 处理耗时 | {self.format_time(s.processing_time_seconds) if s.processing_time_seconds else '未知'} |
| 预估费用 | ¥{s.estimated_cost_rmb:.2f} |

---

## 2. 质量评分

### 整体评分: {s.overall_quality_score:.1f}/100 {emoji} ({rating})

| 评分项 | 得分 | 说明 |
|--------|------|------|
| 有效内容率 | {s.overall_quality_score:.1f}% | 100字符以上页面占比 |
| MARCO规范符合 | {s.marco_compliance_rate:.1f}% | 符合 MARCO 格式规范 |

#### 评分标准:
- 90-100: 优秀 🌟
- 80-89: 良好 ✅
- 60-79: 一般 ⚠️
- 40-59: 较差 ❌
- 0-39: 很差 🚫

---

## 3. 内容分布

| 类别 | 页数 | 占比 | 说明 |
|------|------|------|------|
| 空白/极少 | {s.empty_pages} | {s.empty_pages * 100 / max(s.total_pages, 1):.1f}% | <10 字符 |
| 短内容 | {s.short_pages} | {s.short_pages * 100 / max(s.total_pages, 1):.1f}% | 10-99 字符 |
| 中等内容 | {s.medium_pages} | {s.medium_pages * 100 / max(s.total_pages, 1):.1f}% | 100-499 字符 |
| 长内容 | {s.long_pages} | {s.long_pages * 100 / max(s.total_pages, 1):.1f}% | ≥500 字符 |

```
内容分布可视化:
空白/极少 [{"█" * int(s.empty_pages * 20 / max(s.total_pages, 1))}{"░" * (20 - int(s.empty_pages * 20 / max(s.total_pages, 1)))}] {s.empty_pages * 100 / max(s.total_pages, 1):.1f}%
短内容    [{"█" * int(s.short_pages * 20 / max(s.total_pages, 1))}{"░" * (20 - int(s.short_pages * 20 / max(s.total_pages, 1)))}] {s.short_pages * 100 / max(s.total_pages, 1):.1f}%
中等内容  [{"█" * int(s.medium_pages * 20 / max(s.total_pages, 1))}{"░" * (20 - int(s.medium_pages * 20 / max(s.total_pages, 1)))}] {s.medium_pages * 100 / max(s.total_pages, 1):.1f}%
长内容    [{"█" * int(s.long_pages * 20 / max(s.total_pages, 1))}{"░" * (20 - int(s.long_pages * 20 / max(s.total_pages, 1)))}] {s.long_pages * 100 / max(s.total_pages, 1):.1f}%
```

---

## 4. 图表统计

| 类型 | 检测数量 |
|------|----------|
| 表格 | {s.total_tables} |
| 公式 (LaTeX) | {s.total_formulas} |
| 图片引用 | {s.total_images} |
| 代码块 | {s.total_code_blocks} |

---

## 5. 问题列表

### 5.1 处理失败的 PDF ({len(s.failed_list)})
"""

        if s.failed_list:
            report += "\n| PDF 名称 | 失败原因 |\n|----------|----------|\n"
            for item in s.failed_list:
                report += f"| {item['name'][:50]}... | {item['reason']} |\n"
        else:
            report += "\n✅ 无处理失败的 PDF\n"

        report += f"""
### 5.2 需要人工复核 ({len(s.review_needed)})
"""

        if s.review_needed:
            report += "\n以下 PDF 存在较多空白页或质量问题，建议人工复核:\n\n"
            for name in s.review_needed[:20]:  # 最多显示20个
                report += f"- {name}\n"
            if len(s.review_needed) > 20:
                report += f"\n... 共 {len(s.review_needed)} 个需要复核\n"
        else:
            report += "\n✅ 无需人工复核的 PDF\n"

        # 5.3 重试统计和永久失败页面
        total_permanent = len(s.permanent_failures) + len(s.skipped_pages)
        report += f"""
### 5.3 页面重试统计

| 指标 | 数量 |
|------|------|
| 重试尝试 | {s.retry_attempted} |
| 重试成功 | {s.retry_successful} |
| 永久失败 | {len(s.permanent_failures)} |
| 跳过 (内容审核) | {len(s.skipped_pages)} |

"""

        if s.permanent_failures:
            report += "#### 永久失败页面 (需人工处理)\n\n"
            report += "| 文件 | 页码 | 错误原因 |\n|------|------|----------|\n"
            for failure in s.permanent_failures[:30]:  # 最多显示30个
                chunk = failure.get('chunk', 'Unknown')[:40]
                page = failure.get('page', '?')
                error = failure.get('error', 'Unknown')[:50]
                report += f"| {chunk}... | {page} | {error}... |\n"
            if len(s.permanent_failures) > 30:
                report += f"\n... 共 {len(s.permanent_failures)} 个永久失败\n"

        if s.skipped_pages:
            report += "\n#### 跳过页面 (内容审核无法处理)\n\n"
            report += "以下页面因内容审核被阻止，无法通过重试恢复:\n\n"
            report += "| 文件 | 页码 |\n|------|------|\n"
            for skip in s.skipped_pages[:20]:  # 最多显示20个
                chunk = skip.get('chunk', 'Unknown')[:40]
                page = skip.get('page', '?')
                report += f"| {chunk}... | {page} |\n"
            if len(s.skipped_pages) > 20:
                report += f"\n... 共 {len(s.skipped_pages)} 个被跳过\n"

        if not s.permanent_failures and not s.skipped_pages and s.retry_attempted == 0:
            report += "\n✅ 无需重试的失败页面\n"

        report += """
---

## 6. 详细报告 (按质量评分排序)

| PDF 名称 | 页数 | 质量分 | 空白页 | 表格 | 公式 | MARCO |
|----------|------|--------|--------|------|------|-------|
"""

        # 按质量评分排序
        sorted_pdfs = sorted(s.pdf_stats, key=lambda x: x.quality_score, reverse=True)
        for pdf in sorted_pdfs:
            name_display = pdf.name[:40] + "..." if len(pdf.name) > 40 else pdf.name
            marco_mark = "✅" if pdf.marco_compliant else "❌"
            report += f"| {name_display} | {pdf.total_pages} | {pdf.quality_score:.0f} | {pdf.empty_pages} | {pdf.table_count} | {pdf.formula_count} | {marco_mark} |\n"

        report += f"""
---

## 7. 建议

"""

        # 根据分析结果给出建议
        suggestions = []

        if s.overall_quality_score < 60:
            suggestions.append("⚠️ 整体质量评分较低，建议检查 OCR/LLM 处理是否正常")

        if s.empty_pages / max(s.total_pages, 1) > 0.1:
            suggestions.append(f"⚠️ 空白页比例较高 ({s.empty_pages * 100 / max(s.total_pages, 1):.1f}%)，可能存在扫描质量问题或识别失败")

        if s.failed_pdfs > 0:
            suggestions.append(f"❌ 有 {s.failed_pdfs} 个 PDF 处理失败，建议检查日志排查原因")

        if s.marco_compliance_rate < 100:
            suggestions.append(f"📝 MARCO 规范符合率 {s.marco_compliance_rate:.0f}%，部分文件缺少必要的元数据")

        if len(s.review_needed) > 0:
            suggestions.append(f"👀 有 {len(s.review_needed)} 个 PDF 需要人工复核")

        if not suggestions:
            suggestions.append("✅ 处理质量良好，无特殊建议")

        for suggestion in suggestions:
            report += f"- {suggestion}\n"

        report += """
---
"""

        # 添加资源使用统计（Section 8）
        report += self.format_resource_section()

        report += """---

*报告由 DocMind 0.8 质量报告生成器自动生成*
"""

        return report

    def save_report(self, report: str):
        """保存报告"""
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"✅ 报告已保存: {self.output_path}")

    def run(self) -> str:
        """运行完整流程"""
        self.generate()
        report = self.render_report()
        self.save_report(report)
        return report


def main():
    parser = argparse.ArgumentParser(
        description='DocMind 质量报告生成器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --input ./final-delivery
  %(prog)s --input ./final-delivery --output ./QUALITY_REPORT.md
  %(prog)s --input ./final-delivery --progress ./progress.json
        """
    )

    parser.add_argument(
        '--input', '-i',
        required=True,
        help='final-delivery 目录路径'
    )

    parser.add_argument(
        '--output', '-o',
        help='报告输出路径 (默认: <input>/QUALITY_REPORT.md)'
    )

    parser.add_argument(
        '--progress', '-p',
        help='progress.json 文件路径 (可选，用于获取处理时间)'
    )

    parser.add_argument(
        '--json',
        action='store_true',
        help='同时输出 JSON 格式报告'
    )

    args = parser.parse_args()

    # 验证输入目录
    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"❌ 输入目录不存在: {input_dir}")
        sys.exit(1)

    # 生成报告
    generator = QualityReportGenerator(
        input_dir=str(input_dir),
        output_path=args.output,
        progress_file=args.progress
    )

    report = generator.run()

    # 输出摘要到终端
    s = generator.stats
    rating, emoji = generator.get_quality_rating(s.overall_quality_score)

    print("\n" + "=" * 60)
    print("📊 质量报告摘要")
    print("=" * 60)
    print(f"  总 PDF: {s.total_pdfs} | 成功: {s.successful_pdfs} | 失败: {s.failed_pdfs}")
    print(f"  总页数: {s.total_pages:,} | 总字符: {s.total_chars:,}")
    print(f"  质量评分: {s.overall_quality_score:.1f}/100 {emoji} ({rating})")
    print(f"  MARCO符合: {s.marco_compliance_rate:.1f}%")
    if s.review_needed:
        print(f"  需复核: {len(s.review_needed)} 个 PDF")
    print("=" * 60)

    # 可选: JSON 输出
    if args.json:
        json_path = generator.output_path.with_suffix('.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'total_pdfs': s.total_pdfs,
                'successful_pdfs': s.successful_pdfs,
                'failed_pdfs': s.failed_pdfs,
                'total_pages': s.total_pages,
                'overall_quality_score': s.overall_quality_score,
                'marco_compliance_rate': s.marco_compliance_rate,
                'content_distribution': {
                    'empty': s.empty_pages,
                    'short': s.short_pages,
                    'medium': s.medium_pages,
                    'long': s.long_pages
                },
                'elements': {
                    'tables': s.total_tables,
                    'formulas': s.total_formulas,
                    'images': s.total_images,
                    'code_blocks': s.total_code_blocks
                },
                'resource_usage': s.resource_usage,
                'failed_list': s.failed_list,
                'review_needed': s.review_needed
            }, f, indent=2, ensure_ascii=False)
        print(f"📄 JSON 报告: {json_path}")


if __name__ == "__main__":
    main()
