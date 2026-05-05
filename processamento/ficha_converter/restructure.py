"""
Reestruturação de conteúdo para formato Markdown estruturado.

Fase 4 do pipeline:
- Transforma seções em headers markdown
- Formata passos numerados
- Padroniza bullets
- Monta documento final
"""

import re

from processamento.shared.ragflow import format_bullets
from processamento.shared.yaml_writer import format_authors_display

from .config import SECTION_PATTERNS, SUBSECTION_PATTERNS


__all__ = [
    "restructure_sections",
    "format_steps",
    "format_bullets",
    "extract_body",
    "format_authors_display",
    "assemble_document",
]


def restructure_sections(content: str) -> str:
    """
    Transforma seções de texto em headers markdown apropriados.

    Seções principais (##):
    - Ingredientes:
    - Como preparar...
    - Importante!
    - Como utilizar/aplicar
    - Aplicação

    Subseções (###):
    - Dica agroecológica!
    - Atenção!
    """
    for pattern, replacement in SECTION_PATTERNS:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    for pattern, replacement in SUBSECTION_PATTERNS:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    return content


def format_steps(content: str) -> str:
    """
    Converte passos numerados para headers ###.

    Exemplos:
    - "1º passo:" -> "### 1º passo"
    - "2º Passo:" -> "### 2º passo"
    """
    content = re.sub(
        r'^(\d+)º\s*[Pp]asso\s*:?\s*$',
        r'### \1º passo',
        content, flags=re.MULTILINE
    )
    return content


def extract_body(content: str, title: str) -> str:
    """
    Extrai o corpo do documento (conteúdo principal sem headers e footers).

    Remove:
    - Header "Fichas Agroecológicas..."
    - Título em maiúsculas
    - Número da ficha
    - Footer "Ministério da Agricultura..."
    - Elaboradores da ficha
    """
    lines = content.split('\n')
    body_lines = []
    skip_header = True

    for line in lines:
        stripped = line.strip()

        # Pular linhas do header
        if skip_header:
            if any(x in stripped for x in ['Fichas', 'Agroecológicas', 'Tecnologias Apropriadas',
                                           'Fertilidade do Solo', 'Nutrição de Plantas']):
                continue
            # Pular número da ficha sozinho
            if re.match(r'^\d+$', stripped):
                continue
            # Pular título em maiúsculas
            if title and stripped.upper() == title.upper():
                continue
            # Encontrou conteúdo real - parar de pular header
            if len(stripped) > 20 and not stripped.isupper():
                skip_header = False

        # Pular footer
        if 'Ministério da Agricultura' in stripped:
            continue
        if 'gov.br/agricultura' in stripped:
            continue

        # Pular linha de elaboradores (vai ser incluída nos metadados)
        if stripped.startswith('Elaborador'):
            continue

        # Marcar início de referências
        if 'Referências bibliográficas' in stripped:
            body_lines.append('')
            body_lines.append('## Referências bibliográficas')
            continue

        if not skip_header:
            body_lines.append(line)

    # Limpar linhas vazias excessivas no início e fim
    body = '\n'.join(body_lines)
    body = body.strip()
    body = re.sub(r'\n{3,}', '\n\n', body)

    return body


def assemble_document(frontmatter: str, title: str, authors: list[str],
                      ficha_number: str, body: str) -> str:
    """
    Monta o documento final otimizado para RAGFlow.

    Estrutura:
    ---
    [YAML FRONTMATTER]
    ---

    # TÍTULO

    > Autores: Fulano e Ciclano

    **Fichas Agroecológicas**
    **Tecnologias Apropriadas para Agricultura Orgânica**
    **Fertilidade do Solo e Nutrição de Plantas XX**

    [CONTEÚDO]

    Ministério da Agricultura e Pecuária
    https://...
    """
    authors_display = format_authors_display(authors)

    # Formatar título (Title Case)
    title_formatted = title.title() if title else "Sem Título"

    # Montar documento
    doc_parts = [
        frontmatter,
        '',
        f'# {title_formatted}',
        '',
    ]

    # Adicionar autores se existirem
    if authors_display:
        doc_parts.append(f'> Autores: {authors_display}')
        doc_parts.append('')

    # Header padrão das fichas
    doc_parts.extend([
        '**Fichas Agroecológicas**',
        '**Tecnologias Apropriadas para Agricultura Orgânica**',
        f'**Fertilidade do Solo e Nutrição de Plantas {ficha_number}**',
        '',
        body,
        '',
        'Ministério da Agricultura e Pecuária',
        'https://www.gov.br/agricultura/pt-br/assuntos/sustentabilidade/organicos/fichas-agroecologicas',
    ])

    return '\n'.join(doc_parts)
