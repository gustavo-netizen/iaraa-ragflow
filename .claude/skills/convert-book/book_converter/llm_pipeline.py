"""
Pipeline de conversão de livros usando LLM.

Este módulo orquestra o pipeline completo de conversão:
1. Parsear resposta do LLM (análise já feita externamente)
2. Limpeza OCR (padrões fixos)
3. Aplicar estrutura identificada pelo LLM
4. Otimização RAGFlow
5. Montagem final com YAML frontmatter
"""

from pathlib import Path
from .llm_analyzer import (
    build_analysis_prompt,
    parse_llm_response,
    format_analysis_summary,
    AnalysisResult
)
from .ocr_cleanup import clean_all
from .structure_applier import apply_structure, format_structure_summary, remove_sections
from .models import ChapterBoundary
import re
from .ragflow_optimize import optimize_for_ragflow, format_optimize_summary
from .assembler import assemble_book_document, format_assembly_summary


def get_analysis_prompt(content: str, max_lines: int = 500) -> str:
    """
    Gera o prompt para análise LLM do livro.

    Use esta função para obter o prompt que deve ser enviado ao LLM.
    A resposta do LLM deve então ser passada para convert_book_with_llm().

    Args:
        content: Conteúdo MD do livro
        max_lines: Número máximo de linhas na amostra

    Returns:
        Prompt formatado para o LLM
    """
    return build_analysis_prompt(content, max_lines)


def _remove_sections_and_track(content: str,
                                sections_to_remove: dict,
                                chapters: list[ChapterBoundary]) -> tuple[str, dict]:
    """
    Remove seções marcadas e retorna informações para ajuste de capítulos.

    Args:
        content: Conteúdo do livro
        sections_to_remove: Dicionário com seções para remover
        chapters: Lista de capítulos com posições originais

    Returns:
        Tupla (conteúdo filtrado, dicionário com capítulos ajustados)
    """
    if not sections_to_remove:
        return content, {'chapters': chapters}

    lines = content.split('\n')
    filtered_lines, index_map = remove_sections(lines, sections_to_remove)

    # Ajustar posições dos capítulos
    adjusted_chapters = []
    for ch in chapters:
        old_idx = ch.start_pos - 1  # 1-indexed to 0-indexed
        if old_idx in index_map:
            new_pos = index_map[old_idx] + 1  # Back to 1-indexed
            adjusted_chapters.append(ChapterBoundary(
                title=ch.title,
                start_pos=new_pos,
                end_pos=ch.end_pos,
                level=ch.level
            ))

    return '\n'.join(filtered_lines), {'chapters': adjusted_chapters}


def _insert_chapter_headers_by_title(content: str,
                                      chapters: list[ChapterBoundary]) -> str:
    """
    Insere headers markdown nos capítulos usando busca por título.

    Em vez de depender de números de linha (que mudam com limpeza),
    busca pelo título do capítulo no texto.

    A busca é restritiva para evitar falsos positivos:
    - A linha deve ser curta (< 100 chars)
    - O título deve começar a linha ou ser muito similar
    - Linhas com ":" no meio são ignoradas (indicam descrição)

    Args:
        content: Conteúdo do livro
        chapters: Lista de capítulos

    Returns:
        Conteúdo com headers inseridos
    """
    if not chapters:
        return content

    lines = content.split('\n')

    for chapter in chapters:
        title_pattern = chapter.title.upper()
        prefix = '#' if chapter.level == 'part' else '##'

        # Buscar a linha que contém o título
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            line_upper = line_stripped.upper()

            # Pular se já é header
            if line_stripped.startswith('#'):
                continue

            # Pular se linha muito longa (provavelmente parágrafo)
            if len(line_stripped) > 100:
                continue

            # Pular se linha contém ":" no meio (é descrição/legenda)
            # Ex: "Apresentação, revisão técnica e notas de rodapé:"
            if ':' in line_stripped and not line_upper.endswith(':'):
                continue

            # Verificar match: linha começa com título OU é exatamente igual
            is_match = (
                line_upper == title_pattern or
                line_upper.startswith(title_pattern + ' ') or
                line_upper.startswith(title_pattern + ':')
            )

            if is_match:
                clean_title = _clean_chapter_title_text(line_stripped)
                lines[i] = f"{prefix} {clean_title}"
                break  # Apenas a primeira ocorrência

    return '\n'.join(lines)


def _clean_chapter_title_text(title: str) -> str:
    """
    Limpa título do capítulo removendo numeração.
    """
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


def _fix_chapter_headers_fallback(content: str) -> str:
    """
    Adiciona ## antes de padrões comuns de capítulos/partes.

    Fallback para quando _insert_chapter_headers_by_title() não funciona.
    Detecta linhas ALL CAPS com padrões conhecidos e adiciona headers markdown.

    Padrões detectados:
    - CAPÍTULO I, CAPÍTULO II, etc. (com ou sem texto após)
    - PARTE I, PARTE II, etc. (com ou sem texto após)
    - APRESENTAÇÃO, PREFÁCIO, INTRODUÇÃO, CONCLUSÃO
    - APÊNDICE A, ANEXO B, etc.

    Args:
        content: Conteúdo do livro

    Returns:
        Conteúdo com headers inseridos
    """
    patterns = [
        # Capítulos com número romano e texto
        (r'\n(CAPÍTULO [IVXLC]+ [A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ].*?)\n', r'\n## \1\n'),
        # Capítulos com apenas número romano
        (r'\n(CAPÍTULO [IVXLC]+)\n', r'\n## \1\n'),
        # Partes com número romano e texto
        (r'\n(PARTE [IVXLC]+ [A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ].*?)\n', r'\n# \1\n'),
        # Partes com apenas número romano
        (r'\n(PARTE [IVXLC]+)\n', r'\n# \1\n'),
        # Seções especiais (apenas linha com texto exato, sem mais nada)
        (r'\n(APRESENTAÇÃO)\n', r'\n## \1\n'),
        (r'\n(PREFÁCIO)\n', r'\n## \1\n'),
        (r'\n(INTRODUÇÃO)\n', r'\n## \1\n'),
        (r'\n(CONCLUSÃO)\n', r'\n## \1\n'),
        (r'\n(CONSIDERAÇÕES FINAIS)\n', r'\n## \1\n'),
        # Apêndices com letra e texto
        (r'\n(APÊNDICE [A-Z] [A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ].*?)\n', r'\n## \1\n'),
        # Apêndices com apenas letra
        (r'\n(APÊNDICE [A-Z])\n', r'\n## \1\n'),
        (r'\n(APÊNDICES)\n', r'\n## \1\n'),
        # Anexos
        (r'\n(ANEXO [A-Z] [A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ].*?)\n', r'\n## \1\n'),
        (r'\n(ANEXO [A-Z])\n', r'\n## \1\n'),
        (r'\n(ANEXOS)\n', r'\n## \1\n'),
    ]

    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)

    return content


def convert_book_with_llm(content: str,
                          filename: str,
                          llm_response: str,
                          include_frontmatter: bool = True,
                          verbose: bool = False) -> tuple[str, str]:
    """
    Pipeline completo de conversão usando análise LLM.

    Args:
        content: Conteúdo MD do livro (original)
        filename: Nome do arquivo (para gerar ID)
        llm_response: Resposta JSON do LLM com estrutura
        include_frontmatter: Se True, inclui YAML frontmatter
        verbose: Se True, retorna log detalhado

    Returns:
        Tupla (documento final, log de processamento)
    """
    log_parts = []

    # 1. Parsear resposta do LLM
    log_parts.append("=" * 50)
    log_parts.append("FASE 1: Análise LLM")
    log_parts.append("=" * 50)

    try:
        analysis = parse_llm_response(llm_response)
        log_parts.append(format_analysis_summary(analysis))
    except ValueError as e:
        raise ValueError(f"Erro ao parsear resposta do LLM: {e}")

    # 2. Remover seções (frontmatter, TOC, refs) ANTES da limpeza OCR
    # Os números de linha no JSON referem-se ao arquivo ORIGINAL
    log_parts.append("")
    log_parts.append("=" * 50)
    log_parts.append("FASE 2: Remover Seções")
    log_parts.append("=" * 50)

    original_lines = len(content.split('\n'))
    content, sections_removed_info = _remove_sections_and_track(
        content, analysis.sections_to_remove, analysis.chapters
    )
    after_removal_lines = len(content.split('\n'))
    adjusted_chapters = sections_removed_info['chapters']

    log_parts.append(f"Linhas: {original_lines:,} -> {after_removal_lines:,}")
    log_parts.append(format_structure_summary(
        original_lines, after_removal_lines, 0, analysis.sections_to_remove
    ))

    # 3. Limpeza OCR (padrões fixos + título do livro)
    log_parts.append("")
    log_parts.append("=" * 50)
    log_parts.append("FASE 3: Limpeza OCR")
    log_parts.append("=" * 50)

    pre_clean_size = len(content)
    # Passar título para remover headers/footers específicos do livro
    content = clean_all(content, book_title=analysis.metadata.titulo)
    cleaned_size = len(content)

    log_parts.append(f"Tamanho: {pre_clean_size:,} -> {cleaned_size:,} caracteres")
    log_parts.append(f"Redução: {(1 - cleaned_size/pre_clean_size)*100:.1f}%")

    # 4. Inserir headers de capítulos
    log_parts.append("")
    log_parts.append("=" * 50)
    log_parts.append("FASE 4: Inserir Headers")
    log_parts.append("=" * 50)

    pre_headers_lines = len(content.split('\n'))
    content = _insert_chapter_headers_by_title(content, adjusted_chapters)

    # 4.5 Fallback: adicionar headers para padrões conhecidos
    # Captura CAPÍTULO/PARTE/APRESENTAÇÃO/etc. que não foram detectados
    content = _fix_chapter_headers_fallback(content)
    final_lines = len(content.split('\n'))

    log_parts.append(f"Headers inseridos: {len(adjusted_chapters)} (+ fallback patterns)")

    # 5. Otimização RAGFlow
    log_parts.append("")
    log_parts.append("=" * 50)
    log_parts.append("FASE 5: Otimização RAGFlow")
    log_parts.append("=" * 50)

    pre_optimize_size = len(content)
    content = optimize_for_ragflow(content)

    log_parts.append(format_optimize_summary(content, pre_optimize_size))

    # 6. Montagem final
    log_parts.append("")
    log_parts.append("=" * 50)
    log_parts.append("FASE 6: Montagem Final")
    log_parts.append("=" * 50)

    document = assemble_book_document(
        content=content,
        metadata=analysis.metadata,
        filename=filename,
        toc_entries=None,
        include_frontmatter=include_frontmatter
    )

    log_parts.append(format_assembly_summary(document, analysis.metadata))

    # Resumo final
    log_parts.append("")
    log_parts.append("=" * 50)
    log_parts.append("CONVERSÃO CONCLUÍDA")
    log_parts.append("=" * 50)
    log_parts.append(f"Arquivo: {filename}")
    log_parts.append(f"Tamanho final: {len(document):,} caracteres")

    log = '\n'.join(log_parts)

    return document, log


def convert_book_with_analysis(content: str,
                                filename: str,
                                analysis: AnalysisResult,
                                include_frontmatter: bool = True) -> str:
    """
    Converte livro usando AnalysisResult já parseado.

    Versão simplificada para quando a análise já foi feita.

    Args:
        content: Conteúdo MD do livro
        filename: Nome do arquivo
        analysis: Resultado da análise LLM (já parseado)
        include_frontmatter: Se True, inclui YAML frontmatter

    Returns:
        Documento final
    """
    # Limpeza OCR (passar título para remover headers/footers específicos)
    content = clean_all(content, book_title=analysis.metadata.titulo)

    # Aplicar estrutura
    content = apply_structure(
        content,
        analysis.chapters,
        analysis.sections_to_remove
    )

    # Otimização RAGFlow
    content = optimize_for_ragflow(content)

    # Montagem final
    document = assemble_book_document(
        content=content,
        metadata=analysis.metadata,
        filename=filename,
        include_frontmatter=include_frontmatter
    )

    return document
