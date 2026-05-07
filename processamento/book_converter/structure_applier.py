"""
Aplicação de estrutura identificada pelo LLM.

Funções públicas usadas pelo `llm_pipeline`:
- `remove_sections`: filtra ranges de linhas marcados pelo LLM (figuras, TOC,
  referências, frontmatter institucional) e devolve o índice antigo→novo
  para que `_remove_sections_and_track` ajuste posições de capítulos.
- `format_structure_summary`: produz texto de log do impacto da remoção.
"""


def remove_sections(lines: list[str], sections: dict) -> tuple[list[str], dict]:
    """
    Remove seções marcadas pelo LLM.

    Args:
        lines: Lista de linhas do documento.
        sections: Dicionário com seções para remover. Suporta as chaves
            `figuras` (lista de ranges), `toc` (range único), `referencias`
            (lista de ranges) e `frontmatter` (range único). Ranges são
            `[inicio, fim]` 1-indexed inclusivos.

    Returns:
        Tupla (linhas filtradas, mapeamento de índices antigos → novos).
    """
    lines_to_remove = set()

    for rng in sections.get('figuras', []):
        if len(rng) == 2:
            start, end = rng
            for i in range(start - 1, end):
                if 0 <= i < len(lines):
                    lines_to_remove.add(i)

    toc = sections.get('toc')
    if toc and len(toc) == 2:
        start, end = toc
        for i in range(start - 1, end):
            if 0 <= i < len(lines):
                lines_to_remove.add(i)

    for rng in sections.get('referencias', []):
        if len(rng) == 2:
            start, end = rng
            for i in range(start - 1, end):
                if 0 <= i < len(lines):
                    lines_to_remove.add(i)

    frontmatter = sections.get('frontmatter')
    if frontmatter and len(frontmatter) == 2:
        start, end = frontmatter
        for i in range(start - 1, end):
            if 0 <= i < len(lines):
                lines_to_remove.add(i)

    index_map = {}
    new_idx = 0
    for old_idx in range(len(lines)):
        if old_idx not in lines_to_remove:
            index_map[old_idx] = new_idx
            new_idx += 1

    filtered = [line for i, line in enumerate(lines) if i not in lines_to_remove]

    return filtered, index_map


def format_structure_summary(original_lines: int,
                             final_lines: int,
                             chapters_inserted: int,
                             sections_removed: dict) -> str:
    """Formata resumo da aplicação de estrutura para log do pipeline."""
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
