#!/usr/bin/env python3
"""修复 GPT 补救后页面顺序混乱的问题"""

import os
import re
import glob
from pathlib import Path


def fix_page_order(md_file: str) -> bool:
    """重新排序 Markdown 文件中的页面"""

    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 分离头部和页面内容
    # 头部是 ## Page X 之前的内容
    first_page_match = re.search(r'^## Page \d+', content, re.MULTILINE)
    if not first_page_match:
        return False

    header = content[:first_page_match.start()]
    pages_content = content[first_page_match.start():]

    # 提取所有页面
    # 匹配 ## Page X 到下一个 ## Page 或文件结尾
    page_pattern = r'(## Page (\d+)\n.*?)(?=\n## Page |\Z)'
    pages = re.findall(page_pattern, pages_content, re.DOTALL)

    if not pages:
        return False

    # 按页码排序
    pages_dict = {}
    for page_content, page_num in pages:
        pages_dict[int(page_num)] = page_content.strip()

    # 按页码顺序重建内容
    sorted_pages = sorted(pages_dict.keys())
    new_content = header

    for page_num in sorted_pages:
        new_content += pages_dict[page_num] + "\n\n"

    # 写回文件
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(new_content.rstrip() + "\n")

    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description='修复页面顺序')
    parser.add_argument('--chunks-dir', default='output/chunks', help='Chunks目录')
    parser.add_argument('--dry-run', action='store_true', help='只预览')
    args = parser.parse_args()

    # 找到所有有 .bak 文件的目录（被补救脚本修改过）
    bak_files = glob.glob(os.path.join(args.chunks_dir, '*/*.bak'))

    print(f"找到 {len(bak_files)} 个被修改的文件")

    fixed = 0
    for bak_file in bak_files:
        md_file = bak_file[:-4]  # 去掉 .bak

        if not os.path.exists(md_file):
            continue

        chunk_name = os.path.basename(os.path.dirname(md_file))

        if args.dry_run:
            print(f"  [预览] {chunk_name}")
        else:
            if fix_page_order(md_file):
                print(f"  ✓ 已修复: {chunk_name}")
                fixed += 1
            else:
                print(f"  ✗ 跳过: {chunk_name}")

    print(f"\n修复完成: {fixed}/{len(bak_files)}")


if __name__ == '__main__':
    main()
