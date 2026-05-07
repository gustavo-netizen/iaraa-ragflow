"""
Padrões de regex para limpeza de artefatos OCR — fonte única de verdade.

`CLEANUP_PATTERNS` aplica-se a qualquer documento OCR (ficha ou livro):
metadados Marco/DocMind, divisões de página, headers de figura/tabela
em todas as variações de formato vistas em produção.

`FICHA_EXTRA_PATTERNS` cobre 2 padrões específicos de Fichas Agroecológicas
(filename header com prefixo numérico e título ALL CAPS duplicado) que
NÃO podem entrar na lista comum porque colidiriam com livros (livros têm
títulos de capítulo em ALL CAPS — `CAPÍTULO 1`, `INTRODUÇÃO`).
"""

import re


CLEANUP_PATTERNS: list[tuple[str, str]] = [
    # === METADADOS MARCO CONVERTER ===
    (r'^\*Processed with Marco-Compliant Converter.*?\*\s*\n', ''),
    (r'^\*Model:.*?\*\s*\n', ''),
    (r'^\*Total Figures Detected:.*?\*\s*\n', ''),

    # === METADADOS DOCMIND ===
    (r'^\*Processed with DocMind.*?\*\s*\n', ''),
    (r'^\*Statistics:.*?\*\s*\n', ''),
    (r'^\*Merged from \d+/\d+ chunks\*\s*\n', ''),

    # === HEADERS DE ARQUIVO (livros) ===
    (r'^# [A-Z][A-Z0-9_]+\s*\n', ''),
    (r'^# \d{4}[A-Za-z][A-Za-z0-9_]*\s*\n', ''),
    (r'^# [A-Za-z][A-Za-z0-9_-]+\s*\n', ''),
    (r'^# [A-Za-z0-9_-]+[_-]part\d+of\d+\s*\n', ''),

    # === SEPARADORES ===
    (r'^---\s*\n(?=\s*## Page)', ''),
    (r'^---\s*\n(?=\s*#)', ''),
    (r'^---\s*\n(?=\s*\n)', ''),

    # === DIVISÕES DE PÁGINA ===
    (r'^## Page \d+\s*\n+', ''),

    # === HEADERS DE FIGURA / TABELA ===
    (r'^### Fig \d+:.*\n', ''),
    (r'^### Fig \d+\n', ''),
    (r'^### Figure \d+:.*\n', ''),
    (r'^### Figura \d+:.*\n', ''),
    (r'^### FIGURA \d+:.*\n', ''),
    (r'^### FIGURA \d+\n', ''),
    (r'^### Fig:.*\n', ''),
    (r'^### Table:.*\n', ''),
    (r'^### Table \d+:.*\n', ''),
    (r'^### QUADRO \d+:.*\n', ''),
    (r'^### TABELA \d+:.*\n', ''),
    (r'^### [A-Z]:\s*[A-ZÁÉÍÓÚÀÃÕÂÊÔÇ][A-ZÁÉÍÓÚÀÃÕÂÊÔÇ0-9,\.\s\-\(\)"\']+\n', ''),
    (r'^### [A-Z]+ and [A-Z]+:.*\n', ''),
    (r'^### [IVXLC]+:.*\n', ''),
    (r'^### \d+:.*\n', ''),
    (r'^### None:.*\n', ''),
    (r'^### Figure \([^)]+\):.*\n', ''),
    (r'^### FIGURA \d+[A-Z]:.*\n', ''),

    # === IMAGENS DE FIGURA / TABELA ===
    (r'^!\[Fig \d+:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[Fig \d+\]\(.*?\)\s*\n', ''),
    (r'^!\[Figure \d+:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[Figura \d+:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[Table:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[Table \d+:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[\d+:\s*\]\(.*?\)\s*\n', ''),
    (r'^!\[None:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[A and B:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[[A-Z]:\s*[A-ZÁÉÍÓÚÀÃÕÂÊÔÇ][^\]]*\]\(.*?\)\s*\n', ''),
    (r'^!\[FIGURA \d+:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[FIGURA \d+\]\(.*?\)\s*\n', ''),
    (r'^!\[Figure \([^)]+\):.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[\d+:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[[^\]]+\]\(images/[^)]+\)\s*\n', ''),

    # Descrições longas em itálico (50+ chars) tipicamente legendas
    (r'^\*[A-Z][^*\n]{50,}\*\s*\n', ''),

    # YAML metadata links
    (r'^\*YAML Metadata:.*?\*\s*\n', ''),

    # === FOOTNOTES ===
    # Pattern permissivo: o separador `---` à frente já costuma ser comido pelo
    # pattern genérico de SEPARADORES (linha 37) antes deste rodar, deixando o
    # label órfão. O grupo opcional cobre o caso em que o separador chega aqui
    # ainda intacto. Items `[^N]:` viram filtragem heurística em
    # `processamento/shared/footnote_filter.py:filter_footnote_items` —
    # preserva translator notes / definições / DOIs que pattern indiscriminado
    # apagava.
    (r'^(?:---\s*\n\s*\n)?\*\*Footnotes:\*\*\s*\n', ''),

    # === OUTROS ===
    (r'-{4,}', ' — '),
    # Pontos iniciais espúrios em parágrafos (artefato OCR)
    (r'^(\s*)\. (?=[A-Za-z])', r'\1'),
]


# Patterns específicos da estrutura de Fichas Agroecológicas.
# Não entram em CLEANUP_PATTERNS por colidirem com conteúdo legítimo de livros.
FICHA_EXTRA_PATTERNS: list[tuple[str, str]] = [
    # Filename header com prefixo/sufixo numérico (ex: `# 10-biofertilizante-vairo-1`)
    (r'^# \d+-[\w-]+-\d+\s*\n', ''),
    # Título ALL CAPS duplicado abaixo do header (após extract_title já capturou)
    (r'^[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ]{4,}(?:\s+[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ]{2,})*\s*\n', ''),
]


def remove_artifacts(content: str, patterns: list[tuple[str, str]]) -> str:
    """
    Aplica `patterns` em ordem (re.sub MULTILINE), depois normaliza espaçamento
    de blocos: colapsa 3+ \\n consecutivas em 2 e remove \\n iniciais.
    """
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    content = re.sub(r'\n{3,}', '\n\n', content)
    content = content.lstrip('\n')

    return content
