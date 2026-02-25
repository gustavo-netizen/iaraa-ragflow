#!/usr/bin/env python3
"""
Markdown 后处理模块 - DocMind 0.8
对生成的 Markdown 进行清理和优化

功能:
- 表格对齐修复
- 连续空行合并
- 标题层级标准化
- LaTeX公式验证
- 自动生成目录 (TOC)
- 链接有效性检查
- 孤立标题检测
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class PostProcessResult:
    """后处理结果"""
    file_path: str
    original_size: int
    processed_size: int
    fixes_applied: List[str] = field(default_factory=list)
    toc_generated: bool = False
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class MarkdownPostProcessor:
    """Markdown 后处理器"""

    def __init__(self, fix_tables: bool = True, fix_headings: bool = True,
                 merge_empty_lines: bool = True, generate_toc: bool = False,
                 validate_latex: bool = True, check_links: bool = False,
                 max_empty_lines: int = 2):
        """
        初始化后处理器

        Args:
            fix_tables: 修复表格对齐
            fix_headings: 标准化标题层级
            merge_empty_lines: 合并连续空行
            generate_toc: 生成目录
            validate_latex: 验证LaTeX公式
            check_links: 检查链接有效性
            max_empty_lines: 最大连续空行数
        """
        self.fix_tables = fix_tables
        self.fix_headings = fix_headings
        self.merge_empty_lines = merge_empty_lines
        self.generate_toc = generate_toc
        self.validate_latex = validate_latex
        self.check_links = check_links
        self.max_empty_lines = max_empty_lines

    def process_file(self, file_path: Path) -> PostProcessResult:
        """处理单个 Markdown 文件"""
        result = PostProcessResult(file_path=str(file_path), original_size=0, processed_size=0)

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            result.original_size = len(content)
        except Exception as e:
            result.errors.append(f"无法读取文件: {e}")
            return result

        # 应用各种修复
        # 首先修复 LLM 输出问题
        content, json_fixes = self._remove_json_blocks(content)
        if json_fixes > 0:
            result.fixes_applied.append(f"移除了 {json_fixes} 个 JSON 块")

        content, newline_fixes = self._fix_literal_newlines(content)
        if newline_fixes > 0:
            result.fixes_applied.append(f"修复了 {newline_fixes} 处字面换行符")

        if self.merge_empty_lines:
            content, count = self._merge_empty_lines(content)
            if count > 0:
                result.fixes_applied.append(f"合并了 {count} 处连续空行")

        if self.fix_tables:
            content, count = self._fix_table_alignment(content)
            if count > 0:
                result.fixes_applied.append(f"修复了 {count} 个表格对齐")

        if self.fix_headings:
            content, fixes = self._standardize_headings(content)
            if fixes:
                result.fixes_applied.extend(fixes)

        if self.validate_latex:
            warnings = self._validate_latex_formulas(content)
            result.warnings.extend(warnings)

        if self.check_links:
            warnings = self._check_broken_links(content)
            result.warnings.extend(warnings)

        # 清理尾部空白
        content = self._clean_trailing_whitespace(content)

        # 生成目录（在文件开头）
        if self.generate_toc:
            toc, has_headings = self._generate_toc(content)
            if has_headings:
                content = self._insert_toc(content, toc)
                result.toc_generated = True
                result.fixes_applied.append("生成了目录")

        result.processed_size = len(content)

        # 写回文件
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            result.errors.append(f"无法写入文件: {e}")

        return result

    def _remove_json_blocks(self, content: str) -> Tuple[str, int]:
        """
        移除 LLM 输出中的原始 JSON 块

        有时 LLM 会输出原始 JSON 响应而不是提取的文本内容，如：
        ```json
        {
          "body_text": "实际内容...",
          "tables": [...],
          ...
        }
        ```

        此方法尝试提取 body_text 字段的内容，或者移除整个 JSON 块
        同时处理未闭合的 JSON 块
        """
        import json as json_module

        fixes = 0

        # 首先处理完整的 ```json ... ``` 块
        json_block_pattern = r'```json\s*\n(.*?)\n```'

        def extract_or_remove(match):
            nonlocal fixes
            json_str = match.group(1)

            try:
                # 尝试解析 JSON
                data = json_module.loads(json_str)

                # 尝试提取 body_text
                if isinstance(data, dict):
                    if 'body_text' in data:
                        fixes += 1
                        body = data['body_text']
                        # 如果 body_text 是字符串，直接返回
                        if isinstance(body, str):
                            return body.replace('\\n', '\n')
                        return str(body)
                    elif 'content' in data:
                        fixes += 1
                        return str(data['content']).replace('\\n', '\n')
                    elif 'text' in data:
                        fixes += 1
                        return str(data['text']).replace('\\n', '\n')

                # 无法提取有用内容，移除整个块
                fixes += 1
                return ''

            except json_module.JSONDecodeError:
                # 不是有效 JSON，保留原样
                return match.group(0)

        content = re.sub(json_block_pattern, extract_or_remove, content, flags=re.DOTALL)

        # 然后处理未闭合的 ```json 块（到下一个 ## Page 或文件结尾）
        # 这些块的格式通常是：
        # ```json
        # {
        #   "page_number": X,
        #   "tables": [...],
        #   "figures": [...],
        #   "formulas": [...],
        #   "body_text": "内容..."
        # (没有闭合)

        # 模式1: ```json 块到下一个 ## Page 之前
        unclosed_pattern = r'```json\s*\n\{\s*\n\s*"page_number":\s*\d+,.*?(?=\n\n## Page|\Z)'

        def remove_unclosed_json(match):
            nonlocal fixes
            block = match.group(0)

            # 尝试提取 body_text 内容
            body_match = re.search(r'"body_text":\s*"(.*?)(?:"\s*,|\"\s*\}|$)', block, re.DOTALL)
            if body_match:
                body_text = body_match.group(1)
                # 处理转义
                body_text = body_text.replace('\\n', '\n')
                body_text = body_text.replace('\\t', '\t')
                body_text = body_text.replace('\\"', '"')
                fixes += 1
                return body_text

            # 无法提取，删除整个块
            fixes += 1
            return ''

        content = re.sub(unclosed_pattern, remove_unclosed_json, content, flags=re.DOTALL)

        # 模式2: 删除残留的 JSON 开头标记（只有开头，没有内容）
        content = re.sub(r'```json\s*\n\s*\{\s*\n\s*$', '', content, flags=re.MULTILINE)

        # 模式3: 清理残留的 JSON 属性行（如 "tables": [], 等）
        json_property_pattern = r'^\s*"(?:tables|figures|formulas|page_number)":\s*[\[\d].*?,?\s*$'
        lines = content.split('\n')
        cleaned_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # 如果是 JSON 属性行，跳过
            if re.match(json_property_pattern, line):
                fixes += 1
                i += 1
                continue
            # 如果是 "body_text": 开头，提取内容
            body_match = re.match(r'^\s*"body_text":\s*"(.*)$', line)
            if body_match:
                # 提取到下一个 ## Page 或结尾
                body_content = [body_match.group(1)]
                i += 1
                while i < len(lines):
                    if lines[i].startswith('## Page') or lines[i].startswith('```'):
                        break
                    # 如果行以 ", 结尾，去掉
                    line_content = lines[i]
                    if line_content.endswith('",'):
                        line_content = line_content[:-2]
                    body_content.append(line_content)
                    i += 1
                # 合并内容
                merged = '\n'.join(body_content)
                merged = merged.replace('\\n', '\n')
                merged = merged.replace('\\t', '\t')
                merged = merged.replace('\\"', '"')
                # 去掉末尾的引号和逗号
                merged = re.sub(r'[",]+\s*$', '', merged)
                cleaned_lines.append(merged)
                fixes += 1
                continue
            cleaned_lines.append(line)
            i += 1

        content = '\n'.join(cleaned_lines)

        return content, fixes

    def _fix_literal_newlines(self, content: str) -> Tuple[str, int]:
        """
        修复 LLM 输出中的字面换行符

        有时 LLM 会输出字面的 \\n 而不是实际的换行符
        例如: "第一行\\n第二行" 应该变成 "第一行\n第二行"

        注意：需要小心不要破坏：
        - LaTeX 公式中的 \\n (应该是 \\newline)
        - 代码块中的转义
        """
        # 计算替换次数
        # 匹配不在代码块或 LaTeX 中的 \n

        # 策略：先保护代码块和 LaTeX 块，然后替换，再恢复

        # 保护代码块
        code_blocks = []
        def save_code_block(match):
            code_blocks.append(match.group(0))
            return f'__CODE_BLOCK_{len(code_blocks) - 1}__'

        # 保护 ``` 代码块
        protected = re.sub(r'```.*?```', save_code_block, content, flags=re.DOTALL)

        # 保护 LaTeX 块 $$ ... $$
        latex_blocks = []
        def save_latex_block(match):
            latex_blocks.append(match.group(0))
            return f'__LATEX_BLOCK_{len(latex_blocks) - 1}__'

        protected = re.sub(r'\$\$.*?\$\$', save_latex_block, protected, flags=re.DOTALL)

        # 统计并替换字面 \n
        # 注意：在原始字符串中，\\n 表示反斜杠后跟 n
        original_count = protected.count('\\n')
        protected = protected.replace('\\n', '\n')
        fixes = original_count

        # 恢复 LaTeX 块
        for i, block in enumerate(latex_blocks):
            protected = protected.replace(f'__LATEX_BLOCK_{i}__', block)

        # 恢复代码块
        for i, block in enumerate(code_blocks):
            protected = protected.replace(f'__CODE_BLOCK_{i}__', block)

        return protected, fixes

    def _merge_empty_lines(self, content: str) -> Tuple[str, int]:
        """合并连续空行"""
        # 匹配超过 max_empty_lines 的连续空行
        pattern = r'\n{' + str(self.max_empty_lines + 2) + r',}'
        replacement = '\n' * (self.max_empty_lines + 1)

        # 计算替换次数
        matches = re.findall(pattern, content)
        count = len(matches)

        content = re.sub(pattern, replacement, content)
        return content, count

    def _fix_table_alignment(self, content: str) -> Tuple[str, int]:
        """修复表格对齐"""
        lines = content.split('\n')
        new_lines = []
        i = 0
        fixed_count = 0

        while i < len(lines):
            line = lines[i]

            # 检测表格开始（包含 | 的行）
            if '|' in line and i + 1 < len(lines) and re.match(r'^\s*\|[-:|]+\|', lines[i + 1]):
                # 找到表格范围
                table_start = i
                table_end = i

                # 找表格结束
                while table_end < len(lines) and '|' in lines[table_end]:
                    table_end += 1

                # 提取表格行
                table_lines = lines[table_start:table_end]

                # 修复表格
                fixed_table = self._align_table(table_lines)
                if fixed_table != table_lines:
                    fixed_count += 1

                new_lines.extend(fixed_table)
                i = table_end
            else:
                new_lines.append(line)
                i += 1

        return '\n'.join(new_lines), fixed_count

    def _align_table(self, table_lines: List[str]) -> List[str]:
        """对齐单个表格"""
        if len(table_lines) < 2:
            return table_lines

        # 解析每行的单元格
        rows = []
        for line in table_lines:
            # 去除首尾的 |
            line = line.strip()
            if line.startswith('|'):
                line = line[1:]
            if line.endswith('|'):
                line = line[:-1]

            cells = [cell.strip() for cell in line.split('|')]
            rows.append(cells)

        if not rows:
            return table_lines

        # 计算每列最大宽度
        num_cols = max(len(row) for row in rows)
        col_widths = [0] * num_cols

        for row in rows:
            for j, cell in enumerate(row):
                if j < num_cols:
                    # 对于分隔行，不计算宽度
                    if not re.match(r'^[-:]+$', cell):
                        col_widths[j] = max(col_widths[j], len(cell))

        # 最小宽度为3（分隔符需要至少3个字符 ---）
        col_widths = [max(w, 3) for w in col_widths]

        # 重建表格
        aligned_lines = []
        for i, row in enumerate(rows):
            cells = []
            for j in range(num_cols):
                cell = row[j] if j < len(row) else ''

                # 分隔行特殊处理
                if i == 1 and re.match(r'^[-:]+$', cell):
                    # 保持对齐标记
                    if cell.startswith(':') and cell.endswith(':'):
                        cell = ':' + '-' * (col_widths[j] - 2) + ':'
                    elif cell.startswith(':'):
                        cell = ':' + '-' * (col_widths[j] - 1)
                    elif cell.endswith(':'):
                        cell = '-' * (col_widths[j] - 1) + ':'
                    else:
                        cell = '-' * col_widths[j]
                else:
                    cell = cell.ljust(col_widths[j])

                cells.append(cell)

            aligned_lines.append('| ' + ' | '.join(cells) + ' |')

        return aligned_lines

    def _standardize_headings(self, content: str) -> Tuple[str, List[str]]:
        """标准化标题层级"""
        fixes = []
        lines = content.split('\n')
        new_lines = []

        # 检测是否有孤立标题（标题后直接是另一个标题）
        for i, line in enumerate(lines):
            new_lines.append(line)

            # 检测标题
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2)

                # 检查下一行是否也是标题（孤立标题）
                if i + 1 < len(lines):
                    next_match = re.match(r'^(#{1,6})\s+', lines[i + 1])
                    if next_match:
                        next_level = len(next_match.group(1))
                        # 如果下一个标题级别更低（数字更大），且中间没有内容，发出警告
                        if next_level > level:
                            fixes.append(f"警告: 第 {i+1} 行标题 '{title[:30]}...' 后无内容")

        # 检查标题层级跳跃
        prev_level = 0
        for i, line in enumerate(lines):
            heading_match = re.match(r'^(#{1,6})\s+', line)
            if heading_match:
                level = len(heading_match.group(1))
                if prev_level > 0 and level > prev_level + 1:
                    fixes.append(f"警告: 第 {i+1} 行标题层级跳跃 (H{prev_level} → H{level})")
                prev_level = level

        return '\n'.join(new_lines), fixes

    def _validate_latex_formulas(self, content: str) -> List[str]:
        """验证 LaTeX 公式语法"""
        warnings = []

        # 检测行内公式 $...$
        inline_formulas = re.findall(r'\$([^$]+)\$', content)
        for formula in inline_formulas:
            issues = self._check_latex_syntax(formula)
            if issues:
                warnings.append(f"行内公式问题: ${formula[:30]}... - {issues}")

        # 检测块级公式 $$...$$
        block_formulas = re.findall(r'\$\$([^$]+)\$\$', content, re.DOTALL)
        for formula in block_formulas:
            issues = self._check_latex_syntax(formula)
            if issues:
                warnings.append(f"块级公式问题: $${formula[:30]}... - {issues}")

        return warnings

    def _check_latex_syntax(self, formula: str) -> Optional[str]:
        """检查单个 LaTeX 公式语法"""
        # 检查括号匹配
        brackets = {'{': '}', '(': ')', '[': ']'}
        stack = []

        for char in formula:
            if char in brackets:
                stack.append(char)
            elif char in brackets.values():
                if not stack:
                    return "括号不匹配"
                expected = brackets[stack.pop()]
                if char != expected:
                    return "括号不匹配"

        if stack:
            return "括号未闭合"

        # 检查常见命令是否完整
        incomplete_commands = [
            (r'\\frac\s*$', '\\frac 缺少参数'),
            (r'\\sqrt\s*$', '\\sqrt 缺少参数'),
            (r'\\sum\s*$', '\\sum 可能缺少上下标'),
        ]

        for pattern, msg in incomplete_commands:
            if re.search(pattern, formula):
                return msg

        return None

    def _check_broken_links(self, content: str) -> List[str]:
        """检查可能的断链"""
        warnings = []

        # 检测 Markdown 链接 [text](url)
        links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
        for text, url in links:
            if url.startswith('#'):
                # 内部锚点链接，检查是否存在
                anchor = url[1:]
                # 简化检查：看是否有对应标题
                heading_pattern = re.escape(anchor.replace('-', ' '))
                if not re.search(rf'#{1,6}\s+{heading_pattern}', content, re.IGNORECASE):
                    warnings.append(f"内部链接可能断裂: [{text}]({url})")
            elif not url.startswith(('http://', 'https://', 'mailto:', '/')):
                # 相对路径链接
                warnings.append(f"相对路径链接（需验证）: [{text}]({url})")

        return warnings

    def _clean_trailing_whitespace(self, content: str) -> str:
        """清理行尾空白"""
        lines = content.split('\n')
        cleaned = [line.rstrip() for line in lines]
        return '\n'.join(cleaned)

    def _generate_toc(self, content: str) -> Tuple[str, bool]:
        """生成目录"""
        headings = []

        # 提取所有标题
        for line in content.split('\n'):
            match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                # 生成锚点
                anchor = re.sub(r'[^\w\s-]', '', title.lower())
                anchor = re.sub(r'\s+', '-', anchor)
                headings.append((level, title, anchor))

        if not headings:
            return '', False

        # 生成 TOC
        toc_lines = ['## 目录\n']
        for level, title, anchor in headings:
            if level == 1:
                continue  # 跳过一级标题（通常是文档标题）
            indent = '  ' * (level - 2)
            toc_lines.append(f'{indent}- [{title}](#{anchor})')

        toc_lines.append('\n---\n')
        return '\n'.join(toc_lines), True

    def _insert_toc(self, content: str, toc: str) -> str:
        """在适当位置插入目录"""
        lines = content.split('\n')

        # 找到第一个一级标题后插入
        for i, line in enumerate(lines):
            if re.match(r'^#\s+', line):
                # 在一级标题后插入
                lines.insert(i + 1, '')
                lines.insert(i + 2, toc)
                break
        else:
            # 没有一级标题，插入到开头
            lines.insert(0, toc)

        return '\n'.join(lines)


def process_directory(input_dir: Path, **kwargs) -> List[PostProcessResult]:
    """处理目录中的所有 Markdown 文件"""
    processor = MarkdownPostProcessor(**kwargs)
    results = []

    # 查找所有 .md 文件
    md_files = list(input_dir.rglob('*.md'))

    print(f"📝 找到 {len(md_files)} 个 Markdown 文件")

    for md_file in sorted(md_files):
        # 跳过质量报告文件
        if md_file.name == 'QUALITY_REPORT.md':
            continue

        print(f"   处理: {md_file.name}...", end=' ')
        result = processor.process_file(md_file)

        if result.errors:
            print(f"❌ 错误: {result.errors[0]}")
        elif result.fixes_applied:
            print(f"✅ {len(result.fixes_applied)} 项修复")
        else:
            print("✓ 无需修复")

        results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(
        description='DocMind Markdown 后处理器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --input ./final-delivery
  %(prog)s --input ./final-delivery --generate-toc
  %(prog)s --input ./final-delivery --fix-tables --fix-headings
        """
    )

    parser.add_argument(
        '--input', '-i',
        required=True,
        help='输入目录（包含 Markdown 文件）'
    )

    parser.add_argument(
        '--fix-tables',
        action='store_true',
        default=True,
        help='修复表格对齐 (默认: 开启)'
    )

    parser.add_argument(
        '--no-fix-tables',
        action='store_true',
        help='禁用表格对齐修复'
    )

    parser.add_argument(
        '--fix-headings',
        action='store_true',
        default=True,
        help='标准化标题层级 (默认: 开启)'
    )

    parser.add_argument(
        '--no-fix-headings',
        action='store_true',
        help='禁用标题修复'
    )

    parser.add_argument(
        '--merge-empty-lines',
        action='store_true',
        default=True,
        help='合并连续空行 (默认: 开启)'
    )

    parser.add_argument(
        '--generate-toc',
        action='store_true',
        default=False,
        help='生成目录 (默认: 关闭)'
    )

    parser.add_argument(
        '--validate-latex',
        action='store_true',
        default=True,
        help='验证 LaTeX 公式 (默认: 开启)'
    )

    parser.add_argument(
        '--check-links',
        action='store_true',
        default=False,
        help='检查链接有效性 (默认: 关闭)'
    )

    parser.add_argument(
        '--max-empty-lines',
        type=int,
        default=2,
        help='最大连续空行数 (默认: 2)'
    )

    parser.add_argument(
        '--report',
        help='输出报告文件路径 (可选)'
    )

    args = parser.parse_args()

    # 验证输入目录
    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"❌ 输入目录不存在: {input_dir}")
        sys.exit(1)

    # 处理参数
    fix_tables = args.fix_tables and not args.no_fix_tables
    fix_headings = args.fix_headings and not args.no_fix_headings

    print("=" * 60)
    print("📝 Markdown 后处理器")
    print("=" * 60)
    print(f"输入目录: {input_dir}")
    print(f"修复表格: {'是' if fix_tables else '否'}")
    print(f"修复标题: {'是' if fix_headings else '否'}")
    print(f"合并空行: {'是' if args.merge_empty_lines else '否'}")
    print(f"生成目录: {'是' if args.generate_toc else '否'}")
    print(f"验证LaTeX: {'是' if args.validate_latex else '否'}")
    print("=" * 60)
    print()

    # 处理文件
    results = process_directory(
        input_dir,
        fix_tables=fix_tables,
        fix_headings=fix_headings,
        merge_empty_lines=args.merge_empty_lines,
        generate_toc=args.generate_toc,
        validate_latex=args.validate_latex,
        check_links=args.check_links,
        max_empty_lines=args.max_empty_lines
    )

    # 统计结果
    total_fixes = sum(len(r.fixes_applied) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)
    total_errors = sum(len(r.errors) for r in results)
    files_with_toc = sum(1 for r in results if r.toc_generated)

    print()
    print("=" * 60)
    print("📊 处理结果")
    print("=" * 60)
    print(f"处理文件数: {len(results)}")
    print(f"总修复数: {total_fixes}")
    print(f"生成目录: {files_with_toc}")
    print(f"警告数: {total_warnings}")
    print(f"错误数: {total_errors}")

    # 显示警告
    if total_warnings > 0:
        print()
        print("⚠️  警告:")
        for r in results:
            for w in r.warnings[:5]:  # 最多显示5个
                print(f"   {Path(r.file_path).name}: {w}")
            if len(r.warnings) > 5:
                print(f"   ... 还有 {len(r.warnings) - 5} 个警告")

    # 显示错误
    if total_errors > 0:
        print()
        print("❌ 错误:")
        for r in results:
            for e in r.errors:
                print(f"   {Path(r.file_path).name}: {e}")

    print("=" * 60)

    # 可选：生成报告文件
    if args.report:
        report_path = Path(args.report)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("# Markdown 后处理报告\n\n")
            f.write(f"| 文件 | 原始大小 | 处理后 | 修复数 | 警告 |\n")
            f.write("|------|---------|--------|--------|------|\n")
            for r in results:
                name = Path(r.file_path).name[:30]
                f.write(f"| {name} | {r.original_size:,} | {r.processed_size:,} | {len(r.fixes_applied)} | {len(r.warnings)} |\n")
        print(f"📄 报告已保存: {report_path}")


if __name__ == "__main__":
    main()
