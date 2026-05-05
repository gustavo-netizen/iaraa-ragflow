"""
Otimização de Markdown para ingestão no RAGFlow — fonte única de verdade
para ambos os converters.

RAGFlow reconhece headers Markdown (`## `, `### `) nativamente como
delimitadores de chunk. Estas funções juntam linhas quebradas pelo OCR
e padronizam bullets/espaçamento sem introduzir marcadores adicionais.
"""

import re


def join_paragraph_lines(content: str) -> str:
    """
    Junta linhas que fazem parte do mesmo parágrafo, quebradas pelo OCR.

    Preserva:
        - linhas em branco (separadores de parágrafo)
        - headers (`#`, `##`, `###`)
        - itens de lista com bullet (`*`, `-`, `•`)
        - itens de lista numerada (`1. `, `2. `, ..., `9. `)

    Junta linhas seguintes que são continuação (começam com minúscula,
    `(`, `[`, ou a linha anterior não termina com pontuação final).
    """
    lines = content.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            result.append('')
            i += 1
            continue

        if stripped.startswith('#'):
            result.append(line)
            i += 1
            continue

        if stripped.startswith(('* ', '- ', '• ', '1. ', '2. ', '3. ', '4. ', '5. ',
                                '6. ', '7. ', '8. ', '9. ')):
            combined = line.rstrip()
            i += 1
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                if not next_stripped or next_stripped.startswith(('#', '* ', '- ', '• ')):
                    break
                if re.match(r'^\d+\.\s', next_stripped):
                    break
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

        combined = line.rstrip()
        i += 1
        while i < len(lines):
            next_line = lines[i]
            next_stripped = next_line.strip()
            if not next_stripped or next_stripped.startswith(('#', '* ', '- ', '• ')):
                break
            if re.match(r'^\d+\.\s', next_stripped):
                break
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
    """Padroniza bullets para `* ` (converte `-`, `•`, `◦○●■□▪▫►▻`)."""
    content = re.sub(r'^(\s*)- ', r'\1* ', content, flags=re.MULTILINE)
    # Variante sem espaço: `-palavra` (visto em fichas mal-OCR'd)
    content = re.sub(
        r'^-([A-Za-záéíóúàãõâêôçÁÉÍÓÚÀÃÕÂÊÔÇ])',
        r'* \1',
        content,
        flags=re.MULTILINE,
    )
    content = re.sub(r'^(\s*)• ', r'\1* ', content, flags=re.MULTILINE)
    content = re.sub(r'^(\s*)[◦○●■□▪▫►▻] ', r'\1* ', content, flags=re.MULTILINE)
    return content


def normalize_spacing(content: str) -> str:
    """
    Normaliza espaçamento:
        - colapsa espaços duplos dentro de linhas (preserva indentação)
        - remove espaços antes de pontuação
        - remove espaços no fim de linha
        - limita linhas em branco consecutivas a no máximo 2
    """
    lines = content.split('\n')
    normalized_lines = []

    for line in lines:
        leading_spaces = len(line) - len(line.lstrip())
        indent = line[:leading_spaces]
        text = line[leading_spaces:]

        text = re.sub(r'  +', ' ', text)
        text = re.sub(r'\s+([.,;:!?)])', r'\1', text)
        text = text.rstrip()

        normalized_lines.append(indent + text)

    content = '\n'.join(normalized_lines)
    content = re.sub(r'\n{4,}', '\n\n\n', content)

    return content


def optimize_for_ragflow(content: str) -> str:
    """Pipeline de otimização: bullets → join_paragraph_lines → normalize_spacing."""
    content = format_bullets(content)
    content = join_paragraph_lines(content)
    content = normalize_spacing(content)
    return content
