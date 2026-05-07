#!/usr/bin/env python3
"""
归档 progress.json 并清理旧进度

用法:
    python3 archive_progress.py                    # 归档并清理
    python3 archive_progress.py --keep            # 只归档，保留原文件
    python3 archive_progress.py --list            # 列出历史记录
"""

import os
import sys
import json
import shutil
import argparse
from datetime import datetime
from pathlib import Path


def get_task_info(progress_file: Path) -> dict:
    """从 progress.json 提取任务信息"""
    try:
        with open(progress_file) as f:
            data = json.load(f)

        return {
            "started_at": data.get("started_at", ""),
            "completed_at": data.get("completed_at", ""),
            "status": data.get("status", "unknown"),
            "pdfs": len(data.get("pdfs", {})),
            "total_pages": sum(
                pdf.get("total_pages", 0)
                for pdf in data.get("pdfs", {}).values()
            ),
            "completed_pages": sum(
                pdf.get("processed_pages", 0)
                for pdf in data.get("pdfs", {}).values()
            ),
        }
    except Exception as e:
        return {"error": str(e)}


def archive_progress(base_dir: Path, task_name: str = "", keep: bool = False) -> str:
    """归档 progress.json"""
    progress_file = base_dir / "progress.json"
    history_dir = base_dir / "history"

    if not progress_file.exists():
        print("没有找到 progress.json")
        return ""

    history_dir.mkdir(exist_ok=True)

    # 获取任务信息
    info = get_task_info(progress_file)

    # 生成时间戳
    if info.get("started_at"):
        timestamp = info["started_at"][:19].replace(":", "").replace("-", "").replace("T", "_")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 生成归档文件名
    if not task_name:
        task_name = f"task_{info.get('pdfs', 0)}pdfs"

    archive_name = f"progress_{timestamp}_{task_name}.json"
    archive_path = history_dir / archive_name

    # 添加归档元数据
    try:
        with open(progress_file) as f:
            data = json.load(f)

        data["_archive_info"] = {
            "archived_at": datetime.now().isoformat(),
            "task_name": task_name,
            "summary": info,
        }

        with open(archive_path, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"已归档: {archive_path.name}")
        print(f"  状态: {info.get('status', 'unknown')}")
        print(f"  PDF数: {info.get('pdfs', 0)}")
        print(f"  页数: {info.get('completed_pages', 0)}/{info.get('total_pages', 0)}")

        # 删除原文件
        if not keep:
            progress_file.unlink()
            lock_file = base_dir / "progress.json.lock"
            if lock_file.exists():
                lock_file.unlink()
            print("已清理原 progress.json")

        return str(archive_path)

    except Exception as e:
        print(f"归档失败: {e}")
        return ""


def list_history(base_dir: Path):
    """列出历史记录"""
    history_dir = base_dir / "history"

    if not history_dir.exists():
        print("没有历史记录")
        return

    archives = sorted(history_dir.glob("progress_*.json"), reverse=True)

    if not archives:
        print("没有历史记录")
        return

    print(f"\n{'='*70}")
    print(f"{'历史记录':^70}")
    print(f"{'='*70}")
    print(f"{'文件名':<40} {'状态':<10} {'PDF数':<8} {'页数':<10}")
    print(f"{'-'*70}")

    for archive in archives[:20]:  # 只显示最近 20 条
        try:
            with open(archive) as f:
                data = json.load(f)

            info = data.get("_archive_info", {}).get("summary", {})
            status = info.get("status", "?")
            pdfs = info.get("pdfs", "?")
            pages = f"{info.get('completed_pages', '?')}/{info.get('total_pages', '?')}"

            print(f"{archive.name:<40} {status:<10} {pdfs:<8} {pages:<10}")
        except Exception:
            print(f"{archive.name:<40} {'读取失败':<10}")

    print(f"\n共 {len(archives)} 条记录")


def main():
    parser = argparse.ArgumentParser(description="管理 progress.json 历史")
    parser.add_argument("--base-dir", "-d",
                       default=str(Path(__file__).parent.parent.parent),
                       help="DocMind 根目录")
    parser.add_argument("--task-name", "-t", default="",
                       help="任务名称 (用于归档文件名)")
    parser.add_argument("--keep", "-k", action="store_true",
                       help="归档后保留原文件")
    parser.add_argument("--list", "-l", action="store_true",
                       help="列出历史记录")

    args = parser.parse_args()
    base_dir = Path(args.base_dir)

    if args.list:
        list_history(base_dir)
    else:
        archive_progress(base_dir, args.task_name, args.keep)


if __name__ == "__main__":
    main()
