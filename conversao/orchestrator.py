"""DocMind Stage-1 pipeline orchestrator.

Created in Fase G of ``PLANO_REFATORACAO.md`` (2026-05) to replace inline
JSON parsing and step orchestration in ``run.sh``.

Two responsibilities:

- ``Pipeline.status()`` (Fase G.1) — aggregate ``progress.json`` +
  ``Document.discover`` (Fase E) + the latest ``VALIDATION_REPORT.json``
  (Fase F) into a ``PipelineStatus``.
- ``Pipeline.run()`` (Fase G.2) — run Steps 1–9 of the Stage-1 pipeline
  by invoking the existing scripts via subprocess. Replaces the inline
  JSON parsing in ``run.sh:338-371`` (direct PDF discovery + symlink loop)
  and ``run.sh:495-506`` (expected count). Bash ``set -e`` semantics are
  preserved exactly: each step's exit code is captured but pipeline does
  not abort mid-run, mirroring the legacy ``2>&1 | tee`` swallowing.

Single file (per the plan). Depends on ``conversao/scripts/`` modules
(``config.py``, ``progress_manager.py``) plus the ``conversao/docmind/``
and ``conversao/validation/`` packages. A path-shim at import-time adds
``scripts/`` to ``sys.path`` once.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

import yaml
from dataclasses import asdict, dataclass, field
from datetime import datetime
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
class RunOptions:
    """Knobs controlling ``Pipeline.run()``.

    Defaults match ``run.sh``'s tuned values for 6 API keys:
    50 pages/chunk, 50 MB/chunk, 30 PDFs concurrent, 10 LLM calls/PDF.
    Env-var override matches the legacy bash variable names so existing
    operator muscle memory still works (``MAX_PAGES``, ``MAX_SIZE``,
    ``SEMAPHORE``, ``LLM_CONCURRENT``).
    """

    restart: bool = False
    retry_failed: bool = False
    task_name: Optional[str] = None
    max_pages_per_chunk: int = 50
    max_size_mb: int = 50
    pdf_concurrency: int = 30
    llm_concurrent: int = 10
    quality_gate: bool = True

    @classmethod
    def from_env(cls, **overrides: Any) -> "RunOptions":
        defaults: Dict[str, Any] = dict(
            max_pages_per_chunk=_int_env("MAX_PAGES", cls.max_pages_per_chunk),
            max_size_mb=_int_env("MAX_SIZE", cls.max_size_mb),
            pdf_concurrency=_int_env("SEMAPHORE", cls.pdf_concurrency),
            llm_concurrent=_int_env("LLM_CONCURRENT", cls.llm_concurrent),
        )
        defaults.update(overrides)
        return cls(**defaults)


@dataclass
class PipelineStatus:
    """Aggregate Stage-1 state.

    Mirrors what ``progress_manager.print_status()`` emits, plus per-document
    detail (Fase E) and a validation summary (Fase F). ``progress_present``
    determines whether ``as_text()`` returns the legacy "no progress" string
    or the full rendered report — mirrors the bash branch in ``run.sh:121-125``.
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

    ``config`` carries Stage-1 model/retry/health knobs (read by docmind
    subprocess scripts via env vars; the orchestrator passes them through
    unchanged). ``root`` is the ``conversao/`` directory whose layout the
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
        return self.split_dir / "split_mapping.json"

    @property
    def scripts_dir(self) -> Path:
        return self.root / "scripts"

    @property
    def admin_dir(self) -> Path:
        return self.scripts_dir / "admin"

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def split_dir(self) -> Path:
        return self.input_dir / "split_pdfs"

    @property
    def direct_dir(self) -> Path:
        return self.input_dir / "direct_pdfs"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

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

    # ------------------------------------------------------- run (G.2)

    def run(self, options: Optional[RunOptions] = None) -> int:
        """Run Steps 1–9 of the Stage-1 pipeline.

        Bash semantics preserved: pipeline never aborts mid-run, even if a
        step fails. Each step's exit code is OR'd into the final return
        code. Step 9 is the only step whose failure is silenced (matches
        the explicit ``|| echo`` fallback at run.sh:554).
        """
        opts = options if options is not None else RunOptions.from_env()

        if opts.restart:
            self._archive_and_reset(opts.task_name)

        self._ensure_dirs()

        pdf_count = self._count_input_pdfs()
        if pdf_count == 0:
            print("请将PDF文件放入 input/ 目录")
            return 0

        if opts.retry_failed:
            return self._step2_5_retry()

        print(f"找到 {pdf_count} 个PDF文件\n")
        start = time.time()

        rc = 0
        step1_rc = self._step1_split(opts)
        if step1_rc != 0:
            print(
                "\n❌ Step 1 (split) falhou — pipeline abortada antes do Step 2."
            )
            self._print_summary(time.time() - start)
            return step1_rc
        guard_rc = self._validate_split_mapping_or_abort()
        if guard_rc != 0:
            self._print_summary(time.time() - start)
            return guard_rc
        rc |= self._step2_process_chunks(opts)
        rc |= self._step2_5_retry()
        rc |= self._step3_process_direct(opts)
        rc |= self._step4_merge()
        gate_rc = self._step4_5_quality_gate(opts)
        if gate_rc != 0:
            self._print_summary(time.time() - start)
            return gate_rc
        self._mark_pipeline_completed_safe()
        rc |= self._step5_final_delivery_copy()
        rc |= self._step6_postprocess()
        rc |= self._step7_quality_report()
        rc |= self._step8_validation()
        self._step9_task_report(opts)  # always 0 — failure silenced

        self._print_summary(time.time() - start)
        return rc

    # ----------------------------- step methods (cmd + invocation) -----

    def _step1_cmd(self, opts: RunOptions) -> List[str]:
        return [
            sys.executable,
            str(self.scripts_dir / "split_large_pdfs_smart.py"),
            "--input-dir", str(self.input_dir),
            "--output-dir", str(self.split_dir),
            "--chunk-size", str(opts.max_pages_per_chunk),
            "--max-chunk-size-mb", str(opts.max_size_mb),
            "--mapping-file", str(self.split_mapping_path),
        ]

    def _step1_split(self, opts: RunOptions) -> int:
        return self._run_subprocess(
            f"Step 1: 智能分割大PDF (>{opts.max_pages_per_chunk} 页或 >{opts.max_size_mb} MB)",
            self._step1_cmd(opts),
        )

    def _validate_split_mapping_or_abort(self) -> int:
        """Defesa em profundidade: aborta se mapping marcar algum PDF como erro.

        ``_step1_split`` já curto-circuita o pipeline quando o splitter
        retorna rc=1, mas o mapping pode ter sido editado manualmente ou
        o splitter rodado fora desta sessão. Esta checagem lê
        ``stats.pdfs`` e aborta se algum entry tem ``status='error'``.
        """
        if not self.split_mapping_path.exists():
            return 0
        try:
            with open(self.split_mapping_path, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except (OSError, json.JSONDecodeError):
            return 0
        pdfs = (mapping.get("stats", {}) or {}).get("pdfs", {}) or {}
        errored = [
            name
            for name, info in pdfs.items()
            if isinstance(info, dict) and info.get("status") == "error"
        ]
        if not errored:
            return 0
        print(
            f"\n❌ split_mapping.json marca {len(errored)} PDF(s) com status='error':"
        )
        for name in sorted(errored):
            error_msg = pdfs[name].get("error", "(sem mensagem)")
            print(f"  • {name}: {error_msg}")
        print()
        print("Pipeline abortada antes do Step 2 — corrija ou remova os PDFs.")
        return 1

    def _step2_cmd(self, opts: RunOptions) -> List[str]:
        return [
            sys.executable,
            str(self.scripts_dir / "docmind_converter.py"),
            "--input", str(self.split_dir),
            "--output", str(self.output_dir / "chunks"),
            "--semaphore-limit", str(opts.llm_concurrent),
            "--pdf-concurrency", str(opts.pdf_concurrency),
            "--progress-file", str(self.progress_file),
        ]

    def _step2_process_chunks(self, opts: RunOptions) -> int:
        self._echo_step_header("Step 2: 处理分块PDF")
        chunks = list(self.split_dir.glob("*.pdf")) if self.split_dir.exists() else []
        if not chunks:
            print("没有需要处理的分块PDF")
            return 0
        print(f"处理 {len(chunks)} 个分块PDF...")
        return self._run_subprocess(
            None,
            self._step2_cmd(opts),
            log_path=self.logs_dir / "chunks_processing.log",
            env={"PYTHONUNBUFFERED": "1"},
        )

    def _step2_5_cmd(self) -> List[str]:
        return [
            sys.executable,
            str(self.scripts_dir / "retry_failed_pages.py"),
            "--chunks-dir", str(self.output_dir / "chunks"),
            "--api-keys", str(self.root / "api" / "keys.txt"),
            "--output", str(self.output_dir / "chunks" / "retry_failures.yaml"),
        ]

    def _step2_5_retry(self) -> int:
        self._echo_step_header("Step 2.5: 重试失败的页面")
        chunks_dir = self.output_dir / "chunks"
        if not chunks_dir.exists():
            print("没有chunk输出目录，跳过重试步骤")
            return 0
        failed = _count_failed_chunks(chunks_dir)
        if failed == 0:
            print("没有需要重试的失败页面")
            return 0
        print(f"发现 {failed} 个chunk有失败页面，开始重试...")
        return self._run_subprocess(
            None,
            self._step2_5_cmd(),
            log_path=self.logs_dir / "retry_failed.log",
        )

    def _step3_cmd(self, opts: RunOptions) -> List[str]:
        return [
            sys.executable,
            str(self.scripts_dir / "docmind_converter.py"),
            "--input", str(self.direct_dir),
            "--output", str(self.output_dir),
            "--semaphore-limit", str(opts.llm_concurrent),
            "--pdf-concurrency", str(opts.pdf_concurrency),
            "--progress-file", str(self.progress_file),
        ]

    def _step3_process_direct(self, opts: RunOptions) -> int:
        self._echo_step_header("Step 3: 处理小PDF")
        if not self.split_mapping_path.exists():
            print("没有 split_mapping.json，跳过")
            return 0
        try:
            with open(self.split_mapping_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            print("split_mapping.json 损坏，跳过")
            return 0
        direct_count = len(data.get("direct", []) or [])
        if direct_count == 0:
            print("没有需要直接处理的小PDF")
            return 0
        print(f"处理 {direct_count} 个小PDF...")
        linked = _create_direct_pdf_symlinks(self.split_mapping_path, self.direct_dir)
        if linked == 0:
            print("没有可链接的源PDF（路径不存在）")
            return 0
        return self._run_subprocess(
            None,
            self._step3_cmd(opts),
            log_path=self.logs_dir / "direct_processing.log",
            env={"PYTHONUNBUFFERED": "1"},
        )

    def _step4_cmd(self) -> List[str]:
        return [
            sys.executable,
            str(self.scripts_dir / "merge_results_full.py"),
            "--mapping-file", str(self.split_mapping_path),
            "--results-dir", str(self.output_dir / "chunks"),
            "--output-dir", str(self.output_dir),
        ]

    def _step4_merge(self) -> int:
        self._echo_step_header("Step 4: 合并分块结果")
        if not self.split_mapping_path.exists() or not (self.output_dir / "chunks").exists():
            print("无映射或chunks目录，跳过合并")
            return 0
        return self._run_subprocess(None, self._step4_cmd())

    def _mark_pipeline_completed_safe(self) -> None:
        """Replace the inline Python at run.sh:402-417. Best-effort."""
        if not self.progress_file.exists():
            return
        try:
            pm = ProgressManager(progress_file=str(self.progress_file))
            _mark_pipeline_completed(pm)
        except Exception:
            pass  # match bash `|| true` semantics

    def _step4_5_quality_gate(self, opts: RunOptions) -> int:
        """Abort the pipeline if any PDF failed MARCO thresholds.

        Reads ``output/*/{name}.validation.yaml`` (written by
        ``docmind/pipeline.py`` per processed PDF) and checks
        ``kqi_metrics.overall_quality_pass``. Any False aborts the
        pipeline before Step 5 (final-delivery copy), so partial or
        low-quality OCR results never produce a delivery package nor
        mark ``progress.json`` as ``completed``.

        Disabled by ``--no-quality-gate``.
        """
        self._echo_step_header("Step 4.5: KQI Quality Gate (MARCO)")
        if not opts.quality_gate:
            print("⚠️  --no-quality-gate set — skipping")
            return 0
        if not self.output_dir.exists():
            print("⚠️  output/ não existe — skip")
            return 0
        validation_files = sorted(self.output_dir.glob("*/*.validation.yaml"))
        if not validation_files:
            print("⚠️  Nenhum .validation.yaml encontrado — skip")
            return 0

        expected = _compute_expected_count(self.split_mapping_path)
        if expected is not None and expected > len(validation_files):
            present_stems = {
                vf.stem[: -len(".validation")]
                if vf.stem.endswith(".validation")
                else vf.stem
                for vf in validation_files
            }
            missing = self._missing_validation_names(present_stems)
            print(
                f"❌ {expected - len(validation_files)} PDFs sem .validation.yaml "
                f"({len(validation_files)}/{expected} presentes):"
            )
            for name in sorted(missing):
                print(f"  • {name}")
            print()
            print(
                "Indica merge incompleto — Stage 1 não emitiu validation "
                "para todos os PDFs chunked. Pipeline abortada."
            )
            return 1

        failed: List[Any] = []
        for vf in validation_files:
            try:
                data = yaml.safe_load(vf.read_text(encoding="utf-8")) or {}
            except Exception as e:
                print(f"⚠️  Falha ao ler {vf.name}: {e}")
                continue
            kqi = data.get("kqi_metrics", {}) or {}
            if kqi.get("overall_quality_pass") is not False:
                continue
            stats = data.get("page_statistics", {}) or {}
            pdf_name = (data.get("document_info", {}) or {}).get(
                "filename", vf.stem
            )
            reasons: List[str] = []
            if kqi.get("yaml_insertion_pass") is False:
                reasons.append(
                    f"yaml_insertion={float(kqi.get('yaml_insertion_rate', 0) or 0):.2%}"
                )
            if kqi.get("confidence_pass") is False:
                reasons.append(
                    f"avg_confidence={float(kqi.get('average_confidence', 0) or 0):.2f}"
                )
            psr = float(kqi.get("page_success_rate", 0) or 0)
            if psr < 0.95:
                reasons.append(
                    f"page_success={psr:.2%} "
                    f"({stats.get('failed_pages', 0)}/{stats.get('total_pages', 0)} failed)"
                )
            failed.append((pdf_name, reasons))

        if not failed:
            print(
                f"✅ {len(validation_files)} PDFs atingiram thresholds MARCO "
                f"(yaml_insertion ≥ 95%, avg_confidence ≥ 0.85, page_success ≥ 95%)"
            )
            return 0

        print(
            f"❌ {len(failed)} de {len(validation_files)} PDFs falharam thresholds MARCO:"
        )
        for pdf_name, reasons in failed:
            print(f"  • {pdf_name}")
            for r in reasons:
                print(f"      - {r}")
        print()
        print("Pipeline abortada antes do Step 5. Opções:")
        print("  ./run.sh --retry-failed       # reprocessa apenas páginas falhadas")
        print("  ./run.sh --no-quality-gate    # ignora o gate e prossegue")
        return 1

    def _missing_validation_names(self, present_stems: set) -> set:
        """Names from split_mapping.json with no ``.validation.yaml`` on disk."""
        if not self.split_mapping_path.exists():
            return set()
        try:
            with open(self.split_mapping_path, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except (OSError, json.JSONDecodeError):
            return set()
        expected_stems: set = set()
        for entry in mapping.get("chunks", []) or []:
            if isinstance(entry, dict) and entry.get("original_pdf"):
                expected_stems.add(Path(entry["original_pdf"]).stem)
        for entry in mapping.get("direct", []) or []:
            if not isinstance(entry, dict):
                continue
            path = entry.get("pdf_path") or entry.get("pdf_name")
            if path:
                expected_stems.add(Path(path).stem)
        return expected_stems - present_stems

    def _step5_final_delivery_copy(self) -> int:
        """Replace the bash for-loop at run.sh:427-457 with a Python copy.

        Iterates ``output/*/`` (skipping ``chunks/``), sanitizes the dir
        name with the same rules as ``cut -c1-50 | sed 's/ /-/g' | sed
        's/[^a-zA-Z0-9-]//g'``, and copies the first ``.md`` and the
        ``*_all_figures.yaml`` (with ``.yaml`` fallback) into
        ``final-delivery/``.
        """
        self._echo_step_header("Step 5: Create final-delivery folder")
        self.final_delivery_dir.mkdir(parents=True, exist_ok=True)
        if not self.output_dir.exists():
            return 0
        for pdf_dir in sorted(self.output_dir.iterdir()):
            if not pdf_dir.is_dir() or pdf_dir.name == "chunks":
                continue
            short_name = _sanitize_short_name(pdf_dir.name)
            if not short_name:
                continue
            md_files = sorted(pdf_dir.glob("*.md"))
            if md_files:
                shutil.copy2(md_files[0], self.final_delivery_dir / f"{short_name}.md")
                print(f"  ✅ {short_name}.md")
            yaml_file = next(iter(sorted(pdf_dir.glob("*_all_figures.yaml"))), None)
            if yaml_file is None:
                yaml_file = next(
                    iter(
                        sorted(
                            p for p in pdf_dir.glob("*.yaml")
                            if not p.name.endswith(".validation.yaml")
                        )
                    ),
                    None,
                )
            if yaml_file is not None:
                shutil.copy2(yaml_file, self.final_delivery_dir / f"{short_name}.yaml")
                print(f"  ✅ {short_name}.yaml")
            footnotes_file = next(
                iter(sorted(pdf_dir.glob("*.footnotes.yaml"))), None
            )
            if footnotes_file is not None:
                shutil.copy2(
                    footnotes_file,
                    self.final_delivery_dir / f"{short_name}.footnotes.yaml",
                )
                print(f"  ✅ {short_name}.footnotes.yaml")
        print(f"\nFinal delivery: {self.final_delivery_dir}\n")
        return 0

    def _step6_cmd(self) -> List[str]:
        return [
            sys.executable,
            str(self.scripts_dir / "postprocess.py"),
            "--input", str(self.final_delivery_dir),
            "--fix-tables",
            "--fix-headings",
            "--merge-empty-lines",
            "--validate-latex",
        ]

    def _step6_postprocess(self) -> int:
        return self._run_subprocess("Step 6: Markdown Post-processing", self._step6_cmd())

    def _step7_cmd(self) -> List[str]:
        return [
            sys.executable,
            str(self.scripts_dir / "generate_quality_report.py"),
            "--input", str(self.final_delivery_dir),
            "--progress", str(self.progress_file),
            "--json",
        ]

    def _step7_quality_report(self) -> int:
        return self._run_subprocess("Step 7: Generate Quality Report", self._step7_cmd())

    def _step8_cmd(self) -> List[str]:
        cmd = [
            sys.executable,
            str(self.scripts_dir / "final_delivery_check.py"),
            "--delivery-dir", str(self.final_delivery_dir),
            "--output-report", str(self.final_delivery_dir / "VALIDATION_REPORT.json"),
        ]
        expected = _compute_expected_count(self.split_mapping_path)
        if expected is not None:
            cmd.extend(["--expected-count", str(expected)])
        return cmd

    def _step8_validation(self) -> int:
        return self._run_subprocess("Step 8: Final Delivery Validation", self._step8_cmd())

    def _step9_cmd(self, opts: RunOptions) -> List[str]:
        task_name = opts.task_name or _auto_task_name()
        return [
            sys.executable,
            str(self.admin_dir / "generate_report.py"),
            "--task-name", task_name,
            "--base-dir", str(self.root),
        ]

    def _step9_task_report(self, opts: RunOptions) -> int:
        rc = self._run_subprocess("Step 9: Generate Task Report", self._step9_cmd(opts))
        if rc != 0:
            print("⚠️  报告生成失败，但不影响转换结果")
        return 0  # always 0 — Step 9 failure does not propagate

    # --------------------------------------------------- support helpers

    def _archive_and_reset(self, task_name: Optional[str]) -> None:
        print("\n⚠️  强制重新开始模式")
        if self.progress_file.exists():
            print("   📦 归档旧进度...")
            cmd = [sys.executable, str(self.admin_dir / "archive_progress.py")]
            if task_name:
                cmd.extend(["--task-name", task_name])
            try:
                self._run_subprocess(None, cmd)
            except OSError:
                pass
            for path in (self.progress_file, Path(str(self.progress_file) + ".lock")):
                try:
                    path.unlink()
                except OSError:
                    pass
        if self.split_dir.exists():
            shutil.rmtree(self.split_dir, ignore_errors=True)
        print("   ✅ 已重置")

    def _ensure_dirs(self) -> None:
        for d in (self.input_dir, self.output_dir, self.split_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def _count_input_pdfs(self) -> int:
        if not self.input_dir.exists():
            return 0
        return sum(1 for _ in self.input_dir.glob("*.pdf"))

    def _print_summary(self, elapsed_seconds: float) -> None:
        minutes = int(elapsed_seconds // 60)
        seconds = int(elapsed_seconds % 60)
        print("\n" + "=" * 70)
        print("✅ 处理完成!")
        print("=" * 70)
        print(f"总耗时: {minutes}分{seconds}秒")
        print(f"结束时间: {datetime.now().isoformat()}")
        if self.output_dir.exists():
            yaml_count = len(list(self.output_dir.rglob("*.yaml")))
            md_count = len(list(self.output_dir.rglob("*.md")))
            json_count = len(list(self.output_dir.rglob("*.json")))
            img_count = len(list(self.output_dir.rglob("*.png")))
            print("\n结果统计:")
            print(f"  • YAML 文件: {yaml_count}")
            print(f"  • Markdown 文件: {md_count}")
            print(f"  • JSON 文件: {json_count}")
            print(f"  • 图片文件: {img_count}")
        print(f"输出目录: {self.output_dir}")
        print(f"进度文件: {self.progress_file}")

    def _echo_step_header(self, title: str) -> None:
        bar = "=" * 70
        print(f"\n{bar}\n{title}\n{bar}")

    def _run_subprocess(
        self,
        title: Optional[str],
        cmd: List[str],
        log_path: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> int:
        """Stream a child process to stdout and (optionally) tee to log_path.

        Mirrors ``2>&1 | tee LOG`` from bash. Returns the child's exit code.
        """
        if title:
            self._echo_step_header(title)
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
            env=full_env,
        )
        log_handle = open(log_path, "w", encoding="utf-8") if log_path else None
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                if log_handle:
                    log_handle.write(line)
                    log_handle.flush()
        finally:
            if log_handle:
                log_handle.close()
        return proc.wait()


# --------------------------------------------------- module-level helpers


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _auto_task_name() -> str:
    """Match ``task_$(date +%Y%m%d_%H%M%S)`` from run.sh:159."""
    return f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


_SHORT_NAME_RE = re.compile(r"[^a-zA-Z0-9-]")


def _sanitize_short_name(dir_name: str) -> str:
    """Reproduce ``cut -c1-50 | sed 's/ /-/g' | sed 's/[^a-zA-Z0-9-]//g'``.

    First 50 chars, spaces → dashes, then strip anything that isn't
    alphanumeric or a dash. Used by Step 5 to derive final-delivery filenames.
    """
    truncated = dir_name[:50]
    spaced_to_dashed = truncated.replace(" ", "-")
    return _SHORT_NAME_RE.sub("", spaced_to_dashed)


def _compute_expected_count(mapping_path: Path) -> Optional[int]:
    """Number of unique original PDFs from a ``split_mapping.json``.

    Replaces the inline Python at ``run.sh:495-506``. Returns ``None`` if
    the file is missing/invalid; ``0`` if valid but empty.
    """
    if not mapping_path.exists():
        return None
    try:
        with open(mapping_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    originals = {
        c.get("original_pdf")
        for c in data.get("chunks", []) or []
        if isinstance(c, dict) and c.get("original_pdf")
    }
    for d in data.get("direct", []) or []:
        if not isinstance(d, dict):
            continue
        path = d.get("pdf_path") or d.get("pdf_name")
        if path:
            originals.add(Path(path).name)
    return len(originals)


def _count_failed_chunks(chunks_dir: Path) -> int:
    """Mirror ``find ... -name '*.validation.yaml' -exec grep -l 'failed_pages_detail:'``.

    Counts chunk validation files that have any ``failed_pages_detail:``
    block. Used by Step 2.5 to decide whether to invoke ``retry_failed_pages``.
    """
    if not chunks_dir.exists():
        return 0
    count = 0
    for path in chunks_dir.glob("*.validation.yaml"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                if "failed_pages_detail:" in f.read():
                    count += 1
        except OSError:
            pass
    return count


def _create_direct_pdf_symlinks(mapping_path: Path, direct_dir: Path) -> int:
    """Replace the symlink loop at ``run.sh:354-372``.

    Wipes pre-existing ``*.pdf`` in ``direct_dir`` (matches bash
    ``rm -f *.pdf 2>/dev/null || true``) and links each ``direct`` entry
    that still resolves on disk. Returns the count linked.
    """
    if not mapping_path.exists():
        return 0
    direct_dir.mkdir(parents=True, exist_ok=True)
    for old in direct_dir.glob("*.pdf"):
        try:
            old.unlink()
        except OSError:
            pass
    try:
        with open(mapping_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0
    count = 0
    for entry in data.get("direct", []) or []:
        if not isinstance(entry, dict):
            continue
        pdf_path = Path(entry.get("pdf_path", ""))
        if pdf_path.exists():
            link_path = direct_dir / pdf_path.name
            if link_path.exists() or link_path.is_symlink():
                try:
                    link_path.unlink()
                except OSError:
                    continue
            os.symlink(pdf_path, link_path)
            count += 1
    return count


def _mark_pipeline_completed(pm: ProgressManager) -> None:
    """Replace the inline JSON edit at ``run.sh:402-417``.

    Sets ``status='completed'``, ``completed_at`` (top-level), and the
    ``merge`` step status + completed_at. ProgressManager has no helper
    that does both at once, so this writes through ``pm._data`` and saves.
    """
    pm.load()
    now = datetime.now().isoformat()
    pm._data["status"] = "completed"
    pm._data["completed_at"] = now
    pm._data.setdefault("steps", {})
    pm._data["steps"]["merge"] = {"status": "completed", "completed_at": now}
    pm.save()


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
        passed = (
            all(isinstance(r, dict) and r.get("passed", True) for r in results)
            if results
            else summary_block.get("overall_passed", True)
        )

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
            "PLANO_REFATORACAO.md)."
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

    p_run = sub.add_parser("run", help="Run the full Stage-1 pipeline (Steps 1–9).")
    p_run.add_argument("--restart", action="store_true", help="Archive and reset progress before running.")
    p_run.add_argument("--retry-failed", action="store_true", help="Run only Step 2.5 (retry failed pages).")
    p_run.add_argument("--task-name", "-t", default=None, help="Task name (used for archive + Step 9 report).")
    p_run.add_argument(
        "--no-quality-gate",
        dest="quality_gate",
        action="store_false",
        help="Skip Step 4.5 KQI gate; proceed to Step 5 even if MARCO thresholds fail.",
    )
    p_run.set_defaults(quality_gate=True)

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

    if args.cmd == "run":
        opts = RunOptions.from_env(
            restart=args.restart,
            retry_failed=args.retry_failed,
            task_name=args.task_name,
            quality_gate=args.quality_gate,
        )
        return pipeline.run(opts)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
