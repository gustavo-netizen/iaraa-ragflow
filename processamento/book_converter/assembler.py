"""
Montagem final do documento convertido para RAGFlow.

Helpers genéricos (`generate_id`, `format_yaml_value`, `format_yaml_list`,
`format_authors_display`) vêm de `processamento.shared`. Este módulo só
guarda o que é específico de livros: estrutura do frontmatter (campos
editora/ano/edição/isbn/tags/estrutura) e a montagem do documento com
blockquote de metadados.
"""

import re

from processamento.shared.yaml_writer import (
    generate_id,
    format_yaml_value,
    format_yaml_list,
    format_authors_display,
)

from .models import BookMetadata, TocEntry


def get_output_filename(metadata: 'BookMetadata', original_filename: str) -> str:
    """
    Gera nome de arquivo baseado no título extraído.

    Se o título está disponível nos metadados, usa-o como base para o nome
    do arquivo de saída. Caso contrário, mantém o nome original.

    Args:
        metadata: Metadados do livro com título
        original_filename: Nome original do arquivo

    Returns:
        Nome de arquivo sanitizado baseado no título, ou original se título vazio
    """
    if metadata.titulo and len(metadata.titulo) > 3:
        # Sanitizar título para nome de arquivo válido
        safe_title = metadata.titulo

        # Remover caracteres inválidos em nomes de arquivo
        # Windows: < > : " / \ | ? *
        # Linux/Mac: / (mas tratamos todos para portabilidade)
        safe_title = re.sub(r'[<>:"/\\|?*]', '', safe_title)

        # Remover espaços múltiplos
        safe_title = re.sub(r'\s+', ' ', safe_title).strip()

        # Limitar tamanho (sistemas de arquivo têm limite ~255)
        if len(safe_title) > 200:
            # Cortar em espaço para não quebrar palavra
            safe_title = safe_title[:200].rsplit(' ', 1)[0]

        return f"{safe_title}.md"

    return original_filename


def generate_book_frontmatter(metadata: BookMetadata, filename: str,
                               toc_entries: list[TocEntry] = None) -> str:
    """
    Gera o bloco YAML frontmatter para um livro.

    Args:
        metadata: Metadados extraídos do livro
        filename: Nome do arquivo de origem
        toc_entries: Entradas do sumário (opcional, para contagem)

    Returns:
        String com frontmatter YAML completo
    """
    # Gerar ID
    doc_id = generate_id(filename)

    # Formatar listas
    autores_yaml = format_yaml_list(metadata.autores)
    editora_yaml = format_yaml_list(metadata.editora)
    tags_yaml = format_yaml_list(metadata.palavras_chave)

    # Contar capítulos se TOC disponível
    if toc_entries:
        num_parts = sum(1 for e in toc_entries if e.level == 'part')
        num_chapters = sum(1 for e in toc_entries if e.level == 'chapter')
        num_sections = sum(1 for e in toc_entries if e.level == 'section')
    else:
        num_parts = num_chapters = num_sections = 0

    # Montar frontmatter
    titulo_yaml = format_yaml_value(metadata.titulo)

    lines = [
        "---",
        f"id: {doc_id}",
        f"tipo: livro_tecnico",
        f"titulo: {titulo_yaml}",
        f"autores: {autores_yaml}",
        f"editora: {editora_yaml}",
    ]

    # Campos opcionais
    if metadata.ano:
        lines.append(f"ano: {metadata.ano}")

    if metadata.edicao:
        edicao_yaml = format_yaml_value(metadata.edicao)
        lines.append(f"edicao: {edicao_yaml}")

    if metadata.isbn:
        lines.append(f"isbn: {metadata.isbn}")

    # Tags/palavras-chave
    lines.append(f"tags: {tags_yaml}")

    # Estrutura do documento
    if toc_entries:
        lines.append(f"estrutura:")
        lines.append(f"  partes: {num_parts}")
        lines.append(f"  capitulos: {num_chapters}")
        lines.append(f"  secoes: {num_sections}")

    lines.append("---")

    return '\n'.join(lines)


def assemble_book_document(content: str, metadata: BookMetadata,
                           filename: str, toc_entries: list[TocEntry] = None,
                           include_frontmatter: bool = True) -> str:
    """
    Monta o documento final otimizado para RAGFlow.

    Estrutura do documento:
    ---
    [YAML FRONTMATTER]
    ---

    # Título do Livro

    > Autores: Nome1, Nome2 e Nome3
    > Editora: Editora1 | Ano: 2020 | ISBN: 978-...

    [CONTEÚDO REESTRUTURADO E OTIMIZADO]

    Args:
        content: Conteúdo processado (após todas as fases)
        metadata: Metadados do livro
        filename: Nome do arquivo de origem
        toc_entries: Entradas do sumário (opcional)
        include_frontmatter: Se True, inclui YAML frontmatter

    Returns:
        Documento final montado
    """
    doc_parts = []

    # YAML frontmatter
    if include_frontmatter:
        frontmatter = generate_book_frontmatter(metadata, filename, toc_entries)
        doc_parts.append(frontmatter)
        doc_parts.append('')

    # Título principal
    if metadata.titulo:
        doc_parts.append(f"# {metadata.titulo}")
        doc_parts.append('')

    # Bloco de metadados (blockquote)
    meta_lines = []

    # Autores
    if metadata.autores:
        authors_display = format_authors_display(metadata.autores)
        meta_lines.append(f"> **Autores:** {authors_display}")

    # Editora, ano, edição, ISBN
    pub_info = []
    if metadata.editora:
        pub_info.append(f"**Editora:** {', '.join(metadata.editora)}")
    if metadata.ano:
        pub_info.append(f"**Ano:** {metadata.ano}")
    if metadata.edicao:
        pub_info.append(f"**Edição:** {metadata.edicao}")
    if metadata.isbn:
        pub_info.append(f"**ISBN:** {metadata.isbn}")

    if pub_info:
        meta_lines.append("> " + " | ".join(pub_info))

    if meta_lines:
        doc_parts.extend(meta_lines)
        doc_parts.append('')

    # Conteúdo principal
    doc_parts.append(content)

    # Montar documento final
    result = '\n'.join(doc_parts)

    # Normalizar linhas em branco no final
    result = result.rstrip('\n') + '\n'

    return result


def format_assembly_summary(document: str, metadata: BookMetadata,
                            toc_entries: list[TocEntry] = None) -> str:
    """
    Formata um resumo da montagem para exibição.

    Args:
        document: Documento montado
        metadata: Metadados do livro
        toc_entries: Entradas do sumário

    Returns:
        String formatada com estatísticas
    """
    # Contar elementos
    has_frontmatter = document.startswith('---')
    h1_count = len(re.findall(r'^# [^#]', document, re.MULTILINE))
    h2_count = len(re.findall(r'^## [^#]', document, re.MULTILINE))
    h3_count = len(re.findall(r'^### [^#]', document, re.MULTILINE))
    marker_count = len(re.findall(r'^§$', document, re.MULTILINE))

    lines = [
        "Montagem concluída:",
        "",
        "Metadados:",
        f"  - Título: {metadata.titulo or '(não encontrado)'}",
        f"  - Autores: {len(metadata.autores)}",
        f"  - Editora: {', '.join(metadata.editora) if metadata.editora else '(não encontrada)'}",
        f"  - Ano: {metadata.ano or '(não encontrado)'}",
        f"  - ISBN: {metadata.isbn or '(não encontrado)'}",
        "",
        "Estrutura do documento:",
        f"  - YAML frontmatter: {'Sim' if has_frontmatter else 'Não'}",
        f"  - # (H1 - título/partes): {h1_count}",
        f"  - ## (H2 - capítulos): {h2_count}",
        f"  - ### (H3 - seções): {h3_count}",
        f"  - § (marcadores de chunk): {marker_count}",
        "",
        f"Tamanho final: {len(document):,} caracteres",
    ]

    return '\n'.join(lines)
