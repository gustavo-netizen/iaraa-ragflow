"""
Geração de YAML frontmatter para Fichas Agroecológicas.

Fase 3 do pipeline:
- Gera ID, tags, frontmatter YAML
"""

import re
from .config import TAG_KEYWORDS, ACCENT_MAP


def normalize_tag(text: str) -> str:
    """
    Remove acentos e caracteres especiais de uma tag.

    Exemplo: "Adubação Verde" -> "adubacao-verde"
    """
    text = text.lower()

    for old, new in ACCENT_MAP.items():
        text = text.replace(old, new)

    # Substituir espaços e caracteres especiais por hífen
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


def generate_id(filename: str) -> str:
    """
    Gera ID a partir do nome do arquivo.

    Exemplo: '10-biofertilizante-vairo-1.md' -> 'ficha_agroecologica_biofertilizante_vairo'
    """
    name = re.sub(r'^\d+-', '', filename)      # Remove número inicial
    name = re.sub(r'-\d+\.md$', '', name)      # Remove número final e extensão
    name = re.sub(r'\.md$', '', name)          # Remove extensão se não tinha número
    name = name.replace('-', '_')
    return f'ficha_agroecologica_{name}'


def generate_tags(title: str, content: str) -> list[str]:
    """
    Gera lista de tags a partir do título e palavras-chave no conteúdo.

    Returns:
        Lista de tags normalizadas
    """
    tags = ['agroecologia']

    # Tags derivadas do título
    if title:
        title_normalized = normalize_tag(title)
        # Dividir título em palavras significativas
        for word in title_normalized.split('-'):
            if len(word) > 3 and word not in tags:
                tags.append(word)

    # Palavras-chave no conteúdo -> tags
    content_lower = content.lower()
    for keyword, tag in TAG_KEYWORDS.items():
        if keyword in content_lower and tag not in tags:
            tags.append(tag)

    return tags


def generate_frontmatter(filename: str, title: str, authors: list[str],
                         ficha_number: str, tags: list[str], resumo: str) -> str:
    """
    Gera o bloco YAML frontmatter completo.

    Args:
        filename: Nome do arquivo (para gerar ID)
        title: Título da ficha
        authors: Lista de autores
        ficha_number: Número da ficha
        tags: Lista de tags
        resumo: Resumo da ficha

    Returns:
        Bloco YAML frontmatter formatado
    """
    # Formatar listas para YAML
    authors_str = ', '.join(authors) if authors else ''
    tags_str = ', '.join(tags)

    # Título formatado (Title Case)
    title_formatted = title.title() if title else ''

    # Gerar resumo se não fornecido
    if not resumo and title:
        resumo = f"Ficha técnica sobre {title.lower()}."

    return f'''---
id: {generate_id(filename)}
titulo: {title_formatted}
autores: [{authors_str}]
instituicao: [Ministério da Agricultura e Pecuária]
tags: [{tags_str}]
categoria: ficha_tecnica
ficha_numero: {ficha_number}
resumo: {resumo}
---'''


def test_frontmatter(content: str, filename: str) -> str:
    """
    Gera frontmatter a partir do conteúdo (para testes).

    Args:
        content: Conteúdo limpo da ficha
        filename: Nome do arquivo

    Returns:
        Bloco YAML frontmatter
    """
    from .extraction import extract_all

    data = extract_all(content, filename)
    tags = generate_tags(data['title'], content)

    return generate_frontmatter(
        filename=filename,
        title=data['title'],
        authors=data['authors'],
        ficha_number=data['ficha_number'],
        tags=tags,
        resumo=data['resumo']
    )
