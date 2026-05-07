"""
Fase 1: Limpeza de artefatos OCR para livros técnicos.

Padrões comuns vivem em `processamento.shared.ocr_patterns`. Este módulo
adiciona o que é específico de livros: descrições de figuras
(`**Type:**...*Confidence:*`), cabeçalhos/rodapés de página com letras
espaçadas, footers com título do livro e fix de hifenização.
"""

import re

from processamento.shared.ocr_patterns import (
    CLEANUP_PATTERNS,
    remove_artifacts as _remove_artifacts_shared,
)
from processamento.shared.footnote_filter import filter_footnote_items


def remove_figure_descriptions(content: str) -> str:
    """
    Remove blocos de descrição de figuras gerados pelo OCR Marco Converter.

    Padrão detectado:
        **Type:** ...
        **Description:** ...
        **Key Insight:** ...
        *Confidence: ...*

    Esses blocos são metadados de análise de figuras/tabelas detectadas pelo OCR
    e não representam conteúdo útil para o documento final.

    Args:
        content: Conteúdo do livro

    Returns:
        Conteúdo sem os blocos de descrição de figuras
    """
    # Padrão: **Type:** ... até *Confidence: ...*
    pattern = r'\*\*Type:\*\*.*?(?=\*Confidence:.*?\*)\*Confidence:.*?\*\n*'
    return re.sub(pattern, '', content, flags=re.DOTALL)


def remove_artifacts(content: str) -> str:
    """Remove artefatos OCR comuns (Marco/DocMind, divisões, figuras, etc)."""
    return _remove_artifacts_shared(content, CLEANUP_PATTERNS)


def clean_page_headers(content: str) -> str:
    """
    Remove cabeçalhos de página com letras espaçadas.

    Exemplo: 'M I G U E L  A L T I E R I' -> removido
             'A G R O E C O L O G I A :' -> removido

    Esses cabeçalhos aparecem no OCR de livros quando o nome do autor
    ou título está no topo de cada página com espaçamento entre letras.
    """
    # Padrão: letras maiúsculas separadas por espaços (mínimo 6 letras)
    # Pode terminar com : ou outros caracteres
    # Ex: "M I G U E L  A L T I E R I" ou "A G R O E C O L O G I A :"
    pattern = r'^[A-ZÁÉÍÓÚÀÃÕÂÊÔÇ](?:\s+[A-ZÁÉÍÓÚÀÃÕÂÊÔÇ]){5,}\s*:?\s*$'
    return re.sub(pattern, '', content, flags=re.MULTILINE)


def remove_page_footers(content: str) -> str:
    """
    Remove rodapés de página (título/autor + número de página).

    Padrão: linha com título em CAPS + 2+ espaços + número (1-3 dígitos)
    Ex: "AGROECOLOGIA 7.0                541" -> removido
        "SEBASTIÃO PINHEIRO              123" -> removido

    Esses rodapés aparecem no OCR quando o título ou autor está no
    rodapé de cada página junto com o número da página.
    """
    # Padrão: texto em maiúsculas/números/pontos + 2+ espaços horizontais + número
    # Usa [ \t] em vez de \s para não cruzar quebras de linha
    pattern = r'^[A-ZÁÉÍÓÚÀÃÕÂÊÔÇ][A-ZÁÉÍÓÚÀÃÕÂÊÔÇ0-9\. ]+[ \t]{2,}\d{1,3}[ \t]*$'
    return re.sub(pattern, '', content, flags=re.MULTILINE)


def remove_book_title_headers(content: str, book_title: str) -> str:
    """
    Remove cabeçalhos/rodapés de página que contêm o título do livro.

    Esses aparecem quando o OCR captura o título do livro que está
    no cabeçalho ou rodapé de cada página do PDF.

    Padrões detectados:
    - Título sozinho: "PLANTAR, CRIAR E CONSERVAR: unindo produtividade..."
    - Número + Título: "14 PLANTAR, CRIAR E CONSERVAR..."
    - Título + Número: "PLANTAR, CRIAR E CONSERVAR... 29"

    Args:
        content: Conteúdo do livro
        book_title: Título do livro para detectar

    Returns:
        Conteúdo com rodapés/cabeçalhos do título removidos
    """
    if not book_title or len(book_title) < 10:
        return content

    # Extrair primeiras palavras significativas do título para matching
    # Isso captura "PLANTAR, CRIAR E CONSERVAR" de títulos longos
    title_upper = book_title.upper().strip()
    words = title_upper.split()

    # Usar primeiras 4-5 palavras significativas (até encontrar : ou -)
    key_words = []
    for w in words:
        key_words.append(w)
        if w.endswith(':') or w.endswith('-'):
            break
        if len(key_words) >= 5:
            break

    if len(key_words) < 2:
        return content

    # Construir padrão base (primeiras palavras do título)
    base_pattern = ' '.join(key_words)
    # Escapar caracteres especiais de regex
    base_escaped = re.escape(base_pattern)

    # Também criar padrão para título completo
    full_title_escaped = re.escape(title_upper)

    # Extrair segunda parte do título (após : ou -)
    # Para casos onde o título está em duas linhas
    subtitle_escaped = None
    if ':' in title_upper:
        parts = title_upper.split(':', 1)
        if len(parts) > 1 and len(parts[1].strip()) > 10:
            subtitle_escaped = re.escape(parts[1].strip())
    elif '-' in title_upper and ' - ' in title_upper:
        parts = title_upper.split(' - ', 1)
        if len(parts) > 1 and len(parts[1].strip()) > 10:
            subtitle_escaped = re.escape(parts[1].strip())

    # Padrões para detectar rodapés/cabeçalhos com o título:
    patterns = [
        # 1. Número + Título (ex: "14 PLANTAR, CRIAR E CONSERVAR...")
        # Formato: número sozinho no início + espaço + título
        rf'^\d{{1,3}}\s+{base_escaped}.*$',

        # 2. Título + Número no final (ex: "PLANTAR, CRIAR E CONSERVAR... 29")
        # Formato: título + algum texto + espaço + número no final
        rf'^{base_escaped}.*\s+\d{{1,3}}\s*$',

        # 3. Título completo sozinho na linha
        # Permite variações case-insensitive do título completo
        rf'^{full_title_escaped}\s*$',

        # 4. Título parcial (base) sozinho na linha com texto curto após
        # Para casos onde o título aparece com variações
        rf'^{base_escaped}.{{0,80}}$',
    ]

    # 5. Subtítulo sozinho na linha (quando título está em duas linhas)
    # Ex: "unindo produtividade e meio ambiente" (segunda parte após :)
    if subtitle_escaped:
        patterns.append(rf'^{subtitle_escaped}\s*$')

    lines = content.split('\n')
    result_lines = []

    for line in lines:
        line_stripped = line.strip()

        # Verificar se a linha é curta o suficiente para ser um header/footer
        # Linhas muito longas provavelmente são parágrafos
        if len(line_stripped) > 120:
            result_lines.append(line)
            continue

        # Verificar cada padrão
        is_title_header = False
        for pattern in patterns:
            if re.match(pattern, line_stripped, re.IGNORECASE):
                is_title_header = True
                break

        if not is_title_header:
            result_lines.append(line)

    return '\n'.join(result_lines)


def fix_hyphenation(content: str) -> str:
    """
    Corrige palavras hifenizadas em quebra de linha.

    O OCR preserva hifenização do PDF quando uma palavra é quebrada
    no final da linha. Esta função junta essas palavras.

    Exemplo: 'con-\\nsequências' -> 'consequências'
             'sis-\\n temas' -> 'sistemas' (com espaço no início da próxima linha)
    """
    # Padrão: palavra + hífen + quebra de linha + espaços opcionais + continuação (minúscula)
    # Captura apenas quando a continuação começa com minúscula
    pattern = r'(\w+)-\s*\n\s*([a-záéíóúàãõâêôç]\w*)'
    return re.sub(pattern, r'\1\2', content)


def remove_empty_lines_excess(content: str) -> str:
    """Remove linhas vazias excessivas (máximo 2 consecutivas)."""
    return re.sub(r'\n{3,}', '\n\n', content)


def clean_all(content: str, book_title: str | None = None) -> str:
    """
    Executa todas as limpezas de OCR em sequência.

    Ordem:
    1. Remove artefatos do Marco Converter
    2. Filtra items de footnote ruidosos (preserva translator notes/DOIs)
    3. Remove descrições de figuras (blocos **Type:**...*Confidence:*)
    4. Remove rodapés de página (título + número)
    5. Remove cabeçalhos de página espaçados
    6. Remove cabeçalhos/rodapés com título do livro (se título fornecido)
    7. Corrige hifenização quebrada
    8. Remove linhas vazias excessivas

    Args:
        content: Conteúdo do livro
        book_title: Título do livro para remover headers/footers específicos

    Returns:
        Conteúdo limpo
    """
    content = remove_artifacts(content)
    content = filter_footnote_items(content)
    content = remove_figure_descriptions(content)
    content = remove_page_footers(content)
    content = clean_page_headers(content)
    if book_title:
        content = remove_book_title_headers(content, book_title)
    content = fix_hyphenation(content)
    content = remove_empty_lines_excess(content)
    return content
