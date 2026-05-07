"""
Geração de IDs e helpers de YAML — fonte única de verdade para ambos os
converters (`ficha_converter` e `book_converter`).

Schema do `id` definido em docs/adr/0001-id-schema-frontmatter.md:
slug ASCII transliterado, sem prefixo de tipo. Tipo do documento mora
em campo separado `tipo` no frontmatter.
"""

import re
from pathlib import Path


ACCENT_MAP = {
    'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
    'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
    'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
    'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
    'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
    'ç': 'c', 'ñ': 'n',
}


def transliterate(text: str) -> str:
    """Transliterate Portuguese accents to ASCII (lowercase). `café → cafe`."""
    text = text.lower()
    for old, new in ACCENT_MAP.items():
        text = text.replace(old, new)
    return text


def generate_id(filename: str) -> str:
    """
    Gera ID canônico a partir do nome de arquivo.

    Regras (ADR-0001):
    - lowercase + transliteração de acentos via ACCENT_MAP (`café → cafe`)
    - remove prefixo numérico tipo `10-`
    - remove sufixo numérico tipo `-1`
    - colapsa espaços/hífens em underscore
    - dropa caracteres não-alfanuméricos restantes
    - sem prefixo de tipo (que vai em campo `tipo` separado)

    Exemplos:
        '10-biofertilizante-vairo-1.md'  → 'biofertilizante_vairo'
        'Café Agroecológico.md'          → 'cafe_agroecologico'
        'livro_fixture.md'               → 'livro_fixture'
    """
    name = Path(filename).stem
    name = transliterate(name)
    name = re.sub(r'^\d+[-_]', '', name)
    name = re.sub(r'[-_]\d+$', '', name)
    name = re.sub(r'[\s\-]+', '_', name)
    name = re.sub(r'[^a-z0-9_]', '', name)
    name = re.sub(r'_+', '_', name)
    return name.strip('_')


def format_yaml_value(value: str) -> str:
    """Formata um valor escalar para YAML, quotando se contém caracteres especiais."""
    if not value:
        return '""'

    if any(c in value for c in [':', '#', '[', ']', '{', '}', ',', '&', '*', '?', '|',
                                 '-', '<', '>', '=', '!', '%', '@', '`']):
        value = value.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{value}"'

    return value


def format_yaml_list(items: list[str]) -> str:
    """Formata uma lista para YAML inline: `[item1, item2]`."""
    if not items:
        return "[]"

    escaped = []
    for item in items:
        if any(c in item for c in [',', ':', '"', '[', ']', '{', '}']):
            item = item.replace('\\', '\\\\').replace('"', '\\"')
            escaped.append(f'"{item}"')
        else:
            escaped.append(item)

    return f"[{', '.join(escaped)}]"


def format_authors_display(authors: list[str]) -> str:
    """
    Formata lista de autores para exibição em português.

    Exemplos:
        ["A. B. Silva"]                  → "A. B. Silva"
        ["A. B. Silva", "C. D. Santos"]  → "A. B. Silva e C. D. Santos"
        ["A", "B", "C"]                  → "A, B e C"
    """
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} e {authors[1]}"
    return ", ".join(authors[:-1]) + f" e {authors[-1]}"
