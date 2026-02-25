#!/usr/bin/env python3
"""
DEPRECATED: Use ficha_converter instead.

    python -m ficha_converter [args]

Este arquivo será removido em versões futuras.

---

Conversor de Markdown systemRAG para formato estruturado.

Fase 1: Limpeza Básica
- Remove metadados de processamento
- Remove divisões de página
- Remove referências de figuras e imagens

Fase 2: Extração de Dados
- Extrai título, autores, número da ficha, resumo

Fase 3: Geração de YAML Frontmatter
- Gera frontmatter YAML válido com metadados

Fase 4: Reestruturação de Conteúdo
- Transforma seções em headers markdown
- Formata passos numerados
- Padroniza bullets
- Monta documento final
"""

import re
import argparse
from pathlib import Path


# =============================================================================
# FASE 1: LIMPEZA BÁSICA
# =============================================================================

def remove_artifacts(content: str) -> str:
    """
    Remove todos os artefatos do formato systemRAG.

    Artefatos removidos:
    - Metadados de processamento (*Processed with...*, *Model:...*, etc.)
    - Divisões de página (## Page X)
    - Referências de figuras/tabelas (### Figure X:, ![Figure...], *YAML Metadata:...*)
    - Título original do arquivo (# XX-nome-X)
    """

    # Padrões a remover (ordem importa para alguns casos)
    patterns = [
        # Metadados de processamento no início
        (r'^\*Processed with Marco-Compliant Converter.*?\*\s*\n', ''),
        (r'^\*Model:.*?\*\s*\n', ''),
        (r'^\*Total Figures Detected:.*?\*\s*\n', ''),

        # Título original do arquivo (ex: # 10-biofertilizante-vairo-1)
        (r'^# \d+-[\w-]+-\d+\s*\n', ''),

        # Separador após metadados (antes de ## Page)
        (r'^---\s*\n(?=\s*## Page)', ''),

        # Divisões de página
        (r'^## Page \d+\s*\n+', ''),

        # Headers de figuras e tabelas
        (r'^### Figure \d+:.*?\n', ''),
        (r'^### Table:.*?\n', ''),
        (r'^### Table \d+:.*?\n', ''),

        # Imagens de figuras e tabelas
        (r'^!\[Figure \d+:.*?\]\(.*?\)\s*\n', ''),
        (r'^!\[Table:.*?\]\(.*?\)\s*\n', ''),
        (r'^!\[Table \d+:.*?\]\(.*?\)\s*\n', ''),

        # Links para YAML metadata
        (r'^\*YAML Metadata:.*?\*\s*\n', ''),
    ]

    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    # Limpar linhas em branco excessivas (máximo 2 consecutivas)
    content = re.sub(r'\n{3,}', '\n\n', content)

    # Remover linhas em branco no início
    content = content.lstrip('\n')

    return content


def clean_empty_lines(content: str) -> str:
    """Remove linhas em branco excessivas."""
    return re.sub(r'\n{3,}', '\n\n', content)


# =============================================================================
# FASE 2: EXTRAÇÃO DE DADOS
# =============================================================================

def extract_title(content: str) -> str:
    """
    Extrai o título principal (linha em MAIÚSCULAS após header "Fichas Agroecológicas").

    Exemplo: "BIOFERTILIZANTE VAIRO", "HÚMUS DE MINHOCA", "COMPOSTO FARELADO UPD* SÃO ROQUE"
    """
    # Procurar linha em MAIÚSCULAS (pode ter acentos, espaços e caracteres especiais como *)
    # Deve vir após o número da ficha
    match = re.search(
        r'Nutrição de Plantas\s*\n\d+\s*\n+([A-ZÁÉÍÓÚÀÃÕÂÊÔÇ][A-ZÁÉÍÓÚÀÃÕÂÊÔÇ\s\*\-]+)$',
        content, re.MULTILINE
    )
    if match:
        return match.group(1).strip()

    # Fallback: procurar qualquer linha em maiúsculas com mais de 10 caracteres
    match = re.search(
        r'^([A-ZÁÉÍÓÚÀÃÕÂÊÔÇ][A-ZÁÉÍÓÚÀÃÕÂÊÔÇ\s\*\-]{8,})$',
        content, re.MULTILINE
    )
    return match.group(1).strip() if match else ""


def extract_authors(content: str) -> list[str]:
    """
    Extrai e formata nomes dos autores.

    Formato original: "Elaborador(es) da ficha: LEITE, C. D.; MEIRA, A. L."
    Formato saída: ["C. D. Leite", "A. L. Meira"]
    """
    # Encontrar linha de elaboradores
    match = re.search(
        r'Elaborador(?:es|) da ficha:\s*(.+?)(?:\n|$)',
        content, re.IGNORECASE
    )
    if not match:
        return []

    raw = match.group(1)

    # Extrair padrões "SOBRENOME, I. I." ou "SOBRENOME, I. I;"
    authors = []
    for m in re.finditer(r'([A-ZÁÉÍÓÚÀÃÕÂÊÔÇ]+),\s*([A-Z]\.\s*(?:[A-Z]\.\s*)*)', raw, re.IGNORECASE):
        surname = m.group(1).title()  # LEITE -> Leite
        initials = m.group(2).strip().rstrip(';').strip()  # C. D.
        initials = re.sub(r'\s+', ' ', initials)  # Normalizar espaços
        authors.append(f"{initials} {surname}")

    return authors


def extract_ficha_number(content: str, filename: str = "") -> str:
    """
    Extrai o número da ficha.

    Fonte primária: Linha após "Fertilidade do Solo e Nutrição de Plantas"
    Fallback: Número no início do nome do arquivo
    Exemplo: "10", "21", "23"
    """
    match = re.search(
        r'Nutrição de Plantas\s*\n(\d+)',
        content, re.MULTILINE
    )
    if match:
        return match.group(1)

    # Fallback: extrair do nome do arquivo (ex: "1-adubacao-verde-1.md" -> "1")
    if filename:
        match = re.match(r'^(\d+)-', filename)
        if match:
            return match.group(1)

    return ""


def extract_resumo(content: str, title: str) -> str:
    """
    Extrai o primeiro parágrafo significativo como resumo.

    Critérios:
    - Mais de 50 caracteres
    - Não é header, lista ou blockquote
    - Não contém apenas o título
    - Trunca em ~150 caracteres
    """
    lines = content.split('\n')
    title_lower = title.lower() if title else ""

    for line in lines:
        line = line.strip()

        # Ignorar linhas curtas
        if len(line) < 50:
            continue

        # Ignorar headers, listas, blockquotes
        if line.startswith(('#', '*', '-', '>', '!')):
            continue

        # Ignorar linhas que são apenas o título ou parte do header
        if title_lower and line.lower().startswith(title_lower[:20]):
            continue
        if 'Fichas' in line or 'Agroecológicas' in line or 'Ministério' in line:
            continue

        # Encontrou um parágrafo válido
        if len(line) > 150:
            # Truncar em palavra completa
            truncated = line[:150].rsplit(' ', 1)[0]
            return truncated + "..."
        return line

    return ""


# =============================================================================
# FASE 3: GERAÇÃO DE YAML FRONTMATTER
# =============================================================================

def normalize_tag(text: str) -> str:
    """
    Remove acentos e caracteres especiais de uma tag.
    Exemplo: "Adubação Verde" -> "adubacao-verde"
    """
    text = text.lower()
    replacements = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n',
    }
    for old, new in replacements.items():
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
    KEYWORDS = {
        'biofertilizante': 'biofertilizante',
        'fermentação': 'fermentacao',
        'anaeróbica': 'fermentacao-anaerobica',
        'aeróbica': 'fermentacao-aerobica',
        'esterco': 'esterco',
        'esterco bovino': 'esterco-bovino',
        'composto': 'compostagem',
        'adubação verde': 'adubacao-verde',
        'leguminosas': 'leguminosas',
        'gramíneas': 'gramineas',
        'mamona': 'mamona',
        'supermagro': 'supermagro',
        'bokashi': 'bokashi',
        'húmus': 'humus',
        'minhoca': 'minhoca',
        'microrganismos': 'microrganismos-eficientes',
    }

    content_lower = content.lower()
    for keyword, tag in KEYWORDS.items():
        if keyword in content_lower and tag not in tags:
            tags.append(tag)

    return tags


def generate_frontmatter(filename: str, title: str, authors: list[str],
                         ficha_number: str, tags: list[str], resumo: str) -> str:
    """
    Gera o bloco YAML frontmatter completo.
    """
    # Formatar listas para YAML
    authors_str = ', '.join(authors) if authors else ''
    tags_str = ', '.join(tags)

    # Título formatado (Title Case)
    title_formatted = title.title() if title else ''

    # Gerar resumo completo se não fornecido
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
    Testa a geração de frontmatter para um arquivo.
    """
    cleaned = remove_artifacts(content)

    title = extract_title(cleaned)
    authors = extract_authors(cleaned)
    ficha_number = extract_ficha_number(cleaned, filename)
    resumo = extract_resumo(cleaned, title)
    tags = generate_tags(title, cleaned)

    return generate_frontmatter(filename, title, authors, ficha_number, tags, resumo)


def test_extraction(content: str, filename: str) -> dict:
    """
    Testa as funções de extração e retorna os resultados.
    Útil para debug e validação.
    """
    # Primeiro limpar os artefatos
    cleaned = remove_artifacts(content)

    title = extract_title(cleaned)
    authors = extract_authors(cleaned)
    ficha_number = extract_ficha_number(cleaned, filename)
    resumo = extract_resumo(cleaned, title)

    return {
        'filename': filename,
        'title': title,
        'authors': authors,
        'ficha_number': ficha_number,
        'resumo': resumo[:80] + '...' if len(resumo) > 80 else resumo
    }


# =============================================================================
# FASE 4: REESTRUTURAÇÃO DE CONTEÚDO
# =============================================================================

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
    # Seções principais -> ## Headers
    section_patterns = [
        (r'^(Ingredientes)\s*:?\s*$', r'## \1'),
        (r'^(Como preparar[^:\n]*)\s*:?\s*$', r'## \1'),
        (r'^(Importante)\s*!?\s*$', r'## Importante!'),
        (r'^(Como (?:utilizar|aplicar)[^:\n]*)\s*:?\s*$', r'## \1'),
        (r'^(Aplicação[^:\n]*)\s*:?\s*$', r'## \1'),
        (r'^(Modo de preparo[^:\n]*)\s*:?\s*$', r'## \1'),
        (r'^(Materiais[^:\n]*)\s*:?\s*$', r'## \1'),
        (r'^(Referências bibliográficas)\s*:?\s*$', r'## \1'),
    ]

    # Subseções -> ### Headers
    subsection_patterns = [
        (r'^(Dica [Aa]groecológica)\s*!?\s*$', r'### \1!'),
        (r'^(Atenção)\s*!?\s*$', r'### Atenção!'),
    ]

    for pattern, replacement in section_patterns:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    for pattern, replacement in subsection_patterns:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    return content


def format_steps(content: str) -> str:
    """
    Converte passos numerados para headers ###.

    Exemplos:
    - "1º passo:" -> "### 1º passo"
    - "2º Passo:" -> "### 2º passo"
    """
    # Padrão: número + º + passo + : opcional
    content = re.sub(
        r'^(\d+)º\s*[Pp]asso\s*:?\s*$',
        r'### \1º passo',
        content, flags=re.MULTILINE
    )
    return content


def format_bullets(content: str) -> str:
    """
    Padroniza todos os bullets para asterisco (*).

    Converte:
    - "- item" -> "* item"
    - "-item" -> "* item" (sem espaço)
    - "• item" -> "* item"
    """
    # Hífen para asterisco (com espaço)
    content = re.sub(r'^-\s+', '* ', content, flags=re.MULTILINE)
    # Hífen para asterisco (sem espaço, seguido de letra)
    content = re.sub(r'^-([A-Za-záéíóúàãõâêôçÁÉÍÓÚÀÃÕÂÊÔÇ])', r'* \1', content, flags=re.MULTILINE)
    # Bullet unicode para asterisco
    content = re.sub(r'^•\s*', '* ', content, flags=re.MULTILINE)
    return content


def join_paragraph_lines(content: str) -> str:
    """
    Junta linhas que fazem parte do mesmo parágrafo.

    O OCR do systemRAG preserva quebras de linha da largura da página do PDF.
    RAGFlow usa \n como delimiter, então cada linha vira um chunk separado.

    Esta função junta linhas consecutivas que pertencem ao mesmo parágrafo,
    preservando:
    - Linhas em branco (separadores de parágrafo)
    - Headers (#, ##, ###)
    - Itens de lista (*, -)
    - Linhas que terminam com pontuação de fim de sentença
    """
    lines = content.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Linha em branco - preservar como separador de parágrafo
        if not stripped:
            result.append('')
            i += 1
            continue

        # Headers - preservar como estão
        if stripped.startswith('#'):
            result.append(line)
            i += 1
            continue

        # Itens de lista - podem ter continuação
        if stripped.startswith(('* ', '- ', '• ')):
            # Juntar linhas de continuação do item de lista
            combined = line.rstrip()
            i += 1
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                # Parar se: linha vazia, novo item, header, ou novo parágrafo
                if not next_stripped or next_stripped.startswith(('#', '* ', '- ', '• ')):
                    break
                # Continuação: começa com minúscula OU com ( [ que indica parêntese/complemento
                if next_stripped and (next_stripped[0].islower() or next_stripped[0] in '(['):
                    combined += ' ' + next_stripped
                    i += 1
                else:
                    break
            result.append(combined)
            continue

        # Texto normal - juntar linhas de continuação
        combined = line.rstrip()
        i += 1
        while i < len(lines):
            next_line = lines[i]
            next_stripped = next_line.strip()
            # Parar se: linha vazia, header, item de lista
            if not next_stripped or next_stripped.startswith(('#', '* ', '- ', '• ')):
                break
            # Continuação: começa com minúscula OU com ( [ que indica parêntese/complemento
            if next_stripped and (next_stripped[0].islower() or next_stripped[0] in '(['):
                combined += ' ' + next_stripped
                i += 1
            else:
                break
        result.append(combined)

    return '\n'.join(result)


def insert_section_markers(content: str, marker: str = '§') -> str:
    """
    Insere marcador antes de headers ## para delimitar chunks no RAGFlow.

    O RAGFlow usa o marcador como delimiter para criar chunks por seção.
    Headers ### (subseções) NÃO recebem marcador - ficam no mesmo chunk da seção pai.

    Args:
        content: Conteúdo markdown
        marker: Caractere marcador (padrão: §)

    Returns:
        Conteúdo com marcadores inseridos antes de cada ## header
    """
    # Inserir marcador em linha própria antes de cada ## (mas não ###)
    # Regex: início de linha + "## " (com espaço para não pegar ###)
    return re.sub(r'^(## )', f'{marker}\n\\1', content, flags=re.MULTILINE)


def extract_body(content: str, title: str) -> str:
    """
    Extrai o corpo do documento (conteúdo principal sem headers e footers).

    Remove:
    - Header "Fichas Agroecológicas..."
    - Título em maiúsculas
    - Número da ficha
    - Footer "Ministério da Agricultura..."
    - Elaboradores da ficha
    - Referências bibliográficas (se forem mover para o final)
    """
    lines = content.split('\n')
    body_lines = []
    skip_header = True
    in_references = False

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
            in_references = True
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


def normalize_punctuation(content: str) -> str:
    """
    Normaliza pontuação para otimizar chunking do RAGFlow.

    RAGFlow usa delimiters: \n!?。；！？
    Itens de lista terminando em ; devem terminar em .

    Transformações:
    - "* item;" -> "* item."
    - Apenas itens de lista são modificados (conservador para evitar
      adicionar pontuação em quebras de linha do OCR)
    """
    lines = content.split('\n')
    result = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Pular linhas vazias, headers e blockquotes
        if not stripped or stripped.startswith(('#', '>', '**', '![')):
            result.append(line)
            continue

        # Processar itens de lista (* item)
        if stripped.startswith('* '):
            # Verificar se a próxima linha é continuação (começa com minúscula ou é vazia)
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
            is_continuation = next_line and next_line[0].islower()

            if not is_continuation:
                # Substituir ; final por .
                if stripped.endswith(';'):
                    line = line.rstrip()[:-1] + '.'
                # Adicionar . se não tiver pontuação final adequada
                elif stripped[-1] not in '.!?:)':
                    line = line.rstrip() + '.'

            result.append(line)
            continue

        # Linhas normais: não modificar (preservar pontuação original)
        # Evita adicionar . em quebras de linha do OCR
        result.append(line)

    return '\n'.join(result)


def format_authors_display(authors: list[str]) -> str:
    """
    Formata lista de autores para exibição.

    Exemplos:
    - ["A. B. Silva"] -> "A. B. Silva"
    - ["A. B. Silva", "C. D. Santos"] -> "A. B. Silva e C. D. Santos"
    - ["A", "B", "C"] -> "A, B e C"
    """
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} e {authors[1]}"
    return ', '.join(authors[:-1]) + f' e {authors[-1]}'


def assemble_document(frontmatter: str, title: str, authors: list[str],
                      ficha_number: str, body: str) -> str:
    """
    Monta o documento final otimizado para RAGFlow.

    Estrutura (sem --- internos para melhor chunking):
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

    Nota: Removidos --- internos pois RAGFlow usa delimiter="\n!?。；！？"
    e não reconhece --- como boundary de chunk.
    """
    authors_display = format_authors_display(authors)

    # Formatar título (Title Case, mas preservando siglas)
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

    # Header padrão das fichas (sem --- após)
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


def convert_full(content: str, filename: str) -> str:
    """
    Pipeline completo de conversão (Fases 1-4) otimizado para RAGFlow.

    1. Limpa artefatos do systemRAG
    2. Extrai metadados (título, autores, etc.)
    3. Gera YAML frontmatter
    4. Reestrutura conteúdo e monta documento final (sem --- internos)
    """
    # Fase 1: Limpeza
    cleaned = remove_artifacts(content)

    # Fase 2: Extração de dados
    title = extract_title(cleaned)
    authors = extract_authors(cleaned)
    ficha_number = extract_ficha_number(cleaned, filename)
    resumo = extract_resumo(cleaned, title)

    # Fase 3: YAML frontmatter
    tags = generate_tags(title, cleaned)
    frontmatter = generate_frontmatter(filename, title, authors, ficha_number, tags, resumo)

    # Fase 4: Reestruturação
    body = extract_body(cleaned, title)
    body = restructure_sections(body)
    body = format_steps(body)
    body = format_bullets(body)

    # Fase 5: Otimização para RAGFlow - juntar linhas de parágrafos
    body = join_paragraph_lines(body)

    # Fase 6: Inserir marcadores de seção para chunking no RAGFlow
    body = insert_section_markers(body)

    # Montar documento final (sem --- internos)
    return assemble_document(frontmatter, title, authors, ficha_number, body)


# =============================================================================
# CLI
# =============================================================================

def process_file(input_path: Path, output_path: Path, verbose: bool = False,
                 full_conversion: bool = True) -> bool:
    """
    Processa um único arquivo.

    Args:
        input_path: Caminho do arquivo de entrada
        output_path: Caminho do arquivo de saída
        verbose: Se True, mostra informações detalhadas
        full_conversion: Se True, executa pipeline completo (Fases 1-4).
                        Se False, apenas limpeza (Fase 1).
    """
    try:
        content = input_path.read_text(encoding='utf-8')

        if verbose:
            print(f"Processando: {input_path.name}")
            print(f"  Tamanho original: {len(content)} caracteres")

        if full_conversion:
            # Pipeline completo (Fases 1-4)
            result = convert_full(content, input_path.name)
            if verbose:
                print(f"  Conversão completa (Fases 1-4)")
        else:
            # Apenas limpeza (Fase 1)
            result = remove_artifacts(content)
            if verbose:
                print(f"  Apenas limpeza (Fase 1)")

        if verbose:
            print(f"  Tamanho final: {len(result)} caracteres")

        # Criar diretório de saída se necessário
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Salvar resultado
        result_with_newline = result if result.endswith('\n') else result + '\n'
        output_path.write_text(result_with_newline, encoding='utf-8')

        if verbose:
            print(f"  Salvo em: {output_path}")

        return True

    except Exception as e:
        print(f"Erro ao processar {input_path}: {e}")
        import traceback
        if verbose:
            traceback.print_exc()
        return False


def process_directory(input_dir: Path, output_dir: Path, verbose: bool = False,
                      full_conversion: bool = True) -> tuple:
    """
    Processa todos os arquivos .md em um diretório.

    Args:
        input_dir: Diretório de entrada
        output_dir: Diretório de saída
        verbose: Se True, mostra informações detalhadas
        full_conversion: Se True, executa pipeline completo (Fases 1-4)
    """
    success = 0
    failed = 0

    md_files = list(input_dir.glob('*.md'))

    if not md_files:
        print(f"Nenhum arquivo .md encontrado em {input_dir}")
        return 0, 0

    print(f"Encontrados {len(md_files)} arquivos .md")
    if full_conversion:
        print("Modo: Conversão completa (Fases 1-4)")
    else:
        print("Modo: Apenas limpeza (Fase 1)")
    print()

    for input_path in md_files:
        output_path = output_dir / input_path.name

        if process_file(input_path, output_path, verbose, full_conversion):
            success += 1
        else:
            failed += 1

    print(f"\nResultado: {success} sucesso, {failed} falhas")
    return success, failed


def main():
    import warnings
    warnings.warn(
        "converter.py está deprecado. Use: python -m ficha_converter [args]",
        DeprecationWarning,
        stacklevel=2
    )
    print("AVISO: converter.py está deprecado. Use: python -m ficha_converter [args]\n")

    parser = argparse.ArgumentParser(
        description='Converte MD systemRAG para formato estruturado',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Exemplos de uso:
  # Converter arquivo único (pipeline completo)
  python converter.py "MD/MD systemRAG/10-biofertilizante-vairo-1.md" -o "output.md"

  # Converter diretório inteiro
  python converter.py "MD/MD systemRAG/" -o "MD/converted/" --batch -v

  # Apenas limpeza (sem reestruturação)
  python converter.py "arquivo.md" -o "saida.md" --clean-only

  # Testar extração de dados
  python converter.py "MD/MD systemRAG/" --test-extract

  # Testar geração de YAML
  python converter.py "MD/MD systemRAG/" --test-yaml
'''
    )
    parser.add_argument('input', help='Arquivo ou diretório de entrada')
    parser.add_argument('-o', '--output', help='Arquivo ou diretório de saída')
    parser.add_argument('--batch', action='store_true', help='Processar diretório inteiro')
    parser.add_argument('-v', '--verbose', action='store_true', help='Output detalhado')
    parser.add_argument('--clean-only', action='store_true',
                        help='Apenas limpeza (Fase 1), sem reestruturação')
    parser.add_argument('--test-extract', action='store_true',
                        help='Testar extração de dados (Fase 2)')
    parser.add_argument('--test-yaml', action='store_true',
                        help='Testar geração de YAML frontmatter (Fase 3)')

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Erro: {input_path} não existe")
        return 1

    # Modo de teste de YAML (Fase 3)
    if args.test_yaml:
        if input_path.is_dir():
            files = list(input_path.glob('*.md'))
        else:
            files = [input_path]

        print(f"Testando geração de YAML em {len(files)} arquivo(s)...\n")

        for f in files:
            content = f.read_text(encoding='utf-8')
            frontmatter = test_frontmatter(content, f.name)

            print(f"=== {f.name} ===")
            print(frontmatter)
            print()

        return 0

    # Modo de teste de extração (Fase 2)
    if args.test_extract:
        if input_path.is_dir():
            files = list(input_path.glob('*.md'))
        else:
            files = [input_path]

        print(f"Testando extração em {len(files)} arquivo(s)...\n")
        print("=" * 80)

        for f in files:
            content = f.read_text(encoding='utf-8')
            result = test_extraction(content, f.name)

            print(f"Arquivo: {result['filename']}")
            print(f"  Título: {result['title']}")
            print(f"  Autores: {result['authors']}")
            print(f"  Ficha nº: {result['ficha_number']}")
            print(f"  Resumo: {result['resumo']}")
            print("-" * 80)

        return 0

    # Modo normal (requer output)
    if not args.output:
        print("Erro: -o/--output é obrigatório (exceto com --test-extract ou --test-yaml)")
        return 1

    output_path = Path(args.output)
    full_conversion = not args.clean_only

    if args.batch:
        if not input_path.is_dir():
            print(f"Erro: {input_path} não é um diretório")
            return 1
        process_directory(input_path, output_path, args.verbose, full_conversion)
    else:
        if not input_path.is_file():
            print(f"Erro: {input_path} não é um arquivo")
            return 1
        process_file(input_path, output_path, args.verbose, full_conversion)

    return 0


if __name__ == '__main__':
    exit(main())
