# 资源监控模块设计

> 状态: 📝 已设计，待实现
>
> 优先级: P1 (中高)
>
> 预计代码量: ~250行

---

## 核心目标

实时监控本地机器资源消耗，用于：
- 优化并发参数配置
- 诊断性能瓶颈
- 预防资源耗尽导致的崩溃
- 生成处理报告中的资源使用摘要

---

## 监控指标

```
┌─────────────────────────────────────────────────────────────┐
│                    Resource Monitor                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. CPU 监控                                                 │
│     ├── 整体使用率 (%)                                       │
│     ├── 每核心使用率                                         │
│     └── 进程 CPU 占用                                        │
│                                                              │
│  2. 内存监控                                                 │
│     ├── 总内存 / 可用内存                                    │
│     ├── 进程内存占用 (RSS/VMS)                               │
│     ├── 内存使用率 (%)                                       │
│     └── 峰值内存记录                                         │
│                                                              │
│  3. 磁盘 I/O                                                 │
│     ├── 读取速度 (MB/s)                                      │
│     ├── 写入速度 (MB/s)                                      │
│     ├── 磁盘使用率 (%)                                       │
│     └── 临时文件占用                                         │
│                                                              │
│  4. 网络 I/O                                                 │
│     ├── 上传速度 (KB/s)                                      │
│     ├── 下载速度 (KB/s)                                      │
│     └── API 请求统计                                         │
│                                                              │
│  5. 进程信息                                                 │
│     ├── 子进程数量                                           │
│     ├── 线程数量                                             │
│     └── 打开文件句柄数                                       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 实现方案

### 核心类设计

```python
# scripts/resource_monitor.py

import psutil
import threading
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

@dataclass
class ResourceSnapshot:
    """资源快照"""
    timestamp: str

    # CPU
    cpu_percent: float
    cpu_per_core: List[float]

    # Memory
    memory_total_gb: float
    memory_used_gb: float
    memory_percent: float
    process_memory_mb: float

    # Disk
    disk_read_mb_s: float
    disk_write_mb_s: float
    disk_usage_percent: float

    # Network
    net_sent_kb_s: float
    net_recv_kb_s: float

    # Process
    num_threads: int
    num_open_files: int
    num_children: int


class ResourceMonitor:
    """资源监控器"""

    def __init__(
        self,
        interval: float = 5.0,        # 采样间隔（秒）
        log_dir: Path = None,
        enable_logging: bool = True
    ):
        self.interval = interval
        self.log_dir = log_dir or Path("logs")
        self.enable_logging = enable_logging

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._snapshots: List[ResourceSnapshot] = []
        self._process = psutil.Process()

        # 用于计算速率的上一次采样值
        self._last_disk_io = None
        self._last_net_io = None
        self._last_sample_time = None

        # 峰值记录
        self.peak_cpu = 0.0
        self.peak_memory_mb = 0.0
        self.peak_memory_percent = 0.0

    def start(self):
        """启动后台监控线程"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        print(f"📊 资源监控已启动 (间隔: {self.interval}s)")

    def stop(self) -> Dict:
        """停止监控并返回摘要"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

        summary = self.get_summary()

        if self.enable_logging:
            self._save_logs()

        return summary

    def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                snapshot = self._take_snapshot()
                self._snapshots.append(snapshot)
                self._update_peaks(snapshot)
            except Exception as e:
                print(f"⚠️ 资源监控错误: {e}")

            time.sleep(self.interval)

    def _take_snapshot(self) -> ResourceSnapshot:
        """采集一次资源快照"""
        now = time.time()

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_per_core = psutil.cpu_percent(percpu=True)

        # Memory
        mem = psutil.virtual_memory()
        proc_mem = self._process.memory_info()

        # Disk I/O (计算速率)
        disk_io = psutil.disk_io_counters()
        disk_read_mb_s = 0.0
        disk_write_mb_s = 0.0

        if self._last_disk_io and self._last_sample_time:
            dt = now - self._last_sample_time
            if dt > 0:
                disk_read_mb_s = (disk_io.read_bytes - self._last_disk_io.read_bytes) / dt / 1024 / 1024
                disk_write_mb_s = (disk_io.write_bytes - self._last_disk_io.write_bytes) / dt / 1024 / 1024

        self._last_disk_io = disk_io

        # Network I/O (计算速率)
        net_io = psutil.net_io_counters()
        net_sent_kb_s = 0.0
        net_recv_kb_s = 0.0

        if self._last_net_io and self._last_sample_time:
            dt = now - self._last_sample_time
            if dt > 0:
                net_sent_kb_s = (net_io.bytes_sent - self._last_net_io.bytes_sent) / dt / 1024
                net_recv_kb_s = (net_io.bytes_recv - self._last_net_io.bytes_recv) / dt / 1024

        self._last_net_io = net_io
        self._last_sample_time = now

        # Disk usage
        disk_usage = psutil.disk_usage('/')

        # Process info
        try:
            num_threads = self._process.num_threads()
            num_open_files = len(self._process.open_files())
            num_children = len(self._process.children(recursive=True))
        except:
            num_threads = 0
            num_open_files = 0
            num_children = 0

        return ResourceSnapshot(
            timestamp=datetime.now().isoformat(),
            cpu_percent=cpu_percent,
            cpu_per_core=cpu_per_core,
            memory_total_gb=mem.total / 1024**3,
            memory_used_gb=mem.used / 1024**3,
            memory_percent=mem.percent,
            process_memory_mb=proc_mem.rss / 1024**2,
            disk_read_mb_s=round(disk_read_mb_s, 2),
            disk_write_mb_s=round(disk_write_mb_s, 2),
            disk_usage_percent=disk_usage.percent,
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

    def get_summary(self) -> Dict:
        """生成资源使用摘要"""
        if not self._snapshots:
            return {}

        # 计算平均值
        avg_cpu = sum(s.cpu_percent for s in self._snapshots) / len(self._snapshots)
        avg_mem = sum(s.process_memory_mb for s in self._snapshots) / len(self._snapshots)
        avg_disk_read = sum(s.disk_read_mb_s for s in self._snapshots) / len(self._snapshots)
        avg_disk_write = sum(s.disk_write_mb_s for s in self._snapshots) / len(self._snapshots)
        avg_net_sent = sum(s.net_sent_kb_s for s in self._snapshots) / len(self._snapshots)
        avg_net_recv = sum(s.net_recv_kb_s for s in self._snapshots) / len(self._snapshots)

        return {
            "sample_count": len(self._snapshots),
            "sample_interval_sec": self.interval,
            "cpu": {
                "average_percent": round(avg_cpu, 1),
                "peak_percent": round(self.peak_cpu, 1),
                "core_count": psutil.cpu_count()
            },
            "memory": {
                "average_process_mb": round(avg_mem, 1),
                "peak_process_mb": round(self.peak_memory_mb, 1),
                "peak_system_percent": round(self.peak_memory_percent, 1),
                "total_system_gb": round(self._snapshots[-1].memory_total_gb, 1)
            },
            "disk_io": {
                "average_read_mb_s": round(avg_disk_read, 2),
                "average_write_mb_s": round(avg_disk_write, 2)
            },
            "network_io": {
                "average_sent_kb_s": round(avg_net_sent, 2),
                "average_recv_kb_s": round(avg_net_recv, 2)
            }
        }

    def _save_logs(self):
        """保存详细日志"""
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 保存详细快照
        log_file = self.log_dir / f"resource_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w') as f:
            json.dump({
                "summary": self.get_summary(),
                "snapshots": [asdict(s) for s in self._snapshots]
            }, f, indent=2, ensure_ascii=False)

        print(f"📊 资源日志已保存: {log_file}")

    def get_current(self) -> ResourceSnapshot:
        """获取当前资源状态"""
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
```

---

## 集成方案

### 1. 在 docmind_converter.py 中集成

```python
# 在处理开始时启动监控
from resource_monitor import ResourceMonitor

monitor = ResourceMonitor(interval=5.0, log_dir=Path("logs"))
monitor.start()

try:
    # ... 处理逻辑 ...
    pass
finally:
    # 处理结束时停止监控并获取摘要
    resource_summary = monitor.stop()

    # 将资源摘要写入进度文件
    progress_data["resource_usage"] = resource_summary
```

### 2. 在质量报告中显示

```python
# generate_quality_report.py 中添加

def format_resource_section(resource_data: Dict) -> str:
    """格式化资源使用部分"""
    if not resource_data:
        return "资源监控: 未启用\n"

    return f"""
## 资源使用统计

| 指标 | 平均值 | 峰值 |
|------|--------|------|
| CPU | {resource_data['cpu']['average_percent']}% | {resource_data['cpu']['peak_percent']}% |
| 内存 | {resource_data['memory']['average_process_mb']} MB | {resource_data['memory']['peak_process_mb']} MB |
| 磁盘读取 | {resource_data['disk_io']['average_read_mb_s']} MB/s | - |
| 磁盘写入 | {resource_data['disk_io']['average_write_mb_s']} MB/s | - |
| 网络上传 | {resource_data['network_io']['average_sent_kb_s']} KB/s | - |
| 网络下载 | {resource_data['network_io']['average_recv_kb_s']} KB/s | - |
"""
```

### 3. 实时显示（可选）

```python
# 在进度条旁边显示资源状态
# 使用 Rich 库

from rich.live import Live
from rich.table import Table

def make_resource_table(monitor):
    s = monitor.get_current()
    table = Table(title="Resources")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("CPU", f"{s.cpu_percent:.1f}%")
    table.add_row("Memory", f"{s.process_memory_mb:.0f} MB")
    table.add_row("Disk R/W", f"{s.disk_read_mb_s:.1f}/{s.disk_write_mb_s:.1f} MB/s")
    return table
```

---

## 日志输出格式

### 实时日志（每5秒）

```
[2024-12-03 15:30:05] 📊 CPU: 45.2% | Mem: 2.1GB (32%) | Disk: R 15.3 W 8.2 MB/s | Net: ↑12.5 ↓45.8 KB/s
```

### 最终摘要

```
================================================================================
📊 资源使用摘要
================================================================================
采样次数: 720 (间隔: 5秒, 总时长: 60分钟)

CPU:
  平均使用率: 42.3%
  峰值使用率: 89.5%
  核心数: 8

内存:
  平均进程占用: 1,856 MB
  峰值进程占用: 3,241 MB
  系统峰值使用: 68.2%
  系统总内存: 16.0 GB

磁盘 I/O:
  平均读取: 12.5 MB/s
  平均写入: 5.8 MB/s

网络 I/O:
  平均上传: 125.3 KB/s
  平均下载: 892.4 KB/s
================================================================================
```

---

## 依赖

```
psutil>=5.9.0  # 系统资源监控
```

已在 requirements.txt 中（如未包含需添加）

---

## 实现优先级

1. **Phase 1**: 基础监控 (CPU + Memory)
2. **Phase 2**: 磁盘和网络 I/O
3. **Phase 3**: 实时显示集成
4. **Phase 4**: 告警机制 (资源超限时警告)

---

## 告警阈值（可配置）

```yaml
# config.yaml
resource_monitor:
  enabled: true
  interval_sec: 5
  thresholds:
    cpu_warning: 80      # CPU > 80% 警告
    cpu_critical: 95     # CPU > 95% 严重
    memory_warning: 80   # 内存 > 80% 警告
    memory_critical: 95  # 内存 > 95% 严重
    disk_warning: 90     # 磁盘 > 90% 警告
```
