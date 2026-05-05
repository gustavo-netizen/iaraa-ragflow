"""DocMind Stage-1 pipeline orchestrator.

Created in Fase G of ``PLANO_REFATORACAO.md`` (2026-05) to replace inline
JSON parsing and step orchestration in ``run.sh``. Two responsibilities:

- ``Pipeline.status()`` — aggregate ``progress.json`` + ``Document.discover``
  (Fase E) + the latest ``VALIDATION_REPORT.json`` (Fase F) into a single
  ``PipelineStatus``. Replaces the call to ``progress_manager.py --status``
  from ``run.sh:122`` plus the inline JSON parsing in ``run.sh:338-371``
  (direct PDF count) and ``run.sh:495-506`` (expected count).
- ``Pipeline.run()`` — runs Steps 1-9 by invoking the existing scripts.
  Implementation lands in **Fase G.2**; this commit raises
  ``NotImplementedError`` so callers fail loud rather than silently no-op.

The orchestrator is a single file (per the plan) and depends on
``conversao/scripts/`` modules (``config.py``, ``progress_manager.py``)
plus the ``conversao/docmind/`` and ``conversao/validation/`` packages.
A path-shim adds ``scripts/`` to ``sys.path`` once on import.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------- path shim

_CONVERSAO_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _CONVERSAO_DIR / "scripts"
if str(_CONVERSAO_DIR) not in sys.path:
    sys.path.insert(0, str(_CONVERSAO_DIR))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from config import AppConfig  # noqa: E402
from progress_manager import ProgressManager  # noqa: E402
from docmind.document import Document  # noqa: E402


# ------------------------------------------------------------- data classes


@dataclass
class DocumentStatus:
    """Per-PDF view of Stage-1 progress.

    Built from ``Document.discover`` (chunks vs direct) plus
    ``Document.is_complete()`` and ``Document.failed_pages()``. ``name`` is
    the original PDF stem (no extension).
    """

    name: str
    is_chunked: bool
    is_complete: bool
    chunks_total: int = 0
    failed_pages: List[int] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineStatus:
    """Aggregate Stage-1 state.

    Mirrors what ``progress_manager.print_status()`` used to emit, plus
    per-document detail (Fase E) and a validation summary (Fase F).
    ``progress_present`` is the load-bearing flag that determines whether
    ``as_text()`` returns the legacy "no progress" string or the full
    rendered report — mirrors the bash branch in ``run.sh:121-125``.
    """

    progress_present: bool = False
    overall_status: str = "not_started"
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    steps: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    statistics: Dict[str, Any] = field(default_factory=dict)
    documents: List[DocumentStatus] = field(default_factory=list)
    validation: Optional[Dict[str, Any]] = None

    _STEP_ICONS = {
        "completed": "✅",
        "in_progress": "🔄",
        "pending": "⏳",
        "failed": "❌",
    }

    def as_text(self) -> str:
        """Render the legacy ``progress_manager.print_status`` format.

        When no progress file is found and no other state is available,
        returns the same single line ``run.sh:124`` used to print, so
        existing operators see no change. Otherwise renders the legacy
        report and appends new "文档" and "验证" sections.
        """
        if not self.progress_present and not self.documents and self.validation is None:
            return "没有找到进度文件，尚未开始处理"

        sep = "=" * 60
        lines: List[str] = ["", sep, "📊 DocMind 处理进度", sep]
        lines.append(f"状态: {self.overall_status}")
        lines.append(f"开始时间: {self.started_at or '-'}")
        lines.append(f"更新时间: {self.updated_at or '-'}")
        lines.append("")

        lines.append("步骤状态:")
        for name, step in self.steps.items():
            icon = self._STEP_ICONS.get(step.get("status", "pending"), "❓")
            lines.append(f"  {icon} {name}: {step.get('status', 'pending')}")
            done = step.get("completed", 0)
            pending = step.get("pending", 0)
            failed = step.get("failed", 0)
            if done > 0 or pending > 0:
                lines.append(f"      完成: {done}, 待处理: {pending}, 失败: {failed}")

        lines.append("")
        lines.append("统计:")
        s = self.statistics
        lines.append(f"  PDF: {s.get('completed_pdfs', 0)}/{s.get('total_pdfs', 0)}")
        lines.append(
            f"  页面: {s.get('completed_pages', 0)}/{s.get('total_pages', 0)} "
            f"(失败: {s.get('failed_pages', 0)})"
        )
        if s.get("total_pages", 0) > 0:
            pct = (s.get("completed_pages", 0) / s["total_pages"]) * 100
            lines.append(f"  总进度: {pct:.1f}%")

        if self.documents:
            lines.append("")
            lines.append("文档:")
            for d in self.documents:
                icon = "✅" if d.is_complete else "⏳"
                tag = "chunked" if d.is_chunked else "direct"
                fail_str = f" (失败 {len(d.failed_pages)})" if d.failed_pages else ""
                lines.append(f"  {icon} {d.name} [{tag}]{fail_str}")

        if self.validation is not None:
            lines.append("")
            lines.append("验证:")
            v = self.validation
            mark = "✅" if v.get("passed") else "❌"
            lines.append(
                f"  {mark} {v.get('issues', 0)} 问题, {v.get('warnings', 0)} 警告"
            )

        lines.append(sep)
        return "\n".join(lines)

    def as_json(self) -> Dict[str, Any]:
        return {
            "progress_present": self.progress_present,
            "overall_status": self.overall_status,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "steps": self.steps,
            "statistics": self.statistics,
            "documents": [d.as_dict() for d in self.documents],
            "validation": self.validation,
        }


# ------------------------------------------------------------- Pipeline


@dataclass
class Pipeline:
    """Stage-1 pipeline orchestrator.

    ``config`` carries model/retry/health knobs (used by ``run()`` in
    Fase G.2). ``root`` is the ``conversao/`` directory whose layout the
    pipeline operates on (``input/``, ``output/``, ``progress.json``,
    ``final-delivery/``).
    """

    config: AppConfig
    root: Path

    @classmethod
    def from_env(cls, root: Optional[Path | str] = None) -> "Pipeline":
        """Build a Pipeline using ``AppConfig.from_env`` and a default root.

        Default root is the directory containing ``orchestrator.py`` —
        i.e. ``conversao/``.
        """
        root_p = Path(root) if root is not None else _CONVERSAO_DIR
        return cls(config=AppConfig.from_env(), root=root_p)

    # --------- layout shortcuts (mirror run.sh path constants) ---------

    @property
    def progress_file(self) -> Path:
        return self.root / "progress.json"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def final_delivery_dir(self) -> Path:
        return self.root / "final-delivery"

    @property
    def split_mapping_path(self) -> Path:
        return self.root / "input" / "split_pdfs" / "split_mapping.json"

    # ----------------------------------------------------- status (G.1)

    def status(self) -> PipelineStatus:
        """Aggregate Stage-1 state into a ``PipelineStatus``.

        Reads ``progress.json`` (legacy summary), discovers Documents via
        ``split_mapping.json`` (Fase E), and folds in the latest
        ``VALIDATION_REPORT.json`` from ``final-delivery/`` (Fase F).
        Tolerant of missing files — returns whatever it can.
        """
        status = PipelineStatus()

        if self.progress_file.exists():
            pm = ProgressManager(progress_file=str(self.progress_file))
            data = pm.load()
            summary = pm.get_status_summary()
            status.progress_present = True
            status.overall_status = summary.get("status", "unknown")
            status.started_at = summary.get("started_at")
            status.updated_at = summary.get("updated_at")
            status.completed_at = data.get("completed_at")
            status.steps = summary.get("steps", {})
            status.statistics = summary.get("statistics", {})

        if self.split_mapping_path.exists():
            try:
                docs = Document.discover(self.split_mapping_path, self.output_dir)
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                docs = []
            for d in docs:
                status.documents.append(
                    DocumentStatus(
                        name=d.original_name,
                        is_chunked=d.is_chunked,
                        is_complete=d.is_complete(),
                        chunks_total=len(d.chunks),
                        failed_pages=[fp.page for fp in d.failed_pages()],
                    )
                )

        validation_json = self.final_delivery_dir / "VALIDATION_REPORT.json"
        if validation_json.exists():
            status.validation = _load_validation_summary(validation_json)

        return status

    # ----------------------------------------------------- run (G.2)

    def run(
        self,
        restart: bool = False,
        retry_failed: bool = False,
        task_name: Optional[str] = None,
    ) -> int:
        """Run Steps 1–9 of the Stage-1 pipeline.

        Implementation lands in Fase G.2. Until then we raise to make it
        obvious that ``run.sh`` should keep its current step orchestration.
        """
        raise NotImplementedError("Pipeline.run() lands in Fase G.2")


def _load_validation_summary(path: Path) -> Optional[Dict[str, Any]]:
    """Best-effort parse of ``VALIDATION_REPORT.json`` into a small dict.

    Tolerates both the post-Fase-F shape (``results`` list with ``issues``
    and ``warnings``) and any prior shape that happens to have a top-level
    ``summary.passed``. Returns ``None`` on parse failure.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    summary_block = raw.get("summary", {}) if isinstance(raw, dict) else {}
    results = raw.get("results", []) if isinstance(raw, dict) else []

    total_issues = 0
    total_warnings = 0
    for r in results:
        if not isinstance(r, dict):
            continue
        total_issues += len(r.get("issues", []) or [])
        total_warnings += len(r.get("warnings", []) or [])

    passed = summary_block.get("passed")
    if passed is None:
        passed = all(
            isinstance(r, dict) and r.get("passed", True) for r in results
        ) if results else summary_block.get("overall_passed", True)

    return {
        "passed": bool(passed),
        "issues": total_issues,
        "warnings": total_warnings,
    }


# --------------------------------------------------------------------- CLI


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description=(
            "DocMind Stage-1 pipeline orchestrator (Fase G of "
            "PLANO_REFATORACAO.md). G.1 ships --status only; --run lands in G.2."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="conversao/ root (default: directory of orchestrator.py).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Print current pipeline state.")
    p_status.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON (machine-readable) instead of the legacy text format.",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    pipeline = Pipeline.from_env(args.root)

    if args.cmd == "status":
        status = pipeline.status()
        if args.json:
            print(json.dumps(status.as_json(), indent=2, ensure_ascii=False))
        else:
            print(status.as_text())
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
