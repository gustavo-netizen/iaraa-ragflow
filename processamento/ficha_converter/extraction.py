"""
Extração de metadados das Fichas Agroecológicas.

Fase 2 do pipeline:
- Extrai título, autores, número da ficha, resumo
"""

import re


def extract_title(content: str) -> str:
    """
    Extrai o título principal (linha em MAIÚSCULAS após header "Fichas Agroecológicas").

    Exemplo: "BIOFERTILIZANTE VAIRO", "HÚMUS DE MINHOCA"

    Returns:
        Título extraído ou string vazia se não encontrado
    """
    # Procurar linha em MAIÚSCULAS após "Nutrição de Plantas" e número
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

    Returns:
        Lista de autores formatados ou lista vazia se não encontrados
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

    Returns:
        Número da ficha ou string vazia se não encontrado
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

    Returns:
        Resumo extraído ou string vazia
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


def extract_all(content: str, filename: str, verbose: bool = False) -> dict:
    """
    Extrai todos os metadados de uma ficha.

    Args:
        content: Conteúdo da ficha (já limpo de artefatos)
        filename: Nome do arquivo
        verbose: Se True, imprime warnings quando extração falha

    Returns:
        Dicionário com title, authors, ficha_number, resumo, warnings
    """
    warnings = []

    # Extrair título
    title = extract_title(content)
    if not title:
        warnings.append("Título não encontrado")

    # Extrair autores
    authors = extract_authors(content)
    if not authors:
        warnings.append("Autores não encontrados")

    # Extrair número da ficha
    ficha_number = extract_ficha_number(content, filename)
    if not ficha_number:
        warnings.append("Número da ficha não encontrado")

    # Extrair resumo
    resumo = extract_resumo(content, title)
    if not resumo:
        warnings.append("Resumo não encontrado")

    # Imprimir warnings se verbose
    if verbose and warnings:
        for w in warnings:
            print(f"  Aviso: {w}")

    return {
        'title': title,
        'authors': authors,
        'ficha_number': ficha_number,
        'resumo': resumo,
        'warnings': warnings,
    }


def format_extraction_summary(data: dict, filename: str = "") -> str:
    """
    Formata os dados extraídos para exibição no terminal.

    Args:
        data: Dicionário retornado por extract_all()
        filename: Nome do arquivo (opcional)

    Returns:
        String formatada para exibição
    """
    lines = []

    if filename:
        lines.append(f"Arquivo: {filename}")

    lines.append(f"  Título: {data['title'] or '(não encontrado)'}")
    lines.append(f"  Autores: {data['authors'] or '(não encontrados)'}")
    lines.append(f"  Ficha nº: {data['ficha_number'] or '(não encontrado)'}")

    resumo = data['resumo']
    if resumo and len(resumo) > 80:
        resumo = resumo[:80] + '...'
    lines.append(f"  Resumo: {resumo or '(não encontrado)'}")

    if data['warnings']:
        lines.append(f"  Avisos: {len(data['warnings'])}")

    return '\n'.join(lines)
