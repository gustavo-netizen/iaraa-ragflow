"""Unified cost analysis from real token counts.

Replaces two divergent implementations:

- ``generate_quality_report.py:calculate_estimated_cost`` — heuristic
  (pages × 2000 tokens × Qwen-VL-Plus price); too coarse and uses the
  wrong model price.
- ``generate_report.py:calculate_costs`` — real (sums tokens from
  ``batch_report*.json``); canonical.

This module exposes the canonical version. Both legacy callers will import
``compute_cost`` and ``from_batch_reports`` from here in F.2.d.

Pricing reference: Qwen-VL-Max 2024 list prices, CNY 0.02 per 1K tokens for
both input and output. Real billing may differ due to discounts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


PRICE_INPUT_PER_1K_CNY = 0.02
PRICE_OUTPUT_PER_1K_CNY = 0.02

# Heuristic: ~1500 tokens per A4 page at 150 DPI (used when batch_report
# doesn't carry explicit tokens_input — pre-Fase-D format).
ESTIMATED_INPUT_TOKENS_PER_PAGE = 1500


@dataclass(frozen=True)
class TokenUsage:
    """Input + output token counts. Both individual and sum are available."""

    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class CostBreakdown:
    """Cost analysis for a batch of pages, in CNY."""

    tokens: TokenUsage
    input_cost_cny: float
    output_cost_cny: float
    total_cost_cny: float
    pages: int
    time_sec: float
    recorded_cost_cny: float = 0.0
    pricing_input_per_1k: float = PRICE_INPUT_PER_1K_CNY
    pricing_output_per_1k: float = PRICE_OUTPUT_PER_1K_CNY
    model: str = "qwen-vl-max-latest"

    @property
    def cost_per_page(self) -> float:
        return round(self.total_cost_cny / max(self.pages, 1), 4)

    @property
    def tokens_per_page(self) -> float:
        return round(self.tokens.total / max(self.pages, 1), 0)

    @property
    def time_per_page_sec(self) -> float:
        return round(self.time_sec / max(self.pages, 1), 2)


def compute_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    pages: int = 0,
    time_sec: float = 0.0,
    recorded_cost: float = 0.0,
    price_input_per_1k: float = PRICE_INPUT_PER_1K_CNY,
    price_output_per_1k: float = PRICE_OUTPUT_PER_1K_CNY,
    model: str = "qwen-vl-max-latest",
) -> CostBreakdown:
    """Compute CNY cost from raw token counts."""
    input_cost = input_tokens * price_input_per_1k / 1000
    output_cost = output_tokens * price_output_per_1k / 1000
    return CostBreakdown(
        tokens=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        input_cost_cny=round(input_cost, 4),
        output_cost_cny=round(output_cost, 4),
        total_cost_cny=round(input_cost + output_cost, 4),
        pages=pages,
        time_sec=round(time_sec, 1),
        recorded_cost_cny=round(recorded_cost, 4),
        pricing_input_per_1k=price_input_per_1k,
        pricing_output_per_1k=price_output_per_1k,
        model=model,
    )


def from_batch_reports(reports: Iterable[Dict[str, Any]]) -> CostBreakdown:
    """Sum cost data across one-or-more ``batch_report*.json`` payloads.

    Token resolution order per PDF (preferring more accurate sources):

    1. ``processing.tokens_input`` + ``processing.tokens_output`` (explicit,
       written by ``docmind_converter`` post-Fase D).
    2. ``processing.tokens`` (single sum, treated as output) plus an estimate
       ``pages × 1500`` for input (legacy GR.calculate_costs heuristic).

    Failed PDFs (``success = False``) are skipped.
    """
    total_input = 0
    total_output = 0
    total_pages = 0
    total_time = 0.0
    recorded = 0.0

    for report in reports:
        for pdf in report.get("pdfs", []):
            if not pdf.get("success"):
                continue

            info = pdf.get("pdf_info", {}) or {}
            proc = pdf.get("processing", {}) or {}
            pages = int(info.get("pages", 0) or 0)
            time_sec = float(proc.get("time", 0) or 0)

            if "tokens_input" in proc:
                total_input += int(proc.get("tokens_input", 0) or 0)
                total_output += int(proc.get("tokens_output", 0) or 0)
            else:
                total_input += pages * ESTIMATED_INPUT_TOKENS_PER_PAGE
                total_output += int(proc.get("tokens", 0) or 0)

            total_pages += pages
            total_time += time_sec

        # Sum the per-batch cost recorded by docmind_converter, if present
        recorded += float(report.get("summary", {}).get("total_cost_cny", 0) or 0)

    return compute_cost(
        input_tokens=total_input,
        output_tokens=total_output,
        pages=total_pages,
        time_sec=total_time,
        recorded_cost=recorded,
    )
