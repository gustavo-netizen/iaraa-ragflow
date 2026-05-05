#!/usr/bin/env python3
"""Merge per-chunk Stage-1 outputs back into one Document per original PDF.

Refactored in Fase E of PLANO_REFATORACAO.md to consume ``Document`` from
``conversao/docmind/``. Page-offset transforms (``adjust_md_*``) now live as
``Document.apply_page_offset``; discovery flows through ``Document.discover``.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
_CONVERSAO_DIR = _SCRIPT_DIR.parent
if str(_CONVERSAO_DIR) not in sys.path:
    sys.path.insert(0, str(_CONVERSAO_DIR))

from docmind.document import Chunk, Document  # noqa: E402


def merge_document(document: Document, results_dir: Path) -> Dict[str, Any]:
    """Merge a chunked ``Document``: concatenate MDs, copy images, rewrite YAMLs."""
    chunks = document.chunks
    print(f"\n  📄 Merging: {document.pdf_path.name}")
    print(f"      {len(chunks)} chunks to merge")

    document.output_dir.mkdir(parents=True, exist_ok=True)
    document.images_dir.mkdir(exist_ok=True)
    document.yaml_metadata_dir.mkdir(exist_ok=True)

    md_content: List[str] = []
    all_yaml_metadata: List[Dict[str, Any]] = []
    total_figures = 0
    page_offset = 0
    chunks_success = 0
    chunks_missing_dir = 0
    chunks_missing_md = 0

    for chunk in chunks:
        chunk_result_dir = results_dir / chunk.name

        if not chunk_result_dir.exists():
            print(
                f"      ❌ Chunk {chunk.chunk_idx}/{chunk.total_chunks}: "
                f"目录不存在 - {chunk.name}"
            )
            chunks_missing_dir += 1
            continue

        chunk_md_files = list(chunk_result_dir.glob("*.md"))
        if not chunk_md_files:
            print(
                f"      ❌ Chunk {chunk.chunk_idx}/{chunk.total_chunks}: "
                f"MD文件缺失 - {chunk.name}"
            )
            chunks_missing_md += 1
            continue

        chunk_md = chunk_md_files[0]
        with open(chunk_md, "r", encoding="utf-8") as f:
            content = f.read()

        if len(content.strip()) < 100:
            print(
                f"      ⚠️  Chunk {chunk.chunk_idx}/{chunk.total_chunks}: "
                f"MD文件内容过少 ({len(content)} chars) - {chunk.name}"
            )

        content = Document.apply_page_offset(content, page_offset)
        md_content.append(content)
        chunks_success += 1

        # YAML metadata: shift page numbers, rename file
        chunk_yaml_dir = chunk_result_dir / "yaml_metadata"
        if chunk_yaml_dir.exists():
            for yaml_file in chunk_yaml_dir.glob("*.yaml"):
                with open(yaml_file, "r", encoding="utf-8") as f:
                    yaml_data = yaml.safe_load(f)

                new_page_num = None
                if (
                    "chart_identification" in yaml_data
                    and "page_number" in yaml_data["chart_identification"]
                ):
                    yaml_data["chart_identification"]["page_number"] += page_offset
                    new_page_num = yaml_data["chart_identification"]["page_number"]

                if "metadata" in yaml_data and "page_number" in yaml_data["metadata"]:
                    yaml_data["metadata"]["page_number"] += page_offset
                    if new_page_num is None:
                        new_page_num = yaml_data["metadata"]["page_number"]

                stem_clean = re.sub(r"_page\d+$", "", yaml_file.stem)
                new_yaml_name = f"{stem_clean}_page{new_page_num}.yaml"
                output_yaml_path = document.yaml_metadata_dir / new_yaml_name

                with open(output_yaml_path, "w", encoding="utf-8") as f:
                    yaml.dump(yaml_data, f, allow_unicode=True, sort_keys=False)

                all_yaml_metadata.append(yaml_data)
                total_figures += 1

        # Images: rename by offset
        chunk_images_dir = chunk_result_dir / "images"
        if chunk_images_dir.exists():
            for img_file in chunk_images_dir.glob("*.png"):
                match = re.search(r"page_(\d+)", img_file.name)
                if match:
                    page_num = int(match.group(1))
                    new_page_num = page_num + page_offset
                    new_img_name = f"page_{new_page_num:03d}.png"
                    shutil.copy2(img_file, document.images_dir / new_img_name)

        page_offset += chunk.pages
        print(
            f"      ✅ Chunk {chunk.chunk_idx}/{chunk.total_chunks}: "
            f"{chunk.pages} pages, page offset now {page_offset}"
        )

    chunks_failed = chunks_missing_dir + chunks_missing_md

    if chunks_success == 0:
        print(f"      ❌ 合并失败: 没有任何有效的chunk内容!")
        print(f"         - 目录缺失: {chunks_missing_dir}")
        print(f"         - MD文件缺失: {chunks_missing_md}")
        return {
            "original_pdf": document.pdf_path.name,
            "chunks_merged": 0,
            "chunks_failed": chunks_failed,
            "total_figures": 0,
            "total_pages": 0,
            "success": False,
        }

    with open(document.merged_md_path, "w", encoding="utf-8") as f:
        f.write(f"# {document.original_name}\n\n")
        f.write(f"*Merged from {chunks_success}/{len(chunks)} chunks*\n\n")
        f.write("---\n\n")
        f.write("\n\n".join(md_content))

    with open(document.yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(all_yaml_metadata, f, allow_unicode=True, sort_keys=False)

    if chunks_failed > 0:
        print(
            f"      ⚠️  Merged: {chunks_success}/{len(chunks)} chunks, "
            f"{total_figures} figures ({chunks_failed} chunks失败)"
        )
    else:
        print(
            f"      ✅ Merged: {chunks_success}/{len(chunks)} chunks, "
            f"{total_figures} figures, MD file created"
        )

    return {
        "original_pdf": document.pdf_path.name,
        "chunks_merged": chunks_success,
        "chunks_failed": chunks_failed,
        "total_figures": total_figures,
        "total_pages": page_offset,
        "success": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge chunk results")
    parser.add_argument("--mapping-file", required=True, help="Split mapping JSON file")
    parser.add_argument(
        "--results-dir", required=True, help="Directory containing chunk results"
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for merged results",
    )
    args = parser.parse_args()

    documents = [
        d
        for d in Document.discover(Path(args.mapping_file), Path(args.output_dir))
        if d.is_chunked
    ]

    print("=" * 80)
    print("🔗 Merging Split PDF Results")
    print("=" * 80)
    print(f"Total original PDFs: {len(documents)}")
    print(f"Total chunks: {sum(len(d.chunks) for d in documents)}")
    print()

    merge_stats: List[Dict[str, Any]] = []
    results_dir = Path(args.results_dir)
    for document in documents:
        try:
            result = merge_document(document, results_dir)
            merge_stats.append(result)
        except Exception as e:
            print(f"  ❌ Error merging {document.pdf_path.name}: {e}")
            import traceback

            traceback.print_exc()

    print()
    print("=" * 80)

    success_count = sum(1 for s in merge_stats if s.get("success", True))
    failed_count = len(merge_stats) - success_count
    total_chunks_merged = sum(s.get("chunks_merged", 0) for s in merge_stats)
    total_chunks_failed = sum(s.get("chunks_failed", 0) for s in merge_stats)
    total_figures = sum(s["total_figures"] for s in merge_stats)
    total_pages = sum(s["total_pages"] for s in merge_stats)

    if failed_count > 0 or total_chunks_failed > 0:
        print("⚠️  Merging Complete (with issues)")
        print("=" * 80)
        print(f"PDFs: {success_count} 成功, {failed_count} 失败")
        print(f"Chunks: {total_chunks_merged} 成功, {total_chunks_failed} 失败")
        print(f"Total figures: {total_figures}")
        print(f"Total pages: {total_pages}")
        print()
        print("❌ 失败的PDF:")
        for s in merge_stats:
            if not s.get("success", True) or s.get("chunks_failed", 0) > 0:
                print(
                    f"   - {s['original_pdf']}: {s.get('chunks_merged', 0)} chunks成功, "
                    f"{s.get('chunks_failed', 0)} chunks失败"
                )
    else:
        print("✅ Merging Complete")
        print("=" * 80)
        print(f"PDFs merged: {len(merge_stats)}")
        print(f"Total chunks: {total_chunks_merged}")
        print(f"Total figures: {total_figures}")
        print(f"Total pages: {total_pages}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
