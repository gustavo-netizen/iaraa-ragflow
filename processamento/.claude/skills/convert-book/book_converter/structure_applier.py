"""
Aplica estrutura identificada pelo LLM ao documento.

Este módulo recebe os capítulos e seções identificados pelo LLM
e aplica as modificações necessárias ao conteúdo:
- Remove seções marcadas (figuras, TOC, referências)
- Insere headers markdown nos capítulos identificados
"""

import re
from .models import ChapterBoundary


def remove_sections(lines: list[str], sections: dict) -> tuple[list[str], dict]:
    """
    Remove seções marcadas pelo LLM.

    Args:
        lines: Lista de linhas do documento
        sections: Dicionário com seções para remover:
            - figuras: lista de [inicio, fim]
            - toc: [inicio, fim] ou None
            - referencias: lista de [inicio, fim]

    Returns:
        Tupla (linhas filtradas, mapeamento de índices antigos para novos)
    """
    lines_to_remove = set()

    # Marcar linhas de figuras
    for rng in sections.get('figuras', []):
        if len(rng) == 2:
            start, end = rng
            for i in range(start - 1, end):  # 1-indexed to 0-indexed
                if 0 <= i < len(lines):
                    lines_to_remove.add(i)

    # Marcar TOC
    toc = sections.get('toc')
    if toc and len(toc) == 2:
        start, end = toc
        for i in range(start - 1, end):
            if 0 <= i < len(lines):
                lines_to_remove.add(i)

    # Marcar referências
    for rng in sections.get('referencias', []):
        if len(rng) == 2:
            start, end = rng
            for i in range(start - 1, end):
                if 0 <= i < len(lines):
                    lines_to_remove.add(i)

    # Marcar frontmatter institucional (créditos, ficha catalográfica, etc.)
    frontmatter = sections.get('frontmatter')
    if frontmatter and len(frontmatter) == 2:
        start, end = frontmatter
        for i in range(start - 1, end):
            if 0 <= i < len(lines):
                lines_to_remove.add(i)

    # Criar mapeamento de índices antigos para novos
    index_map = {}
    new_idx = 0
    for old_idx in range(len(lines)):
        if old_idx not in lines_to_remove:
            index_map[old_idx] = new_idx
            new_idx += 1

    # Filtrar linhas
    filtered = [line for i, line in enumerate(lines) if i not in lines_to_remove]

    return filtered, index_map


def adjust_chapter_positions(chapters: list[ChapterBoundary],
                              index_map: dict) -> list[ChapterBoundary]:
    """
    Ajusta posições dos capítulos após remoção de seções.

    Args:
        chapters: Lista de capítulos com posições originais
        index_map: Mapeamento de índices antigos para novos

    Returns:
        Lista de capítulos com posições ajustadas
    """
    adjusted = []
    for ch in chapters:
        old_idx = ch.start_pos - 1  # 1-indexed to 0-indexed
        if old_idx in index_map:
            new_pos = index_map[old_idx] + 1  # Back to 1-indexed
            adjusted.append(ChapterBoundary(
                title=ch.title,
                start_pos=new_pos,
                end_pos=ch.end_pos,
                level=ch.level
            ))
    return adjusted


def insert_chapter_headers(lines: list[str],
                           chapters: list[ChapterBoundary]) -> list[str]:
    """
    Insere headers markdown nos capítulos identificados.

    A função verifica se a linha já possui um header markdown.
    Se não, adiciona o header apropriado (# para part, ## para chapter).

    Args:
        lines: Lista de linhas do documento
        chapters: Lista de capítulos com posições (1-indexed)

    Returns:
        Lista de linhas com headers inseridos
    """
    result = lines.copy()

    # Ordenar por posição (decrescente para não invalidar índices)
    sorted_chapters = sorted(chapters, key=lambda c: c.start_pos, reverse=True)

    for chapter in sorted_chapters:
        idx = chapter.start_pos - 1  # 1-indexed to 0-indexed

        if not (0 <= idx < len(result)):
            continue

        current_line = result[idx].strip()

        # Verificar se já tem header markdown
        if current_line.startswith('#'):
            continue

        # Determinar nível do header
        prefix = '#' if chapter.level == 'part' else '##'

        # Verificar se o título do capítulo está na linha
        # Se a linha contém o título, substituir pela versão com header
        if chapter.title.upper() in current_line.upper():
            # Limpar numeração e usar título limpo
            clean_title = _clean_chapter_title(current_line)
            result[idx] = f"{prefix} {clean_title}"
        else:
            # Inserir header antes da linha atual
            result.insert(idx, f"{prefix} {chapter.title}")

    return result


def _clean_chapter_title(title: str) -> str:
    """
    Limpa título do capítulo removendo numeração.

    Args:
        title: Título original (pode ter "1.", "I.", "Capítulo 1", etc.)

    Returns:
        Título limpo
    """
    # Remover numeração no início
    # Padrões: "1.", "1 -", "I.", "I -", "Capítulo 1", "CAPÍTULO I"
    patterns = [
        r'^(\d+\.?\s*[-–—]?\s*)',           # 1. ou 1 -
        r'^([IVXLC]+\.?\s*[-–—]?\s*)',      # I. ou I -
        r'^(Cap[íi]tulo\s+\d+\.?\s*[-–—]?\s*)',  # Capítulo 1
        r'^(CAP[ÍI]TULO\s+[IVXLC\d]+\.?\s*[-–—]?\s*)',  # CAPÍTULO I
        r'^(Parte\s+\d+\.?\s*[-–—]?\s*)',   # Parte 1
        r'^(PARTE\s+[IVXLC\d]+\.?\s*[-–—]?\s*)',  # PARTE I
    ]

    result = title.strip()
    for pattern in patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)

    return result.strip()


def remove_orphan_markers(content: str) -> str:
    """
    Remove marcadores § órfãos (sem header após).

    Após remover seções, podem sobrar § sem conteúdo associado.

    Args:
        content: Conteúdo com possíveis § órfãos

    Returns:
        Conteúdo limpo
    """
    # Remover § seguido apenas de linhas vazias ou outro §
    content = re.sub(r'^§\s*\n(?=\s*\n|§|\Z)', '', content, flags=re.MULTILINE)
    return content


def apply_structure(content: str,
                    chapters: list[ChapterBoundary],
                    sections_to_remove: dict) -> str:
    """
    Aplica estrutura completa ao documento.

    Pipeline:
    1. Remove seções marcadas (figuras, TOC, referências)
    2. Ajusta posições dos capítulos
    3. Insere headers markdown nos capítulos
    4. Remove marcadores órfãos

    Args:
        content: Conteúdo MD do livro
        chapters: Lista de capítulos identificados pelo LLM
        sections_to_remove: Dicionário com seções para remover

    Returns:
        Conteúdo com estrutura aplicada
    """
    lines = content.split('\n')

    # 1. Remover seções marcadas
    if sections_to_remove:
        lines, index_map = remove_sections(lines, sections_to_remove)
        # 2. Ajustar posições dos capítulos
        chapters = adjust_chapter_positions(chapters, index_map)
    else:
        # Sem remoções, manter posições originais
        pass

    # 3. Inserir headers de capítulos
    if chapters:
        lines = insert_chapter_headers(lines, chapters)

    result = '\n'.join(lines)

    # 4. Remover marcadores órfãos
    result = remove_orphan_markers(result)

    return result


def format_structure_summary(original_lines: int,
                             final_lines: int,
                             chapters_inserted: int,
                             sections_removed: dict) -> str:
    """
    Formata resumo da aplicação de estrutura.

    Args:
        original_lines: Número de linhas original
        final_lines: Número de linhas após processamento
        chapters_inserted: Número de headers inseridos
        sections_removed: Seções que foram removidas

    Returns:
        String formatada com resumo
    """
    lines_removed = original_lines - final_lines

    summary = [
        "Estrutura aplicada:",
        "",
        f"Linhas: {original_lines} -> {final_lines} ({lines_removed} removidas)",
        f"Headers inseridos: {chapters_inserted}",
        "",
        "Seções removidas:",
    ]

    if 'figuras' in sections_removed:
        summary.append(f"  - Figuras: {len(sections_removed['figuras'])} blocos")

    if 'toc' in sections_removed:
        summary.append(f"  - TOC/Sumário: 1 bloco")

    if 'referencias' in sections_removed:
        summary.append(f"  - Referências: {len(sections_removed['referencias'])} seções")

    if not sections_removed:
        summary.append("  (nenhuma)")

    return '\n'.join(summary)
