"""
Heurística de filtragem para items de footnote vindos do Stage 1.

Stage 1 (DocMind) emite footnotes inline como `[^N]: <texto>` sob um label
`**Footnotes:**`. O payload mistura conteúdo substantivo (translator notes,
definições de termo, DOIs) com ruído de OCR (sobrescritos órfãos `¹`,
dígitos isolados, fragmentos de número de página).

Usado por J.0 para limpar items ruidosos preservando os úteis. Reusado
em J.3 pelo `book_converter` ao renderizar `## Notas` a partir do sidecar.
"""

from __future__ import annotations

import re

_FOOTNOTE_ITEM_RE = re.compile(r'^\[\^\d+\]:\s*(.*)$')
_PAYLOAD_PREFIX_RE = re.compile(r'^(?:\*\s+|\d+\.\s+)')

_MIN_ALPHA_CHARS = 5


def is_substantive_footnote(text: str) -> bool:
    """
    True quando o payload do item carrega conteúdo alfabético suficiente
    para ser preservado (translator notes, definições, DOIs).

    Strip do prefixo `* ` ou `N. ` que o OCR às vezes deixa antes de contar.
    """
    payload = _PAYLOAD_PREFIX_RE.sub('', text.strip())
    alpha = sum(1 for c in payload if c.isalpha())
    return alpha >= _MIN_ALPHA_CHARS


def is_footnote_noise(line: str) -> bool:
    """
    True quando a linha é um item `[^N]:` cujo payload é curto/ruidoso.

    Retorna False para linhas que não são footnote — só filtra items.
    """
    match = _FOOTNOTE_ITEM_RE.match(line)
    if not match:
        return False
    return not is_substantive_footnote(match.group(1))


def filter_footnote_items(content: str) -> str:
    """
    Remove items `[^N]: <curto>` ruidosos preservando os substantivos.

    Linha-a-linha:
        [^1]: ¹                         → drop
        [^2]: 4.                        → drop
        [^3]: *Tournois refere-se à...  → keep
    Linhas que não são footnote passam intactas.
    """
    lines = content.split('\n')
    return '\n'.join(line for line in lines if not is_footnote_noise(line))
