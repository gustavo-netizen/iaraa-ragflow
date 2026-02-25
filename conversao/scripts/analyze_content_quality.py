#!/usr/bin/env python3
import os
import re
from pathlib import Path
import statistics

def analyze_content_quality():
    hard7_dir = Path("BATCH4_HARD7_DELIVERY")

    quality_stats = {
        'pdfs': [],
        'total_content_length': 0,
        'page_content_lengths': [],
        'empty_pages': 0,
        'short_pages': 0,  # 少于100字符
        'medium_pages': 0,  # 100-500字符
        'long_pages': 0,    # 超过500字符
    }

    print("=== Hard7 内容质量详细分析 ===\n")

    for pdf_dir in sorted(hard7_dir.iterdir()):
        if pdf_dir.is_dir() and pdf_dir.name != '.DS_Store':
            md_file = pdf_dir / f"{pdf_dir.name}.md"

            if md_file.exists():
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 分析每个页面的内容
                pages = re.split(r'^## Page \d+$', content, flags=re.MULTILINE)
                pages = [p.strip() for p in pages if p.strip()]  # 移除空白

                # 跳过标题
                if pages and pages[0].startswith('#'):
                    pages = pages[1:]

                page_lengths = [len(p) for p in pages]
                avg_length = statistics.mean(page_lengths) if page_lengths else 0
                median_length = statistics.median(page_lengths) if page_lengths else 0

                # 统计页面质量分布
                empty = sum(1 for l in page_lengths if l < 10)
                short = sum(1 for l in page_lengths if 10 <= l < 100)
                medium = sum(1 for l in page_lengths if 100 <= l < 500)
                long = sum(1 for l in page_lengths if l >= 500)

                print(f"📖 {pdf_dir.name[:50]}...")
                print(f"   页面数: {len(pages)}")
                print(f"   平均字符数/页: {avg_length:.0f}")
                print(f"   中位字符数/页: {median_length:.0f}")
                print(f"   内容分布:")
                print(f"     空白(<10字): {empty} 页 ({empty*100/len(pages):.1f}%)" if pages else "")
                print(f"     短内容(10-99字): {short} 页 ({short*100/len(pages):.1f}%)" if pages else "")
                print(f"     中等(100-499字): {medium} 页 ({medium*100/len(pages):.1f}%)" if pages else "")
                print(f"     长内容(≥500字): {long} 页 ({long*100/len(pages):.1f}%)" if pages else "")

                # 抽样检查具体内容
                if len(pages) > 10:
                    sample_page = pages[10]  # 第11页
                    print(f"   第11页内容预览(前200字):")
                    preview = sample_page[:200].replace('\n', ' ')
                    print(f"     {preview}...")

                print()

                # 累计统计
                quality_stats['empty_pages'] += empty
                quality_stats['short_pages'] += short
                quality_stats['medium_pages'] += medium
                quality_stats['long_pages'] += long
                quality_stats['page_content_lengths'].extend(page_lengths)

                quality_stats['pdfs'].append({
                    'name': pdf_dir.name,
                    'pages': len(pages),
                    'avg_length': avg_length,
                    'quality_score': (medium + long) / len(pages) * 100 if pages else 0
                })

    # 总体质量评估
    print("=" * 60)
    print("📊 总体内容质量评估:")

    total_pages = len(quality_stats['page_content_lengths'])
    if total_pages > 0:
        overall_avg = statistics.mean(quality_stats['page_content_lengths'])
        overall_median = statistics.median(quality_stats['page_content_lengths'])

        print(f"   总页数: {total_pages}")
        print(f"   总体平均字符数/页: {overall_avg:.0f}")
        print(f"   总体中位字符数/页: {overall_median:.0f}")
        print(f"\n   内容质量分布:")
        print(f"   ├─ 空白内容(<10字): {quality_stats['empty_pages']} 页 ({quality_stats['empty_pages']*100/total_pages:.1f}%)")
        print(f"   ├─ 短内容(10-99字): {quality_stats['short_pages']} 页 ({quality_stats['short_pages']*100/total_pages:.1f}%)")
        print(f"   ├─ 中等内容(100-499字): {quality_stats['medium_pages']} 页 ({quality_stats['medium_pages']*100/total_pages:.1f}%)")
        print(f"   └─ 长内容(≥500字): {quality_stats['long_pages']} 页 ({quality_stats['long_pages']*100/total_pages:.1f}%)")

        # 质量评分（中等+长内容的百分比）
        quality_score = (quality_stats['medium_pages'] + quality_stats['long_pages']) / total_pages * 100

        print(f"\n   📈 整体质量评分: {quality_score:.1f}%")
        print(f"   (基于有效内容页面占比，≥100字符视为有效)")

        if quality_score >= 80:
            print("   评级: 优秀 ✅")
        elif quality_score >= 60:
            print("   评级: 良好 ✓")
        elif quality_score >= 40:
            print("   评级: 一般 ⚠️")
        else:
            print("   评级: 较差 ❌")

if __name__ == "__main__":
    analyze_content_quality()