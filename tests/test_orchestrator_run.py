"""Fase G.2 — Pipeline.run() and the helpers that replace bash inline parsing.

Two layers of coverage:

1. Pure helpers (``_sanitize_short_name``, ``_compute_expected_count``,
   ``_count_failed_chunks``, ``_create_direct_pdf_symlinks``,
   ``_mark_pipeline_completed``, ``_int_env``) — exercised against synthetic
   inputs without any subprocess.
2. ``Pipeline._stepN_cmd`` — verifies the command list each step builds.
3. ``Pipeline.run()`` — patches ``subprocess.Popen`` to a recorder so we can
   assert the call sequence without spawning real processes.

No live API calls and no real PDFs — tests run in CI without secrets.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "conversao"))
sys.path.insert(0, str(REPO_ROOT / "conversao" / "scripts"))

from progress_manager import ProgressManager  # noqa: E402

from orchestrator import (  # noqa: E402
    Pipeline,
    RunOptions,
    _compute_expected_count,
    _count_failed_chunks,
    _create_direct_pdf_symlinks,
    _int_env,
    _mark_pipeline_completed,
    _sanitize_short_name,
)


# --------------------------------------------------------------- fixtures


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "conversao"
    (r / "input" / "split_pdfs").mkdir(parents=True)
    (r / "output").mkdir()
    (r / "scripts" / "admin").mkdir(parents=True)
    (r / "logs").mkdir()
    (r / "api").mkdir()
    return r


# --------------------------------------------------------- _int_env


def test_int_env_uses_default_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("X_TEST_VAR", raising=False)
    assert _int_env("X_TEST_VAR", 42) == 42


def test_int_env_parses_integer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("X_TEST_VAR", "7")
    assert _int_env("X_TEST_VAR", 42) == 7


def test_int_env_falls_back_on_garbage(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("X_TEST_VAR", "not-a-number")
    assert _int_env("X_TEST_VAR", 42) == 42


# ---------------------------------------------------- RunOptions.from_env


def test_run_options_defaults_match_bash(monkeypatch: pytest.MonkeyPatch):
    for name in ("MAX_PAGES", "MAX_SIZE", "SEMAPHORE", "LLM_CONCURRENT"):
        monkeypatch.delenv(name, raising=False)
    opts = RunOptions.from_env()
    # Defaults from run.sh:31-42 (tuned for 6 API keys).
    assert opts.max_pages_per_chunk == 50
    assert opts.max_size_mb == 50
    assert opts.pdf_concurrency == 30
    assert opts.llm_concurrent == 10
    assert opts.restart is False
    assert opts.retry_failed is False
    assert opts.task_name is None


def test_run_options_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_PAGES", "20")
    monkeypatch.setenv("SEMAPHORE", "5")
    monkeypatch.setenv("LLM_CONCURRENT", "2")
    opts = RunOptions.from_env()
    assert opts.max_pages_per_chunk == 20
    assert opts.pdf_concurrency == 5
    assert opts.llm_concurrent == 2


def test_run_options_overrides_kwarg(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAX_PAGES", raising=False)
    opts = RunOptions.from_env(restart=True, task_name="t1", max_pages_per_chunk=99)
    assert opts.restart is True
    assert opts.task_name == "t1"
    assert opts.max_pages_per_chunk == 99


# ---------------------------------------------- _sanitize_short_name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("simple-name", "simple-name"),
        ("with spaces here", "with-spaces-here"),
        ("punctuation!@#$.md", "punctuationmd"),
        ("Mixed Case 1234", "Mixed-Case-1234"),
        ("Á acentos não viram dash", "-acentos-no-viram-dash"),
        ("a" * 80, "a" * 50),  # truncated at 50
        ("a b c d e f g h i j k l m n o p q r s t u v w x y", "a-b-c-d-e-f-g-h-i-j-k-l-m-n-o-p-q-r-s-t-u-v-w-x-y"),
    ],
)
def test_sanitize_short_name(raw: str, expected: str):
    assert _sanitize_short_name(raw) == expected


def test_sanitize_short_name_matches_bash_pipeline_for_real_dir():
    # "Darnton.cultura.civilidade" → drop dots → "Darntonculturacivilidade".
    assert _sanitize_short_name("Darnton.cultura.civilidade") == "Darntonculturacivilidade"


# ---------------------------------------------- _compute_expected_count


def test_expected_count_none_when_missing(tmp_path: Path):
    assert _compute_expected_count(tmp_path / "missing.json") is None


def test_expected_count_zero_when_empty(tmp_path: Path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"chunks": [], "direct": []}))
    assert _compute_expected_count(p) == 0


def test_expected_count_counts_unique_originals(tmp_path: Path):
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps(
            {
                "chunks": [
                    {"original_pdf": "a.pdf"},
                    {"original_pdf": "a.pdf"},  # duplicate same original
                    {"original_pdf": "b.pdf"},
                ],
                "direct": [
                    {"pdf_path": "/some/c.pdf", "pdf_name": "c.pdf"},
                ],
            }
        )
    )
    assert _compute_expected_count(p) == 3


def test_expected_count_uses_basename_for_direct(tmp_path: Path):
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps(
            {
                "chunks": [],
                "direct": [
                    {"pdf_path": "/long/path/x.pdf"},
                    {"pdf_path": "/other/x.pdf"},  # same basename → unique
                ],
            }
        )
    )
    assert _compute_expected_count(p) == 1


def test_expected_count_returns_none_on_invalid_json(tmp_path: Path):
    p = tmp_path / "m.json"
    p.write_text("not json")
    assert _compute_expected_count(p) is None


# ---------------------------------------------- _count_failed_chunks


def test_count_failed_chunks_empty_dir(tmp_path: Path):
    assert _count_failed_chunks(tmp_path) == 0


def test_count_failed_chunks_missing_dir(tmp_path: Path):
    assert _count_failed_chunks(tmp_path / "absent") == 0


def test_count_failed_chunks_skips_files_without_marker(tmp_path: Path):
    (tmp_path / "a.validation.yaml").write_text("status: ok\n")
    (tmp_path / "b.validation.yaml").write_text(
        "status: partial\nfailed_pages_detail:\n  - page: 5\n"
    )
    (tmp_path / "c.validation.yaml").write_text(
        "failed_pages_detail:\n"
    )
    assert _count_failed_chunks(tmp_path) == 2


# ---------------------------------------------- _create_direct_pdf_symlinks


def test_create_symlinks_links_existing_pdfs(tmp_path: Path):
    src1 = tmp_path / "src" / "a.pdf"
    src2 = tmp_path / "src" / "b.pdf"
    src1.parent.mkdir()
    src1.write_bytes(b"%PDF-fake")
    src2.write_bytes(b"%PDF-fake")
    mapping = tmp_path / "m.json"
    mapping.write_text(
        json.dumps(
            {
                "chunks": [],
                "direct": [
                    {"pdf_path": str(src1), "pdf_name": "a.pdf"},
                    {"pdf_path": str(src2), "pdf_name": "b.pdf"},
                ],
            }
        )
    )
    direct_dir = tmp_path / "direct"
    n = _create_direct_pdf_symlinks(mapping, direct_dir)
    assert n == 2
    assert (direct_dir / "a.pdf").is_symlink()
    assert (direct_dir / "b.pdf").is_symlink()


def test_create_symlinks_skips_missing_sources(tmp_path: Path):
    mapping = tmp_path / "m.json"
    mapping.write_text(
        json.dumps(
            {
                "chunks": [],
                "direct": [
                    {"pdf_path": "/does/not/exist.pdf", "pdf_name": "exist.pdf"},
                ],
            }
        )
    )
    direct_dir = tmp_path / "direct"
    assert _create_direct_pdf_symlinks(mapping, direct_dir) == 0


def test_create_symlinks_clears_old_pdfs(tmp_path: Path):
    direct_dir = tmp_path / "direct"
    direct_dir.mkdir()
    stale = direct_dir / "old.pdf"
    stale.write_bytes(b"old")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({"chunks": [], "direct": []}))
    _create_direct_pdf_symlinks(mapping, direct_dir)
    assert not stale.exists()


# ---------------------------------------------- _mark_pipeline_completed


def test_mark_pipeline_completed_writes_status_and_step(tmp_path: Path):
    progress = tmp_path / "progress.json"
    progress.write_text(
        json.dumps(
            {
                "version": "0.8",
                "started_at": "2026-05-04T10:00:00",
                "updated_at": "2026-05-04T10:30:00",
                "status": "in_progress",
                "steps": {
                    "split": {"status": "completed"},
                    "merge": {"status": "pending"},
                },
                "pdf_progress": {},
                "statistics": {},
            }
        )
    )
    pm = ProgressManager(progress_file=str(progress))
    _mark_pipeline_completed(pm)
    written = json.loads(progress.read_text())
    assert written["status"] == "completed"
    assert "completed_at" in written
    assert written["steps"]["merge"]["status"] == "completed"
    assert "completed_at" in written["steps"]["merge"]


# --------------------------------------- step command shapes -------------


def test_step1_cmd_shape(root: Path):
    p = Pipeline.from_env(root)
    cmd = p._step1_cmd(RunOptions(max_pages_per_chunk=20, max_size_mb=10))
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("/scripts/split_large_pdfs_smart.py")
    assert "--input-dir" in cmd
    assert str(root / "input") in cmd
    assert "--chunk-size" in cmd and "20" in cmd
    assert "--max-chunk-size-mb" in cmd and "10" in cmd
    assert "--mapping-file" in cmd


def test_step2_cmd_targets_split_dir(root: Path):
    p = Pipeline.from_env(root)
    cmd = p._step2_cmd(RunOptions(pdf_concurrency=4, llm_concurrent=3))
    assert str(root / "input" / "split_pdfs") in cmd
    assert str(root / "output" / "chunks") in cmd
    assert "--semaphore-limit" in cmd and "3" in cmd
    assert "--pdf-concurrency" in cmd and "4" in cmd


def test_step3_cmd_targets_direct_dir(root: Path):
    p = Pipeline.from_env(root)
    cmd = p._step3_cmd(RunOptions())
    assert str(root / "input" / "direct_pdfs") in cmd
    assert str(root / "output") in cmd


def test_step4_cmd_passes_mapping(root: Path):
    p = Pipeline.from_env(root)
    cmd = p._step4_cmd()
    assert cmd[1].endswith("/scripts/merge_results_full.py")
    assert "--mapping-file" in cmd


def test_step8_cmd_omits_expected_when_no_mapping(root: Path):
    p = Pipeline.from_env(root)
    cmd = p._step8_cmd()
    assert "--expected-count" not in cmd


def test_step8_cmd_includes_expected_when_mapping_present(root: Path):
    mapping = root / "input" / "split_pdfs" / "split_mapping.json"
    mapping.write_text(
        json.dumps({"chunks": [], "direct": [{"pdf_path": "/x/a.pdf"}]})
    )
    p = Pipeline.from_env(root)
    cmd = p._step8_cmd()
    assert "--expected-count" in cmd
    idx = cmd.index("--expected-count")
    assert cmd[idx + 1] == "1"


def test_step9_cmd_uses_task_name(root: Path):
    p = Pipeline.from_env(root)
    cmd = p._step9_cmd(RunOptions(task_name="batch-x"))
    assert "--task-name" in cmd
    assert "batch-x" in cmd


def test_step9_cmd_auto_generates_task_name_when_absent(root: Path):
    p = Pipeline.from_env(root)
    cmd = p._step9_cmd(RunOptions(task_name=None))
    idx = cmd.index("--task-name")
    assert cmd[idx + 1].startswith("task_")


# ----------------------- step5 final-delivery copy (pure I/O) -----------


def test_step5_copies_md_and_yaml_with_sanitized_name(root: Path):
    # Build output/<dir>/ with .md + _all_figures.yaml
    pdf_dir = root / "output" / "Darnton.cultura.civilidade"
    pdf_dir.mkdir()
    (pdf_dir / "Darnton.cultura.civilidade.md").write_text("# x", encoding="utf-8")
    (pdf_dir / "Darnton.cultura.civilidade_all_figures.yaml").write_text("k: v", encoding="utf-8")

    pipeline = Pipeline.from_env(root)
    rc = pipeline._step5_final_delivery_copy()
    assert rc == 0

    delivery = root / "final-delivery"
    assert (delivery / "Darntonculturacivilidade.md").exists()
    assert (delivery / "Darntonculturacivilidade.yaml").exists()


def test_step5_skips_chunks_directory(root: Path):
    chunks = root / "output" / "chunks"
    chunks.mkdir()
    (chunks / "x.md").write_text("x", encoding="utf-8")
    pipeline = Pipeline.from_env(root)
    pipeline._step5_final_delivery_copy()
    assert not (root / "final-delivery" / "x.md").exists()


def test_step5_falls_back_to_non_validation_yaml(root: Path):
    pdf_dir = root / "output" / "doc"
    pdf_dir.mkdir()
    (pdf_dir / "doc.md").write_text("# x", encoding="utf-8")
    # No _all_figures.yaml — only doc.yaml (non-validation)
    (pdf_dir / "doc.yaml").write_text("k: v", encoding="utf-8")
    (pdf_dir / "doc.validation.yaml").write_text("ignored: 1", encoding="utf-8")
    pipeline = Pipeline.from_env(root)
    pipeline._step5_final_delivery_copy()
    delivery_yaml = (root / "final-delivery" / "doc.yaml").read_text(encoding="utf-8")
    assert delivery_yaml == "k: v"


def test_step5_copies_footnotes_sidecar(root: Path):
    """J.4: <pdf>.footnotes.yaml viaja com .md como <short_name>.footnotes.yaml."""
    pdf_dir = root / "output" / "Darnton.cultura.civilidade"
    pdf_dir.mkdir()
    (pdf_dir / "Darnton.cultura.civilidade.md").write_text("# x", encoding="utf-8")
    (pdf_dir / "Darnton.cultura.civilidade_all_figures.yaml").write_text("k: v", encoding="utf-8")
    (pdf_dir / "Darnton.cultura.civilidade.footnotes.yaml").write_text(
        "version: '1.0'\nnotes: []\n", encoding="utf-8"
    )

    pipeline = Pipeline.from_env(root)
    pipeline._step5_final_delivery_copy()

    delivery = root / "final-delivery"
    assert (delivery / "Darntonculturacivilidade.md").exists()
    assert (delivery / "Darntonculturacivilidade.yaml").exists()
    assert (delivery / "Darntonculturacivilidade.footnotes.yaml").exists()


def test_step5_no_sidecar_skipped_silently(root: Path):
    """Livro legacy sem sidecar: step5 não falha, simplesmente não copia."""
    pdf_dir = root / "output" / "legacy_doc"
    pdf_dir.mkdir()
    (pdf_dir / "legacy_doc.md").write_text("# x", encoding="utf-8")
    (pdf_dir / "legacy_doc_all_figures.yaml").write_text("k: v", encoding="utf-8")
    # No footnotes.yaml

    pipeline = Pipeline.from_env(root)
    rc = pipeline._step5_final_delivery_copy()
    assert rc == 0

    delivery = root / "final-delivery"
    assert (delivery / "legacydoc.md").exists()
    assert not (delivery / "legacydoc.footnotes.yaml").exists()


# --------------------- full run() with subprocess patched ----------------


class _RecordingPopen:
    """Stand-in for subprocess.Popen used by both ``Pipeline._run_subprocess``
    (which iterates ``stdout`` and calls ``wait``) and ``subprocess.run``
    (which uses ``Popen`` as a context manager and calls ``communicate``).
    """

    invocations: List[Dict[str, Any]] = []
    return_code: int = 0
    stdout_text: str = ""

    def __init__(self, cmd: List[str], **kwargs: Any):
        self.cmd = cmd
        self.kwargs = kwargs
        type(self).invocations.append({"cmd": list(cmd), "env": kwargs.get("env", {})})
        self.stdout = iter(self.stdout_text.splitlines(keepends=True))
        self.stderr = None
        self.stdin = None
        self.returncode = type(self).return_code

    def wait(self, timeout: Optional[float] = None) -> int:
        self.returncode = type(self).return_code
        return self.returncode

    def communicate(self, input: Any = None, timeout: Optional[float] = None):
        self.returncode = type(self).return_code
        return ("", "")

    def poll(self) -> int:
        self.returncode = type(self).return_code
        return self.returncode

    def __enter__(self) -> "_RecordingPopen":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False

    @classmethod
    def reset(cls) -> None:
        cls.invocations = []
        cls.return_code = 0
        cls.stdout_text = ""


@pytest.fixture
def patch_popen(monkeypatch: pytest.MonkeyPatch):
    import orchestrator as orch
    _RecordingPopen.reset()
    monkeypatch.setattr(orch.subprocess, "Popen", _RecordingPopen)
    yield _RecordingPopen
    _RecordingPopen.reset()


def test_run_with_no_input_pdfs_skips_steps(root: Path, patch_popen):
    pipeline = Pipeline.from_env(root)
    rc = pipeline.run()
    assert rc == 0
    assert patch_popen.invocations == []


def test_run_retry_failed_only_invokes_step_2_5(root: Path, patch_popen):
    # input/ needs at least one PDF for run() to enter the body
    (root / "input" / "smoke.pdf").write_bytes(b"%PDF-fake")
    chunks = root / "output" / "chunks"
    chunks.mkdir()
    (chunks / "v.validation.yaml").write_text("failed_pages_detail:\n  - page: 1\n")

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run(RunOptions(retry_failed=True))
    assert rc == 0
    assert len(patch_popen.invocations) == 1
    cmd = patch_popen.invocations[0]["cmd"]
    assert any("retry_failed_pages.py" in arg for arg in cmd)


def test_run_full_invokes_steps_in_order(root: Path, patch_popen):
    """A full run with one direct PDF and no chunks calls the expected sequence."""
    src = root / "src" / "smoke.pdf"
    src.parent.mkdir()
    src.write_bytes(b"%PDF-fake")
    (root / "input" / "smoke.pdf").symlink_to(src)
    mapping = root / "input" / "split_pdfs" / "split_mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "chunks": [],
                "direct": [{"pdf_path": str(src), "pdf_name": "smoke.pdf"}],
            }
        )
    )

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run()
    assert rc == 0

    # Each subprocess invocation maps to one of the scripts.
    scripts_invoked = [
        Path(inv["cmd"][1]).name for inv in patch_popen.invocations
    ]
    # Step 1 (split), Step 3 (docmind direct), Step 6 (postprocess),
    # Step 7 (quality report), Step 8 (final_delivery_check), Step 9 (generate_report).
    # Steps 2, 2.5, 4 skip because no chunks exist.
    assert scripts_invoked == [
        "split_large_pdfs_smart.py",
        "docmind_converter.py",
        "postprocess.py",
        "generate_quality_report.py",
        "final_delivery_check.py",
        "generate_report.py",
    ]


def test_run_step_failure_is_or_aggregated(root: Path, monkeypatch):
    """Non-zero exit codes from steps OR into the final return code."""
    (root / "input" / "smoke.pdf").write_bytes(b"%PDF-fake")
    mapping = root / "input" / "split_pdfs" / "split_mapping.json"
    mapping.write_text(json.dumps({"chunks": [], "direct": []}))

    import orchestrator as orch
    _RecordingPopen.reset()
    _RecordingPopen.return_code = 2
    monkeypatch.setattr(orch.subprocess, "Popen", _RecordingPopen)

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run()
    # Step 9 silences its own failures; other failing steps OR up to non-zero.
    assert rc != 0


def test_run_step9_failure_is_silenced(root: Path, monkeypatch):
    """Even if generate_report.py fails, run() returns 0 when other steps OK."""
    (root / "input" / "smoke.pdf").write_bytes(b"%PDF-fake")

    class Step9OnlyFailure(_RecordingPopen):
        def wait(self, timeout: Optional[float] = None) -> int:
            cmd_name = Path(self.cmd[1]).name if len(self.cmd) > 1 else ""
            self.returncode = 7 if cmd_name == "generate_report.py" else 0
            return self.returncode

    import orchestrator as orch
    _RecordingPopen.reset()
    monkeypatch.setattr(orch.subprocess, "Popen", Step9OnlyFailure)

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run()
    assert rc == 0


def _seed_validation_yaml(
    root: Path,
    pdf_name: str,
    *,
    overall_pass: bool,
    page_success_rate: float = 1.0,
    total_pages: int = 10,
) -> None:
    """Write `output/{pdf_name}/{pdf_name}.validation.yaml` to drive the gate."""
    pdf_dir = root / "output" / pdf_name
    pdf_dir.mkdir(parents=True, exist_ok=True)
    failed = round(total_pages * (1 - page_success_rate))
    content = (
        "document_info:\n"
        f"  filename: {pdf_name}.pdf\n"
        f"  total_pages: {total_pages}\n"
        "kqi_metrics:\n"
        "  yaml_insertion_rate: 1.0\n"
        "  yaml_insertion_pass: true\n"
        "  average_confidence: 0.9\n"
        "  confidence_pass: true\n"
        f"  page_success_rate: {page_success_rate}\n"
        f"  overall_quality_pass: {'true' if overall_pass else 'false'}\n"
        "page_statistics:\n"
        f"  total_pages: {total_pages}\n"
        f"  failed_pages: {failed}\n"
    )
    (pdf_dir / f"{pdf_name}.validation.yaml").write_text(content, encoding="utf-8")


def test_quality_gate_aborts_when_overall_quality_pass_false(root: Path, patch_popen):
    """Gate failure aborts pipeline before Step 5 and leaves progress.json untouched."""
    (root / "input" / "bad.pdf").write_bytes(b"%PDF-fake")
    _seed_validation_yaml(
        root, "bad", overall_pass=False, page_success_rate=0.65, total_pages=27
    )

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run()

    assert rc != 0
    # Steps 5-9 must not run (no postprocess/quality/final/report invocations)
    scripts_invoked = [Path(inv["cmd"][1]).name for inv in patch_popen.invocations]
    assert "postprocess.py" not in scripts_invoked
    assert "final_delivery_check.py" not in scripts_invoked
    assert "generate_quality_report.py" not in scripts_invoked
    assert "generate_report.py" not in scripts_invoked


def test_quality_gate_passes_when_all_overall_quality_pass_true(
    root: Path, patch_popen
):
    """All validation.yaml passing lets the pipeline reach Steps 5-9."""
    (root / "input" / "good.pdf").write_bytes(b"%PDF-fake")
    _seed_validation_yaml(root, "good", overall_pass=True, page_success_rate=0.99)

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run()

    assert rc == 0
    scripts_invoked = [Path(inv["cmd"][1]).name for inv in patch_popen.invocations]
    assert "postprocess.py" in scripts_invoked
    assert "final_delivery_check.py" in scripts_invoked


def test_quality_gate_skipped_by_no_quality_gate_flag(root: Path, patch_popen):
    """--no-quality-gate lets a failing run continue to Step 5+."""
    (root / "input" / "bad.pdf").write_bytes(b"%PDF-fake")
    _seed_validation_yaml(
        root, "bad", overall_pass=False, page_success_rate=0.65, total_pages=27
    )

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run(RunOptions(quality_gate=False))

    assert rc == 0
    scripts_invoked = [Path(inv["cmd"][1]).name for inv in patch_popen.invocations]
    assert "postprocess.py" in scripts_invoked
    assert "final_delivery_check.py" in scripts_invoked


def test_step1_failure_short_circuits_pipeline(root: Path, monkeypatch):
    """rc=1 from Step 1 (splitter) must skip every downstream step."""
    (root / "input" / "smoke.pdf").write_bytes(b"%PDF-fake")

    class Step1Fails(_RecordingPopen):
        def wait(self, timeout: Optional[float] = None) -> int:
            cmd_name = Path(self.cmd[1]).name if len(self.cmd) > 1 else ""
            self.returncode = 1 if cmd_name == "split_large_pdfs_smart.py" else 0
            return self.returncode

    import orchestrator as orch
    _RecordingPopen.reset()
    monkeypatch.setattr(orch.subprocess, "Popen", Step1Fails)

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run()

    assert rc == 1
    scripts_invoked = [Path(inv["cmd"][1]).name for inv in _RecordingPopen.invocations]
    # Only Step 1 was attempted; no Step 2/2.5/3/4/5/6/7/8/9.
    assert scripts_invoked == ["split_large_pdfs_smart.py"]


def test_validate_split_mapping_aborts_on_status_error(root: Path, patch_popen):
    """Pre-Step-2 guard: split_mapping marking a PDF as status=error aborts run."""
    (root / "input" / "smoke.pdf").write_bytes(b"%PDF-fake")
    mapping = root / "input" / "split_pdfs" / "split_mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "stats": {
                    "pdfs": {
                        "broken.pdf": {
                            "status": "error",
                            "error": "Invalid Elementary Object",
                        }
                    }
                },
                "chunks": [],
                "direct": [],
            }
        )
    )

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run()

    assert rc == 1
    scripts_invoked = [Path(inv["cmd"][1]).name for inv in patch_popen.invocations]
    # Only Step 1 ran (subprocess was patched to rc=0); guard then aborted.
    assert scripts_invoked == ["split_large_pdfs_smart.py"]


def test_quality_gate_aborts_when_validation_count_mismatch(
    root: Path, patch_popen
):
    """split_mapping says 3 PDFs but only 2 .validation.yaml on disk → gate aborts."""
    (root / "input" / "big.pdf").write_bytes(b"%PDF-fake")
    mapping = root / "input" / "split_pdfs" / "split_mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "chunks": [
                    {"original_pdf": "big.pdf"},
                    {"original_pdf": "absent.pdf"},
                ],
                "direct": [
                    {"pdf_path": "/x/good.pdf", "pdf_name": "good.pdf"},
                ],
            }
        )
    )
    _seed_validation_yaml(root, "big", overall_pass=True, page_success_rate=1.0)
    _seed_validation_yaml(root, "good", overall_pass=True, page_success_rate=1.0)

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run()

    assert rc != 0
    scripts_invoked = [Path(inv["cmd"][1]).name for inv in patch_popen.invocations]
    assert "postprocess.py" not in scripts_invoked
    assert "final_delivery_check.py" not in scripts_invoked


def test_quality_gate_reads_chunked_pdf_validation(root: Path, patch_popen):
    """Aggregated <merged>.validation.yaml is consumed by the gate just like direct PDFs."""
    (root / "input" / "huge.pdf").write_bytes(b"%PDF-fake")
    mapping = root / "input" / "split_pdfs" / "split_mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "chunks": [
                    {"original_pdf": "huge.pdf", "chunk_idx": 1},
                    {"original_pdf": "huge.pdf", "chunk_idx": 2},
                ],
                "direct": [],
            }
        )
    )
    # Aggregated validation produced by merge_document — overall_pass=False
    _seed_validation_yaml(
        root, "huge", overall_pass=False, page_success_rate=0.60, total_pages=20
    )

    pipeline = Pipeline.from_env(root)
    rc = pipeline.run()

    assert rc != 0
    scripts_invoked = [Path(inv["cmd"][1]).name for inv in patch_popen.invocations]
    assert "postprocess.py" not in scripts_invoked
    assert "final_delivery_check.py" not in scripts_invoked


def test_archive_and_reset_runs_admin_script(root: Path, patch_popen):
    """--restart with existing progress.json invokes archive_progress.py."""
    progress = root / "progress.json"
    progress.write_text(json.dumps({"status": "in_progress"}))
    (progress.parent / "progress.json.lock").write_text("")
    (root / "input" / "split_pdfs" / "stale.pdf").write_bytes(b"x")

    pipeline = Pipeline.from_env(root)
    pipeline._archive_and_reset(task_name="my-batch")

    cmd = patch_popen.invocations[0]["cmd"]
    assert any("archive_progress.py" in c for c in cmd)
    assert "--task-name" in cmd
    assert "my-batch" in cmd
    # File cleanup
    assert not progress.exists()
    assert not (root / "input" / "split_pdfs").exists()
