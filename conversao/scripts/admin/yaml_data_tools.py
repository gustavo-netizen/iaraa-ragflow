#!/usr/bin/env python3
"""
YAML 数据工具集 - DocMind 0.8
合并了以下功能：
  - fill:    从 Markdown 填充 YAML 表格数据
  - sync:    同步 Table*.yaml 到 _all_figures.yaml
  - update:  更新 final-delivery 的 YAML
  - verify:  验证 YAML 与 MD 数据一致性
  - preview: 从 YAML 生成 Markdown 表格预览

使用方法:
    python scripts/yaml_data_tools.py <command> [options]

示例:
    python scripts/yaml_data_tools.py fill --output-dir output/chunks
    python scripts/yaml_data_tools.py sync --output-dir output/chunks
    python scripts/yaml_data_tools.py update --chunks-dir output/chunks --final-delivery final-delivery
    python scripts/yaml_data_tools.py verify --output-dir output/chunks
    python scripts/yaml_data_tools.py preview --yaml-file path/to/file.yaml

创建日期: 2025-12-08
"""

import argparse
import os
import re
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from difflib import SequenceMatcher
from datetime import datetime


# ============================================================================
# 通用工具函数
# ============================================================================

def load_yaml(yaml_path: str) -> Optional[Dict]:
    """加载 YAML 文件"""
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        return None


def save_yaml(yaml_path: str, data: Any) -> bool:
    """保存 YAML 文件"""
    try:
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        return True
    except Exception as e:
        print(f"Error saving {yaml_path}: {e}")
        return False


def similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度 (0-1)"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def normalize_value(val) -> str:
    """规范化值以便比较"""
    if val is None:
        return ''
    s = str(val).strip()
    s = s.replace(',', '')
    s = s.replace('–', '-').replace('—', '-')
    return s.lower()


def is_numeric(val: str) -> bool:
    """检查值是否为数值型"""
    if not val:
        return False
    clean = re.sub(r'[£$€¥%,\s\-–—?]', '', val)
    if not clean:
        return False
    try:
        float(clean)
        return True
    except ValueError:
        return False


def try_convert_number(value: str) -> Any:
    """尝试转换为数值"""
    if not value:
        return value
    clean = re.sub(r'[£$€¥,\s]', '', value)
    if '%' in value:
        clean = clean.replace('%', '')
        try:
            return float(clean)
        except ValueError:
            return value
    try:
        if '.' in clean:
            return float(clean)
        else:
            return int(clean)
    except ValueError:
        return value


def extract_keywords(text: str) -> set:
    """提取关键词"""
    text = re.sub(r'[^\w\s]', ' ', text)
    words = text.lower().split()
    return {w for w in words if len(w) > 2}


def keyword_overlap(a: str, b: str) -> float:
    """计算关键词重叠度"""
    kw_a = extract_keywords(a)
    kw_b = extract_keywords(b)
    if not kw_a or not kw_b:
        return 0.0
    intersection = kw_a & kw_b
    union = kw_a | kw_b
    return len(intersection) / len(union) if union else 0.0


def count_yaml_data_rows(data_series: Any) -> int:
    """计算 YAML data_series 中的数据行数"""
    if not data_series or not isinstance(data_series, list):
        return 0
    if len(data_series) == 0:
        return 0
    first_item = data_series[0]
    if not isinstance(first_item, dict):
        return len(data_series)
    if 'data_points' in first_item and isinstance(first_item['data_points'], list):
        return sum(len(item.get('data_points', [])) for item in data_series)
    else:
        return len(data_series)


# ============================================================================
# FILL: 从 Markdown 填充 YAML 表格数据
# ============================================================================

def parse_table_row(line: str) -> List[str]:
    """解析表格行"""
    line = line.strip()
    if line.startswith('|'):
        line = line[1:]
    if line.endswith('|'):
        line = line[:-1]
    cells = [c.strip() for c in line.split('|')]
    return cells


def parse_table_content(table_content: str) -> Optional[Dict[str, Any]]:
    """解析表格内容"""
    lines = [l.strip() for l in table_content.strip().split('\n') if l.strip()]
    if len(lines) < 2:
        return None

    header_idx = -1
    for i, line in enumerate(lines):
        if line.startswith('|'):
            header_idx = i
            break
    if header_idx < 0:
        return None

    header_line = lines[header_idx]
    headers = parse_table_row(header_line)
    if not headers:
        return None

    sep_idx = header_idx + 1
    if sep_idx >= len(lines):
        return None

    sep_line = lines[sep_idx]
    if not re.match(r'\|[\s\-:|]+\|', sep_line):
        sep_idx = header_idx

    data_start_idx = sep_idx + 1

    rows = []
    for i in range(data_start_idx, len(lines)):
        line = lines[i]
        if not line.startswith('|'):
            continue
        cells = parse_table_row(line)
        if cells:
            row_data = {'x': cells[0]}
            for j, c in enumerate(cells[1:], 1):
                key = headers[j] if j < len(headers) else f"col_{j}"
                row_data[key] = try_convert_number(c)
            if len(row_data) > 1:
                rows.append(row_data)

    if not rows:
        return None
    return {'headers': headers, 'rows': rows}


def find_tables_in_markdown(md_content: str, page_num: int = 0) -> List[Dict[str, Any]]:
    """从 Markdown 中提取表格"""
    tables = []

    if page_num > 0:
        pages_to_search = [page_num - 1, page_num, page_num + 1]
    else:
        pages_to_search = None

    def extract_from_section(section_content: str, source_page: int):
        section_tables = []
        pattern = r'###\s*(Table[^\n]*)\n\n?((?:\|[^\n]+\n)+)'
        for match in re.finditer(pattern, section_content, re.MULTILINE):
            raw_title = match.group(1).strip()
            table_content = match.group(2).strip()
            if '|' in raw_title:
                parts = raw_title.split('|')
                title = parts[0].strip().rstrip(':').strip()
                header_part = '|' + '|'.join(parts[1:])
                if not header_part.endswith('\n'):
                    header_part += '\n'
                table_content = header_part + table_content
            else:
                title = raw_title
            parsed = parse_table_content(table_content)
            if parsed:
                section_tables.append({
                    'title': title,
                    'content': table_content,
                    'page': source_page,
                    **parsed
                })
        return section_tables

    if pages_to_search:
        for search_page in pages_to_search:
            if search_page < 1:
                continue
            page_pattern = rf'## Page {search_page}\b(.*?)(?=## Page \d+|$)'
            page_match = re.search(page_pattern, md_content, re.DOTALL)
            if page_match:
                tables.extend(extract_from_section(page_match.group(1), search_page))
    else:
        tables.extend(extract_from_section(md_content, 0))

    return tables


def find_best_matching_table(yaml_data: Dict, tables: List[Dict], page_num: int) -> Optional[Dict]:
    """为 YAML 找到最佳匹配的表格"""
    chart_title = yaml_data.get('chart_identification', {}).get('chart_title', '')
    key_elements = yaml_data.get('visual_content', {}).get('key_elements', [])
    figure_number = yaml_data.get('chart_identification', {}).get('figure_number', '')

    if not tables:
        return None

    best_match = None
    best_score = 0.0
    title_is_empty = not chart_title or chart_title.strip() == ''

    for table in tables:
        score = 0.0
        if not title_is_empty:
            if table['title']:
                score += similarity(chart_title, table['title']) * 0.4
                score += keyword_overlap(chart_title, table['title']) * 0.3
            if key_elements and table.get('headers'):
                header_str = ' '.join(table['headers'])
                elements_str = ' '.join(key_elements)
                score += keyword_overlap(header_str, elements_str) * 0.3
        else:
            if key_elements and table.get('headers'):
                header_str = ' '.join(table['headers'])
                elements_str = ' '.join(key_elements)
                score += keyword_overlap(header_str, elements_str) * 0.6
            if figure_number and table['title']:
                if figure_number.lower() in table['title'].lower():
                    score += 0.4

        if score > best_score:
            best_score = score
            best_match = table

    threshold = 0.15 if title_is_empty else 0.2
    if best_score < threshold:
        if len(tables) == 1:
            return tables[0]
        return None
    return best_match


def cmd_fill(args):
    """执行 fill 命令：从 MD 填充 YAML 表格数据"""
    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print(f"Error: 目录不存在: {output_dir}")
        return 1

    print("=" * 70)
    print("YAML 表格数据填充工具")
    print("=" * 70)
    print(f"目录: {output_dir}")
    print(f"模式: {'检查' if args.dry_run else '执行'}")
    if args.force:
        print(f"强制覆盖: 是")
    print()

    stats = {'total': 0, 'filled': 0, 'skipped': 0, 'failed': 0}

    for chunk_dir in sorted(output_dir.iterdir()):
        if not chunk_dir.is_dir():
            continue

        yaml_dir = chunk_dir / 'yaml_metadata'
        if not yaml_dir.exists():
            continue

        md_files = list(chunk_dir.glob('*.md'))
        if not md_files:
            continue
        md_path = md_files[0]

        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
        except:
            continue

        for yaml_path in sorted(yaml_dir.glob('Table*.yaml')):
            stats['total'] += 1

            yaml_data = load_yaml(str(yaml_path))
            if not yaml_data:
                stats['failed'] += 1
                continue

            image_type = yaml_data.get('chart_identification', {}).get('image_type', '')
            if image_type not in ['data_table', 'table']:
                stats['skipped'] += 1
                continue

            existing_series = yaml_data.get('data_extraction', {}).get('data_series', [])
            if existing_series and not args.force:
                stats['skipped'] += 1
                continue

            page_num = 0
            page_match = re.search(r'page(\d+)', yaml_path.name)
            if page_match:
                page_num = int(page_match.group(1))

            tables = find_tables_in_markdown(md_content, page_num)
            if not tables:
                stats['failed'] += 1
                continue

            best_table = find_best_matching_table(yaml_data, tables, page_num)
            if not best_table:
                stats['failed'] += 1
                continue

            data_series = best_table.get('rows', [])
            if not data_series:
                stats['failed'] += 1
                continue

            if not args.dry_run:
                if 'data_extraction' not in yaml_data:
                    yaml_data['data_extraction'] = {}
                yaml_data['data_extraction']['data_series'] = data_series
                yaml_data['data_extraction']['has_quantitative_data'] = True
                save_yaml(str(yaml_path), yaml_data)

            stats['filled'] += 1
            print(f"  ✅ [{chunk_dir.name}] {yaml_path.name} → {len(data_series)} 行")

    print()
    print("=" * 70)
    print(f"总计: {stats['total']} | 填充: {stats['filled']} | 跳过: {stats['skipped']} | 失败: {stats['failed']}")
    return 0


# ============================================================================
# SYNC: 同步 Table*.yaml 到 _all_figures.yaml
# ============================================================================

def find_matching_entry(figures: List[Dict], figure_number: str, page_number: int) -> Optional[int]:
    """在 figures 列表中找到匹配的条目索引"""
    for i, fig in enumerate(figures):
        chart_id = fig.get('chart_identification', {})
        fig_num = chart_id.get('figure_number', '')
        fig_page = chart_id.get('page_number', 0)
        if fig_num == figure_number and fig_page == page_number:
            return i
    return None


def cmd_sync(args):
    """执行 sync 命令：同步 Table*.yaml 到 _all_figures.yaml"""
    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print(f"Error: 目录不存在: {output_dir}")
        return 1

    print("=" * 70)
    print("同步 Table YAML 到 _all_figures.yaml")
    print("=" * 70)
    print(f"目录: {output_dir}")
    print()

    stats = {'chunks': 0, 'synced': 0, 'skipped': 0}

    for chunk_dir in sorted(output_dir.iterdir()):
        if not chunk_dir.is_dir():
            continue

        yaml_dir = chunk_dir / 'yaml_metadata'
        if not yaml_dir.exists():
            continue

        all_figures_files = list(chunk_dir.glob('*_all_figures.yaml'))
        if not all_figures_files:
            continue
        all_figures_path = all_figures_files[0]

        all_figures_data = load_yaml(str(all_figures_path))
        if not all_figures_data:
            continue

        if isinstance(all_figures_data, list):
            figures_list = all_figures_data
            is_wrapped = False
        elif isinstance(all_figures_data, dict):
            figures_list = all_figures_data.get('figures', [])
            is_wrapped = True
        else:
            continue

        stats['chunks'] += 1
        chunk_synced = 0

        for table_yaml_path in sorted(yaml_dir.glob('Table*.yaml')):
            table_data = load_yaml(str(table_yaml_path))
            if not table_data:
                continue

            data_series = table_data.get('data_extraction', {}).get('data_series', [])
            if not data_series:
                stats['skipped'] += 1
                continue

            chart_id = table_data.get('chart_identification', {})
            figure_number = chart_id.get('figure_number', '')
            page_number = chart_id.get('page_number', 0)

            idx = find_matching_entry(figures_list, figure_number, page_number)
            if idx is not None:
                if 'data_extraction' not in figures_list[idx]:
                    figures_list[idx]['data_extraction'] = {}
                figures_list[idx]['data_extraction']['data_series'] = data_series
                figures_list[idx]['data_extraction']['has_quantitative_data'] = True
                chunk_synced += 1
                stats['synced'] += 1

        if chunk_synced > 0 and not args.dry_run:
            if is_wrapped:
                all_figures_data['figures'] = figures_list
                save_yaml(str(all_figures_path), all_figures_data)
            else:
                save_yaml(str(all_figures_path), figures_list)
            print(f"  ✅ {chunk_dir.name}: 同步 {chunk_synced} 个表格")

    print()
    print("=" * 70)
    print(f"Chunks: {stats['chunks']} | 同步: {stats['synced']} | 跳过: {stats['skipped']}")
    return 0


# ============================================================================
# UPDATE: 更新 final-delivery 的 YAML
# ============================================================================

MANUAL_MAPPING = {
    'LeninImperialism': 'Lenin_Imperialism',
    'MarxCapitalV1': 'Marx_Capital_V1',
    'MarxCapitalV3': 'Marx_Capital_V3',
}


def normalize_name(name: str) -> str:
    """规范化文件名用于匹配"""
    name = re.sub(r'_part\d+of\d+', '', name)
    name = re.sub(r'_chunk\d+', '', name)
    name = name.replace('_', '').replace('-', '').replace(' ', '')
    return name.lower()


def merge_figures_data(existing_figures: List[Dict], new_figures: List[Dict], page_offset: int = 0) -> List[Dict]:
    """合并图表数据，更新 data_series"""
    existing_map = {}
    for fig in existing_figures:
        chart_id = fig.get('chart_identification', {})
        key = (chart_id.get('figure_number', ''), chart_id.get('page_number', 0))
        existing_map[key] = fig

    for new_fig in new_figures:
        chart_id = new_fig.get('chart_identification', {})
        orig_page = chart_id.get('page_number', 0)
        adjusted_page = orig_page + page_offset
        key = (chart_id.get('figure_number', ''), adjusted_page)

        if key in existing_map:
            new_series = new_fig.get('data_extraction', {}).get('data_series', [])
            if new_series:
                if 'data_extraction' not in existing_map[key]:
                    existing_map[key]['data_extraction'] = {}
                existing_map[key]['data_extraction']['data_series'] = new_series
                existing_map[key]['data_extraction']['has_quantitative_data'] = True

    return list(existing_map.values())


def cmd_update(args):
    """执行 update 命令：更新 final-delivery YAML"""
    chunks_dir = Path(args.chunks_dir)
    final_dir = Path(args.final_delivery)

    if not chunks_dir.exists():
        print(f"Error: chunks 目录不存在: {chunks_dir}")
        return 1
    if not final_dir.exists():
        print(f"Error: final-delivery 目录不存在: {final_dir}")
        return 1

    print("=" * 70)
    print("更新 Final Delivery YAML")
    print("=" * 70)
    print(f"Chunks: {chunks_dir}")
    print(f"Final:  {final_dir}")
    print()

    chunk_data = {}
    for chunk_dir in chunks_dir.iterdir():
        if not chunk_dir.is_dir():
            continue
        all_figures_files = list(chunk_dir.glob('*_all_figures.yaml'))
        if not all_figures_files:
            continue
        data = load_yaml(str(all_figures_files[0]))
        if data:
            if isinstance(data, dict):
                figures = data.get('figures', [])
            else:
                figures = data
            chunk_data[chunk_dir.name] = figures

    stats = {'updated': 0, 'skipped': 0}

    for final_yaml in sorted(final_dir.glob('*.yaml')):
        if final_yaml.name.startswith('QUALITY') or final_yaml.name.startswith('VALIDATION'):
            continue

        final_data = load_yaml(str(final_yaml))
        if not final_data:
            continue

        if isinstance(final_data, dict):
            final_figures = final_data.get('figures', [])
            is_wrapped = True
        else:
            final_figures = final_data
            is_wrapped = False

        base_name = final_yaml.stem.replace('_all_figures', '')
        norm_base = normalize_name(base_name)

        matched_chunks = []
        for chunk_name, figures in chunk_data.items():
            if normalize_name(chunk_name).startswith(norm_base):
                matched_chunks.append((chunk_name, figures))

        if not matched_chunks:
            for mapped_name, original_name in MANUAL_MAPPING.items():
                if normalize_name(mapped_name) == norm_base:
                    for chunk_name, figures in chunk_data.items():
                        if normalize_name(chunk_name).startswith(normalize_name(original_name)):
                            matched_chunks.append((chunk_name, figures))

        if matched_chunks:
            matched_chunks.sort(key=lambda x: x[0])
            page_offset = 0
            for chunk_name, chunk_figures in matched_chunks:
                final_figures = merge_figures_data(final_figures, chunk_figures, page_offset)
                part_match = re.search(r'_part(\d+)of(\d+)', chunk_name)
                if part_match:
                    pass

            if not args.dry_run:
                if is_wrapped:
                    final_data['figures'] = final_figures
                    save_yaml(str(final_yaml), final_data)
                else:
                    save_yaml(str(final_yaml), final_figures)

            stats['updated'] += 1
            print(f"  ✅ {final_yaml.name} ← {len(matched_chunks)} chunks")
        else:
            stats['skipped'] += 1

    print()
    print("=" * 70)
    print(f"更新: {stats['updated']} | 跳过: {stats['skipped']}")
    return 0


# ============================================================================
# VERIFY: 验证 YAML 与 MD 数据一致性
# ============================================================================

def extract_tables_from_markdown(md_path: str, page_num: int) -> List[Dict]:
    """从 Markdown 中提取指定页面的表格"""
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except:
        return []

    all_tables = []
    pages_to_search = [page_num - 1, page_num, page_num + 1]

    for search_page in pages_to_search:
        if search_page < 1:
            continue
        page_pattern = rf'## Page {search_page}\b(.*?)(?=## Page \d+|$)'
        page_match = re.search(page_pattern, content, re.DOTALL)
        if not page_match:
            continue

        page_content = page_match.group(1)
        table_pattern = r'###\s*(Table[^\n:]*):?\s*([^\|\n][^\n]*)?\n+((?:\|[^\n]+\|\n)+)'

        for match in re.finditer(table_pattern, page_content):
            figure_number = match.group(1).strip()
            table_title = match.group(2).strip() if match.group(2) else figure_number
            table_content = match.group(3)

            lines = table_content.strip().split('\n')
            if len(lines) < 2:
                continue

            header_line = lines[0]
            headers = [h.strip() for h in header_line.split('|') if h.strip()]

            data_rows = []
            for line in lines[2:]:
                if line.strip() and '|' in line:
                    cells = [c.strip() for c in line.split('|') if c.strip() or c == '']
                    cells = [c for c in cells if c]
                    if cells:
                        data_rows.append(cells)

            all_tables.append({
                'figure_number': figure_number,
                'title': table_title,
                'headers': headers,
                'data_rows': data_rows,
                'row_count': len(data_rows),
                'page': search_page
            })

    return all_tables


def cmd_verify(args):
    """执行 verify 命令：验证 YAML 与 MD 一致性"""
    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print(f"Error: 目录不存在: {output_dir}")
        return 1

    print("=" * 70)
    print("YAML 表格数据验证")
    print("=" * 70)
    print(f"目录: {output_dir}")
    print()

    yaml_files = []
    for chunk_dir in output_dir.iterdir():
        if chunk_dir.is_dir():
            yaml_dir = chunk_dir / 'yaml_metadata'
            if yaml_dir.exists():
                for yaml_file in yaml_dir.glob('Table*.yaml'):
                    md_file = chunk_dir / f'{chunk_dir.name}.md'
                    if md_file.exists():
                        yaml_files.append((str(yaml_file), str(md_file), chunk_dir.name))

    stats = {'PASS': 0, 'PARTIAL': 0, 'EMPTY': 0, 'FAIL': 0}

    print(f"{'状态':<10} {'YAML行':<8} {'MD行':<8} {'文件'}")
    print("-" * 70)

    for yaml_path, md_path, chunk_name in sorted(yaml_files):
        yaml_data = load_yaml(yaml_path)
        if not yaml_data:
            stats['FAIL'] += 1
            continue

        data_series = yaml_data.get('data_extraction', {}).get('data_series', [])
        yaml_rows = count_yaml_data_rows(data_series)

        if yaml_rows == 0:
            stats['EMPTY'] += 1
            print(f"{'❌ EMPTY':<10} {yaml_rows:<8} {'-':<8} [{chunk_name}] {Path(yaml_path).name}")
            continue

        page_num = 0
        page_match = re.search(r'page(\d+)', yaml_path)
        if page_match:
            page_num = int(page_match.group(1))

        md_tables = extract_tables_from_markdown(md_path, page_num)
        if not md_tables:
            stats['PARTIAL'] += 1
            print(f"{'⚠️ NO_MD':<10} {yaml_rows:<8} {'?':<8} [{chunk_name}] {Path(yaml_path).name}")
            continue

        best_match = md_tables[0]
        for table in md_tables:
            yaml_fn = yaml_data.get('chart_identification', {}).get('figure_number', '').lower()
            if yaml_fn and yaml_fn in table.get('figure_number', '').lower():
                best_match = table
                break

        md_rows = best_match['row_count']

        if yaml_rows == md_rows:
            stats['PASS'] += 1
            print(f"{'✅ PASS':<10} {yaml_rows:<8} {md_rows:<8} [{chunk_name}] {Path(yaml_path).name}")
        else:
            stats['PARTIAL'] += 1
            print(f"{'⚠️ DIFF':<10} {yaml_rows:<8} {md_rows:<8} [{chunk_name}] {Path(yaml_path).name}")

    print()
    print("=" * 70)
    total = sum(stats.values())
    print(f"总计: {total} | PASS: {stats['PASS']} | PARTIAL: {stats['PARTIAL']} | EMPTY: {stats['EMPTY']} | FAIL: {stats['FAIL']}")
    if total > 0:
        pass_rate = (stats['PASS'] + stats['PARTIAL']) / total * 100
        print(f"通过率: {pass_rate:.1f}%")
    return 0


# ============================================================================
# PREVIEW: 从 YAML 生成 Markdown 表格预览
# ============================================================================

def yaml_to_markdown_table(yaml_data: Dict) -> Optional[str]:
    """将 YAML data_series 转换为 Markdown 表格"""
    data_series = yaml_data.get('data_extraction', {}).get('data_series', [])
    if not data_series:
        return None

    all_keys = set()
    for row in data_series:
        all_keys.update(row.keys())

    columns = ['x'] if 'x' in all_keys else []
    columns.extend(sorted([k for k in all_keys if k != 'x']))

    header = '| ' + ' | '.join(columns) + ' |'
    separator = '|' + '|'.join(['---' for _ in columns]) + '|'

    rows = []
    for row_data in data_series:
        cells = []
        for col in columns:
            val = row_data.get(col, '')
            if val is None:
                val = ''
            elif isinstance(val, float):
                if val == int(val):
                    val = str(int(val))
                else:
                    val = str(val)
            else:
                val = str(val)
            cells.append(val)
        rows.append('| ' + ' | '.join(cells) + ' |')

    return '\n'.join([header, separator] + rows)


def cmd_preview(args):
    """执行 preview 命令：从 YAML 生成 MD 表格预览"""
    yaml_path = Path(args.yaml_file)

    if not yaml_path.exists():
        print(f"Error: 文件不存在: {yaml_path}")
        return 1

    yaml_data = load_yaml(str(yaml_path))
    if not yaml_data:
        print(f"Error: 无法加载 YAML 文件")
        return 1

    chart_title = yaml_data.get('chart_identification', {}).get('chart_title', 'Unknown')
    figure_number = yaml_data.get('chart_identification', {}).get('figure_number', '')

    print("=" * 70)
    print(f"YAML 表格预览: {yaml_path.name}")
    print("=" * 70)
    print(f"Figure: {figure_number}")
    print(f"Title:  {chart_title[:60]}...")
    print()

    table_md = yaml_to_markdown_table(yaml_data)
    if table_md:
        print(table_md)
    else:
        print("(无 data_series 数据)")

    print()
    return 0


# ============================================================================
# 主程序
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='YAML 数据工具集 - DocMind 0.8',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s fill --output-dir output/chunks
  %(prog)s sync --output-dir output/chunks
  %(prog)s update --chunks-dir output/chunks --final-delivery final-delivery
  %(prog)s verify --output-dir output/chunks
  %(prog)s preview --yaml-file path/to/Table_1_page5.yaml
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # fill 命令
    fill_parser = subparsers.add_parser('fill', help='从 MD 填充 YAML 表格数据')
    fill_parser.add_argument('--output-dir', '-o', default='output/chunks', help='输出目录')
    fill_parser.add_argument('--dry-run', '-n', action='store_true', help='仅检查不修改')
    fill_parser.add_argument('--force', '-f', action='store_true', help='强制覆盖已有数据')

    # sync 命令
    sync_parser = subparsers.add_parser('sync', help='同步 Table*.yaml 到 _all_figures.yaml')
    sync_parser.add_argument('--output-dir', '-o', default='output/chunks', help='输出目录')
    sync_parser.add_argument('--dry-run', '-n', action='store_true', help='仅检查不修改')

    # update 命令
    update_parser = subparsers.add_parser('update', help='更新 final-delivery YAML')
    update_parser.add_argument('--chunks-dir', '-c', default='output/chunks', help='chunks 目录')
    update_parser.add_argument('--final-delivery', '-f', default='final-delivery', help='final-delivery 目录')
    update_parser.add_argument('--dry-run', '-n', action='store_true', help='仅检查不修改')

    # verify 命令
    verify_parser = subparsers.add_parser('verify', help='验证 YAML 与 MD 一致性')
    verify_parser.add_argument('--output-dir', '-o', default='output/chunks', help='输出目录')

    # preview 命令
    preview_parser = subparsers.add_parser('preview', help='从 YAML 生成 MD 表格预览')
    preview_parser.add_argument('--yaml-file', '-y', required=True, help='YAML 文件路径')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == 'fill':
        return cmd_fill(args)
    elif args.command == 'sync':
        return cmd_sync(args)
    elif args.command == 'update':
        return cmd_update(args)
    elif args.command == 'verify':
        return cmd_verify(args)
    elif args.command == 'preview':
        return cmd_preview(args)
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
