"""
Otimização do conteúdo para RAGFlow.

Este módulo prepara o conteúdo reestruturado para ingestão no RAGFlow:
- Junta linhas de parágrafos quebradas pelo OCR
- Padroniza bullets para formato consistente
- Normaliza espaçamento

O RAGFlow reconhece nativamente headers Markdown (## , ### ) como
delimitadores de chunk. Não é necessário marcador adicional.
"""

import re


def join_paragraph_lines(content: str) -> str:
    """
    Junta linhas que fazem parte do mesmo parágrafo.

    O OCR preserva quebras de linha da largura da página do PDF.
    RAGFlow usa \\n como delimiter, então cada linha viraria um chunk separado.

    Esta função junta linhas consecutivas que pertencem ao mesmo parágrafo,
    preservando:
    - Linhas em branco (separadores de parágrafo)
    - Headers (#, ##, ###)
    - Itens de lista (*, -, •)
    - Linhas que começam com maiúscula (novo parágrafo)

    Args:
        content: Conteúdo markdown

    Returns:
        Conteúdo com linhas de parágrafo unidas
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
        if stripped.startswith(('* ', '- ', '• ', '1. ', '2. ', '3. ', '4. ', '5. ',
                                '6. ', '7. ', '8. ', '9. ')):
            # Juntar linhas de continuação do item de lista
            combined = line.rstrip()
            i += 1
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                # Parar se: linha vazia, novo item, header, ou novo parágrafo
                if not next_stripped or next_stripped.startswith(('#', '* ', '- ', '• ')):
                    break
                # Parar se começa com número seguido de ponto (novo item numerado)
                if re.match(r'^\d+\.\s', next_stripped):
                    break
                # Continuação se:
                # 1. Começa com minúscula, OU
                # 2. Começa com ( [ (complemento), OU
                # 3. Linha anterior não termina com pontuação final (referências bibliográficas)
                is_continuation = (
                    next_stripped[0].islower() or
                    next_stripped[0] in '([' or
                    combined[-1] not in '.!?)]'
                )
                if next_stripped and is_continuation:
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
            # Parar se: linha vazia, header, item de lista, marcador
            if not next_stripped or next_stripped.startswith(('#', '* ', '- ', '• ')):
                break
            # Parar se começa com número seguido de ponto (item numerado)
            if re.match(r'^\d+\.\s', next_stripped):
                break
            # Continuação se:
            # 1. Começa com minúscula, OU
            # 2. Começa com ( [ (complemento), OU
            # 3. Linha anterior não termina com pontuação final (referências bibliográficas)
            is_continuation = (
                next_stripped[0].islower() or
                next_stripped[0] in '([' or
                combined[-1] not in '.!?)]'
            )
            if next_stripped and is_continuation:
                combined += ' ' + next_stripped
                i += 1
            else:
                break
        result.append(combined)

    return '\n'.join(result)


def format_bullets(content: str) -> str:
    """
    Padroniza todos os bullets para usar *.

    Converte:
    - Bullet com hífen (- item) -> * item
    - Bullet com círculo (• item) -> * item
    - Outros símbolos de bullet -> * item

    Args:
        content: Conteúdo markdown

    Returns:
        Conteúdo com bullets padronizados
    """
    # Converter - para * no início de linha (com espaço)
    content = re.sub(r'^(\s*)- ', r'\1* ', content, flags=re.MULTILINE)

    # Converter • para * no início de linha
    content = re.sub(r'^(\s*)• ', r'\1* ', content, flags=re.MULTILINE)

    # Converter outros símbolos comuns de bullet
    content = re.sub(r'^(\s*)[◦○●■□▪▫►▻] ', r'\1* ', content, flags=re.MULTILINE)

    return content


def normalize_spacing(content: str) -> str:
    """
    Normaliza espaçamento no documento.

    - Remove espaços duplos dentro de linhas
    - Remove espaços no final de linhas
    - Limita linhas em branco consecutivas a máximo de 2
    - Remove espaços antes de pontuação

    Args:
        content: Conteúdo markdown

    Returns:
        Conteúdo com espaçamento normalizado
    """
    # Remover espaços duplos dentro de linhas (exceto indentação)
    lines = content.split('\n')
    normalized_lines = []

    for line in lines:
        # Preservar indentação inicial
        leading_spaces = len(line) - len(line.lstrip())
        indent = line[:leading_spaces]
        text = line[leading_spaces:]

        # Remover espaços duplos no texto
        text = re.sub(r'  +', ' ', text)

        # Remover espaços antes de pontuação
        text = re.sub(r'\s+([.,;:!?)])', r'\1', text)

        # Remover espaços no final
        text = text.rstrip()

        normalized_lines.append(indent + text)

    content = '\n'.join(normalized_lines)

    # Limitar linhas em branco consecutivas a máximo de 2
    content = re.sub(r'\n{4,}', '\n\n\n', content)

    return content


def optimize_for_ragflow(content: str) -> str:
    """
    Executa todas as otimizações para RAGFlow.

    Pipeline de otimização:
    1. Padroniza bullets
    2. Junta linhas de parágrafos quebradas
    3. Normaliza espaçamento

    O RAGFlow reconhece nativamente headers Markdown (## , ### ) como
    delimitadores de chunk, dispensando marcadores adicionais.

    Args:
        content: Conteúdo markdown (após reestruturação)

    Returns:
        Conteúdo otimizado para RAGFlow
    """
    # 1. Padronizar bullets primeiro (antes de join_paragraph_lines)
    content = format_bullets(content)

    # 2. Juntar linhas de parágrafos
    content = join_paragraph_lines(content)

    # 3. Normalizar espaçamento
    content = normalize_spacing(content)

    return content


def format_optimize_summary(content: str, original_size: int) -> str:
    """
    Formata um resumo da otimização para exibição.

    Args:
        content: Conteúdo otimizado
        original_size: Tamanho original antes da otimização

    Returns:
        String formatada com estatísticas
    """
    final_size = len(content)
    reduction = (1 - final_size / original_size) * 100 if original_size > 0 else 0

    # Contar elementos
    h1_count = len(re.findall(r'^# [^#]', content, re.MULTILINE))
    h2_count = len(re.findall(r'^## [^#]', content, re.MULTILINE))
    h3_count = len(re.findall(r'^### [^#]', content, re.MULTILINE))
    bullet_count = len(re.findall(r'^\s*\* ', content, re.MULTILINE))
    paragraph_count = len(re.findall(r'\n\n[A-Z]', content))

    lines = [
        "Otimização RAGFlow concluída:",
        "",
        f"Headers (delimitadores nativos do RAGFlow):",
        f"  - Partes (#): {h1_count}",
        f"  - Capítulos (##): {h2_count}",
        f"  - Seções (###): {h3_count}",
        "",
        f"Estatísticas do documento:",
        f"  - Bullets padronizados: {bullet_count}",
        f"  - Parágrafos: ~{paragraph_count}",
        "",
        f"Tamanho:",
        f"  - Original: {original_size:,} caracteres",
        f"  - Final: {final_size:,} caracteres",
        f"  - Redução: {reduction:.1f}%",
    ]

    return '\n'.join(lines)
