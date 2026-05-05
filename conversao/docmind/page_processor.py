"""Per-page Phase-3 orchestration: prompt building + LLM call + result parsing.

Owns the chain-of-thought prompt template, context-window logic, the prompt
mode auto-detection, and the YAML metadata generator. Talks to dashscope only
through ``QwenClient`` — no direct ``MultiModalConversation`` import here.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .qwen_client import CallResult, QwenClient, safe_get_text_from_response
from .retry import RetryConfig

# ============ Context window + prompt modes ============


class ContextMode(Enum):
    """Three-page context window sizing."""

    MINIMAL = "minimal"
    STANDARD = "standard"
    FULL = "full"


class PromptMode(Enum):
    """Prompt template selection."""

    SIMPLE = "simple"
    ENHANCED = "enhanced"


DEFAULT_CONTEXT_MODE = ContextMode.STANDARD
DEFAULT_PROMPT_MODE = PromptMode.ENHANCED


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


CHART_INDICATORS = [
    r"Figure\s*\d+", r"Fig\.\s*\d+", r"Table\s*\d+",
    r"Chart\s*\d+", r"Graph\s*\d+", r"Diagram\s*\d+",
    r"%", r"\$\d", r"million", r"billion", r"percent",
    r"x[\-\s]?axis", r"y[\-\s]?axis", r"legend",
    r"scatter", r"histogram", r"bar chart", r"pie chart",
]


def has_chart_indicators(ocr_text: Optional[str]) -> bool:
    """Detect chart-related keywords in OCR text (used to upgrade SIMPLE→ENHANCED)."""
    if not ocr_text:
        return False
    for pattern in CHART_INDICATORS:
        if re.search(pattern, ocr_text, re.IGNORECASE):
            return True
    return False


def build_context_window(
    prev_ocr: str,
    current_ocr: str,
    next_ocr: str,
    mode: ContextMode = ContextMode.STANDARD,
) -> tuple:
    """Trim prev/current/next OCR text to per-mode budgets, preserving figure refs."""
    if mode == ContextMode.MINIMAL:
        prev_limit, current_limit, next_limit = 100, 300, 100
    elif mode == ContextMode.STANDARD:
        prev_limit, current_limit, next_limit = 500, 0, 500
    else:
        prev_limit, current_limit, next_limit = 2000, 0, 2000

    def truncate_with_refs(text: str, max_chars: int) -> str:
        if not text:
            return "N/A"
        if max_chars == 0 or len(text) <= max_chars:
            return text
        refs = re.findall(
            r"((?:Figure|Fig\.?|Table|Chart)\s*\d+[^.]*\.)",
            text,
            re.IGNORECASE,
        )
        refs_text = " ".join(refs)
        if refs_text and len(refs_text) < max_chars:
            remaining = max_chars - len(refs_text) - 20
            if remaining > 50:
                return f"{text[:remaining]}...\n[Refs: {refs_text}]"
        return text[:max_chars] + "..."

    prev_context = truncate_with_refs(prev_ocr, prev_limit)
    current_context = truncate_with_refs(current_ocr, current_limit)
    next_context = truncate_with_refs(next_ocr, next_limit)

    return prev_context, current_context, next_context


def build_prompt(
    page_num: int,
    prev_context: str,
    current_context: str,
    next_context: str,
    prompt_mode: PromptMode,
) -> str:
    """Pick ENHANCED chain-of-thought template or SIMPLE fallback."""
    if prompt_mode == PromptMode.ENHANCED:
        return CHART_EXTRACTION_PROMPT.format(
            page_num=page_num,
            prev_context=prev_context,
            next_context=next_context,
        )

    current_excerpt = (
        current_context[:300] + "..." if len(current_context) > 300 else current_context
    )
    prev_excerpt = (
        prev_context[:100] + "..." if len(prev_context) > 100 else prev_context
    )
    next_excerpt = (
        next_context[:100] + "..." if len(next_context) > 100 else next_context
    )
    return f"""Page {page_num} analysis:

OCR text: {current_excerpt}

Context:
- Previous page {page_num - 1}: {prev_excerpt}
- Next page {page_num + 1}: {next_excerpt}

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


# ============ Response parsing ============


def _fix_latex_escapes(s: str) -> str:
    """Escape unescaped backslashes from LaTeX commands so JSON parses.

    JSON only legitimates ``\\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX``;
    LaTeX commands like ``\\frac \\alpha`` would break it. Escape those.
    """
    result = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            next_char = s[i + 1]
            if next_char in '"\\/':
                result.append(s[i:i + 2])
                i += 2
            elif next_char in "bfnrt":
                if i + 2 < n and s[i + 2].isalpha():
                    result.append("\\\\")
                    i += 1
                else:
                    result.append(s[i:i + 2])
                    i += 2
            elif next_char == "u" and i + 5 < n:
                hex_part = s[i + 2:i + 6]
                if all(c in "0123456789abcdefABCDEF" for c in hex_part):
                    result.append(s[i:i + 6])
                    i += 6
                else:
                    result.append("\\\\")
                    i += 1
            else:
                result.append("\\\\")
                i += 1
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def _extract_json_str(result_text: str) -> str:
    """Try ```json fences, then ``` fences, then a brace-delimited slice."""
    json_match = re.search(r"```json\s*(.*?)\s*```", result_text, re.DOTALL)
    if json_match:
        return json_match.group(1)

    json_match = re.search(r"```\s*(\{.*?\})\s*```", result_text, re.DOTALL)
    if json_match:
        return json_match.group(1)

    first_brace = result_text.find("{")
    last_brace = result_text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return result_text[first_brace:last_brace + 1]

    return result_text


def _salvage_truncated_json(json_str: str, result_text: str, page_num: int) -> Dict[str, Any]:
    """Best-effort recovery for truncated/malformed JSON. Returns minimal dict."""
    try:
        test_str = json_str.rstrip()
        if not test_str.endswith("}"):
            open_braces = test_str.count("{") - test_str.count("}")
            if open_braces > 0:
                test_str += '"' + "}" * open_braces
                try:
                    fixed = json.loads(test_str)
                    print(f"      ✅ JSON修复成功(添加闭合括号)")
                    return fixed
                except Exception:
                    pass
    except Exception:
        pass

    body_text = ""
    text_labels = []
    description = ""

    labels_match = re.search(r'"text_labels"\s*:\s*\[(.*?)(?:\]|$)', json_str, re.DOTALL)
    if labels_match:
        labels_str = labels_match.group(1)
        text_labels = re.findall(r'"([^"]+)"', labels_str)
        if text_labels:
            print(f"      ✅ 从截断JSON提取到 {len(text_labels)} 个标签")

    desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', json_str)
    if desc_match:
        description = desc_match.group(1).replace("\\n", "\n").replace('\\"', '"')

    body_match = re.search(r'"body_text"\s*:\s*"((?:[^"\\]|\\.)*)', json_str, re.DOTALL)
    if body_match:
        body_text = body_match.group(1)
        body_text = body_text.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')

    combined = ""
    if description:
        combined = description + "\n\n"
    if text_labels:
        combined += "**提取的文字标签:**\n\n"
        combined += "\n".join(f"- {label}" for label in text_labels)
    if body_text and len(body_text) > len(combined):
        combined = body_text

    if len(combined) < 100 and result_text:
        clean_text = re.sub(r"```json\s*", "", result_text)
        clean_text = re.sub(r"```\s*$", "", clean_text)
        if len(clean_text) > len(combined):
            combined = clean_text

    return {
        "page_number": page_num,
        "tables": [],
        "figures": [],
        "formulas": [],
        "body_text": combined if combined else result_text,
        "footnotes": [],
        "page_markers": [],
    }


# ============ Figure YAML metadata generator ============


def generate_figure_yaml(
    figure_data: Dict[str, Any],
    figure_index: int,
    page_num: int,
) -> Dict[str, Any]:
    """Build the 6-section MARCO-compliant YAML metadata for one figure."""
    confidence = figure_data.get("extraction_confidence", "medium")
    conf_score = {"high": 0.95, "medium": 0.70, "low": 0.40}.get(confidence, 0.70)

    return {
        "chart_identification": {
            "chart_title": figure_data.get(
                "chart_title", figure_data.get("caption", "Untitled")
            ),
            "figure_number": figure_data.get("figure_number", f"Figure {figure_index}"),
            "figure_reference_in_text": figure_data.get(
                "figure_number", f"Figure {figure_index}"
            ),
            "page_number": page_num,
            "image_path": f"images/page_{page_num:03d}.png",
            "image_type": figure_data.get("image_type", "figure"),
            "chart_type": figure_data.get("chart_type", "unknown"),
        },
        "visual_content": {
            "content_description": figure_data.get(
                "content_description", figure_data.get("description", "")
            ),
            "key_elements": figure_data.get("key_elements", []),
            "text_labels": figure_data.get("text_labels", []),
            "content_summary": (
                figure_data.get("content_description", "")
                or figure_data.get("description", "")
            )[:200],
            "key_insight": figure_data.get("key_insight", ""),
        },
        "data_extraction": {
            "axes": figure_data.get(
                "axes",
                {
                    "x_axis": {"label": "N/A", "unit": "N/A", "range": "N/A"},
                    "y_axis": {"label": "N/A", "unit": "N/A", "range": "N/A"},
                },
            ),
            "data_series": (
                figure_data.get("data_series", [])
                if figure_data.get("data_series")
                else (
                    [
                        {
                            "series_name": "Main Data",
                            "data_points": figure_data.get("data_points", []),
                            "trend": figure_data.get("trend", "N/A"),
                        }
                    ]
                    if figure_data.get("data_points")
                    else []
                )
            ),
            "has_quantitative_data": bool(
                figure_data.get("data_points") or figure_data.get("has_data")
            ),
        },
        "statistical_information": figure_data.get(
            "statistics",
            {
                "sample_size": "N/A",
                "statistical_tests": [],
                "confidence_intervals": [],
                "p_values": [],
                "notes": "No statistical data extracted",
            },
        ),
        "visual_design": figure_data.get(
            "visual_design",
            {
                "color_scheme": [],
                "legend_present": False,
                "grid_lines": "N/A",
                "annotations": [],
            },
        ),
        "quality_check": {
            "data_completeness": {
                "all_labels_readable": (
                    "yes"
                    if confidence == "high"
                    else ("partial" if confidence == "medium" else "no")
                ),
                "all_values_extracted": (
                    "yes"
                    if figure_data.get("has_data") or figure_data.get("data_points")
                    else "no"
                ),
                "uncertainties": figure_data.get("uncertainties", []),
                "total_data_points_visible": len(figure_data.get("data_points", [])),
            },
            "extraction_confidence": confidence,
            "confidence_score": conf_score,
            "validation_checklist": {
                "figure_number_found": "yes" if figure_data.get("figure_number") else "no",
                "image_type_identified": "yes" if figure_data.get("image_type") else "no",
                "all_axes_labeled": "yes" if figure_data.get("axes") else "no",
                "data_points_extracted": "yes" if figure_data.get("data_points") else "no",
                "manual_verification_needed": "no" if confidence == "high" else "yes",
            },
        },
    }


# ============ Per-page orchestration ============


async def process_single_page_with_context(
    page_num: int,
    image: Any,
    current_ocr: str,
    prev_ocr: Optional[str],
    next_ocr: Optional[str],
    semaphore: asyncio.Semaphore,
    images_dir: Path,
    yaml_dir: Path,
    *,
    client: QwenClient,
    context_mode: ContextMode = DEFAULT_CONTEXT_MODE,
    prompt_mode: PromptMode = DEFAULT_PROMPT_MODE,
    model: str,
    retry_config: Optional[RetryConfig] = None,  # kept for compat; unused (lives on client)
) -> Dict[str, Any]:
    """Phase 3 for one page: build prompt, call VLM, parse JSON, write YAML files."""
    del retry_config  # retained for backwards-compatible signature; use client.retry

    async with semaphore:
        page_start = time.time()

        # Save the page image (one-shot, not retried)
        page_image_path = images_dir / f"page_{page_num:03d}.png"
        image.save(page_image_path, "PNG")

        # Auto-downgrade ENHANCED→SIMPLE when no chart indicators are present
        detected_prompt_mode = prompt_mode
        if prompt_mode == PromptMode.ENHANCED:
            if (
                not has_chart_indicators(current_ocr)
                and not has_chart_indicators(prev_ocr or "")
                and not has_chart_indicators(next_ocr or "")
            ):
                detected_prompt_mode = PromptMode.SIMPLE

        prev_context, current_context, next_context = build_context_window(
            prev_ocr or "", current_ocr, next_ocr or "", context_mode
        )
        prompt = build_prompt(
            page_num, prev_context, current_context, next_context, detected_prompt_mode
        )

        result: CallResult = await client.call_vlm(
            image, prompt, model=model, log_prefix=f"Page {page_num} "
        )

        if not result.success:
            print(
                f"      ❌ Page {page_num} 失败(重试{client.retry.max_retries}次后): {result.error}"
            )
            return {
                "success": False,
                "page": page_num,
                "error": result.error or "Unknown error after retries",
            }

        try:
            response = result.response
            result_text = safe_get_text_from_response(response)
            usage = response.usage

            json_str = _extract_json_str(result_text)
            json_str = _fix_latex_escapes(json_str)

            try:
                result_json = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"      ⚠️ JSON解析失败(Page {page_num}): {e}")
                result_json = _salvage_truncated_json(json_str, result_text, page_num)

            page_time = time.time() - page_start

            figures_metadata = []
            figure_refs = []

            if result_json.get("figures"):
                for fig_idx, figure in enumerate(result_json["figures"], 1):
                    figure_yaml = generate_figure_yaml(figure, fig_idx, page_num)
                    figure_ref = figure.get("figure_number", f"Figure_{fig_idx}")
                    yaml_filename = (
                        f"{figure_ref.replace(' ', '_').replace(':', '')}_page{page_num}.yaml"
                    )
                    yaml_path = yaml_dir / yaml_filename

                    with open(yaml_path, "w", encoding="utf-8") as f:
                        yaml.dump(
                            figure_yaml,
                            f,
                            allow_unicode=True,
                            sort_keys=False,
                            default_flow_style=False,
                        )

                    figures_metadata.append(figure_yaml)
                    figure_refs.append(
                        {
                            "figure_ref": figure_ref,
                            "yaml_file": yaml_filename,
                            "description": figure.get("description", ""),
                            "confidence": figure.get("extraction_confidence", "medium"),
                        }
                    )

            tables_data = []
            if result_json.get("tables"):
                for table in result_json["tables"]:
                    tables_data.append(
                        {
                            "table_number": table.get("table_number", ""),
                            "caption": table.get("caption", ""),
                            "markdown": table.get("markdown", ""),
                        }
                    )

            formulas = result_json.get("formulas", [])

            print(f"   [VLM] [{page_num}] ✅ ({len(result_text)} 字符)", flush=True)

            return {
                "success": True,
                "page": page_num,
                "figure_count": len(figure_refs),
                "table_count": len(tables_data),
                "formula_count": len(formulas),
                "figures": figure_refs,
                "figures_metadata": figures_metadata,
                "tables": tables_data,
                "formulas": formulas,
                "body_text": result_json.get("body_text", ""),
                "footnotes": result_json.get("footnotes", []),
                "tokens": {
                    "input": usage.input_tokens,
                    "output": usage.output_tokens,
                },
                "time": page_time,
            }

        except Exception as e:
            return {
                "success": False,
                "page": page_num,
                "error": str(e),
                "traceback": __import__("traceback").format_exc(),
            }
