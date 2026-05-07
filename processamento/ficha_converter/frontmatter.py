"""
Geração de YAML frontmatter para Fichas Agroecológicas.

Fase 3 do pipeline. `generate_id` e `ACCENT_MAP` vêm de
`processamento.shared` (ADR-0001: schema de ID canônico, sem prefixo
de tipo; tipo mora em campo `tipo` separado).
"""

import re

from processamento.shared.yaml_writer import generate_id, transliterate

from .config import TAG_KEYWORDS


__all__ = [
    "generate_id",
    "normalize_tag",
    "generate_tags",
    "generate_frontmatter",
    "test_frontmatter",
]


def normalize_tag(text: str) -> str:
    """
    Normaliza uma tag: lowercase + transliteração + hífen.

    Exemplo: "Adubação Verde" → "adubacao-verde"
    """
    text = transliterate(text)
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


def generate_tags(title: str, content: str) -> list[str]:
    """Gera lista de tags a partir do título e palavras-chave no conteúdo."""
    tags = ['agroecologia']

    if title:
        title_normalized = normalize_tag(title)
        for word in title_normalized.split('-'):
            if len(word) > 3 and word not in tags:
                tags.append(word)

    content_lower = content.lower()
    for keyword, tag in TAG_KEYWORDS.items():
        if keyword in content_lower and tag not in tags:
            tags.append(tag)

    return tags


def generate_frontmatter(filename: str, title: str, authors: list[str],
                         ficha_number: str, tags: list[str], resumo: str) -> str:
    """Gera o bloco YAML frontmatter de uma ficha (vocabulário ADR-0001)."""
    authors_str = ', '.join(authors) if authors else ''
    tags_str = ', '.join(tags)
    title_formatted = title.title() if title else ''

    if not resumo and title:
        resumo = f"Ficha técnica sobre {title.lower()}."

    return f'''---
id: {generate_id(filename)}
tipo: ficha_agroecologica
titulo: {title_formatted}
autores: [{authors_str}]
instituicao: [Ministério da Agricultura e Pecuária]
tags: [{tags_str}]
ficha_numero: {ficha_number}
resumo: {resumo}
---'''


def test_frontmatter(content: str, filename: str) -> str:
    """Gera frontmatter a partir do conteúdo (helper para testes manuais)."""
    from .extraction import extract_all

    data = extract_all(content, filename)
    tags = generate_tags(data['title'], content)

    return generate_frontmatter(
        filename=filename,
        title=data['title'],
        authors=data['authors'],
        ficha_number=data['ficha_number'],
        tags=tags,
        resumo=data['resumo'],
    )
