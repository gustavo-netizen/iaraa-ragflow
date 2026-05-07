"""
Constantes editáveis específicas de Fichas Agroecológicas.

Patterns OCR (`CLEANUP_PATTERNS`, `FICHA_EXTRA_PATTERNS`) e `ACCENT_MAP`
moraram aqui — agora são canônicos em `processamento.shared`.
"""


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

# Seções principais → ## headers
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

# Subseções → ### headers
SUBSECTION_PATTERNS = [
    (r'^(Dica [Aa]groecológica)\s*!?\s*$', r'### \1!'),
    (r'^(Atenção)\s*!?\s*$', r'### Atenção!'),
]
