"""``Document`` — one Stage-1 PDF with its chunks, outputs and progress hooks.

Built in Fase E of PLANO_REFATORACAO.md (2026-05). Consolidates two flows
that used to read ``split_mapping.json`` and the ``output/{name}/`` layout
independently: ``merge_results_full.py`` and the resume-validation in
``progress_manager.py``.

Scope intentionally narrow (per ADR-0002 reasoning): represents a Stage-1
PDF only. Stage-2 (Ficha/Livro post-processing) keeps its own dataclasses.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Optional

import yaml


@dataclass(frozen=True)
class Chunk:
    """One slice of a PDF that was too large to process in a single pass."""

    path: Path
    pages: int
    chunk_idx: int
    total_chunks: int
    original_pdf: str

    @property
    def name(self) -> str:
        """Stem of the chunk PDF (used as the per-chunk ``output/{name}/`` dir)."""
        return self.path.stem


@dataclass(frozen=True)
class FailedPage:
    """One page that Stage 1 could not extract — drawn from validation.yaml."""

    page: int
    error: str


@dataclass
class Document:
    """One original PDF processed by Stage 1.

    For chunked PDFs ``chunks`` holds the slices in ``chunk_idx`` order; for
    PDFs that didn't need splitting ``chunks`` is empty and the PDF was
    processed straight into ``output/{name}/``.
    """

    pdf_path: Path
    original_name: str
    chunks: List[Chunk] = field(default_factory=list)
    output_dir: Path = field(default_factory=Path)

    # ------------------------------------------------------------------ paths

    @property
    def is_chunked(self) -> bool:
        return len(self.chunks) > 0

    @property
    def merged_md_path(self) -> Path:
        return self.output_dir / f"{self.original_name}.md"

    @property
    def yaml_path(self) -> Path:
        return self.output_dir / f"{self.original_name}_all_figures.yaml"

    @property
    def validation_path(self) -> Path:
        return self.output_dir / f"{self.original_name}.validation.yaml"

    @property
    def images_dir(self) -> Path:
        return self.output_dir / "images"

    @property
    def yaml_metadata_dir(self) -> Path:
        return self.output_dir / "yaml_metadata"

    def total_pages(self) -> int:
        """Sum of pages across chunks; 0 for direct PDFs (unknown without inspecting the PDF)."""
        return sum(c.pages for c in self.chunks)

    # ------------------------------------------------------------ discovery

    @classmethod
    def discover(
        cls,
        mapping_path: Path,
        output_root: Path,
    ) -> List["Document"]:
        """Build a Document list from ``split_mapping.json``.

        ``output_root`` is the directory where ``{name}/`` subdirectories live
        (i.e. the parent of the per-PDF output dirs — for chunked PDFs that's
        usually ``output/chunks/`` pre-merge or ``output/`` post-merge; for
        direct PDFs it's ``output/``).
        """
        mapping_path = Path(mapping_path)
        output_root = Path(output_root)

        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)

        docs: List[Document] = []

        # Chunked PDFs — group slices by ``original_pdf``
        chunks_by_pdf: dict[str, List[Chunk]] = defaultdict(list)
        for entry in mapping.get("chunks", []) or []:
            chunk = Chunk(
                path=Path(entry["path"]),
                pages=int(entry["pages"]),
                chunk_idx=int(entry["chunk_idx"]),
                total_chunks=int(entry["total_chunks"]),
                original_pdf=entry["original_pdf"],
            )
            chunks_by_pdf[chunk.original_pdf].append(chunk)

        for original_pdf, chunks in chunks_by_pdf.items():
            chunks_sorted = sorted(chunks, key=lambda c: c.chunk_idx)
            original_name = Path(original_pdf).stem
            # split_mapping.json doesn't carry the original PDF path for chunks;
            # approximate as a sibling of the first chunk's parent directory.
            approx_path = (
                chunks_sorted[0].path.parent.parent / original_pdf
                if chunks_sorted
                else Path(original_pdf)
            )
            docs.append(
                cls(
                    pdf_path=approx_path,
                    original_name=original_name,
                    chunks=chunks_sorted,
                    output_dir=output_root / original_name,
                )
            )

        # Direct PDFs — one Document with empty chunks
        for entry in mapping.get("direct", []) or []:
            pdf_path = Path(entry["pdf_path"])
            pdf_name = entry.get("pdf_name") or pdf_path.name
            original_name = Path(pdf_name).stem
            docs.append(
                cls(
                    pdf_path=pdf_path,
                    original_name=original_name,
                    chunks=[],
                    output_dir=output_root / original_name,
                )
            )

        return docs

    # ----------------------------------------------------------- completion

    def _infer_step_name(self) -> str:
        """Match the legacy convention from ``docmind_converter.py``."""
        return "process_chunks" if "chunks" in str(self.output_dir) else "process_direct"

    def is_complete(
        self,
        progress_manager: Any = None,
        step_name: Optional[str] = None,
    ) -> bool:
        """Has Stage 1 finished this PDF?

        - With ``progress_manager``: defers to its ``validate_pdf_completion``
          (deep check: completed list + MD existence + min size + page rate).
        - Without: fast check that ``merged_md_path`` exists and is non-empty.
        """
        if progress_manager is not None:
            step = step_name or self._infer_step_name()
            if hasattr(progress_manager, "validate_pdf_completion"):
                report = progress_manager.validate_pdf_completion(
                    step,
                    self.original_name,
                    str(self.output_dir.parent),
                )
                return bool(report.get("valid"))
            if hasattr(progress_manager, "is_pdf_completed"):
                return bool(progress_manager.is_pdf_completed(step, self.original_name))
            return False

        if not self.merged_md_path.exists():
            return False
        try:
            return self.merged_md_path.stat().st_size > 0
        except OSError:
            return False

    def failed_pages(self) -> List[FailedPage]:
        """Read ``failed_pages_detail`` from validation.yaml.

        Returns an empty list if the file is missing, malformed, or has no
        failed entries. Doesn't raise — quality reporting often runs against
        partial output.
        """
        if not self.validation_path.exists():
            return []
        try:
            with open(self.validation_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return []

        detail = data.get("failed_pages_detail", []) or []
        out: List[FailedPage] = []
        for item in detail:
            if not isinstance(item, dict):
                continue
            if "page" not in item:
                continue
            try:
                page = int(item["page"])
            except (TypeError, ValueError):
                continue
            error = str(item.get("error", "") or "")
            out.append(FailedPage(page=page, error=error))
        return out

    # -------------------------------------------------- chunk-merge helpers

    @staticmethod
    def _adjust_md_page_numbers(content: str, offset: int) -> str:
        """Renumber ``[Page N]`` and ``## Page N`` headers by ``offset``."""
        def replace_page_bracket(match: re.Match) -> str:
            page_num = int(match.group(1))
            return f"[Page {page_num + offset}]"

        def replace_page_header(match: re.Match) -> str:
            page_num = int(match.group(1))
            return f"## Page {page_num + offset}"

        content = re.sub(r"\[Page (\d+)\]", replace_page_bracket, content)
        content = re.sub(
            r"^## Page (\d+)$",
            replace_page_header,
            content,
            flags=re.MULTILINE,
        )
        return content

    @staticmethod
    def _adjust_md_image_references(content: str, offset: int) -> str:
        """Renumber ``images/page_NNN.png`` references by ``offset``."""
        def replace_image_ref(match: re.Match) -> str:
            alt_text = match.group(1)
            page_num = int(match.group(2))
            return f"![{alt_text}](images/page_{page_num + offset:03d}.png)"

        return re.sub(
            r"!\[(.*?)\]\(images/page_(\d+)\.png\)",
            replace_image_ref,
            content,
        )

    @staticmethod
    def _adjust_md_yaml_references(content: str, offset: int) -> str:
        """Renumber ``yaml_metadata/Figure_N_pageM.yaml`` references by ``offset``.

        The character class is restricted to filename-safe chars (``\\w./-``),
        not the original ``[^_]`` (any non-underscore). The legacy class let
        the match span across ``](`` in Markdown link syntax — when the same
        path appeared as both link-text and URL (``[path](path)``), only the
        URL got renumbered. Bug captured in Fase E xfail, fixed in Fase H.2.
        """
        def replace_yaml_ref(match: re.Match) -> str:
            prefix = match.group(1)
            page_num = int(match.group(2))
            return f"{prefix}_page{page_num + offset}.yaml"

        return re.sub(
            r"(yaml_metadata/[\w./-]+?)_page(\d+)\.yaml",
            replace_yaml_ref,
            content,
        )

    @classmethod
    def apply_page_offset(cls, content: str, offset: int) -> str:
        """Shift page numbers, image refs and YAML refs in chunk MD by ``offset``.

        Chunk N's pages are numbered 1..pages_in_chunk; merging concatenates
        chunks into the original PDF's numbering, so chunk N+1 needs an offset
        equal to the sum of pages in chunks 1..N.
        """
        if offset == 0:
            return content
        content = cls._adjust_md_page_numbers(content, offset)
        content = cls._adjust_md_image_references(content, offset)
        content = cls._adjust_md_yaml_references(content, offset)
        return content
