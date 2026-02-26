"""
Limpeza e otimização de texto para RAGFlow.

Fases 1 e 5 do pipeline:
- Fase 1: Remoção de artefatos OCR
- Fase 5: Junção de linhas de parágrafo
"""

import re
from .config import CLEANUP_PATTERNS


# =============================================================================
# FASE 1: LIMPEZA BÁSICA
# =============================================================================

def remove_artifacts(content: str) -> str:
    """
    Remove todos os artefatos do formato systemRAG.

    Artefatos removidos:
    - Metadados de processamento (*Processed with...*, *Model:...*, etc.)
    - Divisões de página (## Page X)
    - Referências de figuras/tabelas (### Figure X:, ![Figure...])
    - Título original do arquivo (# XX-nome-X)
    """
    for pattern, replacement in CLEANUP_PATTERNS:
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
# FASE 5: OTIMIZAÇÃO RAGFLOW
# =============================================================================

def join_paragraph_lines(content: str) -> str:
    """
    Junta linhas que fazem parte do mesmo parágrafo.

    O OCR do systemRAG preserva quebras de linha da largura da página do PDF.
    RAGFlow usa \\n como delimiter, então cada linha vira um chunk separado.

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
            # Parar se: linha vazia, header, item de lista
            if not next_stripped or next_stripped.startswith(('#', '* ', '- ', '• ')):
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


def normalize_punctuation(content: str) -> str:
    """
    Normaliza pontuação para otimizar chunking do RAGFlow.

    RAGFlow usa delimiters: \\n!?。；！？
    Itens de lista terminando em ; devem terminar em .

    Transformações:
    - "* item;" -> "* item."
    - Apenas itens de lista são modificados
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
            # Verificar se a próxima linha é continuação
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

        # Linhas normais: não modificar
        result.append(line)

    return '\n'.join(result)


# =============================================================================
# FUNÇÕES COMBINADAS
# =============================================================================

def clean_all(content: str) -> str:
    """
    Executa todas as limpezas da Fase 1.

    Returns:
        Conteúdo limpo de artefatos OCR
    """
    content = remove_artifacts(content)
    return content


def optimize_for_ragflow(content: str) -> str:
    """
    Executa otimizações para RAGFlow (Fase 5).

    Returns:
        Conteúdo otimizado com linhas de parágrafo unidas
    """
    content = join_paragraph_lines(content)
    return content
