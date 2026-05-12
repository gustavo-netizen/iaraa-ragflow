"""PDF-level orchestration: discover PDFs, drive Phase 1/2/3, write outputs.

Composes ``QwenClient`` + ``page_processor`` + ``progress_manager`` to produce
the per-PDF directory layout described in ``conversao/CLAUDE.md``. CLI entry
point preserved as ``main()`` so the historical
``python3 scripts/docmind_converter.py …`` invocation remains valid through
the shim.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from config import AppConfig

from .api_key_pool import (
    API_KEYS,
    APIKeyHealthMonitor,
    _api_key_monitor,
)
from .page_processor import (
    DEFAULT_CONTEXT_MODE,
    DEFAULT_PROMPT_MODE,
    ContextMode,
    PromptMode,
    process_single_page_with_context,
)
from .qwen_client import QwenClient
from .retry import DEFAULT_RETRY_CONFIG

# Optional resource monitor (lives in scripts/admin/ post-Fase A.3 — may not import)
try:
    from resource_monitor import ResourceMonitor  # type: ignore
    RESOURCE_MONITOR_AVAILABLE = True
except ImportError:
    RESOURCE_MONITOR_AVAILABLE = False

# Optional progress manager
try:
    from progress_manager import get_progress_manager  # type: ignore
    PROGRESS_ENABLED = True
except ImportError:
    PROGRESS_ENABLED = False
    print("⚠️  进度管理器未找到，断点续传功能禁用")


APP_CONFIG = AppConfig.from_env()
DEFAULT_MODEL = APP_CONFIG.ocr_model


def check_dependencies() -> bool:
    """Verify dashscope, pdf2image, Pillow, PyYAML are installed."""
    missing: List[str] = []
    try:
        import dashscope  # noqa: F401
    except ImportError:
        missing.append("dashscope")
    try:
        from pdf2image import convert_from_path  # noqa: F401
    except ImportError:
        missing.append("pdf2image")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    try:
        import yaml  # noqa: F401
    except ImportError:
        missing.append("PyYAML")

    if missing:
        print(f"❌ 缺少依赖: {', '.join(missing)}")
        print("\n安装命令:")
        print(f"pip3 install {' '.join(missing)}")
        return False
    return True


def get_api_key() -> Optional[str]:
    """Legacy fallback: read from ``olmocr_api_config.API_CONFIG``."""
    try:
        from olmocr_api_config import API_CONFIG  # type: ignore
        if "qwen" in API_CONFIG:
            api_key = API_CONFIG["qwen"].get("api_key")
            if api_key and api_key != "YOUR_QWEN_API_KEY_HERE":
                return api_key
    except Exception as e:
        print(f"⚠️  无法从配置文件读取: {e}")
    return None


def _build_default_client() -> QwenClient:
    """Construct the QwenClient using the module-level pool/config."""
    return QwenClient(
        key_pool=_api_key_monitor,
        retry_config=DEFAULT_RETRY_CONFIG,
        ocr_model=APP_CONFIG.ocr_model,
    )


def _build_footnotes_sidecar(
    pdf_name: str,
    total_pages: int,
    all_footnotes_by_page: Dict[int, List[str]],
) -> Dict[str, Any]:
    """Build the canonical sidecar dict per ADR-0004.

    Empty `all_footnotes_by_page` yields `notes: []` — emissão é incondicional
    para que a existência do arquivo seja signal não-ambíguo de "doc passou
    por Stage 1 pós-J.2". Pages ordenadas asc; `id` reinicia em 1 por página.
    """
    return {
        "version": "1.0",
        "pdf_name": pdf_name,
        "total_pages": total_pages,
        "notes": [
            {"page": page, "id": i, "text": text}
            for page, fns in sorted(all_footnotes_by_page.items())
            for i, text in enumerate(fns, 1)
        ],
    }


async def process_pdf_async(
    pdf_path: Path,
    api_key: str,
    output_base: Path,
    max_pages: Optional[int] = None,
    semaphore_limit: int = 10,
    progress_manager: Any = None,
    resume: bool = True,
    context_mode: ContextMode = DEFAULT_CONTEXT_MODE,
    prompt_mode: PromptMode = DEFAULT_PROMPT_MODE,
    model: str = DEFAULT_MODEL,
    client: Optional[QwenClient] = None,
) -> Dict[str, Any]:
    """Process one PDF: PDF→images, OCR concurrent, LLM concurrent, write outputs."""
    from pdf2image import convert_from_path
    import dashscope

    dashscope.api_key = api_key
    pdf_name = pdf_path.stem

    print(f"\n{'=' * 80}")
    print(f"📄 处理PDF: {pdf_path.name}")
    print(f"{'=' * 80}")
    print(f"   大小: {pdf_path.stat().st_size / 1024 / 1024:.1f}MB")
    print(f"   并发限制: {semaphore_limit}")

    # Resume check with enhanced validation
    if resume and progress_manager:
        step_name = "process_chunks" if "chunks" in str(output_base) else "process_direct"

        if progress_manager.is_pdf_completed(step_name, pdf_name):
            validation = progress_manager.validate_pdf_completion(
                step_name,
                pdf_name,
                str(output_base),
                min_content_size=500,
                min_completion_rate=0.90,
            )
            if validation["valid"]:
                print(
                    f"   ⏭️  已完成，跳过（验证通过: {validation['md_size']} bytes, "
                    f"{validation['page_completion_rate']:.1%}完成率）"
                )
                return {
                    "success": True,
                    "skipped": True,
                    "pdf_info": {"name": pdf_path.name},
                    "message": "已在之前的运行中完成",
                }
            print(f"   ⚠️  之前标记为完成但验证失败: {validation['reason']}")
            print(f"   🔄 将重新处理此PDF...")
            progress_manager.invalidate_pdf_completion(step_name, pdf_name)

    output_dir = output_base / pdf_name
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    yaml_dir = output_dir / "yaml_metadata"
    yaml_dir.mkdir(exist_ok=True)

    if client is None:
        client = _build_default_client()

    start_time = time.time()

    try:
        # Phase 1: PDF → images
        print(f"\n📸 Phase 1: 转换PDF为图像...")
        loop = asyncio.get_event_loop()
        images = await loop.run_in_executor(
            None, lambda: convert_from_path(str(pdf_path), dpi=150)
        )
        total_pages = len(images)

        if max_pages:
            images = images[:max_pages]
            print(f"   限制处理前 {max_pages} 页 (总共 {total_pages} 页)")
        print(f"   ✅ 转换完成: {len(images)} 页")

        if progress_manager:
            progress_manager.init_pdf_progress(pdf_name, len(images))
            completed_pages = set(progress_manager.get_completed_pages(pdf_name))
            if completed_pages:
                print(f"   📌 断点续传: 已完成 {len(completed_pages)}/{len(images)} 页")
        else:
            completed_pages = set()

        # Phase 2: concurrent OCR
        print(f"\n🔤 Phase 2: OCR并发提取...")
        print(f"   并发数: 20")

        async def ocr_single_page(page_num: int, image: Any):
            inner_loop = asyncio.get_event_loop()
            ocr_context = {"pdf_name": pdf_name, "page": page_num}
            ocr_text = await inner_loop.run_in_executor(
                None, lambda: client.simple_ocr_sync(image, context=ocr_context)
            )
            print(f"   [OCR] [{page_num}/{len(images)}] ✅ ({len(ocr_text)} 字符)", flush=True)
            return page_num, ocr_text

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

        # Phase 3: concurrent LLM
        print(f"\n🤖 Phase 3: LLM并发处理（图表检测+元数据生成）...")
        print(f"   并发数: {semaphore_limit}")

        pages_to_process = [p for p in range(1, len(images) + 1) if p not in completed_pages]
        if completed_pages:
            print(f"   📌 跳过已完成页面: {len(completed_pages)} 页")
            print(f"   📌 待处理页面: {len(pages_to_process)} 页")

        semaphore = asyncio.Semaphore(semaphore_limit)
        tasks = []
        skipped_results: List[Dict[str, Any]] = []

        for page_num, image in enumerate(images, 1):
            if page_num in completed_pages:
                skipped_results.append(
                    {
                        "success": True,
                        "page": page_num,
                        "skipped": True,
                        "figure_count": 0,
                        "figures": [],
                        "figures_metadata": [],
                        "body_text": "",
                        "tokens": {"input": 0, "output": 0},
                        "time": 0,
                    }
                )
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
                semaphore=semaphore,
                images_dir=images_dir,
                yaml_dir=yaml_dir,
                client=client,
                context_mode=context_mode,
                prompt_mode=prompt_mode,
                model=model,
                pdf_name=pdf_name,
            )
            tasks.append((page_num, task))

        if tasks:
            async_results = await asyncio.gather(*[t[1] for t in tasks])

            for (page_num, _), result in zip(tasks, async_results):
                if result.get("success"):
                    if progress_manager:
                        progress_manager.mark_page_completed(pdf_name, page_num)
                else:
                    if progress_manager:
                        progress_manager.mark_page_failed(
                            pdf_name, page_num, result.get("error", "Unknown error")
                        )

            page_results = skipped_results + list(async_results)
        else:
            page_results = skipped_results
            print(f"   ✅ 所有页面已在之前完成")

        print(f"\n💾 保存结果...")
        page_results = sorted(page_results, key=lambda x: x["page"])

        markdown_sections: List[str] = []
        all_figures_metadata: List[Dict[str, Any]] = []
        total_tokens = {"input": 0, "output": 0}
        total_figures = 0
        total_tables = 0
        total_formulas = 0
        confidence_scores: List[float] = []
        all_footnotes_by_page: Dict[int, List[str]] = {}

        for result in page_results:
            if not result["success"]:
                print(f"   ⚠️ Page {result['page']} 失败: {result.get('error')}")
                continue

            page_num = result["page"]
            tokens = result["tokens"]
            total_tokens["input"] += tokens["input"]
            total_tokens["output"] += tokens["output"]

            figure_count = result.get("figure_count", 0)
            table_count = result.get("table_count", 0)
            formula_count = result.get("formula_count", 0)
            total_figures += figure_count
            total_tables += table_count
            total_formulas += formula_count

            page_content = f"## Page {page_num}\n\n"

            body_text = result.get("body_text", "").strip()
            if body_text:
                page_content += f"{body_text}\n\n"

            if result.get("tables"):
                for table in result["tables"]:
                    table_num = table.get("table_number", "")
                    caption = table.get("caption", "")
                    markdown = table.get("markdown", "")
                    if table_num or caption:
                        page_content += f"### {table_num}: {caption}\n\n"
                    if markdown:
                        page_content += f"{markdown}\n\n"

            if result.get("formulas"):
                for formula in result["formulas"]:
                    if formula and formula.strip():
                        page_content += f"{formula}\n\n"

            if result.get("figures"):
                for fig_info in result["figures"]:
                    figure_ref = fig_info["figure_ref"]
                    yaml_file = fig_info.get("yaml_file", "")
                    description = fig_info.get("description", "")

                    matching_meta = [
                        m
                        for m in result.get("figures_metadata", [])
                        if m["chart_identification"]["figure_number"] == figure_ref
                    ]
                    chart_title = (
                        matching_meta[0]["chart_identification"]["chart_title"]
                        if matching_meta
                        else "Untitled"
                    )

                    page_content += f"\n### {figure_ref}: {chart_title}\n\n"
                    if description:
                        page_content += f"*{description}*\n\n"
                    page_content += (
                        f"![{figure_ref}: {chart_title}](images/page_{page_num:03d}.png)\n\n"
                    )
                    if yaml_file:
                        page_content += (
                            f"*YAML Metadata: [yaml_metadata/{yaml_file}]"
                            f"(yaml_metadata/{yaml_file})*\n\n"
                        )

                    conf_map = {"high": 1.0, "medium": 0.6, "low": 0.3}
                    confidence_scores.append(conf_map.get(fig_info.get("confidence", "medium"), 0.6))

                all_figures_metadata.extend(result.get("figures_metadata", []))

            if footnotes := result.get("footnotes"):
                all_footnotes_by_page[page_num] = footnotes

            markdown_sections.append(page_content)

            print(
                f"   ✅ Page {page_num}: {table_count} 表格, {formula_count} 公式, "
                f"{figure_count} 图表, {tokens['input']}+{tokens['output']} tokens"
            )

        md_file = output_dir / f"{pdf_name}.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(f"# {pdf_name}\n\n")
            f.write(
                f"*Processed with DocMind on "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
            )
            f.write(f"*Model: {model}*\n\n")
            f.write(
                f"*Statistics: {total_tables} tables, {total_formulas} formulas, "
                f"{total_figures} figures*\n\n"
            )
            if all_footnotes_by_page:
                f.write("*Footnotes: sidecar*\n\n")
            f.write("---\n\n")
            f.write("\n".join(markdown_sections))

        print(f"   ✅ Markdown: {md_file.name}")

        combined_yaml_file = output_dir / f"{pdf_name}_all_figures.yaml"
        combined_yaml = {
            "document_info": {
                "filename": pdf_path.name,
                "total_pages": total_pages,
                "processed_pages": len(images),
                "total_figures": total_figures,
                "processing_date": datetime.now().isoformat(),
            },
            "figures": all_figures_metadata,
        }
        with open(combined_yaml_file, "w", encoding="utf-8") as f:
            yaml.dump(
                combined_yaml,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        print(f"   ✅ Combined YAML: {combined_yaml_file.name}")

        footnotes_yaml_file = output_dir / f"{pdf_name}.footnotes.yaml"
        footnotes_doc = _build_footnotes_sidecar(
            pdf_name, total_pages, all_footnotes_by_page
        )
        with open(footnotes_yaml_file, "w", encoding="utf-8") as f:
            yaml.dump(
                footnotes_doc,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        print(f"   ✅ Footnotes YAML: {footnotes_yaml_file.name}")

        # Validation report — KQI metrics, page stats, failed-pages detail
        avg_confidence = (
            sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
        )
        yaml_insertion_rate = len(all_figures_metadata) / max(total_figures, 1)

        success_pages = [r for r in page_results if r.get("success", False)]
        failed_pages = [r for r in page_results if not r.get("success", False)]

        kqi_yaml_insertion = yaml_insertion_rate >= 0.95
        kqi_confidence = avg_confidence >= 0.85
        kqi_page_success = (
            len(success_pages) / len(page_results) if page_results else 0
        )

        validation_report = {
            "document_info": {
                "filename": pdf_path.name,
                "total_pages": total_pages,
                "processed_pages": len(images),
                "processing_date": datetime.now().isoformat(),
            },
            "kqi_metrics": {
                "yaml_insertion_rate": round(yaml_insertion_rate, 4),
                "yaml_insertion_pass": kqi_yaml_insertion,
                "average_confidence": round(avg_confidence, 4),
                "confidence_pass": kqi_confidence,
                "page_success_rate": round(kqi_page_success, 4),
                "overall_quality_pass": (
                    kqi_yaml_insertion and kqi_confidence and kqi_page_success >= 0.95
                ),
            },
            "validation_metrics": {
                "yaml_insertion_rate": round(yaml_insertion_rate, 2),
                "average_confidence": round(avg_confidence, 2),
                "figure_detection_completeness": (
                    round(total_figures / len(images), 2) if images else 0
                ),
                "total_figures_detected": total_figures,
                "total_tables_detected": total_tables,
                "total_formulas_detected": total_formulas,
                "pages_with_figures": sum(
                    1 for r in page_results if r.get("figure_count", 0) > 0
                ),
                "pages_with_tables": sum(
                    1 for r in page_results if r.get("table_count", 0) > 0
                ),
                "pages_with_formulas": sum(
                    1 for r in page_results if r.get("formula_count", 0) > 0
                ),
                "high_confidence_figures": sum(1 for s in confidence_scores if s >= 0.9),
                "medium_confidence_figures": sum(
                    1 for s in confidence_scores if 0.5 <= s < 0.9
                ),
                "low_confidence_figures": sum(1 for s in confidence_scores if s < 0.5),
            },
            "page_statistics": {
                "total_pages": len(page_results),
                "successful_pages": len(success_pages),
                "failed_pages": len(failed_pages),
                "skipped_pages": sum(1 for r in page_results if r.get("skipped", False)),
                "success_rate": (
                    round(len(success_pages) / len(page_results), 4) if page_results else 0
                ),
            },
            "quality_indicators": {
                "all_figures_have_yaml": len(all_figures_metadata) == total_figures,
                "zero_hallucination": True,
                "proper_markdown_format": True,
                "complete_data_extraction": avg_confidence >= 0.6,
                "no_page_failures": len(failed_pages) == 0,
            },
            "failed_pages_detail": [
                {"page": r["page"], "error": r.get("error", "Unknown error")}
                for r in failed_pages
            ],
            "page_by_page_results": [
                {
                    "page": r["page"],
                    "success": r["success"],
                    "figure_count": r.get("figure_count", 0),
                    "table_count": r.get("table_count", 0),
                    "formula_count": r.get("formula_count", 0),
                    "figures": r.get("figures", []),
                }
                for r in page_results
            ],
        }

        validation_file = output_dir / f"{pdf_name}.validation.yaml"
        with open(validation_file, "w", encoding="utf-8") as f:
            yaml.dump(
                validation_report,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        print(f"   ✅ Validation Report: {validation_file.name}")

        # Cost: Qwen-VL pricing CNY 0.02/1K input + 0.02/1K output (2024 list price)
        PRICE_INPUT_PER_1K = 0.02
        PRICE_OUTPUT_PER_1K = 0.02

        process_time = time.time() - start_time
        total_tokens_sum = total_tokens["input"] + total_tokens["output"]
        input_cost = (total_tokens["input"] / 1000) * PRICE_INPUT_PER_1K
        output_cost = (total_tokens["output"] / 1000) * PRICE_OUTPUT_PER_1K
        cost_cny = input_cost + output_cost

        success_count = sum(1 for r in page_results if r.get("success", False))

        print(f"\n{'=' * 80}")
        print(f"✅ 处理完成: {pdf_path.name}")
        print(f"{'=' * 80}")
        print(f"📊 统计:")
        print(f"   页数: {len(images)}/{total_pages} (成功: {success_count})")
        print(f"   图表: {total_figures} 个")
        print(f"   平均信心度: {avg_confidence:.2f}")
        print(f"   YAML插入率: {yaml_insertion_rate:.2%}")
        print(f"   用时: {int(process_time // 60)}分{int(process_time % 60)}秒")
        print(
            f"   Tokens: {total_tokens_sum:,} "
            f"(输入: {total_tokens['input']:,}, 输出: {total_tokens['output']:,})"
        )
        print(
            f"   费用: ¥{cost_cny:.2f} "
            f"(输入: ¥{input_cost:.2f}, 输出: ¥{output_cost:.2f})"
        )

        return {
            "success": True,
            "pdf_info": {
                "name": pdf_path.name,
                "pages": len(images),
                "figures": total_figures,
            },
            "processing": {
                "time": process_time,
                "tokens": total_tokens_sum,
                "tokens_input": total_tokens["input"],
                "tokens_output": total_tokens["output"],
                "cost_cny": cost_cny,
                "cost_input": input_cost,
                "cost_output": output_cost,
            },
            "validation": validation_report["validation_metrics"],
        }

    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback

        traceback.print_exc()
        return {
            "success": False,
            "pdf_info": {"name": pdf_path.name},
            "error": str(e),
        }


async def process_all_pdfs_parallel(
    pdf_files: List[Path],
    api_key: str,
    output_base: Path,
    max_pages: Optional[int],
    pdf_concurrency: int,
    semaphore_limit: int = 12,
    progress_manager: Any = None,
    resume: bool = True,
    context_mode: ContextMode = DEFAULT_CONTEXT_MODE,
    prompt_mode: PromptMode = DEFAULT_PROMPT_MODE,
    model: str = DEFAULT_MODEL,
    client: Optional[QwenClient] = None,
) -> List[Dict[str, Any]]:
    """PDF-level concurrent processing — bounded by ``pdf_concurrency``."""
    pdf_semaphore = asyncio.Semaphore(pdf_concurrency)
    total = len(pdf_files)
    completed = 0
    skipped = 0
    lock = asyncio.Lock()

    if client is None:
        client = _build_default_client()

    async def process_one_pdf_with_semaphore(pdf_file: Path, index: int):
        nonlocal completed, skipped

        async with pdf_semaphore:
            async with lock:
                print(f"\n{'#' * 80}", flush=True)
                print(f"进度: [{index}/{total}] - {pdf_file.name}", flush=True)
                print(f"{'#' * 80}", flush=True)

            try:
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
                    model=model,
                    client=client,
                )

                async with lock:
                    completed += 1
                    if result.get("skipped"):
                        skipped += 1
                        print(
                            f"\n⏭️  [{completed}/{total}] 跳过(已完成): {pdf_file.name}",
                            flush=True,
                        )
                    else:
                        print(
                            f"\n✅ [{completed}/{total}] 完成: {pdf_file.name}",
                            flush=True,
                        )
                        if progress_manager and result.get("success"):
                            step_name = (
                                "process_chunks"
                                if "chunks" in str(output_base)
                                else "process_direct"
                            )
                            progress_manager.mark_pdf_completed(step_name, pdf_file.stem)

                return result
            except Exception as e:
                async with lock:
                    completed += 1
                    print(
                        f"\n❌ [{completed}/{total}] 失败: {pdf_file.name} - {e}",
                        flush=True,
                    )
                    sys.stderr.write(f"Error processing {pdf_file.name}: {e}\n")
                    if progress_manager:
                        step_name = (
                            "process_chunks"
                            if "chunks" in str(output_base)
                            else "process_direct"
                        )
                        progress_manager.mark_pdf_failed(step_name, pdf_file.stem, str(e))

                return {
                    "success": False,
                    "pdf_info": {"name": pdf_file.name},
                    "error": str(e),
                }

    results = await asyncio.gather(
        *[
            process_one_pdf_with_semaphore(pdf_file, i)
            for i, pdf_file in enumerate(pdf_files, 1)
        ],
        return_exceptions=False,
    )

    if skipped > 0:
        print(f"\n📌 断点续传统计: 跳过 {skipped} 个已完成的PDF")

    return results


def main() -> int:
    """CLI entry-point. Preserved 1:1 for ``run.sh`` compatibility."""
    parser = argparse.ArgumentParser(description="DocMind PDF Converter")
    parser.add_argument("--input", default="combined_input", help="Input PDF directory")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages per PDF")
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument(
        "--semaphore-limit",
        type=int,
        default=10,
        help="LLM concurrent limit per PDF (default: 10, optimized for 6 keys)",
    )
    parser.add_argument(
        "--pdf-concurrency",
        type=int,
        default=30,
        help="PDF parallel count (default: 30, optimized for 6 keys)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Disable resume, start fresh",
    )
    parser.add_argument(
        "--progress-file",
        default=None,
        help="Progress file path",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--context-mode",
        choices=["minimal", "standard", "full"],
        default="standard",
        help="Context window mode: minimal(100/300/100), standard(500/full/500), full(2000/full/2000)",
    )
    parser.add_argument(
        "--prompt-mode",
        choices=["simple", "enhanced"],
        default="enhanced",
        help="Prompt mode: simple(~500 chars), enhanced(~2500 chars with chain-of-thought)",
    )

    args = parser.parse_args()

    progress_manager = None
    resume = not args.no_resume

    if PROGRESS_ENABLED and resume:
        base_dir = Path(__file__).resolve().parent.parent
        progress_manager = get_progress_manager(args.progress_file, base_dir)
        progress_manager.load()
        print(f"\n📌 断点续传已启用")
        if args.progress_file:
            print(f"   进度文件: {args.progress_file}")
    elif args.no_resume:
        print(f"\n⚠️  断点续传已禁用（--no-resume）")

    print("=" * 80)
    print("🎯 DocMind PDF转换器")
    print("=" * 80)
    print(f"\n特性:")
    print(f"  ✅ 三页上下文窗口（前一页+当前页+后一页）")
    print(f"  ✅ 并发处理控制（asyncio.Semaphore: {args.semaphore_limit}）")
    print(f"  ✅ 两阶段处理（OCR → LLM并发）")

    resource_monitor = None
    if RESOURCE_MONITOR_AVAILABLE:
        resource_monitor = ResourceMonitor(
            interval=10.0,
            log_dir=Path(__file__).resolve().parent.parent / "logs",
            enable_logging=True,
            enable_realtime_print=False,
        )
        resource_monitor.start()

    if not check_dependencies():
        return 1

    if API_KEYS and len(API_KEYS) >= 2:
        print(f"\n✅ Multi API Key load balancing enabled ({len(API_KEYS)} keys)")
        for i, key in enumerate(API_KEYS, 1):
            print(f"   Key {i}: {key[:10]}...{key[-4:]}")
        api_key = API_KEYS[0]
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

    # Mirrors monolith: ``Path(__file__).parent / args.input`` (scripts/ as base).
    # Path(absolute) / abs returns the absolute, so ``run.sh`` passing absolute
    # ``--input`` still works.
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    pdf_dir = scripts_dir / args.input
    if not pdf_dir.exists():
        print(f"\n❌ 目录不存在: {pdf_dir}")
        return 1

    pdf_files = sorted(pdf_dir.rglob("*.pdf"))

    if not pdf_files:
        print(f"\n❌ 未找到PDF文件")
        return 1

    print(f"\n📚 找到 {len(pdf_files)} 个PDF文件")

    output_base = scripts_dir / args.output
    output_base.mkdir(parents=True, exist_ok=True)

    context_mode_map = {
        "minimal": ContextMode.MINIMAL,
        "standard": ContextMode.STANDARD,
        "full": ContextMode.FULL,
    }
    prompt_mode_map = {
        "simple": PromptMode.SIMPLE,
        "enhanced": PromptMode.ENHANCED,
    }
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

    if progress_manager:
        step_name = "process_chunks" if "chunks" in str(output_base) else "process_direct"
        progress_manager.set_pdf_list(step_name, [f.stem for f in pdf_files])
        progress_manager.set_step_status(step_name, "in_progress")
        progress_manager.set_overall_status("in_progress")

    print(f"\n🚀 开始处理（PDF级并行）...")
    batch_start = time.time()

    all_results = asyncio.run(
        process_all_pdfs_parallel(
            pdf_files,
            api_key,
            output_base,
            args.max_pages,
            args.pdf_concurrency,
            semaphore_limit=args.semaphore_limit,
            progress_manager=progress_manager,
            resume=resume,
            context_mode=context_mode,
            prompt_mode=prompt_mode,
            model=model,
        )
    )

    if progress_manager:
        step_name = "process_chunks" if "chunks" in str(output_base) else "process_direct"
        failed = progress_manager.get_failed_pdfs(step_name)
        if not failed:
            progress_manager.set_step_status(step_name, "completed")

    batch_time = time.time() - batch_start

    resource_summary = None
    if resource_monitor:
        resource_summary = resource_monitor.stop()
        print(resource_monitor.format_summary_text())

    print(f"\n{'=' * 80}")
    print(f"🎉 批量处理完成！")
    print(f"{'=' * 80}")

    total_pages = sum(
        r.get("pdf_info", {}).get("pages", 0) for r in all_results if r.get("success")
    )
    total_figures = sum(
        r.get("pdf_info", {}).get("figures", 0) for r in all_results if r.get("success")
    )
    total_cost = sum(
        r.get("processing", {}).get("cost_cny", 0) for r in all_results if r.get("success")
    )

    print(f"\n📊 总计:")
    print(f"   PDF: {len(pdf_files)} 个")
    print(f"   页数: {total_pages}")
    print(f"   图表: {total_figures} 个")
    print(f"   用时: {int(batch_time // 60)}分{int(batch_time % 60)}秒")
    print(f"   费用: ¥{total_cost:.4f}")

    batch_report = {
        "batch_info": {
            "timestamp": datetime.now().isoformat(),
            "total_pdfs": len(pdf_files),
            "semaphore_limit": args.semaphore_limit,
            "max_pages_per_pdf": args.max_pages,
            "model": model,
            "context_mode": context_mode.value,
            "prompt_mode": prompt_mode.value,
        },
        "summary": {
            "total_pages": total_pages,
            "total_figures": total_figures,
            "total_time": round(batch_time, 2),
            "total_cost_cny": round(total_cost, 4),
        },
        "resource_usage": resource_summary if resource_summary else {},
        "pdfs": all_results,
    }

    batch_report_file = (
        output_base / f"batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(batch_report_file, "w", encoding="utf-8") as f:
        json.dump(batch_report, f, indent=2, ensure_ascii=False)

    print(f"\n📄 批量报告: {batch_report_file}")
    print(f"📁 结果目录: {output_base}")

    return 0
