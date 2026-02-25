#!/usr/bin/env python3
"""
进度管理器 - 支持断点续传
管理PDF处理的进度状态，支持中断后继续处理
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from filelock import FileLock
import threading

class ProgressManager:
    """进度管理器"""

    VERSION = "0.8"

    def __init__(self, progress_file: str = None, base_dir: str = None):
        """
        初始化进度管理器

        Args:
            progress_file: 进度文件路径，默认为 base_dir/progress.json
            base_dir: 基础目录，默认为脚本所在目录的父目录
        """
        if base_dir is None:
            base_dir = Path(__file__).parent.parent
        self.base_dir = Path(base_dir)

        if progress_file is None:
            self.progress_file = self.base_dir / "progress.json"
        else:
            self.progress_file = Path(progress_file)

        self.lock_file = str(self.progress_file) + ".lock"
        self._lock = threading.Lock()
        self._data = None

    def _get_file_lock(self):
        """获取文件锁"""
        return FileLock(self.lock_file, timeout=10)

    def load(self) -> Dict:
        """加载进度文件"""
        with self._lock:
            if self.progress_file.exists():
                try:
                    with self._get_file_lock():
                        with open(self.progress_file, 'r', encoding='utf-8') as f:
                            self._data = json.load(f)
                except (json.JSONDecodeError, Exception) as e:
                    print(f"⚠️  进度文件损坏，创建新文件: {e}")
                    self._data = self._create_new_progress()
            else:
                self._data = self._create_new_progress()
            return self._data

    def save(self):
        """保存进度文件"""
        with self._lock:
            if self._data is None:
                return

            self._data['updated_at'] = datetime.now().isoformat()

            with self._get_file_lock():
                # 先写入临时文件，再重命名（原子操作）
                temp_file = str(self.progress_file) + ".tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                os.replace(temp_file, self.progress_file)

    def _create_new_progress(self) -> Dict:
        """创建新的进度结构"""
        return {
            "version": self.VERSION,
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "initialized",
            "steps": {
                "split": {"status": "pending"},
                "process_chunks": {"status": "pending", "completed": [], "failed": [], "pending": []},
                "process_direct": {"status": "pending", "completed": [], "failed": [], "pending": []},
                "merge": {"status": "pending"}
            },
            "pdf_progress": {},
            "statistics": {
                "total_pdfs": 0,
                "completed_pdfs": 0,
                "total_pages": 0,
                "completed_pages": 0,
                "failed_pages": 0
            }
        }

    def reset(self):
        """重置进度（从头开始）"""
        self._data = self._create_new_progress()
        self.save()
        print("✅ 进度已重置")

    # ============ Step 管理 ============

    def get_step_status(self, step_name: str) -> str:
        """获取步骤状态"""
        if self._data is None:
            self.load()
        return self._data.get('steps', {}).get(step_name, {}).get('status', 'pending')

    def set_step_status(self, step_name: str, status: str):
        """设置步骤状态"""
        if self._data is None:
            self.load()

        if step_name not in self._data['steps']:
            self._data['steps'][step_name] = {}

        self._data['steps'][step_name]['status'] = status

        if status == 'completed':
            self._data['steps'][step_name]['completed_at'] = datetime.now().isoformat()
        elif status == 'in_progress':
            self._data['steps'][step_name]['started_at'] = datetime.now().isoformat()

        self.save()

    def is_step_completed(self, step_name: str) -> bool:
        """检查步骤是否已完成"""
        return self.get_step_status(step_name) == 'completed'

    # ============ PDF 级别管理 ============

    def get_pending_pdfs(self, step_name: str) -> List[str]:
        """获取待处理的PDF列表"""
        if self._data is None:
            self.load()
        return self._data.get('steps', {}).get(step_name, {}).get('pending', [])

    def get_completed_pdfs(self, step_name: str) -> List[str]:
        """获取已完成的PDF列表"""
        if self._data is None:
            self.load()
        return self._data.get('steps', {}).get(step_name, {}).get('completed', [])

    def get_failed_pdfs(self, step_name: str) -> List[str]:
        """获取失败的PDF列表"""
        if self._data is None:
            self.load()
        return self._data.get('steps', {}).get(step_name, {}).get('failed', [])

    def set_pdf_list(self, step_name: str, pending: List[str]):
        """设置待处理的PDF列表"""
        if self._data is None:
            self.load()

        if step_name not in self._data['steps']:
            self._data['steps'][step_name] = {}

        # 过滤掉已完成的
        completed = self._data['steps'][step_name].get('completed', [])
        pending = [p for p in pending if p not in completed]

        self._data['steps'][step_name]['pending'] = pending
        if 'completed' not in self._data['steps'][step_name]:
            self._data['steps'][step_name]['completed'] = []
        if 'failed' not in self._data['steps'][step_name]:
            self._data['steps'][step_name]['failed'] = []

        self.save()

    def mark_pdf_completed(self, step_name: str, pdf_name: str):
        """标记PDF为已完成"""
        if self._data is None:
            self.load()

        step = self._data['steps'].get(step_name, {})

        # 从pending和failed中移除
        if pdf_name in step.get('pending', []):
            step['pending'].remove(pdf_name)
        if pdf_name in step.get('failed', []):
            step['failed'].remove(pdf_name)

        # 添加到completed
        if pdf_name not in step.get('completed', []):
            if 'completed' not in step:
                step['completed'] = []
            step['completed'].append(pdf_name)

        self._data['steps'][step_name] = step
        self._data['statistics']['completed_pdfs'] = len(step.get('completed', []))
        self.save()

    def mark_pdf_failed(self, step_name: str, pdf_name: str, error: str = None):
        """标记PDF为失败"""
        if self._data is None:
            self.load()

        step = self._data['steps'].get(step_name, {})

        # 从pending中移除
        if pdf_name in step.get('pending', []):
            step['pending'].remove(pdf_name)

        # 添加到failed
        if pdf_name not in step.get('failed', []):
            if 'failed' not in step:
                step['failed'] = []
            step['failed'].append(pdf_name)

        # 记录错误信息
        if error:
            if 'errors' not in step:
                step['errors'] = {}
            step['errors'][pdf_name] = {
                'error': error,
                'timestamp': datetime.now().isoformat()
            }

        self._data['steps'][step_name] = step
        self.save()

    def is_pdf_completed(self, step_name: str, pdf_name: str) -> bool:
        """检查PDF是否已完成（仅检查列表）"""
        return pdf_name in self.get_completed_pdfs(step_name)

    def validate_pdf_completion(self, step_name: str, pdf_name: str, output_dir: str,
                                 min_content_size: int = 500,
                                 min_completion_rate: float = 0.90) -> dict:
        """
        验证PDF是否真正完成（检查实际输出）

        Args:
            step_name: 步骤名称
            pdf_name: PDF文件名（不含扩展名）
            output_dir: 输出目录路径
            min_content_size: MD文件最小内容大小（字节）
            min_completion_rate: 最小页面完成率（0.0-1.0）

        Returns:
            dict: {
                'valid': bool,           # 是否有效完成
                'reason': str,           # 原因说明
                'md_exists': bool,       # MD文件是否存在
                'md_size': int,          # MD文件大小
                'page_completion_rate': float,  # 页面完成率
                'should_reprocess': bool # 是否需要重新处理
            }
        """
        from pathlib import Path

        result = {
            'valid': False,
            'reason': '',
            'md_exists': False,
            'md_size': 0,
            'page_completion_rate': 0.0,
            'should_reprocess': False
        }

        # 检查是否在completed列表中
        if not self.is_pdf_completed(step_name, pdf_name):
            result['reason'] = '未在completed列表中'
            result['should_reprocess'] = True
            return result

        # 检查输出目录和MD文件
        output_path = Path(output_dir) / pdf_name
        md_files = list(output_path.glob("*.md")) if output_path.exists() else []

        if not md_files:
            result['reason'] = 'MD文件不存在'
            result['should_reprocess'] = True
            return result

        # 检查MD文件大小
        md_file = md_files[0]
        md_size = md_file.stat().st_size
        result['md_exists'] = True
        result['md_size'] = md_size

        if md_size < min_content_size:
            result['reason'] = f'MD文件过小 ({md_size} bytes < {min_content_size})'
            result['should_reprocess'] = True
            return result

        # 检查页面完成率
        if self._data is None:
            self.load()

        pdf_progress = self._data.get('pdf_progress', {}).get(pdf_name, {})
        total_pages = pdf_progress.get('total_pages', 0)
        completed_pages = len(pdf_progress.get('completed_pages', []))

        if total_pages > 0:
            completion_rate = completed_pages / total_pages
            result['page_completion_rate'] = completion_rate

            if completion_rate < min_completion_rate:
                result['reason'] = f'页面完成率不足 ({completion_rate:.1%} < {min_completion_rate:.0%})'
                result['should_reprocess'] = True
                return result

        # 所有检查通过
        result['valid'] = True
        result['reason'] = '验证通过'
        return result

    def invalidate_pdf_completion(self, step_name: str, pdf_name: str):
        """
        将PDF从completed移回pending（用于重新处理无效的"完成"状态）
        """
        if self._data is None:
            self.load()

        step = self._data['steps'].get(step_name, {})

        # 从completed中移除
        if pdf_name in step.get('completed', []):
            step['completed'].remove(pdf_name)
            print(f"   ⚠️  从completed移除: {pdf_name}")

        # 添加回pending
        if pdf_name not in step.get('pending', []):
            if 'pending' not in step:
                step['pending'] = []
            step['pending'].append(pdf_name)

        # 清除页面进度（允许重新处理）
        if pdf_name in self._data.get('pdf_progress', {}):
            old_progress = self._data['pdf_progress'][pdf_name]
            # 更新统计
            self._data['statistics']['completed_pages'] -= len(old_progress.get('completed_pages', []))
            self._data['statistics']['failed_pages'] -= len(old_progress.get('failed_pages', []))
            # 删除页面进度
            del self._data['pdf_progress'][pdf_name]

        self._data['steps'][step_name] = step
        self.save()

    # ============ 页面级别管理 ============

    def init_pdf_progress(self, pdf_name: str, total_pages: int):
        """初始化PDF的页面进度"""
        if self._data is None:
            self.load()

        if pdf_name not in self._data['pdf_progress']:
            self._data['pdf_progress'][pdf_name] = {
                'total_pages': total_pages,
                'completed_pages': [],
                'failed_pages': [],
                'started_at': datetime.now().isoformat()
            }
            self._data['statistics']['total_pages'] += total_pages
            self.save()

    def get_completed_pages(self, pdf_name: str) -> List[int]:
        """获取已完成的页面列表"""
        if self._data is None:
            self.load()
        return self._data.get('pdf_progress', {}).get(pdf_name, {}).get('completed_pages', [])

    def get_failed_pages(self, pdf_name: str) -> List[int]:
        """获取失败的页面列表"""
        if self._data is None:
            self.load()
        return self._data.get('pdf_progress', {}).get(pdf_name, {}).get('failed_pages', [])

    def mark_page_completed(self, pdf_name: str, page_num: int):
        """标记页面为已完成"""
        if self._data is None:
            self.load()

        if pdf_name not in self._data['pdf_progress']:
            self._data['pdf_progress'][pdf_name] = {
                'total_pages': 0,
                'completed_pages': [],
                'failed_pages': []
            }

        progress = self._data['pdf_progress'][pdf_name]

        # 从failed中移除
        if page_num in progress.get('failed_pages', []):
            progress['failed_pages'].remove(page_num)

        # 添加到completed
        if page_num not in progress.get('completed_pages', []):
            progress['completed_pages'].append(page_num)
            progress['completed_pages'].sort()
            self._data['statistics']['completed_pages'] += 1

        self.save()

    def mark_page_failed(self, pdf_name: str, page_num: int, error: str = None):
        """标记页面为失败"""
        if self._data is None:
            self.load()

        if pdf_name not in self._data['pdf_progress']:
            self._data['pdf_progress'][pdf_name] = {
                'total_pages': 0,
                'completed_pages': [],
                'failed_pages': []
            }

        progress = self._data['pdf_progress'][pdf_name]

        if page_num not in progress.get('failed_pages', []):
            progress['failed_pages'].append(page_num)
            progress['failed_pages'].sort()
            self._data['statistics']['failed_pages'] += 1

        if error:
            if 'page_errors' not in progress:
                progress['page_errors'] = {}
            progress['page_errors'][str(page_num)] = error

        self.save()

    def is_page_completed(self, pdf_name: str, page_num: int) -> bool:
        """检查页面是否已完成"""
        return page_num in self.get_completed_pages(pdf_name)

    def get_pdf_progress_percent(self, pdf_name: str) -> float:
        """获取PDF处理进度百分比"""
        if self._data is None:
            self.load()

        progress = self._data.get('pdf_progress', {}).get(pdf_name, {})
        total = progress.get('total_pages', 0)
        completed = len(progress.get('completed_pages', []))

        if total == 0:
            return 0.0
        return (completed / total) * 100

    # ============ 状态查询 ============

    def get_status_summary(self) -> Dict:
        """获取状态摘要"""
        if self._data is None:
            self.load()

        return {
            'status': self._data.get('status', 'unknown'),
            'started_at': self._data.get('started_at'),
            'updated_at': self._data.get('updated_at'),
            'steps': {
                name: {
                    'status': step.get('status', 'pending'),
                    'completed': len(step.get('completed', [])),
                    'pending': len(step.get('pending', [])),
                    'failed': len(step.get('failed', []))
                }
                for name, step in self._data.get('steps', {}).items()
            },
            'statistics': self._data.get('statistics', {})
        }

    def print_status(self):
        """打印状态报告"""
        summary = self.get_status_summary()

        print("\n" + "=" * 60)
        print("📊 DocMind 处理进度")
        print("=" * 60)
        print(f"状态: {summary['status']}")
        print(f"开始时间: {summary['started_at']}")
        print(f"更新时间: {summary['updated_at']}")
        print()

        print("步骤状态:")
        for step_name, step_info in summary['steps'].items():
            status_icon = {
                'completed': '✅',
                'in_progress': '🔄',
                'pending': '⏳',
                'failed': '❌'
            }.get(step_info['status'], '❓')

            print(f"  {status_icon} {step_name}: {step_info['status']}")
            if step_info['completed'] > 0 or step_info['pending'] > 0:
                print(f"      完成: {step_info['completed']}, 待处理: {step_info['pending']}, 失败: {step_info['failed']}")

        print()
        stats = summary['statistics']
        print("统计:")
        print(f"  PDF: {stats.get('completed_pdfs', 0)}/{stats.get('total_pdfs', 0)}")
        print(f"  页面: {stats.get('completed_pages', 0)}/{stats.get('total_pages', 0)} (失败: {stats.get('failed_pages', 0)})")

        if stats.get('total_pages', 0) > 0:
            progress = (stats.get('completed_pages', 0) / stats['total_pages']) * 100
            print(f"  总进度: {progress:.1f}%")

        print("=" * 60)

    def set_overall_status(self, status: str):
        """设置整体状态"""
        if self._data is None:
            self.load()
        self._data['status'] = status
        self.save()

    def is_all_completed(self) -> bool:
        """检查是否全部完成"""
        if self._data is None:
            self.load()

        for step_name, step in self._data.get('steps', {}).items():
            if step.get('status') != 'completed':
                return False
        return True


# 便捷函数
_default_manager = None

def get_progress_manager(progress_file: str = None, base_dir: str = None) -> ProgressManager:
    """获取进度管理器单例"""
    global _default_manager
    if _default_manager is None or progress_file is not None:
        _default_manager = ProgressManager(progress_file, base_dir)
    return _default_manager


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="进度管理器")
    parser.add_argument("--status", action="store_true", help="显示当前进度")
    parser.add_argument("--reset", action="store_true", help="重置进度")
    parser.add_argument("--progress-file", default=None, help="进度文件路径")

    args = parser.parse_args()

    manager = ProgressManager(args.progress_file)
    manager.load()

    if args.reset:
        manager.reset()
    elif args.status:
        manager.print_status()
    else:
        manager.print_status()
