#!/usr/bin/env python3
"""
Resource Monitor Module for DocMind 0.8

实时监控本地机器资源消耗:
- CPU 使用率
- 内存占用
- 磁盘 I/O
- 网络 I/O
- 进程信息

Author: DocMind Team
Date: 2024-12-03
"""

import psutil
import threading
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field


@dataclass
class ResourceSnapshot:
    """资源快照"""
    timestamp: str

    # CPU
    cpu_percent: float
    cpu_per_core: List[float] = field(default_factory=list)

    # Memory
    memory_total_gb: float = 0.0
    memory_used_gb: float = 0.0
    memory_percent: float = 0.0
    process_memory_mb: float = 0.0

    # Disk
    disk_read_mb_s: float = 0.0
    disk_write_mb_s: float = 0.0
    disk_usage_percent: float = 0.0

    # Network
    net_sent_kb_s: float = 0.0
    net_recv_kb_s: float = 0.0

    # Process
    num_threads: int = 0
    num_open_files: int = 0
    num_children: int = 0


class ResourceMonitor:
    """
    资源监控器

    使用方法:
        monitor = ResourceMonitor(interval=5.0)
        monitor.start()

        # ... 处理逻辑 ...

        summary = monitor.stop()
        print(summary)
    """

    def __init__(
        self,
        interval: float = 5.0,
        log_dir: Path = None,
        enable_logging: bool = True,
        enable_realtime_print: bool = False,
        thresholds: Dict = None
    ):
        """
        初始化资源监控器

        Args:
            interval: 采样间隔（秒），默认5秒
            log_dir: 日志目录
            enable_logging: 是否保存日志文件
            enable_realtime_print: 是否实时打印资源状态
            thresholds: 告警阈值配置
        """
        self.interval = interval
        self.log_dir = Path(log_dir) if log_dir else Path("logs")
        self.enable_logging = enable_logging
        self.enable_realtime_print = enable_realtime_print

        # 告警阈值
        self.thresholds = thresholds or {
            "cpu_warning": 80,
            "cpu_critical": 95,
            "memory_warning": 80,
            "memory_critical": 95,
            "disk_warning": 90
        }

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._snapshots: List[ResourceSnapshot] = []
        self._process = psutil.Process()
        self._start_time: Optional[datetime] = None

        # 用于计算速率的上一次采样值
        self._last_disk_io = None
        self._last_net_io = None
        self._last_sample_time = None

        # 峰值记录
        self.peak_cpu = 0.0
        self.peak_memory_mb = 0.0
        self.peak_memory_percent = 0.0

        # 告警计数
        self._warnings = []

    def start(self):
        """启动后台监控线程"""
        if self._running:
            return

        self._running = True
        self._start_time = datetime.now()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        print(f"📊 资源监控已启动 (采样间隔: {self.interval}s)")

    def stop(self) -> Dict:
        """停止监控并返回摘要"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

        summary = self.get_summary()

        if self.enable_logging and self._snapshots:
            self._save_logs()

        print(f"📊 资源监控已停止 (共采样 {len(self._snapshots)} 次)")

        return summary

    def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                snapshot = self._take_snapshot()
                self._snapshots.append(snapshot)
                self._update_peaks(snapshot)
                self._check_thresholds(snapshot)

                if self.enable_realtime_print:
                    self._print_realtime(snapshot)

            except Exception as e:
                # 静默处理错误，不中断监控
                pass

            time.sleep(self.interval)

    def _take_snapshot(self) -> ResourceSnapshot:
        """采集一次资源快照"""
        now = time.time()

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        try:
            cpu_per_core = psutil.cpu_percent(percpu=True)
        except:
            cpu_per_core = []

        # Memory
        mem = psutil.virtual_memory()
        try:
            proc_mem = self._process.memory_info()
            process_memory_mb = proc_mem.rss / 1024**2
        except:
            process_memory_mb = 0

        # Disk I/O (计算速率)
        disk_read_mb_s = 0.0
        disk_write_mb_s = 0.0

        try:
            disk_io = psutil.disk_io_counters()
            if self._last_disk_io and self._last_sample_time:
                dt = now - self._last_sample_time
                if dt > 0:
                    disk_read_mb_s = (disk_io.read_bytes - self._last_disk_io.read_bytes) / dt / 1024 / 1024
                    disk_write_mb_s = (disk_io.write_bytes - self._last_disk_io.write_bytes) / dt / 1024 / 1024
            self._last_disk_io = disk_io
        except:
            pass

        # Network I/O (计算速率)
        net_sent_kb_s = 0.0
        net_recv_kb_s = 0.0

        try:
            net_io = psutil.net_io_counters()
            if self._last_net_io and self._last_sample_time:
                dt = now - self._last_sample_time
                if dt > 0:
                    net_sent_kb_s = (net_io.bytes_sent - self._last_net_io.bytes_sent) / dt / 1024
                    net_recv_kb_s = (net_io.bytes_recv - self._last_net_io.bytes_recv) / dt / 1024
            self._last_net_io = net_io
        except:
            pass

        self._last_sample_time = now

        # Disk usage
        try:
            disk_usage = psutil.disk_usage('/')
            disk_usage_percent = disk_usage.percent
        except:
            disk_usage_percent = 0

        # Process info
        try:
            num_threads = self._process.num_threads()
        except:
            num_threads = 0

        try:
            num_open_files = len(self._process.open_files())
        except:
            num_open_files = 0

        try:
            num_children = len(self._process.children(recursive=True))
        except:
            num_children = 0

        return ResourceSnapshot(
            timestamp=datetime.now().isoformat(),
            cpu_percent=cpu_percent,
            cpu_per_core=cpu_per_core,
            memory_total_gb=mem.total / 1024**3,
            memory_used_gb=mem.used / 1024**3,
            memory_percent=mem.percent,
            process_memory_mb=process_memory_mb,
            disk_read_mb_s=round(disk_read_mb_s, 2),
            disk_write_mb_s=round(disk_write_mb_s, 2),
            disk_usage_percent=disk_usage_percent,
            net_sent_kb_s=round(net_sent_kb_s, 2),
            net_recv_kb_s=round(net_recv_kb_s, 2),
            num_threads=num_threads,
            num_open_files=num_open_files,
            num_children=num_children
        )

    def _update_peaks(self, snapshot: ResourceSnapshot):
        """更新峰值记录"""
        self.peak_cpu = max(self.peak_cpu, snapshot.cpu_percent)
        self.peak_memory_mb = max(self.peak_memory_mb, snapshot.process_memory_mb)
        self.peak_memory_percent = max(self.peak_memory_percent, snapshot.memory_percent)

    def _check_thresholds(self, snapshot: ResourceSnapshot):
        """检查告警阈值"""
        if snapshot.cpu_percent > self.thresholds.get("cpu_critical", 95):
            self._warnings.append(f"[{snapshot.timestamp}] ⚠️ CPU 严重: {snapshot.cpu_percent:.1f}%")
        elif snapshot.cpu_percent > self.thresholds.get("cpu_warning", 80):
            self._warnings.append(f"[{snapshot.timestamp}] ⚡ CPU 警告: {snapshot.cpu_percent:.1f}%")

        if snapshot.memory_percent > self.thresholds.get("memory_critical", 95):
            self._warnings.append(f"[{snapshot.timestamp}] ⚠️ 内存严重: {snapshot.memory_percent:.1f}%")
        elif snapshot.memory_percent > self.thresholds.get("memory_warning", 80):
            self._warnings.append(f"[{snapshot.timestamp}] ⚡ 内存警告: {snapshot.memory_percent:.1f}%")

    def _print_realtime(self, snapshot: ResourceSnapshot):
        """打印实时状态"""
        print(f"[{snapshot.timestamp[11:19]}] 📊 "
              f"CPU: {snapshot.cpu_percent:5.1f}% | "
              f"Mem: {snapshot.process_memory_mb:.0f}MB ({snapshot.memory_percent:.1f}%) | "
              f"Disk: R{snapshot.disk_read_mb_s:.1f}/W{snapshot.disk_write_mb_s:.1f} MB/s | "
              f"Net: ↑{snapshot.net_sent_kb_s:.1f}/↓{snapshot.net_recv_kb_s:.1f} KB/s")

    def get_summary(self) -> Dict:
        """生成资源使用摘要"""
        if not self._snapshots:
            return {"error": "No data collected"}

        # 计算平均值
        n = len(self._snapshots)
        avg_cpu = sum(s.cpu_percent for s in self._snapshots) / n
        avg_mem = sum(s.process_memory_mb for s in self._snapshots) / n
        avg_mem_percent = sum(s.memory_percent for s in self._snapshots) / n
        avg_disk_read = sum(s.disk_read_mb_s for s in self._snapshots) / n
        avg_disk_write = sum(s.disk_write_mb_s for s in self._snapshots) / n
        avg_net_sent = sum(s.net_sent_kb_s for s in self._snapshots) / n
        avg_net_recv = sum(s.net_recv_kb_s for s in self._snapshots) / n

        # 计算监控时长
        duration_sec = 0
        if self._start_time:
            duration_sec = (datetime.now() - self._start_time).total_seconds()

        return {
            "monitoring": {
                "sample_count": n,
                "sample_interval_sec": self.interval,
                "duration_sec": round(duration_sec, 1),
                "duration_formatted": self._format_duration(duration_sec)
            },
            "cpu": {
                "average_percent": round(avg_cpu, 1),
                "peak_percent": round(self.peak_cpu, 1),
                "core_count": psutil.cpu_count()
            },
            "memory": {
                "average_process_mb": round(avg_mem, 1),
                "peak_process_mb": round(self.peak_memory_mb, 1),
                "average_system_percent": round(avg_mem_percent, 1),
                "peak_system_percent": round(self.peak_memory_percent, 1),
                "total_system_gb": round(self._snapshots[-1].memory_total_gb, 1)
            },
            "disk_io": {
                "average_read_mb_s": round(avg_disk_read, 2),
                "average_write_mb_s": round(avg_disk_write, 2),
                "usage_percent": round(self._snapshots[-1].disk_usage_percent, 1)
            },
            "network_io": {
                "average_sent_kb_s": round(avg_net_sent, 2),
                "average_recv_kb_s": round(avg_net_recv, 2)
            },
            "warnings": self._warnings[-10:] if self._warnings else []  # 最近10条告警
        }

    def _format_duration(self, seconds: float) -> str:
        """格式化时长"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    def _save_logs(self):
        """保存详细日志"""
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 保存详细快照
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = self.log_dir / f"resource_monitor_{timestamp}.json"

        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump({
                "summary": self.get_summary(),
                "snapshots": [asdict(s) for s in self._snapshots]
            }, f, indent=2, ensure_ascii=False)

        print(f"📊 资源日志已保存: {log_file}")

        return log_file

    def get_current(self) -> ResourceSnapshot:
        """获取当前资源状态（不记录到历史）"""
        return self._take_snapshot()

    def print_status(self):
        """打印当前资源状态"""
        s = self.get_current()
        print(f"""
┌─────────────────────────────────────┐
│         Resource Status             │
├─────────────────────────────────────┤
│ CPU:    {s.cpu_percent:5.1f}% (peak: {self.peak_cpu:.1f}%)     │
│ Memory: {s.process_memory_mb:5.0f} MB ({s.memory_percent:.1f}% sys)  │
│ Disk:   R {s.disk_read_mb_s:5.1f} / W {s.disk_write_mb_s:5.1f} MB/s │
│ Net:    ↑ {s.net_sent_kb_s:5.1f} / ↓ {s.net_recv_kb_s:5.1f} KB/s │
│ Procs:  {s.num_children:3d} children, {s.num_threads:3d} threads  │
└─────────────────────────────────────┘
""")

    def format_summary_text(self) -> str:
        """生成格式化的摘要文本"""
        summary = self.get_summary()
        if "error" in summary:
            return "资源监控: 无数据\n"

        return f"""
================================================================================
📊 资源使用摘要
================================================================================
采样次数: {summary['monitoring']['sample_count']} (间隔: {summary['monitoring']['sample_interval_sec']}s)
监控时长: {summary['monitoring']['duration_formatted']}

CPU:
  平均使用率: {summary['cpu']['average_percent']}%
  峰值使用率: {summary['cpu']['peak_percent']}%
  核心数: {summary['cpu']['core_count']}

内存:
  平均进程占用: {summary['memory']['average_process_mb']:.0f} MB
  峰值进程占用: {summary['memory']['peak_process_mb']:.0f} MB
  系统平均使用: {summary['memory']['average_system_percent']}%
  系统峰值使用: {summary['memory']['peak_system_percent']}%
  系统总内存: {summary['memory']['total_system_gb']} GB

磁盘 I/O:
  平均读取: {summary['disk_io']['average_read_mb_s']} MB/s
  平均写入: {summary['disk_io']['average_write_mb_s']} MB/s
  磁盘使用率: {summary['disk_io']['usage_percent']}%

网络 I/O:
  平均上传: {summary['network_io']['average_sent_kb_s']} KB/s
  平均下载: {summary['network_io']['average_recv_kb_s']} KB/s

告警记录: {len(summary['warnings'])} 条
================================================================================
"""


def format_resource_for_report(resource_data: Dict) -> str:
    """
    格式化资源数据用于质量报告

    Args:
        resource_data: get_summary() 返回的数据

    Returns:
        Markdown 格式的资源使用部分
    """
    if not resource_data or "error" in resource_data:
        return "## 资源使用统计\n\n资源监控: 未启用或无数据\n"

    return f"""## 资源使用统计

**监控时长**: {resource_data['monitoring']['duration_formatted']} ({resource_data['monitoring']['sample_count']} 次采样)

| 指标 | 平均值 | 峰值 |
|------|--------|------|
| CPU 使用率 | {resource_data['cpu']['average_percent']}% | {resource_data['cpu']['peak_percent']}% |
| 进程内存 | {resource_data['memory']['average_process_mb']:.0f} MB | {resource_data['memory']['peak_process_mb']:.0f} MB |
| 系统内存 | {resource_data['memory']['average_system_percent']}% | {resource_data['memory']['peak_system_percent']}% |
| 磁盘读取 | {resource_data['disk_io']['average_read_mb_s']} MB/s | - |
| 磁盘写入 | {resource_data['disk_io']['average_write_mb_s']} MB/s | - |
| 网络上传 | {resource_data['network_io']['average_sent_kb_s']} KB/s | - |
| 网络下载 | {resource_data['network_io']['average_recv_kb_s']} KB/s | - |

**系统配置**: {resource_data['cpu']['core_count']} CPU 核心, {resource_data['memory']['total_system_gb']} GB 内存
"""


# 测试代码
if __name__ == "__main__":
    print("测试资源监控模块...")

    monitor = ResourceMonitor(
        interval=2.0,
        enable_realtime_print=True,
        log_dir=Path("logs")
    )

    monitor.start()

    # 模拟一些工作负载
    print("\n模拟10秒工作负载...\n")
    time.sleep(10)

    summary = monitor.stop()

    print("\n" + monitor.format_summary_text())

    print("\n质量报告格式:")
    print(format_resource_for_report(summary))
