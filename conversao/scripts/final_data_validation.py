#!/usr/bin/env python3
"""
补救被内容审核拦截的页面 (并行版本)
使用 OpenAI GPT-4o-mini 重新处理

用法:
    python3 scripts/补救_moderation_blocked.py --dry-run      # 预览
    python3 scripts/补救_moderation_blocked.py                 # 执行 (默认10并发)
    python3 scripts/补救_moderation_blocked.py --concurrency 15  # 15并发

API 限制 (你的账户):
    - RPM: 5,000 请求/分钟
    - TPM: 2,000,000 tokens/分钟
    - 每页约 40,000 tokens → 理论最大 50 页/分钟
    - 建议并发: 10-15 (保守策略)
"""

import os
import sys
import json
import yaml
import glob
import base64
import asyncio
import argparse
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

# OpenAI
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("警告: openai 库未安装，请运行: pip install openai")

# 配置
CHUNKS_DIR = "output/chunks"
REPORT_FILE = "reports/moderation_blocked_pages.json"
# OpenAI API Key: 从环境变量读取
# 设置方式: export OPENAI_API_KEY="sk-xxx" 或在 .env 文件中配置

# 默认并发数
DEFAULT_CONCURRENCY = 10

# Prompt
EXTRACTION_PROMPT = """请将这张图片中的内容转换为 Markdown 格式。

要求：
1. 保持原有的段落结构和换行
2. 正确识别并格式化标题层级 (# ## ### 等)
3. 表格使用 Markdown 表格语法
4. 数学公式使用 LaTeX 语法 ($..$ 或 $$..$$)
5. 保持原文语言（不要翻译）
6. 不要添加任何解释，只输出转换后的内容

直接输出 Markdown 内容，不要用代码块包裹。"""


@dataclass
class ProcessResult:
    """处理结果"""
    chunk: str
    page: int
    success: bool
    content: str = ""
    error: str = ""
    tokens: int = 0
    duration: float = 0.0


@dataclass
class ProcessStats:
    """处理统计"""
    total: int = 0
    success: int = 0
    failed: int = 0
    total_tokens: int = 0
    total_duration: float = 0.0
    errors: List[Dict] = field(default_factory=list)


def load_openai_key() -> str:
    """从环境变量加载 OpenAI API Key"""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY 环境变量未设置。\n"
            "请设置: export OPENAI_API_KEY='sk-xxx' 或在 .env 文件中配置"
        )
    return api_key


def load_blocked_pages(chunks_dir: str = CHUNKS_DIR) -> List[Dict]:
    """加载被拦截的页面列表"""

    # 优先从报告文件加载
    report_path = Path(__file__).parent.parent / REPORT_FILE
    if report_path.exists():
        with open(report_path, 'r') as f:
            pages = json.load(f)
            # 确保 chunk_dir 字段存在
            for p in pages:
                if 'chunk_dir' not in p:
                    p['chunk_dir'] = str(Path(__file__).parent.parent / CHUNKS_DIR / p['chunk'])
            return pages

    # 从 validation.yaml 扫描
    blocked = []
    chunks_path = Path(__file__).parent.parent / chunks_dir

    for vfile in glob.glob(str(chunks_path / "*/*.validation.yaml")):
        try:
            with open(vfile, 'r') as f:
                data = yaml.safe_load(f)

            if not data or 'failed_pages_detail' not in data:
                continue

            chunk_dir = os.path.dirname(vfile)
            chunk_name = os.path.basename(chunk_dir)

            for item in data.get('failed_pages_detail', []):
                if isinstance(item, dict):
                    error = item.get('error', '')
                    if 'DataInspectionFailed' in str(error) and 'inappropriate' in str(error):
                        page = item.get('page')
                        png_path = os.path.join(chunk_dir, "images", f"page_{page:03d}.png")
                        if os.path.exists(png_path):
                            blocked.append({
                                'chunk': chunk_name,
                                'page': page,
                                'png_path': png_path,
                                'chunk_dir': chunk_dir
                            })
        except Exception as e:
            print(f"警告: 解析 {vfile} 失败: {e}")

    return blocked


def encode_image(image_path: str) -> str:
    """将图片编码为 base64"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode('utf-8')


async def process_page_async(
    page_info: Dict,
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    model: str = "gpt-4o-mini"
) -> ProcessResult:
    """异步处理单个页面"""

    chunk = page_info['chunk']
    page_num = page_info['page']
    png_path = page_info.get('png_path')

    if not png_path:
        png_path = os.path.join(page_info['chunk_dir'], "images", f"page_{page_num:03d}.png")

    result = ProcessResult(chunk=chunk, page=page_num, success=False)

    if not os.path.exists(png_path):
        result.error = f"PNG 不存在: {png_path}"
        return result

    async with semaphore:
        start_time = time.time()

        try:
            # 编码图片
            base64_image = encode_image(png_path)

            # 调用 GPT-4o-mini
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": EXTRACTION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=4096
            )

            result.content = response.choices[0].message.content
            result.tokens = response.usage.total_tokens
            result.success = True

        except Exception as e:
            result.error = str(e)

        result.duration = time.time() - start_time
        return result


def update_markdown_file(chunk_dir: str, page_num: int, content: str) -> bool:
    """将补救内容插入到 Markdown 文件"""
    import re

    # 找到对应的 .md 文件
    md_files = glob.glob(os.path.join(chunk_dir, "*.md"))
    if not md_files:
        return False

    md_file = md_files[0]

    try:
        with open(md_file, 'r', encoding='utf-8') as f:
            original = f.read()

        # 备份原文件
        backup_path = md_file + ".bak"
        if not os.path.exists(backup_path):
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(original)

        # 查找并替换页面内容
        # 格式: ## Page X\n[content until next ## Page or end]
        pattern = rf'(## Page {page_num}\n).*?(?=\n## Page |\Z)'
        replacement = f"## Page {page_num}\n\n<!-- Recovered by GPT-4o-mini -->\n{content}\n"

        new_content, count = re.subn(pattern, replacement, original, flags=re.DOTALL)

        if count == 0:
            # 页面标记不存在，追加到末尾
            new_content = original + f"\n\n## Page {page_num}\n\n<!-- Recovered by GPT-4o-mini -->\n{content}\n"

        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return True

    except Exception as e:
        print(f"    更新文件失败: {e}")
        return False


def update_validation_file(chunk_dir: str, page_num: int, success: bool):
    """更新 validation.yaml 标记页面已恢复"""
    validation_file = glob.glob(os.path.join(chunk_dir, "*.validation.yaml"))
    if not validation_file:
        return

    try:
        with open(validation_file[0], 'r') as f:
            data = yaml.safe_load(f)

        if not data:
            return

        # 更新 failed_pages_detail
        if 'failed_pages_detail' in data:
            for item in data['failed_pages_detail']:
                if item.get('page') == page_num:
                    if success:
                        item['recovered'] = True
                        item['recovered_by'] = 'gpt-4o-mini'
                        item['recovered_at'] = datetime.now().isoformat()
                    break

        # 添加恢复信息
        if 'recovery_info' not in data:
            data['recovery_info'] = {
                'recovery_date': datetime.now().isoformat(),
                'pages_recovered': 0,
                'recovery_method': 'gpt-4o-mini'
            }

        if success:
            data['recovery_info']['pages_recovered'] = data['recovery_info'].get('pages_recovered', 0) + 1

        with open(validation_file[0], 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    except Exception as e:
        pass


async def process_all_pages(
    pages: List[Dict],
    api_key: str,
    concurrency: int = DEFAULT_CONCURRENCY,
    model: str = "gpt-4o-mini"
) -> ProcessStats:
    """并行处理所有页面"""

    client = AsyncOpenAI(api_key=api_key)
    semaphore = asyncio.Semaphore(concurrency)
    stats = ProcessStats(total=len(pages))

    print(f"\n开始并行处理 {len(pages)} 页 (并发数: {concurrency})")
    print("=" * 70)

    # 创建所有任务
    tasks = [
        process_page_async(page, client, semaphore, model)
        for page in pages
    ]

    # 进度显示
    completed = 0
    start_time = time.time()

    for coro in asyncio.as_completed(tasks):
        result = await coro
        completed += 1

        # 状态符号
        if result.success:
            status = "✓"
            stats.success += 1
            stats.total_tokens += result.tokens

            # 更新文件
            chunk_dir = None
            for p in pages:
                if p['chunk'] == result.chunk and p['page'] == result.page:
                    chunk_dir = p.get('chunk_dir')
                    break

            if chunk_dir:
                if update_markdown_file(chunk_dir, result.page, result.content):
                    update_validation_file(chunk_dir, result.page, True)
                else:
                    status = "⚠"  # 文件更新失败
        else:
            status = "✗"
            stats.failed += 1
            stats.errors.append({
                'chunk': result.chunk,
                'page': result.page,
                'error': result.error
            })

        stats.total_duration += result.duration

        # 进度输出
        elapsed = time.time() - start_time
        rate = completed / elapsed if elapsed > 0 else 0
        eta = (len(pages) - completed) / rate if rate > 0 else 0

        print(f"  [{completed}/{len(pages)}] {status} {result.chunk} Page {result.page} "
              f"({result.duration:.1f}s, {result.tokens} tokens) "
              f"[{rate:.1f} 页/秒, ETA: {eta:.0f}s]")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='补救被内容审核拦截的页面 (并行版本)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python3 scripts/补救_moderation_blocked.py --dry-run       # 预览
    python3 scripts/补救_moderation_blocked.py                  # 执行
    python3 scripts/补救_moderation_blocked.py --concurrency 15 # 15并发
    python3 scripts/补救_moderation_blocked.py --limit 10       # 只处理前10页

API 限制 (你的账户):
    - RPM: 5,000 请求/分钟
    - TPM: 2,000,000 tokens/分钟
    - 建议并发: 10-15
        """
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='只预览，不实际处理')
    parser.add_argument('--concurrency', type=int, default=DEFAULT_CONCURRENCY,
                        help=f'并发数 (默认: {DEFAULT_CONCURRENCY})')
    parser.add_argument('--limit', type=int, default=0,
                        help='限制处理数量 (0=全部)')
    parser.add_argument('--model', type=str, default='gpt-4o-mini',
                        help='模型 (默认: gpt-4o-mini)')
    parser.add_argument('--chunks-dir', type=str, default=CHUNKS_DIR,
                        help=f'Chunks目录 (默认: {CHUNKS_DIR})')

    args = parser.parse_args()

    if not OPENAI_AVAILABLE:
        print("错误: 请先安装 openai 库")
        print("  pip install openai")
        sys.exit(1)

    print("=" * 70)
    print("DocMind 内容审核补救工具 (并行版)")
    print("=" * 70)

    # 加载 API Key
    try:
        api_key = load_openai_key()
        print(f"✓ API Key 已加载: {api_key[:20]}...{api_key[-4:]}")
    except Exception as e:
        print(f"✗ 加载 API Key 失败: {e}")
        sys.exit(1)

    # 加载被拦截的页面
    blocked = load_blocked_pages(args.chunks_dir)
    print(f"✓ 发现 {len(blocked)} 个被拦截的页面")

    if args.limit > 0:
        blocked = blocked[:args.limit]
        print(f"  限制处理前 {args.limit} 个")

    if not blocked:
        print("\n没有需要处理的页面")
        return

    # 成本估算
    estimated_tokens = len(blocked) * 40000
    estimated_cost_usd = estimated_tokens * 0.15 / 1000000  # $0.15/1M input tokens
    estimated_cost_cny = estimated_cost_usd * 7.2

    print(f"\n预估:")
    print(f"  - Tokens: ~{estimated_tokens:,}")
    print(f"  - 成本: ${estimated_cost_usd:.4f} (约 ¥{estimated_cost_cny:.2f})")
    print(f"  - 并发数: {args.concurrency}")
    print(f"  - 预计时间: ~{len(blocked) / args.concurrency * 3:.0f} 秒")

    if args.dry_run:
        print("\n[预览模式] 将处理以下页面:")
        for i, page in enumerate(blocked[:20]):
            png_exists = "✓" if os.path.exists(page.get('png_path', '')) else "✗"
            print(f"  {i+1}. {page['chunk']} - Page {page['page']} [PNG: {png_exists}]")
        if len(blocked) > 20:
            print(f"  ... 还有 {len(blocked) - 20} 页")
        return

    # 确认执行
    print(f"\n即将处理 {len(blocked)} 页，预计成本 ¥{estimated_cost_cny:.2f}")
    confirm = input("是否继续? [y/N]: ").strip().lower()
    if confirm != 'y':
        print("已取消")
        return

    # 执行处理
    stats = asyncio.run(process_all_pages(
        blocked,
        api_key,
        concurrency=args.concurrency,
        model=args.model
    ))

    # 输出统计
    print("\n" + "=" * 70)
    print("处理完成")
    print("=" * 70)
    print(f"  总页数: {stats.total}")
    print(f"  成功: {stats.success}")
    print(f"  失败: {stats.failed}")
    print(f"  总 Tokens: {stats.total_tokens:,}")
    print(f"  总耗时: {stats.total_duration:.1f}s")
    print(f"  平均速度: {stats.total / stats.total_duration:.1f} 页/秒" if stats.total_duration > 0 else "")

    if stats.errors:
        print(f"\n失败页面:")
        for err in stats.errors[:10]:
            print(f"  - {err['chunk']} Page {err['page']}: {err['error'][:50]}")
        if len(stats.errors) > 10:
            print(f"  ... 还有 {len(stats.errors) - 10} 个错误")

    # 保存报告
    report_path = Path(__file__).parent.parent / "reports" / "recovery_report.json"
    report_path.parent.mkdir(exist_ok=True)

    report = {
        'timestamp': datetime.now().isoformat(),
        'model': args.model,
        'concurrency': args.concurrency,
        'stats': {
            'total': stats.total,
            'success': stats.success,
            'failed': stats.failed,
            'total_tokens': stats.total_tokens,
            'total_duration': stats.total_duration
        },
        'errors': stats.errors
    }

    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()
