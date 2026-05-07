"""Stage-1+2 validation pipeline.

Consolidates checks that used to live across ``final_delivery_check.py``
(structural + syntactic integrity) and ``generate_quality_report.py``
(semantic content analysis + element detection + MARCO compliance) into a
single set of pluggable ``Checker``s coordinated by ``ValidationPipeline``.

Created in Fase F of PLANO_REFATORACAO.md (2026-05). Inventory in F.1
identified that the plan's "4 scripts" was wrong: ``final_data_validation.py``
is content-moderation recovery (not validation) and ``generate_report.py``
is per-task aggregation. Only FDC and GQR fold here.
"""

from __future__ import annotations
