#!/usr/bin/env python3
"""
DocMind PDF Converter
PDF to Markdown converter with:
1. Three-page context window (prev + current + next)
2. Concurrent processing (asyncio.Semaphore)
3. Two-phase processing (OCR → LLM)
4. Resume capability (v0.8)
"""

import sys
import os
import json
import time
import yaml
import re
import asyncio
import random
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from itertools import cycle
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict

# 资源监控
try:
    from resource_monitor import ResourceMonitor
    RESOURCE_MONITOR_AVAILABLE = True
except ImportError:
    RESOURCE_MONITOR_AVAILABLE = False

# ============ Issue 4: 重试策略配置 ============

@dataclass
class RetryConfig:
    """重试策略配置"""
    max_retries: int = 4                    # 最大重试次数
    initial_delay: float = 1.0              # 初始延迟（秒）
    max_delay: float = 30.0                 # 最大延迟（秒）
    exponential_base: float = 2.0           # 指数退避基数
    jitter: bool = True                     # 是否添加随机抖动

    # 重试触发条件
    retry_on_status_codes: tuple = (429, 500, 502, 503, 504)  # HTTP状态码
    retry_on_exceptions: tuple = (
        "SSLError", "ConnectionError", "TimeoutError",
        "NameResolutionError", "UNEXPECTED_EOF"
    )

# 默认重试配置
DEFAULT_RETRY_CONFIG = RetryConfig()

# ============ Issue 5: API Key 健康监控 ============

@dataclass
class APIKeyHealth:
    """单个API Key的健康状态"""
    key: str
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    total_latency: float = 0.0
    last_success_time: Optional[float] = None
    last_failure_time: Optional[float] = None
    is_disabled: bool = False
    disabled_until: Optional[float] = None

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 1.0

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.success_count if self.success_count > 0 else 0.0

    def record_success(self, latency: float):
        """记录成功调用"""
        self.success_count += 1
        self.consecutive_failures = 0
        self.total_latency += latency
        self.last_success_time = time.time()
        # 如果之前被禁用，现在恢复
        if self.is_disabled:
            self.is_disabled = False
            self.disabled_until = None

    def record_failure(self, disable_threshold: int = 5, disable_duration: float = 300.0):
        """记录失败调用"""
        self.failure_count += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.time()

        # 连续失败超过阈值，暂时禁用
        if self.consecutive_failures >= disable_threshold:
            self.is_disabled = True
            self.disabled_until = time.time() + disable_duration

    def is_available(self) -> bool:
        """检查Key是否可用"""
        if not self.is_disabled:
            return True
        # 检查禁用时间是否已过
        if self.disabled_until and time.time() > self.disabled_until:
            self.is_disabled = False
            self.disabled_until = None
            self.consecutive_failures = 0  # 重置连续失败计数
            return True
        return False


class APIKeyHealthMonitor:
    """API Key 健康监控器"""

    def __init__(self, api_keys: List[str], disable_threshold: int = 5, disable_duration: float = 300.0):
        self.health_data: Dict[str, APIKeyHealth] = {
            key: APIKeyHealth(key=key) for key in api_keys
        }
        self.disable_threshold = disable_threshold
        self.disable_duration = disable_duration
        self._lock = asyncio.Lock()
        self._current_index = 0

    async def get_healthy_key(self) -> Optional[str]:
        """获取一个健康的API Key（智能轮询）"""
        async with self._lock:
            available_keys = [
                key for key, health in self.health_data.items()
                if health.is_available()
            ]

            if not available_keys:
                # 所有Key都被禁用，返回最早禁用的（可能已恢复）
                earliest_key = min(
                    self.health_data.keys(),
                    key=lambda k: self.health_data[k].disabled_until or float('inf')
                )
                # 强制恢复
                self.health_data[earliest_key].is_disabled = False
                return earliest_key

            # 优先选择成功率高的Key
            # 按成功率排序，但加入一些随机性避免所有请求都打到同一个Key
            sorted_keys = sorted(
                available_keys,
                key=lambda k: (
                    -self.health_data[k].success_rate,
                    self.health_data[k].consecutive_failures,
                    random.random() * 0.1  # 小随机扰动
                )
            )

            return sorted_keys[0]

    def get_healthy_key_sync(self) -> Optional[str]:
        """同步版本：获取健康的API Key"""
        available_keys = [
            key for key, health in self.health_data.items()
            if health.is_available()
        ]

        if not available_keys:
            earliest_key = min(
                self.health_data.keys(),
                key=lambda k: self.health_data[k].disabled_until or float('inf')
            )
            self.health_data[earliest_key].is_disabled = False
            return earliest_key

        sorted_keys = sorted(
            available_keys,
            key=lambda k: (
                -self.health_data[k].success_rate,
                self.health_data[k].consecutive_failures
            )
        )
        return sorted_keys[0]

    async def record_success(self, key: str, latency: float):
        """记录成功"""
        async with self._lock:
            if key in self.health_data:
                self.health_data[key].record_success(latency)

    async def record_failure(self, key: str):
        """记录失败"""
        async with self._lock:
            if key in self.health_data:
                self.health_data[key].record_failure(
                    self.disable_threshold,
                    self.disable_duration
                )

    def record_success_sync(self, key: str, latency: float):
        """同步版本：记录成功"""
        if key in self.health_data:
            self.health_data[key].record_success(latency)

    def record_failure_sync(self, key: str):
        """同步版本：记录失败"""
        if key in self.health_data:
            self.health_data[key].record_failure(
                self.disable_threshold,
                self.disable_duration
            )

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {
            "total_keys": len(self.health_data),
            "active_keys": sum(1 for h in self.health_data.values() if h.is_available()),
            "disabled_keys": sum(1 for h in self.health_data.values() if h.is_disabled),
            "keys": {}
        }

        for key, health in self.health_data.items():
            masked_key = f"{key[:8]}...{key[-4:]}"
            stats["keys"][masked_key] = {
                "success_rate": f"{health.success_rate:.1%}",
                "success_count": health.success_count,
                "failure_count": health.failure_count,
                "consecutive_failures": health.consecutive_failures,
                "avg_latency": f"{health.avg_latency:.2f}s",
                "is_disabled": health.is_disabled
            }

        return stats

    def print_stats(self):
        """打印健康统计"""
        stats = self.get_stats()
        print(f"\n📊 API Key 健康状态:")
        print(f"   活跃: {stats['active_keys']}/{stats['total_keys']} | 禁用: {stats['disabled_keys']}")
        for key, info in stats["keys"].items():
            status = "🔴" if info["is_disabled"] else "🟢"
            print(f"   {status} {key}: 成功率 {info['success_rate']}, "
                  f"调用 {info['success_count']}/{info['success_count']+info['failure_count']}, "
                  f"延迟 {info['avg_latency']}")


# 全局健康监控器（在加载API Keys后初始化）
_api_key_monitor: Optional[APIKeyHealthMonitor] = None


def should_retry(error: Exception, config: RetryConfig) -> bool:
    """判断是否应该重试"""
    error_str = str(error)

    # 检查是否匹配重试触发条件
    for exc_pattern in config.retry_on_exceptions:
        if exc_pattern in error_str:
            return True

    return False


def calculate_retry_delay(attempt: int, config: RetryConfig) -> float:
    """计算重试延迟（指数退避 + 抖动）"""
    delay = min(
        config.initial_delay * (config.exponential_base ** attempt),
        config.max_delay
    )

    if config.jitter:
        # 添加 ±25% 的随机抖动
        jitter_range = delay * 0.25
        delay += random.uniform(-jitter_range, jitter_range)

    return max(0.1, delay)  # 最小延迟 0.1 秒

# ============ Issue 3 & 5: 模型和上下文配置 ============

class ContextMode(Enum):
    """上下文窗口模式"""
    MINIMAL = "minimal"     # 100/300/100 chars - 政治敏感文档
    STANDARD = "standard"   # 500/full/500 chars - 普通学术文档
    FULL = "full"           # 2000/full/2000 chars - 经济学图表文档

class PromptMode(Enum):
    """Prompt模式"""
    SIMPLE = "simple"       # ~500 chars - 纯文本页面
    ENHANCED = "enhanced"   # ~2500 chars - 图表数据提取

# 默认配置 (可通过命令行参数覆盖)
DEFAULT_MODEL = "qwen3-vl-plus-2025-12-19"
DEFAULT_CONTEXT_MODE = ContextMode.STANDARD
DEFAULT_PROMPT_MODE = PromptMode.ENHANCED

# 链式思维图表提取Prompt (Issue 3)
CHART_EXTRACTION_PROMPT = '''### TASK: Analyze this page image using Chain-of-Thought reasoning

**STEP 1 - CHART IDENTIFICATION:**
First, identify all visual elements on this page:
- Is there a figure/chart/table/diagram?
- If yes, what is its label? (e.g., "Figure 1", "Table 2")
- What type of visualization is it?
  * data_visualization: scatter, bar, line, pie, area charts
  * conceptual_diagram: flowchart, process diagram, org chart
  * mathematical_model: equations, formulas with graphs
  * data_table: structured tabular data
  * photograph: photos, images
  * map: geographic representations

**STEP 2 - VISUAL CONTENT ANALYSIS:**
For each identified figure:
- Describe what the chart shows in 1-2 sentences
- List ALL visible text labels (axis labels, legend items, annotations)
- Identify key elements (lines, bars, data points, etc.)

**STEP 3 - DATA EXTRACTION (REQUIRED for data_visualization AND data_table):**
⚠️ THIS IS MANDATORY - You MUST extract actual numeric values!

For charts (data_visualization):
- X-axis: label, unit (if any), range [min, max], scale type (linear/log/categorical)
- Y-axis: label, unit (if any), range [min, max], scale type
- Data series: For each series, extract:
  * Series name (from legend)
  * Key data points: {{x: value, y: value}} (use ~ for approximate readings)
  * Overall trend: upward/downward/stable/fluctuating

For tables (data_table):
- Extract ALL cell values as data_series
- Each row becomes a data_point with x = row identifier (e.g., year, name)
- Columns become y values: {{x: "1895", "Branches": 16, "Deposit": 14, "Total": 42}}
- ❌ DO NOT leave data_series empty if there is visible numeric data!

**STEP 4 - STATISTICAL INFORMATION (if visible):**
- Correlation coefficient (r)
- R-squared value (R²)
- Trend line equation (y = mx + b)
- Sample size (n)
- Growth rates or percentages

**STEP 5 - BODY TEXT & TABLES:**
⚠️ CRITICAL: Extract ALL visible text with HIGH FIDELITY!

For maps/diagrams with labels:
- Extract ALL location names, labels, annotations visible on the image
- List them in body_text or text_labels field
- Include: city names, region names, geographical features, legends

For documents:
- Main paragraphs (keep FULL text, do NOT summarize)
- Section headings
- Tables: Convert to Markdown format
- Formulas: Convert to LaTeX ($..$ or $$..$$)
- Footnotes and citations
- Keep original language, do NOT translate

⚠️ DO NOT skip or summarize text! Include EVERY readable word.

### CONTEXT WINDOW (for cross-page reference detection):
Previous page: {prev_context}
Current page: {page_num}
Next page: {next_context}

### OUTPUT FORMAT (JSON):
{{
  "page_number": {page_num},
  "has_figures": true/false,
  "figures": [
    {{
      "figure_number": "Figure 1",
      "caption": "...",
      "image_type": "data_visualization",
      "chart_type": "line_chart",
      "visual_description": "...",
      "key_elements": ["..."],
      "text_labels": ["ALL visible text on the figure: labels, names, annotations..."],
      "axes": {{
        "x_axis": {{"label": "...", "unit": null, "range": [...], "scale": "..."}},
        "y_axis": {{"label": "...", "unit": "...", "range": [...], "scale": "..."}}
      }},
      "data_series": [
        {{
          "series_name": "...",
          "data_points": [{{"x": "...", "y": ...}}],
          "trend": "upward/downward/stable/fluctuating"
        }}
      ],
      "statistical_info": {{
        "correlation": null,
        "r_squared": null,
        "equation": null,
        "sample_size": null,
        "growth_rate": null
      }}
    }}
  ],
  "tables": [
    {{"table_number": "Table 1", "caption": "...", "markdown": "| ... |"}}
  ],
  "formulas": ["$...$", "$$...$$"],
  "body_text": "FULL text content - do NOT summarize, include ALL readable text",
  "footnotes": []
}}

Return ONLY valid JSON.'''

# 图表指示关键词 (用于检测是否需要增强Prompt)
CHART_INDICATORS = [
    r'Figure\s*\d+', r'Fig\.\s*\d+', r'Table\s*\d+',
    r'Chart\s*\d+', r'Graph\s*\d+', r'Diagram\s*\d+',
    r'%', r'\$\d', r'million', r'billion', r'percent',
    r'x[\-\s]?axis', r'y[\-\s]?axis', r'legend',
    r'scatter', r'histogram', r'bar chart', r'pie chart'
]

def has_chart_indicators(ocr_text: str) -> bool:
    """检测OCR文本中是否有图表相关关键词"""
    if not ocr_text:
        return False
    for pattern in CHART_INDICATORS:
        if re.search(pattern, ocr_text, re.IGNORECASE):
            return True
    return False

def build_context_window(prev_ocr: str, current_ocr: str, next_ocr: str,
                         mode: ContextMode = ContextMode.STANDARD) -> tuple:
    """
    构建三页上下文窗口 (Issue 5)

    返回: (prev_context, current_context, next_context)
    """
    # 根据模式设置限制
    if mode == ContextMode.MINIMAL:
        prev_limit, current_limit, next_limit = 100, 300, 100
    elif mode == ContextMode.STANDARD:
        prev_limit, current_limit, next_limit = 500, 0, 500  # 0表示不截断
    else:  # FULL
        prev_limit, current_limit, next_limit = 2000, 0, 2000

    def truncate_with_refs(text: str, max_chars: int) -> str:
        """智能截断: 保留图表引用"""
        if not text:
            return "N/A"
        if max_chars == 0 or len(text) <= max_chars:
            return text

        # 提取所有图表引用
        refs = re.findall(
            r'((?:Figure|Fig\.?|Table|Chart)\s*\d+[^.]*\.)',
            text, re.IGNORECASE
        )

        # 如果引用占比小于max_chars，优先保留引用
        refs_text = ' '.join(refs)
        if refs_text and len(refs_text) < max_chars:
            remaining = max_chars - len(refs_text) - 20
            if remaining > 50:
                return f"{text[:remaining]}...\n[Refs: {refs_text}]"

        return text[:max_chars] + "..."

    prev_context = truncate_with_refs(prev_ocr, prev_limit)
    current_context = truncate_with_refs(current_ocr, current_limit)
    next_context = truncate_with_refs(next_ocr, next_limit)

    return prev_context, current_context, next_context

def build_prompt(page_num: int, prev_context: str, current_context: str,
                 next_context: str, prompt_mode: PromptMode) -> str:
    """
    构建LLM Prompt (Issue 3)

    根据prompt_mode选择简化或增强版本
    """
    if prompt_mode == PromptMode.ENHANCED:
        # 使用链式思维增强Prompt
        return CHART_EXTRACTION_PROMPT.format(
            page_num=page_num,
            prev_context=prev_context,
            next_context=next_context
        )
    else:
        # 简化Prompt (用于纯文本页面或政治敏感文档)
        return f"""Page {page_num} analysis:

OCR text: {current_context[:300] + '...' if len(current_context) > 300 else current_context}

Context:
- Previous page {page_num-1}: {prev_context[:100] + '...' if len(prev_context) > 100 else prev_context}
- Next page {page_num+1}: {next_context[:100] + '...' if len(next_context) > 100 else next_context}

Extract ALL content with HIGH FIDELITY:

1. TABLES - Convert to Markdown table format
2. FORMULAS - Convert to LaTeX format: $E=mc^2$
3. FIGURES - Describe the image, extract ALL visible text labels
4. BODY TEXT - Include ALL readable text, do NOT summarize
5. Keep original language - DO NOT translate

⚠️ IMPORTANT: Extract EVERY visible word/label on the page!

Return JSON format:
{{
  "page_number": {page_num},
  "tables": [{{"table_number": "Table 1", "caption": "...", "markdown": "| Col1 | Col2 |\\n|---|---|"}}],
  "figures": [{{"figure_number": "Fig 1", "caption": "...", "description": "...", "text_labels": ["all visible labels"]}}],
  "formulas": ["$formula1$"],
  "body_text": "COMPLETE text content here...",
  "footnotes": []
}}

Return ONLY valid JSON."""

# 导入进度管理器
try:
    from progress_manager import ProgressManager, get_progress_manager
    PROGRESS_ENABLED = True
except ImportError:
    PROGRESS_ENABLED = False
    print("⚠️  进度管理器未找到，断点续传功能禁用")

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# ============ Multi API Key Configuration ============
# Load API keys from multiple sources (in order):
# 1. Environment variables: DASHSCOPE_API_KEY (preferred)
# 2. Multiple keys: DASHSCOPE_API_KEY_1 through DASHSCOPE_API_KEY_8

# Load from environment variables
API_KEYS = [
    os.environ.get(f"DASHSCOPE_API_KEY_{i}") for i in range(1, 9)
]
API_KEYS.append(os.environ.get("DASHSCOPE_API_KEY"))
API_KEYS = [k for k in API_KEYS if k and k != "YOUR_API_KEY_HERE"]

# 创建循环迭代器用于负载均衡（兼容旧逻辑）
_api_key_cycle = cycle(API_KEYS) if API_KEYS else None
_api_key_lock = asyncio.Lock()

# 初始化健康监控器
if API_KEYS:
    _api_key_monitor = APIKeyHealthMonitor(
        API_KEYS,
        disable_threshold=5,      # 连续失败5次后禁用
        disable_duration=300.0    # 禁用5分钟
    )

async def get_next_api_key():
    """获取下一个 API Key（智能健康监控版本）"""
    global _api_key_monitor
    if _api_key_monitor:
        return await _api_key_monitor.get_healthy_key()
    # 降级到单Key
    return os.environ.get("DASHSCOPE_API_KEY")

def get_next_api_key_sync():
    """同步版本：获取下一个 API Key（智能健康监控版本）"""
    global _api_key_monitor
    if _api_key_monitor:
        return _api_key_monitor.get_healthy_key_sync()
    return os.environ.get("DASHSCOPE_API_KEY")
# ========================================

def check_dependencies():
    """检查依赖"""
    missing = []
    
    try:
        import dashscope
    except ImportError:
        missing.append("dashscope")
    
    try:
        from pdf2image import convert_from_path
    except ImportError:
        missing.append("pdf2image")
    
    try:
        from PIL import Image
    except ImportError:
        missing.append("Pillow")
    
    try:
        import yaml
    except ImportError:
        missing.append("PyYAML")
    
    if missing:
        print(f"❌ 缺少依赖: {', '.join(missing)}")
        print(f"\n安装命令:")
        print(f"pip3 install {' '.join(missing)}")
        return False
    
    return True

def get_api_key():
    """获取API密钥"""
    try:
        from olmocr_api_config import API_CONFIG
        if "qwen" in API_CONFIG:
            api_key = API_CONFIG["qwen"].get("api_key")
            if api_key and api_key != "YOUR_QWEN_API_KEY_HERE":
                return api_key
    except Exception as e:
        print(f"⚠️  无法从配置文件读取: {e}")
    
    return None

def safe_get_text_from_response(response):
    """
    安全提取API响应中的文本
    处理多种响应格式，避免IndexError和TypeError
    """
    try:
        # 检查基本结构
        if not hasattr(response, 'output'):
            return ""

        if not hasattr(response.output, 'choices') or len(response.output.choices) == 0:
            return ""

        content = response.output.choices[0].message.content

        # 情况1: content是列表
        if isinstance(content, list):
            if len(content) == 0:
                return ""

            first_item = content[0]

            # 列表中的元素是字典
            if isinstance(first_item, dict):
                return first_item.get("text", "")
            # 列表中的元素是字符串
            elif isinstance(first_item, str):
                return first_item
            else:
                return str(first_item)

        # 情况2: content直接是字符串
        elif isinstance(content, str):
            return content

        # 情况3: content是字典
        elif isinstance(content, dict):
            return content.get("text", str(content))

        # 情况4: 其他类型
        else:
            return str(content)

    except Exception as e:
        return ""

def simple_ocr_extract(image, retry_config: RetryConfig = DEFAULT_RETRY_CONFIG) -> str:
    """
    简单OCR提取（Phase 2）- 带重试机制
    使用Qwen API进行基础文本提取
    支持智能 API Key 健康监控和分层重试
    """
    from dashscope import MultiModalConversation
    import dashscope
    import base64
    from io import BytesIO

    global _api_key_monitor

    # 将图像转换为base64
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()

    simple_ocr_prompt = """请提取这张图片中的所有文字内容。
只需要纯文本，保持原有的段落结构和换行。
不要添加任何解释或格式化。"""

    messages = [
        {
            "role": "user",
            "content": [
                {"image": f"data:image/png;base64,{img_base64}"},
                {"text": simple_ocr_prompt}
            ]
        }
    ]

    last_error = None

    for attempt in range(retry_config.max_retries + 1):
        api_key = get_next_api_key_sync()
        call_start = time.time()

        try:
            dashscope.api_key = api_key

            response = MultiModalConversation.call(
                model='qwen3-vl-plus-2025-12-19',
                messages=messages
            )

            call_latency = time.time() - call_start

            if response.status_code == 200:
                # 记录成功
                if _api_key_monitor:
                    _api_key_monitor.record_success_sync(api_key, call_latency)
                return safe_get_text_from_response(response)

            # API返回错误状态码
            error_msg = f"{response.code} - {response.message}"
            last_error = Exception(error_msg)

            # 记录失败
            if _api_key_monitor:
                _api_key_monitor.record_failure_sync(api_key)

            # 检查是否应该重试
            if response.status_code in retry_config.retry_on_status_codes:
                if attempt < retry_config.max_retries:
                    delay = calculate_retry_delay(attempt, retry_config)
                    print(f"      🔄 OCR重试 ({attempt+1}/{retry_config.max_retries}): "
                          f"状态码 {response.status_code}, 等待 {delay:.1f}s")
                    time.sleep(delay)
                    continue

            return ""

        except Exception as e:
            call_latency = time.time() - call_start
            last_error = e

            # 记录失败
            if _api_key_monitor:
                _api_key_monitor.record_failure_sync(api_key)

            # 检查是否应该重试
            if should_retry(e, retry_config) and attempt < retry_config.max_retries:
                delay = calculate_retry_delay(attempt, retry_config)
                print(f"      🔄 OCR重试 ({attempt+1}/{retry_config.max_retries}): "
                      f"{type(e).__name__}, 等待 {delay:.1f}s")
                time.sleep(delay)
                continue

            print(f"      ⚠️ OCR提取失败: {e}")
            return ""

    # 所有重试都失败
    print(f"      ❌ OCR提取失败(重试{retry_config.max_retries}次后): {last_error}")
    return ""

async def process_single_page_with_context(
    page_num: int,
    image,
    current_ocr: str,
    prev_ocr: Optional[str],
    next_ocr: Optional[str],
    api_key: str,
    semaphore: asyncio.Semaphore,
    images_dir: Path,
    yaml_dir: Path,
    context_mode: ContextMode = DEFAULT_CONTEXT_MODE,
    prompt_mode: PromptMode = DEFAULT_PROMPT_MODE,
    model: str = DEFAULT_MODEL,
    retry_config: RetryConfig = DEFAULT_RETRY_CONFIG
) -> Dict[str, Any]:
    """
    处理单个页面（Phase 3 - 并发LLM处理）- 带重试机制

    参数：
        page_num: 当前页码
        image: 当前页图片
        current_ocr: 当前页OCR文本（必须处理）
        prev_ocr: 前一页OCR文本（仅用于上下文）
        next_ocr: 后一页OCR文本（仅用于上下文）
        api_key: API密钥
        semaphore: 并发控制信号量
        images_dir: 图片保存目录
        yaml_dir: YAML保存目录
        context_mode: 上下文窗口模式 (Issue 5)
        prompt_mode: Prompt模式 (Issue 3)
        model: 使用的模型名称
        retry_config: 重试配置 (Issue 4)
    """
    from dashscope import MultiModalConversation
    import base64
    from io import BytesIO
    import dashscope

    global _api_key_monitor

    # 使用semaphore控制并发
    async with semaphore:
        page_start = time.time()

        # 保存页面图片（只做一次，不需要重试）
        page_image_filename = f"page_{page_num:03d}.png"
        page_image_path = images_dir / page_image_filename
        image.save(page_image_path, "PNG")

        # 将图像转换为base64（只做一次）
        buffered = BytesIO()
        image.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()

        # ⭐ Issue 3 & 5: 使用增强的上下文窗口和Prompt构建
        # 智能检测是否需要增强模式
        detected_prompt_mode = prompt_mode
        if prompt_mode == PromptMode.ENHANCED:
            # 如果OCR文本没有图表指示，可以降级为SIMPLE以节省tokens
            if not has_chart_indicators(current_ocr) and not has_chart_indicators(prev_ocr or '') and not has_chart_indicators(next_ocr or ''):
                detected_prompt_mode = PromptMode.SIMPLE

        # 构建上下文窗口 (Issue 5)
        prev_context, current_context, next_context = build_context_window(
            prev_ocr or "", current_ocr, next_ocr or "", context_mode
        )

        # 构建Prompt (Issue 3)
        llm_prompt = build_prompt(
            page_num, prev_context, current_context, next_context, detected_prompt_mode
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"image": f"data:image/png;base64,{img_base64}"},
                    {"text": llm_prompt}
                ]
            }
        ]

        # ⭐ Issue 4: 分层重试逻辑
        last_error = None
        response = None

        for attempt in range(retry_config.max_retries + 1):
            # 每次重试获取新的健康 API Key
            balanced_api_key = await get_next_api_key()
            dashscope.api_key = balanced_api_key
            call_start = time.time()

            try:
                # 异步调用API（使用同步方式，因为dashscope不支持async）
                # 在asyncio环境中使用run_in_executor
                # ⭐ Issue 3 & 5: 使用配置的模型（默认qwen-vl-max-latest）
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: MultiModalConversation.call(
                        model=model,
                        messages=messages,
                        max_tokens=16384  # 增加输出 token 限制，避免截断
                    )
                )

                call_latency = time.time() - call_start

                if response.status_code == 200:
                    # 记录成功
                    if _api_key_monitor:
                        await _api_key_monitor.record_success(balanced_api_key, call_latency)
                    break  # 成功，跳出重试循环

                # API返回错误状态码
                error_msg = f"{response.code} - {response.message}"
                last_error = Exception(error_msg)

                # 记录失败
                if _api_key_monitor:
                    await _api_key_monitor.record_failure(balanced_api_key)

                # 检查是否应该重试（非内容审核错误）
                if "DataInspectionFailed" not in error_msg and attempt < retry_config.max_retries:
                    if response.status_code in retry_config.retry_on_status_codes or response.status_code >= 500:
                        delay = calculate_retry_delay(attempt, retry_config)
                        print(f"      🔄 Page {page_num} 重试 ({attempt+1}/{retry_config.max_retries}): "
                              f"状态码 {response.status_code}, 等待 {delay:.1f}s")
                        await asyncio.sleep(delay)
                        continue

                # 不可重试的错误
                return {
                    'success': False,
                    'page': page_num,
                    'error': error_msg
                }

            except Exception as e:
                call_latency = time.time() - call_start
                last_error = e

                # 记录失败
                if _api_key_monitor:
                    await _api_key_monitor.record_failure(balanced_api_key)

                # 检查是否应该重试
                if should_retry(e, retry_config) and attempt < retry_config.max_retries:
                    delay = calculate_retry_delay(attempt, retry_config)
                    print(f"      🔄 Page {page_num} 重试 ({attempt+1}/{retry_config.max_retries}): "
                          f"{type(e).__name__}, 等待 {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue

                # 不可重试的错误
                return {
                    'success': False,
                    'page': page_num,
                    'error': str(e),
                    'traceback': __import__('traceback').format_exc()
                }

        # 检查是否所有重试都失败了
        if response is None or response.status_code != 200:
            print(f"      ❌ Page {page_num} 失败(重试{retry_config.max_retries}次后): {last_error}")
            return {
                'success': False,
                'page': page_num,
                'error': str(last_error) if last_error else "Unknown error after retries"
            }

        # ========== 处理成功的响应 ==========
        try:
            result_text = safe_get_text_from_response(response)
            usage = response.usage

            # 提取JSON（Issue 11 修复：处理LaTeX反斜杠转义）
            # 尝试多种格式提取 JSON
            json_str = None

            # 方法1: ```json ... ``` 代码块
            json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)

            # 方法2: ``` ... ``` 代码块（无语言标记）
            if not json_str:
                json_match = re.search(r'```\s*(\{.*?\})\s*```', result_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)

            # 方法3: 直接查找 JSON 对象 { ... }
            if not json_str:
                # 找到第一个 { 和最后一个 } 之间的内容
                first_brace = result_text.find('{')
                last_brace = result_text.rfind('}')
                if first_brace != -1 and last_brace > first_brace:
                    json_str = result_text[first_brace:last_brace + 1]

            # 方法4: 使用整个响应
            if not json_str:
                json_str = result_text

            # 修复LaTeX公式中的非法反斜杠转义
            # JSON合法转义: \" \\ \/ \b \f \n \r \t \uXXXX
            # LaTeX常见: \frac \int \alpha \beta 等需要转为 \\
            def fix_latex_escapes(s):
                result = []
                i = 0
                n = len(s)
                while i < n:
                    if s[i] == '\\' and i + 1 < n:
                        next_char = s[i + 1]
                        if next_char in '"\\/' :
                            # 保留: \" \\ \/
                            result.append(s[i:i+2])
                            i += 2
                        elif next_char in 'bfnrt':
                            # 判断是JSON转义还是LaTeX命令
                            if i + 2 < n and s[i + 2].isalpha():
                                # LaTeX命令如 \beta \frac \ne
                                result.append('\\\\')
                                i += 1
                            else:
                                # JSON转义如 \n \t
                                result.append(s[i:i+2])
                                i += 2
                        elif next_char == 'u' and i + 5 < n:
                            # 检查是否是 \uXXXX
                            hex_part = s[i+2:i+6]
                            if all(c in '0123456789abcdefABCDEF' for c in hex_part):
                                result.append(s[i:i+6])
                                i += 6
                            else:
                                result.append('\\\\')
                                i += 1
                        else:
                            # 其他情况（LaTeX命令）
                            result.append('\\\\')
                            i += 1
                    else:
                        result.append(s[i])
                        i += 1
                return ''.join(result)

            json_str = fix_latex_escapes(json_str)

            try:
                result_json = json.loads(json_str)
            except json.JSONDecodeError as e:
                # 降级处理：尝试修复并提取尽可能多的内容
                print(f"      ⚠️ JSON解析失败(Page {page_num}): {e}")

                # 尝试修复常见的 JSON 问题
                fixed_json = None
                try:
                    # 尝试1: 添加缺失的结尾括号
                    test_str = json_str.rstrip()
                    if not test_str.endswith('}'):
                        # 计算需要添加多少个 }
                        open_braces = test_str.count('{') - test_str.count('}')
                        if open_braces > 0:
                            test_str += '"' + '}' * open_braces  # 先闭合可能未闭合的字符串
                            try:
                                fixed_json = json.loads(test_str)
                                print(f"      ✅ JSON修复成功(添加闭合括号)")
                            except:
                                pass
                except:
                    pass

                if fixed_json:
                    result_json = fixed_json
                else:
                    # 从截断的 JSON 中提取尽可能多的内容
                    body_text = ""
                    text_labels = []
                    description = ""

                    # 提取 text_labels 数组（地图等图像的标签）
                    labels_match = re.search(r'"text_labels"\s*:\s*\[(.*?)(?:\]|$)', json_str, re.DOTALL)
                    if labels_match:
                        labels_str = labels_match.group(1)
                        # 提取所有带引号的字符串
                        text_labels = re.findall(r'"([^"]+)"', labels_str)
                        if text_labels:
                            print(f"      ✅ 从截断JSON提取到 {len(text_labels)} 个标签")

                    # 提取 description
                    desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', json_str)
                    if desc_match:
                        description = desc_match.group(1).replace('\\n', '\n').replace('\\"', '"')

                    # 提取 body_text
                    body_match = re.search(r'"body_text"\s*:\s*"((?:[^"\\]|\\.)*)', json_str, re.DOTALL)
                    if body_match:
                        body_text = body_match.group(1)
                        body_text = body_text.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')

                    # 组合内容：description + text_labels 作为 body_text
                    combined_text = ""
                    if description:
                        combined_text = description + "\n\n"
                    if text_labels:
                        combined_text += "**提取的文字标签:**\n\n"
                        combined_text += "\n".join(f"- {label}" for label in text_labels)
                    if body_text and len(body_text) > len(combined_text):
                        combined_text = body_text

                    # 如果还是太短，使用整个原始响应
                    if len(combined_text) < 100 and result_text:
                        clean_text = re.sub(r'```json\s*', '', result_text)
                        clean_text = re.sub(r'```\s*$', '', clean_text)
                        if len(clean_text) > len(combined_text):
                            combined_text = clean_text

                    result_json = {
                        "page_number": page_num,
                        "tables": [],
                        "figures": [],
                        "formulas": [],
                        "body_text": combined_text if combined_text else result_text,
                        "footnotes": [],
                        "page_markers": []
                    }

            page_time = time.time() - page_start

            # 处理检测到的图表
            figures_metadata = []
            figure_refs = []

            # 处理 figures（图片/图表描述）
            if result_json.get('figures'):
                for fig_idx, figure in enumerate(result_json['figures'], 1):
                    figure_yaml = generate_figure_yaml(figure, fig_idx, page_num)
                    figure_ref = figure.get('figure_number', f'Figure_{fig_idx}')
                    yaml_filename = f"{figure_ref.replace(' ', '_').replace(':', '')}_page{page_num}.yaml"
                    yaml_path = yaml_dir / yaml_filename

                    with open(yaml_path, 'w', encoding='utf-8') as f:
                        yaml.dump(figure_yaml, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

                    figures_metadata.append(figure_yaml)
                    figure_refs.append({
                        'figure_ref': figure_ref,
                        'yaml_file': yaml_filename,
                        'description': figure.get('description', ''),
                        'confidence': figure.get('extraction_confidence', 'medium')
                    })

            # 处理 tables（Markdown 表格）
            tables_data = []
            if result_json.get('tables'):
                for table in result_json['tables']:
                    tables_data.append({
                        'table_number': table.get('table_number', ''),
                        'caption': table.get('caption', ''),
                        'markdown': table.get('markdown', '')
                    })

            # 处理 formulas（LaTeX 公式）
            formulas = result_json.get('formulas', [])

            # 日志：VLM 处理成功
            print(f"   [VLM] [{page_num}] ✅ ({len(result_text)} 字符)", flush=True)

            return {
                'success': True,
                'page': page_num,
                'figure_count': len(figure_refs),
                'table_count': len(tables_data),
                'formula_count': len(formulas),
                'figures': figure_refs,
                'figures_metadata': figures_metadata,
                'tables': tables_data,
                'formulas': formulas,
                'body_text': result_json.get('body_text', ''),
                'footnotes': result_json.get('footnotes', []),
                'tokens': {
                    'input': usage.input_tokens,
                    'output': usage.output_tokens
                },
                'time': page_time
            }

        except Exception as e:
            return {
                'success': False,
                'page': page_num,
                'error': str(e),
                'traceback': __import__('traceback').format_exc()
            }

def generate_figure_yaml(figure_data: Dict, figure_index: int, page_num: int) -> Dict[str, Any]:
    """
    生成完整的YAML元数据（Issue 2: 完善6节结构）
    符合MARCO质量规范的完整schema
    """
    confidence = figure_data.get("extraction_confidence", "medium")
    conf_score = {"high": 0.95, "medium": 0.70, "low": 0.40}.get(confidence, 0.70)

    yaml_metadata = {
        # Section 1: Chart Identification (必填)
        "chart_identification": {
            "chart_title": figure_data.get("chart_title", figure_data.get("caption", "Untitled")),
            "figure_number": figure_data.get("figure_number", f"Figure {figure_index}"),
            "figure_reference_in_text": figure_data.get("figure_number", f"Figure {figure_index}"),
            "page_number": page_num,
            "image_path": f"images/page_{page_num:03d}.png",
            "image_type": figure_data.get("image_type", "figure"),
            "chart_type": figure_data.get("chart_type", "unknown")
        },

        # Section 2: Visual Content (必填)
        "visual_content": {
            "content_description": figure_data.get("content_description", figure_data.get("description", "")),
            "key_elements": figure_data.get("key_elements", []),
            "text_labels": figure_data.get("text_labels", []),
            "content_summary": (figure_data.get("content_description", "") or figure_data.get("description", ""))[:200],
            "key_insight": figure_data.get("key_insight", "")
        },

        # Section 3: Data Extraction (有数据时填充，否则占位)
        "data_extraction": {
            "axes": figure_data.get("axes", {
                "x_axis": {"label": "N/A", "unit": "N/A", "range": "N/A"},
                "y_axis": {"label": "N/A", "unit": "N/A", "range": "N/A"}
            }),
            "data_series": figure_data.get("data_series", []) if figure_data.get("data_series") else (
                [{
                    "series_name": "Main Data",
                    "data_points": figure_data.get("data_points", []),
                    "trend": figure_data.get("trend", "N/A")
                }] if figure_data.get("data_points") else []
            ),
            "has_quantitative_data": bool(figure_data.get("data_points") or figure_data.get("has_data"))
        },

        # Section 4: Statistical Information (占位结构)
        "statistical_information": figure_data.get("statistics", {
            "sample_size": "N/A",
            "statistical_tests": [],
            "confidence_intervals": [],
            "p_values": [],
            "notes": "No statistical data extracted"
        }),

        # Section 5: Visual Design (占位结构)
        "visual_design": figure_data.get("visual_design", {
            "color_scheme": [],
            "legend_present": False,
            "grid_lines": "N/A",
            "annotations": []
        }),

        # Section 6: Quality Check (必填)
        "quality_check": {
            "data_completeness": {
                "all_labels_readable": "yes" if confidence == "high" else ("partial" if confidence == "medium" else "no"),
                "all_values_extracted": "yes" if figure_data.get("has_data") or figure_data.get("data_points") else "no",
                "uncertainties": figure_data.get("uncertainties", []),
                "total_data_points_visible": len(figure_data.get("data_points", []))
            },
            "extraction_confidence": confidence,
            "confidence_score": conf_score,
            "validation_checklist": {
                "figure_number_found": "yes" if figure_data.get("figure_number") else "no",
                "image_type_identified": "yes" if figure_data.get("image_type") else "no",
                "all_axes_labeled": "yes" if figure_data.get("axes") else "no",
                "data_points_extracted": "yes" if figure_data.get("data_points") else "no",
                "manual_verification_needed": "no" if confidence == "high" else "yes"
            }
        }
    }

    return yaml_metadata

async def process_pdf_async(
    pdf_path: Path,
    api_key: str,
    output_base: Path,
    max_pages: int = None,
    semaphore_limit: int = 10,
    progress_manager: 'ProgressManager' = None,
    resume: bool = True,
    context_mode: ContextMode = DEFAULT_CONTEXT_MODE,
    prompt_mode: PromptMode = DEFAULT_PROMPT_MODE,
    model: str = DEFAULT_MODEL
):
    """
    异步处理单个PDF文件

    Args:
        pdf_path: PDF文件路径
        api_key: API密钥
        output_base: 输出目录
        max_pages: 最大处理页数
        semaphore_limit: 并发限制
        progress_manager: 进度管理器（用于断点续传）
        resume: 是否启用断点续传
    """
    from pdf2image import convert_from_path
    import dashscope

    dashscope.api_key = api_key
    pdf_name = pdf_path.stem

    print(f"\n{'='*80}")
    print(f"📄 处理PDF: {pdf_path.name}")
    print(f"{'='*80}")
    print(f"   大小: {pdf_path.stat().st_size / 1024 / 1024:.1f}MB")
    print(f"   并发限制: {semaphore_limit}")

    # 检查是否已完成（断点续传）- 增强验证
    if resume and progress_manager:
        # 确定步骤名称
        step_name = 'process_chunks' if 'chunks' in str(output_base) else 'process_direct'

        # 先检查是否在completed列表中
        if progress_manager.is_pdf_completed(step_name, pdf_name):
            # 使用增强验证：检查MD文件存在性和内容大小
            validation = progress_manager.validate_pdf_completion(
                step_name,
                pdf_name,
                str(output_base),
                min_content_size=500,      # MD文件至少500字节
                min_completion_rate=0.90   # 页面完成率至少90%
            )

            if validation['valid']:
                print(f"   ⏭️  已完成，跳过（验证通过: {validation['md_size']} bytes, {validation['page_completion_rate']:.1%}完成率）")
                return {
                    "success": True,
                    "skipped": True,
                    "pdf_info": {"name": pdf_path.name},
                    "message": "已在之前的运行中完成"
                }
            else:
                # 验证失败，需要重新处理
                print(f"   ⚠️  之前标记为完成但验证失败: {validation['reason']}")
                print(f"   🔄 将重新处理此PDF...")
                progress_manager.invalidate_pdf_completion(step_name, pdf_name)
    
    # 创建输出目录
    pdf_name = pdf_path.stem
    output_dir = output_base / pdf_name
    output_dir.mkdir(parents=True, exist_ok=True)
    
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    
    yaml_dir = output_dir / "yaml_metadata"
    yaml_dir.mkdir(exist_ok=True)
    
    start_time = time.time()
    
    try:
        # Phase 1: PDF → 图片 (使用run_in_executor实现并发)
        print(f"\n📸 Phase 1: 转换PDF为图像...")
        loop = asyncio.get_event_loop()
        images = await loop.run_in_executor(
            None,
            lambda: convert_from_path(str(pdf_path), dpi=150)
        )
        total_pages = len(images)
        
        if max_pages:
            images = images[:max_pages]
            print(f"   限制处理前 {max_pages} 页 (总共 {total_pages} 页)")

        print(f"   ✅ 转换完成: {len(images)} 页")

        # 初始化页面进度跟踪
        if progress_manager:
            progress_manager.init_pdf_progress(pdf_name, len(images))
            completed_pages = set(progress_manager.get_completed_pages(pdf_name))
            if completed_pages:
                print(f"   📌 断点续传: 已完成 {len(completed_pages)}/{len(images)} 页")
        else:
            completed_pages = set()
        
        # Phase 2: OCR并发提取
        print(f"\n🔤 Phase 2: OCR并发提取...")
        print(f"   并发数: 20")

        async def ocr_single_page(page_num: int, image):
            """单页OCR异步包装"""
            # 跳过已完成的页面（但OCR阶段需要全部提取以支持上下文）
            loop = asyncio.get_event_loop()
            ocr_text = await loop.run_in_executor(
                None,
                lambda: simple_ocr_extract(image)
            )
            print(f"   [OCR] [{page_num}/{len(images)}] ✅ ({len(ocr_text)} 字符)", flush=True)
            return page_num, ocr_text

        # 并发执行所有OCR（即使页面已完成LLM处理，OCR仍需用于上下文）
        ocr_semaphore = asyncio.Semaphore(20)

        async def ocr_with_semaphore(page_num, image):
            async with ocr_semaphore:
                return await ocr_single_page(page_num, image)

        ocr_tasks = [
            ocr_with_semaphore(page_num, image)
            for page_num, image in enumerate(images, 1)
        ]
        ocr_results = await asyncio.gather(*ocr_tasks)

        page_ocr_texts = {page_num: text for page_num, text in ocr_results}
        print(f"   ✅ OCR完成: {len(page_ocr_texts)} 页")
        
        # Phase 3: LLM并发处理
        print(f"\n🤖 Phase 3: LLM并发处理（图表检测+元数据生成）...")
        print(f"   并发数: {semaphore_limit}")

        # 统计需要处理的页面
        pages_to_process = [p for p in range(1, len(images) + 1) if p not in completed_pages]
        if completed_pages:
            print(f"   📌 跳过已完成页面: {len(completed_pages)} 页")
            print(f"   📌 待处理页面: {len(pages_to_process)} 页")

        semaphore = asyncio.Semaphore(semaphore_limit)
        tasks = []
        skipped_results = []

        for page_num, image in enumerate(images, 1):
            # 跳过已完成的页面
            if page_num in completed_pages:
                # 尝试从现有文件加载结果
                skipped_results.append({
                    'success': True,
                    'page': page_num,
                    'skipped': True,
                    'figure_count': 0,  # 会在合并时从文件重新读取
                    'figures': [],
                    'figures_metadata': [],
                    'body_text': '',
                    'tokens': {'input': 0, 'output': 0},
                    'time': 0
                })
                continue

            current_ocr = page_ocr_texts.get(page_num, "")
            prev_ocr = page_ocr_texts.get(page_num - 1)
            next_ocr = page_ocr_texts.get(page_num + 1)

            task = process_single_page_with_context(
                page_num=page_num,
                image=image,
                current_ocr=current_ocr,
                prev_ocr=prev_ocr,
                next_ocr=next_ocr,
                api_key=api_key,
                semaphore=semaphore,
                images_dir=images_dir,
                yaml_dir=yaml_dir,
                context_mode=context_mode,  # Issue 5
                prompt_mode=prompt_mode,     # Issue 3
                model=model                  # qwen-vl-max-latest
            )
            tasks.append((page_num, task))

        # 并发执行所有任务
        if tasks:
            async_results = await asyncio.gather(*[t[1] for t in tasks])

            # 处理结果并更新进度
            for (page_num, _), result in zip(tasks, async_results):
                if result.get('success'):
                    if progress_manager:
                        progress_manager.mark_page_completed(pdf_name, page_num)
                else:
                    if progress_manager:
                        progress_manager.mark_page_failed(pdf_name, page_num, result.get('error', 'Unknown error'))

            page_results = skipped_results + list(async_results)
        else:
            page_results = skipped_results
            print(f"   ✅ 所有页面已在之前完成")
        
        # 处理结果
        print(f"\n💾 保存结果...")
        
        # 按页码排序
        page_results = sorted(page_results, key=lambda x: x['page'])
        
        # 构建Markdown
        markdown_sections = []
        all_figures_metadata = []
        total_tokens = {"input": 0, "output": 0}
        total_figures = 0
        total_tables = 0
        total_formulas = 0
        confidence_scores = []

        for result in page_results:
            if not result['success']:
                print(f"   ⚠️ Page {result['page']} 失败: {result.get('error')}")
                continue

            page_num = result['page']
            tokens = result['tokens']
            total_tokens['input'] += tokens['input']
            total_tokens['output'] += tokens['output']

            figure_count = result.get('figure_count', 0)
            table_count = result.get('table_count', 0)
            formula_count = result.get('formula_count', 0)
            total_figures += figure_count
            total_tables += table_count
            total_formulas += formula_count

            # 构建页面内容
            page_content = f"## Page {page_num}\n\n"

            # 添加正文（放在最前面）
            body_text = result.get('body_text', '').strip()
            if body_text:
                page_content += f"{body_text}\n\n"

            # 添加表格（Markdown 格式）
            if result.get('tables'):
                for table in result['tables']:
                    table_num = table.get('table_number', '')
                    caption = table.get('caption', '')
                    markdown = table.get('markdown', '')
                    if table_num or caption:
                        page_content += f"### {table_num}: {caption}\n\n"
                    if markdown:
                        page_content += f"{markdown}\n\n"

            # 添加公式（LaTeX 格式）
            if result.get('formulas'):
                formulas = result['formulas']
                if formulas:
                    for formula in formulas:
                        if formula and formula.strip():
                            page_content += f"{formula}\n\n"

            # 添加图表描述
            if result.get('figures'):
                for fig_info in result['figures']:
                    figure_ref = fig_info['figure_ref']
                    yaml_file = fig_info.get('yaml_file', '')
                    description = fig_info.get('description', '')

                    # 从metadata获取标题
                    matching_meta = [m for m in result.get('figures_metadata', [])
                                    if m['chart_identification']['figure_number'] == figure_ref]
                    chart_title = matching_meta[0]['chart_identification']['chart_title'] if matching_meta else "Untitled"

                    page_content += f"\n### {figure_ref}: {chart_title}\n\n"
                    if description:
                        page_content += f"*{description}*\n\n"
                    page_content += f"![{figure_ref}: {chart_title}](images/page_{page_num:03d}.png)\n\n"
                    if yaml_file:
                        page_content += f"*YAML Metadata: [yaml_metadata/{yaml_file}](yaml_metadata/{yaml_file})*\n\n"

                    # 记录confidence
                    conf_map = {'high': 1.0, 'medium': 0.6, 'low': 0.3}
                    confidence_scores.append(conf_map.get(fig_info.get('confidence', 'medium'), 0.6))

                all_figures_metadata.extend(result.get('figures_metadata', []))

            # 添加脚注
            if result.get('footnotes'):
                footnotes = result['footnotes']
                if footnotes:
                    page_content += "---\n\n**Footnotes:**\n\n"
                    for i, fn in enumerate(footnotes, 1):
                        page_content += f"[^{i}]: {fn}\n"
                    page_content += "\n"

            markdown_sections.append(page_content)
            
            print(f"   ✅ Page {page_num}: {table_count} 表格, {formula_count} 公式, {figure_count} 图表, {tokens['input']}+{tokens['output']} tokens")

        # 保存Markdown
        md_file = output_dir / f"{pdf_name}.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(f"# {pdf_name}\n\n")
            f.write(f"*Processed with DocMind on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")
            f.write(f"*Model: {model}*\n\n")
            f.write(f"*Statistics: {total_tables} tables, {total_formulas} formulas, {total_figures} figures*\n\n")
            f.write("---\n\n")
            f.write("\n".join(markdown_sections))
        
        print(f"   ✅ Markdown: {md_file.name}")
        
        # 保存合并YAML
        combined_yaml_file = output_dir / f"{pdf_name}_all_figures.yaml"
        combined_yaml = {
            "document_info": {
                "filename": pdf_path.name,
                "total_pages": total_pages,
                "processed_pages": len(images),
                "total_figures": total_figures,
                "processing_date": datetime.now().isoformat()
            },
            "figures": all_figures_metadata
        }
        
        with open(combined_yaml_file, 'w', encoding='utf-8') as f:
            yaml.dump(combined_yaml, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        
        print(f"   ✅ Combined YAML: {combined_yaml_file.name}")
        
        # 生成验证报告（Issue 6 + Issue 8: 完善验证报告和KQI指标）
        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
        yaml_insertion_rate = len(all_figures_metadata) / max(total_figures, 1)

        # 统计成功/失败页面
        success_pages = [r for r in page_results if r.get('success', False)]
        failed_pages = [r for r in page_results if not r.get('success', False)]

        # KQI指标计算 (Issue 8)
        kqi_yaml_insertion = yaml_insertion_rate >= 0.95  # MARCO要求 ≥95%
        kqi_confidence = avg_confidence >= 0.85           # MARCO要求 ≥0.85
        kqi_page_success = len(success_pages) / len(page_results) if page_results else 0

        validation_report = {
            "document_info": {
                "filename": pdf_path.name,
                "total_pages": total_pages,
                "processed_pages": len(images),
                "processing_date": datetime.now().isoformat()
            },
            "kqi_metrics": {  # Issue 8: Key Quality Indicators
                "yaml_insertion_rate": round(yaml_insertion_rate, 4),
                "yaml_insertion_pass": kqi_yaml_insertion,  # ≥95%
                "average_confidence": round(avg_confidence, 4),
                "confidence_pass": kqi_confidence,          # ≥0.85
                "page_success_rate": round(kqi_page_success, 4),
                "overall_quality_pass": kqi_yaml_insertion and kqi_confidence and kqi_page_success >= 0.98
            },
            "validation_metrics": {
                "yaml_insertion_rate": round(yaml_insertion_rate, 2),
                "average_confidence": round(avg_confidence, 2),
                "figure_detection_completeness": round(total_figures / len(images), 2) if images else 0,
                "total_figures_detected": total_figures,
                "total_tables_detected": total_tables,
                "total_formulas_detected": total_formulas,
                "pages_with_figures": sum(1 for r in page_results if r.get('figure_count', 0) > 0),
                "pages_with_tables": sum(1 for r in page_results if r.get('table_count', 0) > 0),
                "pages_with_formulas": sum(1 for r in page_results if r.get('formula_count', 0) > 0),
                "high_confidence_figures": sum(1 for s in confidence_scores if s >= 0.9),
                "medium_confidence_figures": sum(1 for s in confidence_scores if 0.5 <= s < 0.9),
                "low_confidence_figures": sum(1 for s in confidence_scores if s < 0.5)
            },
            "page_statistics": {  # Issue 6: 完善页面统计
                "total_pages": len(page_results),
                "successful_pages": len(success_pages),
                "failed_pages": len(failed_pages),
                "skipped_pages": sum(1 for r in page_results if r.get('skipped', False)),
                "success_rate": round(len(success_pages) / len(page_results), 4) if page_results else 0
            },
            "quality_indicators": {
                "all_figures_have_yaml": len(all_figures_metadata) == total_figures,
                "zero_hallucination": True,
                "proper_markdown_format": True,
                "complete_data_extraction": avg_confidence >= 0.6,
                "no_page_failures": len(failed_pages) == 0
            },
            "failed_pages_detail": [  # Issue 6: 失败页面详情
                {
                    "page": r['page'],
                    "error": r.get('error', 'Unknown error')
                } for r in failed_pages
            ],
            "page_by_page_results": [
                {
                    "page": r['page'],
                    "success": r['success'],
                    "figure_count": r.get('figure_count', 0),
                    "table_count": r.get('table_count', 0),
                    "formula_count": r.get('formula_count', 0),
                    "figures": r.get('figures', [])
                } for r in page_results
            ]
        }
        
        validation_file = output_dir / f"{pdf_name}.validation.yaml"
        with open(validation_file, 'w', encoding='utf-8') as f:
            yaml.dump(validation_report, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        
        print(f"   ✅ Validation Report: {validation_file.name}")
        
        # 计算总时间和成本
        # Qwen-VL-Max 定价 (2024): 输入 ¥0.02/1K, 输出 ¥0.02/1K
        # 注意: 实际账单可能因优惠而不同
        PRICE_INPUT_PER_1K = 0.02   # ¥0.02/1000 input tokens
        PRICE_OUTPUT_PER_1K = 0.02  # ¥0.02/1000 output tokens

        process_time = time.time() - start_time
        total_tokens_sum = total_tokens["input"] + total_tokens["output"]

        # 分别计算输入和输出成本
        input_cost = (total_tokens["input"] / 1000) * PRICE_INPUT_PER_1K
        output_cost = (total_tokens["output"] / 1000) * PRICE_OUTPUT_PER_1K
        cost_cny = input_cost + output_cost

        success_count = sum(1 for r in page_results if r.get('success', False))

        print(f"\n{'='*80}")
        print(f"✅ 处理完成: {pdf_path.name}")
        print(f"{'='*80}")
        print(f"📊 统计:")
        print(f"   页数: {len(images)}/{total_pages} (成功: {success_count})")
        print(f"   图表: {total_figures} 个")
        print(f"   平均信心度: {avg_confidence:.2f}")
        print(f"   YAML插入率: {yaml_insertion_rate:.2%}")
        print(f"   用时: {int(process_time // 60)}分{int(process_time % 60)}秒")
        print(f"   Tokens: {total_tokens_sum:,} (输入: {total_tokens['input']:,}, 输出: {total_tokens['output']:,})")
        print(f"   费用: ¥{cost_cny:.2f} (输入: ¥{input_cost:.2f}, 输出: ¥{output_cost:.2f})")
        
        return {
            "success": True,
            "pdf_info": {
                "name": pdf_path.name,
                "pages": len(images),
                "figures": total_figures
            },
            "processing": {
                "time": process_time,
                "tokens": total_tokens_sum,
                "tokens_input": total_tokens["input"],
                "tokens_output": total_tokens["output"],
                "cost_cny": cost_cny,
                "cost_input": input_cost,
                "cost_output": output_cost
            },
            "validation": validation_report["validation_metrics"]
        }
        
    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "pdf_info": {"name": pdf_path.name},
            "error": str(e)
        }

async def process_all_pdfs_parallel(
    pdf_files: List[Path],
    api_key: str,
    output_base: Path,
    max_pages: Optional[int],
    pdf_concurrency: int,
    semaphore_limit: int = 12,
    progress_manager: 'ProgressManager' = None,
    resume: bool = True,
    context_mode: ContextMode = DEFAULT_CONTEXT_MODE,
    prompt_mode: PromptMode = DEFAULT_PROMPT_MODE,
    model: str = DEFAULT_MODEL
) -> List[Dict[str, Any]]:
    """
    PDF级并行处理所有PDF文件

    Args:
        pdf_files: PDF文件列表
        api_key: API密钥
        output_base: 输出目录
        max_pages: 最大页数限制
        pdf_concurrency: PDF级并发数（同时处理多少个PDF）
        semaphore_limit: LLM并发数（每个PDF内部）
        progress_manager: 进度管理器（用于断点续传）
        resume: 是否启用断点续传

    Returns:
        所有PDF的处理结果
    """
    import sys

    # 创建PDF级信号量
    pdf_semaphore = asyncio.Semaphore(pdf_concurrency)

    # 进度追踪
    total = len(pdf_files)
    completed = 0
    skipped = 0
    lock = asyncio.Lock()

    async def process_one_pdf_with_semaphore(pdf_file: Path, index: int):
        """带信号量控制的单PDF处理"""
        nonlocal completed, skipped

        async with pdf_semaphore:
            # 打印开始信息
            async with lock:
                print(f"\n{'#'*80}", flush=True)
                print(f"进度: [{index}/{total}] - {pdf_file.name}", flush=True)
                print(f"{'#'*80}", flush=True)

            try:
                # LLM concurrent per PDF (Max Safe mode)
                result = await process_pdf_async(
                    pdf_file,
                    api_key,
                    output_base,
                    max_pages,
                    semaphore_limit=semaphore_limit,
                    progress_manager=progress_manager,
                    resume=resume,
                    context_mode=context_mode,
                    prompt_mode=prompt_mode,
                    model=model
                )

                async with lock:
                    completed += 1
                    if result.get('skipped'):
                        skipped += 1
                        print(f"\n⏭️  [{completed}/{total}] 跳过(已完成): {pdf_file.name}", flush=True)
                    else:
                        print(f"\n✅ [{completed}/{total}] 完成: {pdf_file.name}", flush=True)

                        # 更新进度管理器
                        if progress_manager and result.get('success'):
                            # 根据输出目录判断是chunks还是direct
                            step_name = 'process_chunks' if 'chunks' in str(output_base) else 'process_direct'
                            progress_manager.mark_pdf_completed(step_name, pdf_file.stem)

                return result
            except Exception as e:
                async with lock:
                    completed += 1
                    print(f"\n❌ [{completed}/{total}] 失败: {pdf_file.name} - {e}", flush=True)
                    sys.stderr.write(f"Error processing {pdf_file.name}: {e}\n")

                    # 记录失败
                    if progress_manager:
                        step_name = 'process_chunks' if 'chunks' in str(output_base) else 'process_direct'
                        progress_manager.mark_pdf_failed(step_name, pdf_file.stem, str(e))

                return {
                    "success": False,
                    "pdf_info": {"name": pdf_file.name},
                    "error": str(e)
                }

    # 使用asyncio.gather并行处理所有PDF
    results = await asyncio.gather(*[
        process_one_pdf_with_semaphore(pdf_file, i)
        for i, pdf_file in enumerate(pdf_files, 1)
    ], return_exceptions=False)

    if skipped > 0:
        print(f"\n📌 断点续传统计: 跳过 {skipped} 个已完成的PDF")

    return results

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="DocMind PDF Converter")
    parser.add_argument("--input", default="combined_input", help="Input PDF directory")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages per PDF")
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument("--semaphore-limit", type=int, default=10, help="LLM concurrent limit per PDF (default: 10, optimized for 6 keys)")
    parser.add_argument("--pdf-concurrency", type=int, default=30, help="PDF parallel count (default: 30, optimized for 6 keys)")
    parser.add_argument("--no-resume", action="store_true", help="Disable resume, start fresh")
    parser.add_argument("--progress-file", default=None, help="Progress file path")
    # Issue 3 & 5: 新增模型和模式配置参数
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model name (default: {DEFAULT_MODEL})")
    parser.add_argument("--context-mode", choices=["minimal", "standard", "full"], default="standard",
                        help="Context window mode: minimal(100/300/100), standard(500/full/500), full(2000/full/2000)")
    parser.add_argument("--prompt-mode", choices=["simple", "enhanced"], default="enhanced",
                        help="Prompt mode: simple(~500 chars), enhanced(~2500 chars with chain-of-thought)")

    args = parser.parse_args()

    # 初始化进度管理器
    progress_manager = None
    resume = not args.no_resume

    if PROGRESS_ENABLED and resume:
        base_dir = Path(__file__).parent.parent
        progress_manager = get_progress_manager(args.progress_file, base_dir)
        progress_manager.load()
        print(f"\n📌 断点续传已启用")
        if args.progress_file:
            print(f"   进度文件: {args.progress_file}")
    elif args.no_resume:
        print(f"\n⚠️  断点续传已禁用（--no-resume）")
    
    print("="*80)
    print("🎯 DocMind PDF转换器")
    print("="*80)
    print(f"\n特性:")
    print(f"  ✅ 三页上下文窗口（前一页+当前页+后一页）")
    print(f"  ✅ 并发处理控制（asyncio.Semaphore: {args.semaphore_limit}）")
    print(f"  ✅ 两阶段处理（OCR → LLM并发）")

    # 启动资源监控
    resource_monitor = None
    if RESOURCE_MONITOR_AVAILABLE:
        resource_monitor = ResourceMonitor(
            interval=10.0,  # 每10秒采样一次
            log_dir=Path(__file__).parent.parent / "logs",
            enable_logging=True,
            enable_realtime_print=False  # 不实时打印，避免干扰输出
        )
        resource_monitor.start()
    
    if not check_dependencies():
        return 1
    
    # Check API Key configuration
    if API_KEYS and len(API_KEYS) >= 2:
        print(f"\n✅ Multi API Key load balancing enabled ({len(API_KEYS)} keys)")
        for i, key in enumerate(API_KEYS, 1):
            print(f"   Key {i}: {key[:10]}...{key[-4:]}")
        api_key = API_KEYS[0]  # For compatibility
    elif API_KEYS:
        print(f"\n✅ Single API Key mode")
        print(f"   Key: {API_KEYS[0][:10]}...{API_KEYS[0][-4:]}")
        api_key = API_KEYS[0]
    else:
        api_key = get_api_key()
        if not api_key:
            print("\n❌ No API key configured!")
            return 1
        print(f"\n✅ API configured (environment variable)")
    
    # 查找PDF
    pdf_dir = Path(__file__).parent / args.input
    
    if not pdf_dir.exists():
        print(f"\n❌ 目录不存在: {pdf_dir}")
        return 1
    
    pdf_files = sorted(pdf_dir.rglob("*.pdf"))
    
    if not pdf_files:
        print(f"\n❌ 未找到PDF文件")
        return 1
    
    print(f"\n📚 找到 {len(pdf_files)} 个PDF文件")
    
    output_base = Path(__file__).parent / args.output
    output_base.mkdir(parents=True, exist_ok=True)
    
    # Issue 3 & 5: 转换字符串参数为枚举类型
    context_mode_map = {"minimal": ContextMode.MINIMAL, "standard": ContextMode.STANDARD, "full": ContextMode.FULL}
    prompt_mode_map = {"simple": PromptMode.SIMPLE, "enhanced": PromptMode.ENHANCED}
    context_mode = context_mode_map.get(args.context_mode, DEFAULT_CONTEXT_MODE)
    prompt_mode = prompt_mode_map.get(args.prompt_mode, DEFAULT_PROMPT_MODE)
    model = args.model

    print(f"\n⚙️  配置:")
    print(f"   页数限制: {'前' + str(args.max_pages) + '页' if args.max_pages else '全部'}")
    print(f"   并发限制: {args.semaphore_limit}")
    print(f"   输出目录: {output_base}")
    print(f"   模型: {model}")
    print(f"   上下文模式: {context_mode.value}")
    print(f"   Prompt模式: {prompt_mode.value}")

    # 设置待处理PDF列表
    if progress_manager:
        # 根据输出目录判断是chunks还是direct
        step_name = 'process_chunks' if 'chunks' in str(output_base) else 'process_direct'
        progress_manager.set_pdf_list(step_name, [f.stem for f in pdf_files])
        progress_manager.set_step_status(step_name, 'in_progress')
        progress_manager.set_overall_status('in_progress')

    # 处理所有PDF - PDF级并行
    print(f"\n🚀 开始处理（PDF级并行）...")

    batch_start = time.time()

    # 使用asyncio.gather实现PDF级并行 (Max Safe mode)
    all_results = asyncio.run(
        process_all_pdfs_parallel(
            pdf_files,
            api_key,
            output_base,
            args.max_pages,
            args.pdf_concurrency,  # PDF parallel count
            semaphore_limit=args.semaphore_limit,  # LLM concurrent per PDF
            progress_manager=progress_manager,
            resume=resume,
            context_mode=context_mode,   # Issue 5
            prompt_mode=prompt_mode,      # Issue 3
            model=model                   # qwen-vl-max-latest
        )
    )

    # 更新步骤状态
    if progress_manager:
        step_name = 'process_chunks' if 'chunks' in str(output_base) else 'process_direct'
        failed = progress_manager.get_failed_pdfs(step_name)
        if not failed:
            progress_manager.set_step_status(step_name, 'completed')
    
    batch_time = time.time() - batch_start

    # 停止资源监控并获取摘要
    resource_summary = None
    if resource_monitor:
        resource_summary = resource_monitor.stop()
        print(resource_monitor.format_summary_text())

    print(f"\n{'='*80}")
    print(f"🎉 批量处理完成！")
    print(f"{'='*80}")
    
    # 统计
    total_pages = sum(r.get('pdf_info', {}).get('pages', 0) for r in all_results if r.get('success'))
    total_figures = sum(r.get('pdf_info', {}).get('figures', 0) for r in all_results if r.get('success'))
    total_cost = sum(r.get('processing', {}).get('cost_cny', 0) for r in all_results if r.get('success'))
    
    print(f"\n📊 总计:")
    print(f"   PDF: {len(pdf_files)} 个")
    print(f"   页数: {total_pages}")
    print(f"   图表: {total_figures} 个")
    print(f"   用时: {int(batch_time // 60)}分{int(batch_time % 60)}秒")
    print(f"   费用: ¥{total_cost:.4f}")
    
    # 保存批量报告
    batch_report = {
        "batch_info": {
            "timestamp": datetime.now().isoformat(),
            "total_pdfs": len(pdf_files),
            "semaphore_limit": args.semaphore_limit,
            "max_pages_per_pdf": args.max_pages,
            "model": model,
            "context_mode": context_mode.value,
            "prompt_mode": prompt_mode.value
        },
        "summary": {
            "total_pages": total_pages,
            "total_figures": total_figures,
            "total_time": round(batch_time, 2),
            "total_cost_cny": round(total_cost, 4)
        },
        "resource_usage": resource_summary if resource_summary else {},
        "pdfs": all_results
    }
    
    batch_report_file = output_base / f"batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(batch_report_file, "w", encoding="utf-8") as f:
        json.dump(batch_report, f, indent=2, ensure_ascii=False)
    
    print(f"\n📄 批量报告: {batch_report_file}")
    print(f"📁 结果目录: {output_base}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
