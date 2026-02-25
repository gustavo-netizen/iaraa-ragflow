#!/usr/bin/env python3

import json
from pathlib import Path
import shutil
import re

def load_split_mapping():
    """加载split映射文件"""
    mapping_file = Path('split_mapping.json')
    if not mapping_file.exists():
        print("❌ split_mapping.json不存在")
        return None

    with open(mapping_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def merge_markdown_files(parts_info, output_file):
    """合并多个part的Markdown文件"""
    print(f"\n📝 合并Markdown文件到: {output_file}")

    all_content = []
    total_pages = 0

    for part in parts_info:
        md_file = Path(f"chunk_results/{part['name']}/{part['name']}.md")
        if not md_file.exists():
            print(f"  ⚠️  {part['name']}.md 不存在，跳过")
            continue

        with open(md_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 调整页码（相对页码转换为绝对页码）
        def replace_page(match):
            relative_page = int(match.group(1))
            absolute_page = relative_page + part['start_page'] - 1
            return f"## Page {absolute_page}"

        adjusted_content = re.sub(r'## Page (\d+)', replace_page, content)
        all_content.append(adjusted_content)

        # 统计页数
        pages = re.findall(r'## Page \d+', content)
        total_pages += len(pages)
        print(f"  ✅ Part {part['part_num']}: {len(pages)} 页")

    # 写入合并后的文件
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(all_content))

    print(f"  📊 总页数: {total_pages}")
    return total_pages

def merge_images(parts_info, output_dir):
    """合并图片文件夹"""
    print(f"\n🖼️  合并图片到: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    total_images = 0

    for part in parts_info:
        img_dir = Path(f"chunk_results/{part['name']}/images")
        if not img_dir.exists():
            print(f"  ⚠️  {part['name']}/images 不存在，跳过")
            continue

        images = list(img_dir.glob('*.png'))
        for img in images:
            # 调整图片文件名中的页码
            img_name = img.name
            if img_name.startswith('page_'):
                # 提取页码并调整
                match = re.match(r'page_(\d+)(_.*)?\.png', img_name)
                if match:
                    relative_page = int(match.group(1))
                    absolute_page = relative_page + part['start_page'] - 1
                    suffix = match.group(2) or ''
                    new_name = f"page_{absolute_page}{suffix}.png"
                else:
                    new_name = img_name
            else:
                new_name = img_name

            dst = output_dir / new_name
            shutil.copy2(img, dst)
            total_images += 1

    print(f"  📊 总图片数: {total_images}")
    return total_images

def merge_yaml_files(parts_info, output_dir):
    """合并YAML元数据"""
    print(f"\n📋 合并YAML到: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    total_yaml = 0

    for part in parts_info:
        yaml_dir = Path(f"chunk_results/{part['name']}/yaml_metadata")
        if not yaml_dir.exists():
            print(f"  ⚠️  {part['name']}/yaml_metadata 不存在，跳过")
            continue

        yaml_files = list(yaml_dir.glob('*.yaml'))
        for yml in yaml_files:
            # 调整YAML文件名中的页码
            yml_name = yml.name
            if yml_name.startswith('page_'):
                # 提取页码并调整
                match = re.match(r'page_(\d+)(_.*)?\.yaml', yml_name)
                if match:
                    relative_page = int(match.group(1))
                    absolute_page = relative_page + part['start_page'] - 1
                    suffix = match.group(2) or ''
                    new_name = f"page_{absolute_page}{suffix}.yaml"
                else:
                    new_name = yml_name
            else:
                new_name = yml_name

            dst = output_dir / new_name
            shutil.copy2(yml, dst)
            total_yaml += 1

    print(f"  📊 总YAML数: {total_yaml}")
    return total_yaml

def main():
    print('='*80)
    print('🔧 合并Split PDFs为完整书籍')
    print('='*80)

    # 加载映射
    mapping = load_split_mapping()
    if not mapping:
        return

    # 按原始PDF分组
    books = {}
    for chunk in mapping.get('chunks', []):
        original = chunk['original_pdf']
        if original not in books:
            books[original] = []
        books[original].append(chunk)

    # 排序每本书的parts
    for book in books:
        books[book].sort(key=lambda x: x['start_page'])

    # 创建输出目录
    merged_dir = Path('merged_books')
    merged_dir.mkdir(exist_ok=True)

    success_count = 0
    skip_count = 0

    for book_name, parts in books.items():
        print(f'\n{"="*60}')
        print(f'📚 处理: {book_name}')
        print(f'   Parts: {len(parts)}')

        # 准备parts信息
        parts_info = []
        all_exist = True

        for i, part in enumerate(parts, 1):
            part_name = Path(part['path']).stem
            chunk_dir = Path(f'chunk_results/{part_name}')

            if not chunk_dir.exists():
                print(f'  ❌ Part {i} 不存在: {part_name}')
                all_exist = False
                break

            parts_info.append({
                'name': part_name,
                'part_num': i,
                'start_page': part['start_page'],
                'end_page': part['end_page']
            })

        if not all_exist:
            print(f'  ⚠️  跳过此书（parts不完整）')
            skip_count += 1
            continue

        # 创建输出目录
        book_stem = Path(book_name).stem
        output_dir = merged_dir / book_stem
        output_dir.mkdir(exist_ok=True)

        # 合并Markdown
        md_output = output_dir / f"{book_stem}.md"
        md_pages = merge_markdown_files(parts_info, md_output)

        # 合并图片
        img_output = output_dir / 'images'
        img_count = merge_images(parts_info, img_output)

        # 合并YAML
        yaml_output = output_dir / 'yaml_metadata'
        yaml_count = merge_yaml_files(parts_info, yaml_output)

        # 创建合并信息
        merge_info = {
            'original': book_name,
            'parts': len(parts),
            'total_pages': sum(p['pages'] for p in parts),
            'merged_pages': md_pages,
            'merged_images': img_count,
            'merged_yaml': yaml_count,
            'parts_detail': parts
        }

        with open(output_dir / 'merge_info.json', 'w', encoding='utf-8') as f:
            json.dump(merge_info, f, ensure_ascii=False, indent=2)

        print(f'\n  ✅ 合并成功!')
        print(f'     输出目录: {output_dir}')
        success_count += 1

    # 统计报告
    print()
    print('='*80)
    print('📊 合并完成统计')
    print('='*80)
    print(f'✅ 成功合并: {success_count} 本书')
    print(f'⚠️  跳过(不完整): {skip_count} 本书')
    print(f'📁 输出目录: {merged_dir}')

    # 列出成功合并的书籍
    if success_count > 0:
        print('\n成功合并的书籍:')
        for book_dir in sorted(merged_dir.iterdir()):
            if book_dir.is_dir():
                info_file = book_dir / 'merge_info.json'
                if info_file.exists():
                    with open(info_file, 'r') as f:
                        info = json.load(f)
                    print(f"  - {book_dir.name}")
                    print(f"    Parts: {info['parts']}, Pages: {info['merged_pages']}")

if __name__ == '__main__':
    main()