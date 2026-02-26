"""
Dataclasses para o book_converter.

Define as estruturas de dados usadas em todo o pipeline de conversão.
"""

from dataclasses import dataclass, field


@dataclass
class TocEntry:
    """Entrada do sumário (Table of Contents)."""
    level: str  # 'part' | 'chapter' | 'section'
    title: str
    page_number: int | None = None
    parent: str | None = None


@dataclass
class ChapterBoundary:
    """Delimitação de um capítulo no texto."""
    title: str
    start_pos: int
    end_pos: int | None = None
    level: str = 'chapter'  # 'part' | 'chapter'


@dataclass
class BookMetadata:
    """Metadados extraídos do livro."""
    titulo: str = ""
    autores: list[str] = field(default_factory=list)
    editora: list[str] = field(default_factory=list)
    ano: int | None = None
    isbn: str | None = None
    edicao: str | None = None
    palavras_chave: list[str] = field(default_factory=list)
