"""
Configurações e constantes editáveis do conversor de Fichas Agroecológicas.

Este arquivo centraliza todas as constantes usadas pelo conversor,
facilitando a manutenção e adição de novos padrões.
"""

# =============================================================================
# PADRÕES DE LIMPEZA OCR (Fase 1)
# =============================================================================

CLEANUP_PATTERNS = [
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

    # Headers de figuras e tabelas (inglês e português)
    (r'^### Figure \d+:.*?\n', ''),
    (r'^### Figura \d+:.*?\n', ''),
    (r'^### Table:.*?\n', ''),
    (r'^### Table \d+:.*?\n', ''),

    # Imagens de figuras e tabelas (inglês e português)
    (r'^!\[Figure \d+:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[Figura \d+:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[Table:.*?\]\(.*?\)\s*\n', ''),
    (r'^!\[Table \d+:.*?\]\(.*?\)\s*\n', ''),

    # Links para YAML metadata
    (r'^\*YAML Metadata:.*?\*\s*\n', ''),

    # Título duplicado em ALL CAPS (ex: MINHOCÁRIO após # Minhocário)
    (r'^[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ]{4,}(?:\s+[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ]{2,})*\s*\n', ''),

    # Hífens decorativos (ex: "texto ------- texto")
    (r'-{4,}', ' — '),
]

# =============================================================================
# KEYWORDS PARA GERAÇÃO DE TAGS (Fase 3)
# =============================================================================

TAG_KEYWORDS = {
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

# =============================================================================
# PADRÕES DE SEÇÃO (Fase 4)
# =============================================================================

# Seções principais -> ## Headers
SECTION_PATTERNS = [
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
SUBSECTION_PATTERNS = [
    (r'^(Dica [Aa]groecológica)\s*!?\s*$', r'### \1!'),
    (r'^(Atenção)\s*!?\s*$', r'### Atenção!'),
]

# =============================================================================
# MAPEAMENTO DE ACENTOS PARA NORMALIZAÇÃO
# =============================================================================

ACCENT_MAP = {
    'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
    'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
    'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
    'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
    'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
    'ç': 'c', 'ñ': 'n',
}
