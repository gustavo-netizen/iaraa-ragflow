#!/usr/bin/env python3
"""
DocMind Monitor Daemon - 后台资源监控脚本
自动收集系统资源、处理进度、API 性能等数据

用法:
    python3 monitor_daemon.py --task-name "lenin_21-30" &

停止:
    kill $(cat /tmp/docmind_monitor.pid)
"""

import os
import sys
import json
import time
import signal
import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import re

class DocMindMonitor:
    def __init__(self, task_name: str, base_dir: str, interval: int = 30):
        self.task_name = task_name
        self.base_dir = Path(base_dir)
        self.interval = interval
        self.running = True

        # 目录设置
        self.monitor_dir = self.base_dir / "monitor"
        self.history_dir = self.base_dir / "history"
        self.output_dir = self.base_dir / "output" / "chunks"
        self.progress_file = self.base_dir / "progress.json"
        self.logs_dir = self.base_dir / "logs"

        # 创建目录
        self.monitor_dir.mkdir(exist_ok=True)
        self.history_dir.mkdir(exist_ok=True)

        # 时间戳
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 日志文件
        self.metrics_file = self.monitor_dir / f"{task_name}_{self.timestamp}_metrics.jsonl"
        self.summary_file = self.monitor_dir / f"{task_name}_{self.timestamp}_summary.json"

        # 统计数据
        self.stats = {
            "task_name": task_name,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "config": self._get_config(),
            "metrics": {
                "cpu_max": 0,
                "cpu_avg": 0,
                "mem_max": 0,
                "mem_avg": 0,
                "disk_write_mb": 0,
            },
            "progress": {
                "total_chunks": 0,
                "completed_chunks": 0,
                "total_pages": 0,
                "completed_pages": 0,
                "failed_pages": 0,
            },
            "api": {
                "total_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "avg_response_time": 0,
            },
            "samples": []
        }

        # 注册信号处理
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # 写入 PID
        pid_file = Path("/tmp/docmind_monitor.pid")
        pid_file.write_text(str(os.getpid()))

    def _get_config(self) -> Dict[str, Any]:
        """读取当前配置"""
        config = {
            "semaphore": 30,
            "llm_concurrent": 10,
            "max_pages": 50,
            "api_keys": 0,
        }

        # 从 .env 读取
        env_file = self.base_dir / ".env"
        if env_file.exists():
            content = env_file.read_text()
            for line in content.split('\n'):
                if line.startswith('SEMAPHORE='):
                    config["semaphore"] = int(line.split('=')[1])
                elif line.startswith('LLM_CONCURRENT='):
                    config["llm_concurrent"] = int(line.split('=')[1])
                elif line.startswith('MAX_PAGES='):
                    config["max_pages"] = int(line.split('=')[1])
                elif line.startswith('DASHSCOPE_API_KEY_'):
                    config["api_keys"] += 1

        # 从环境变量统计 API key 数量
        for i in range(1, 9):
            if os.environ.get(f"DASHSCOPE_API_KEY_{i}"):
                config["api_keys"] += 1
        if os.environ.get("DASHSCOPE_API_KEY") and config["api_keys"] == 0:
            config["api_keys"] = 1

        return config

    def _handle_signal(self, signum, frame):
        """处理退出信号"""
        print(f"\n收到信号 {signum}，正在保存数据...")
        self.running = False

    def _get_cpu_memory(self) -> Dict[str, float]:
        """获取 CPU 和内存使用率 (macOS)"""
        result = {"cpu": 0.0, "memory": 0.0, "memory_gb": 0.0}

        try:
            # CPU - 使用 ps 获取 Python 进程
            ps_output = subprocess.run(
                ["ps", "-A", "-o", "%cpu,comm"],
                capture_output=True, text=True, timeout=5
            )
            cpu_total = 0.0
            for line in ps_output.stdout.split('\n'):
                if 'python' in line.lower() or 'docmind' in line.lower():
                    try:
                        cpu_total += float(line.split()[0])
                    except (ValueError, IndexError):
                        pass
            result["cpu"] = min(cpu_total, 100.0)

            # Memory - 使用 vm_stat
            vm_output = subprocess.run(
                ["vm_stat"],
                capture_output=True, text=True, timeout=5
            )

            page_size = 16384  # macOS default
            pages_free = 0
            pages_active = 0
            pages_inactive = 0
            pages_wired = 0

            for line in vm_output.stdout.split('\n'):
                if 'page size' in line.lower():
                    match = re.search(r'(\d+)', line)
                    if match:
                        page_size = int(match.group(1))
                elif 'Pages free:' in line:
                    pages_free = int(line.split(':')[1].strip().rstrip('.'))
                elif 'Pages active:' in line:
                    pages_active = int(line.split(':')[1].strip().rstrip('.'))
                elif 'Pages inactive:' in line:
                    pages_inactive = int(line.split(':')[1].strip().rstrip('.'))
                elif 'Pages wired down:' in line:
                    pages_wired = int(line.split(':')[1].strip().rstrip('.'))

            total_pages = pages_free + pages_active + pages_inactive + pages_wired
            used_pages = pages_active + pages_wired

            if total_pages > 0:
                result["memory"] = (used_pages / total_pages) * 100
                result["memory_gb"] = (used_pages * page_size) / (1024**3)

        except Exception as e:
            print(f"获取系统资源失败: {e}")

        return result

    def _get_progress(self) -> Dict[str, int]:
        """获取处理进度"""
        progress = {
            "md_files": 0,
            "png_files": 0,
            "yaml_files": 0,
            "dirs": 0,
        }

        try:
            if self.output_dir.exists():
                progress["md_files"] = len(list(self.output_dir.glob("**/*.md")))
                progress["png_files"] = len(list(self.output_dir.glob("**/*.png")))
                progress["yaml_files"] = len(list(self.output_dir.glob("**/*.yaml")))
                progress["dirs"] = len([d for d in self.output_dir.iterdir() if d.is_dir()])
        except Exception as e:
            print(f"获取进度失败: {e}")

        return progress

    def _get_token_stats(self) -> Dict[str, int]:
        """从日志中提取 token 使用统计"""
        stats = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

        log_file = self.logs_dir / "chunks_processing.log"
        if not log_file.exists():
            return stats

        try:
            content = log_file.read_text()
            # 匹配格式: 1342+635 tokens
            matches = re.findall(r'(\d+)\+(\d+) tokens', content)
            for input_t, output_t in matches:
                stats["input_tokens"] += int(input_t)
                stats["output_tokens"] += int(output_t)
                stats["calls"] += 1
        except Exception as e:
            print(f"读取 token 统计失败: {e}")

        return stats

    def _get_api_response_times(self) -> float:
        """从日志中计算平均 API 响应时间"""
        log_file = self.logs_dir / "chunks_processing.log"
        if not log_file.exists():
            return 0.0

        try:
            content = log_file.read_text()
            # 匹配格式: (3.2s) 或 耗时: 3.2s
            times = re.findall(r'[\(耗时:\s](\d+\.?\d*)s[\)]?', content)
            if times:
                return sum(float(t) for t in times) / len(times)
        except Exception:
            pass

        return 0.0

    def collect_sample(self) -> Dict[str, Any]:
        """收集一次采样数据"""
        resources = self._get_cpu_memory()
        progress = self._get_progress()
        tokens = self._get_token_stats()

        sample = {
            "timestamp": datetime.now().isoformat(),
            "cpu_percent": round(resources["cpu"], 2),
            "memory_percent": round(resources["memory"], 2),
            "memory_gb": round(resources["memory_gb"], 2),
            "md_files": progress["md_files"],
            "png_files": progress["png_files"],
            "dirs": progress["dirs"],
            "input_tokens": tokens["input_tokens"],
            "output_tokens": tokens["output_tokens"],
            "api_calls": tokens["calls"],
        }

        # 更新最大值
        self.stats["metrics"]["cpu_max"] = max(
            self.stats["metrics"]["cpu_max"],
            sample["cpu_percent"]
        )
        self.stats["metrics"]["mem_max"] = max(
            self.stats["metrics"]["mem_max"],
            sample["memory_percent"]
        )

        # 保存样本
        self.stats["samples"].append({
            "time": sample["timestamp"],
            "cpu": sample["cpu_percent"],
            "mem": sample["memory_percent"],
            "pages": sample["png_files"],
        })

        return sample

    def write_sample(self, sample: Dict[str, Any]):
        """写入采样数据到 JSONL"""
        with open(self.metrics_file, 'a') as f:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')

    def calculate_summary(self):
        """计算汇总统计"""
        self.stats["end_time"] = datetime.now().isoformat()

        # 计算平均值
        if self.stats["samples"]:
            cpu_values = [s["cpu"] for s in self.stats["samples"]]
            mem_values = [s["mem"] for s in self.stats["samples"]]
            self.stats["metrics"]["cpu_avg"] = round(sum(cpu_values) / len(cpu_values), 2)
            self.stats["metrics"]["mem_avg"] = round(sum(mem_values) / len(mem_values), 2)

        # Token 统计
        tokens = self._get_token_stats()
        self.stats["api"]["input_tokens"] = tokens["input_tokens"]
        self.stats["api"]["output_tokens"] = tokens["output_tokens"]
        self.stats["api"]["total_calls"] = tokens["calls"]
        self.stats["api"]["avg_response_time"] = round(self._get_api_response_times(), 2)

        # 进度统计
        progress = self._get_progress()
        self.stats["progress"]["completed_chunks"] = progress["dirs"]
        self.stats["progress"]["completed_pages"] = progress["png_files"]

        # 计算耗时和吞吐量
        start = datetime.fromisoformat(self.stats["start_time"])
        end = datetime.fromisoformat(self.stats["end_time"])
        duration_sec = (end - start).total_seconds()
        duration_min = duration_sec / 60

        self.stats["duration"] = {
            "seconds": int(duration_sec),
            "minutes": round(duration_min, 1),
            "formatted": f"{int(duration_min)}m {int(duration_sec % 60)}s"
        }

        if duration_min > 0 and progress["png_files"] > 0:
            self.stats["throughput"] = {
                "pages_per_minute": round(progress["png_files"] / duration_min, 1),
                "pages_per_second": round(progress["png_files"] / duration_sec, 2),
            }

        # 费用估算 (阿里云 qwen-vl-max: ¥0.02/1000 tokens)
        total_tokens = tokens["input_tokens"] + tokens["output_tokens"]
        self.stats["cost"] = {
            "total_tokens": total_tokens,
            "estimated_rmb": round(total_tokens * 0.00002, 2),
        }

        # 只保留最近 100 个样本用于图表
        if len(self.stats["samples"]) > 100:
            step = len(self.stats["samples"]) // 100
            self.stats["samples"] = self.stats["samples"][::step][:100]

    def save_summary(self):
        """保存汇总报告"""
        self.calculate_summary()

        with open(self.summary_file, 'w') as f:
            json.dump(self.stats, f, indent=2, ensure_ascii=False)

        print(f"\n{'='*60}")
        print(f"监控完成 - {self.task_name}")
        print(f"{'='*60}")
        print(f"耗时: {self.stats['duration']['formatted']}")
        print(f"CPU 最大: {self.stats['metrics']['cpu_max']}%")
        print(f"内存最大: {self.stats['metrics']['mem_max']}%")
        print(f"处理页数: {self.stats['progress']['completed_pages']}")
        if 'throughput' in self.stats:
            print(f"吞吐量: {self.stats['throughput']['pages_per_minute']} 页/分钟")
        print(f"Token 消耗: {self.stats['api']['input_tokens'] + self.stats['api']['output_tokens']:,}")
        print(f"预估费用: ¥{self.stats['cost']['estimated_rmb']}")
        print(f"\n详细报告: {self.summary_file}")
        print(f"采样数据: {self.metrics_file}")

    def is_task_running(self) -> bool:
        """检查 DocMind 任务是否在运行"""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "docmind_converter.py"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def run(self):
        """主循环"""
        print(f"DocMind 监控已启动")
        print(f"任务: {self.task_name}")
        print(f"采样间隔: {self.interval}秒")
        print(f"日志文件: {self.metrics_file}")
        print(f"按 Ctrl+C 停止监控\n")

        sample_count = 0

        while self.running:
            # 检查任务是否还在运行
            if not self.is_task_running():
                print("\n检测到 DocMind 任务已结束")
                break

            # 收集并写入样本
            sample = self.collect_sample()
            self.write_sample(sample)
            sample_count += 1

            # 打印状态
            print(f"[{sample['timestamp'][11:19]}] "
                  f"CPU: {sample['cpu_percent']:5.1f}% | "
                  f"MEM: {sample['memory_percent']:5.1f}% ({sample['memory_gb']:.1f}GB) | "
                  f"Pages: {sample['png_files']} | "
                  f"Tokens: {sample['input_tokens']+sample['output_tokens']:,}")

            # 等待下一次采样
            time.sleep(self.interval)

        # 保存汇总
        self.save_summary()

        # 清理 PID 文件
        pid_file = Path("/tmp/docmind_monitor.pid")
        if pid_file.exists():
            pid_file.unlink()


def archive_progress(base_dir: str, task_name: str) -> Optional[str]:
    """归档旧的 progress.json"""
    base = Path(base_dir)
    progress_file = base / "progress.json"
    history_dir = base / "history"

    if not progress_file.exists():
        return None

    history_dir.mkdir(exist_ok=True)

    # 读取旧进度获取时间戳
    try:
        with open(progress_file) as f:
            old_progress = json.load(f)

        # 使用开始时间作为归档名
        start_time = old_progress.get("started_at", "")
        if start_time:
            timestamp = start_time[:19].replace(":", "").replace("-", "").replace("T", "_")
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 归档文件名
        archive_name = f"progress_{timestamp}_{task_name}.json"
        archive_path = history_dir / archive_name

        # 复制到归档
        import shutil
        shutil.copy(progress_file, archive_path)

        print(f"已归档旧进度: {archive_path}")
        return str(archive_path)

    except Exception as e:
        print(f"归档失败: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="DocMind 后台监控")
    parser.add_argument("--task-name", "-t", required=True, help="任务名称")
    parser.add_argument("--base-dir", "-d",
                       default=str(Path(__file__).parent.parent),
                       help="DocMind 根目录")
    parser.add_argument("--interval", "-i", type=int, default=30,
                       help="采样间隔(秒)")
    parser.add_argument("--archive-progress", "-a", action="store_true",
                       help="开始前归档旧的 progress.json")

    args = parser.parse_args()

    # 归档旧进度
    if args.archive_progress:
        archive_progress(args.base_dir, args.task_name)

    # 启动监控
    monitor = DocMindMonitor(
        task_name=args.task_name,
        base_dir=args.base_dir,
        interval=args.interval
    )
    monitor.run()


if __name__ == "__main__":
    main()
