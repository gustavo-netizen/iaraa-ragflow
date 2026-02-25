"""Módulo para extração e formatação de tabelas do YAML.

Fase A: find_yaml_file() e load_tables_from_yaml()
Fase B: translate_to_portuguese(), filter_text_labels(), format_table_section()
"""

import yaml
from pathlib import Path


def find_yaml_file(md_path: str) -> str | None:
    """Busca [nome]_all_figures.yaml no mesmo diretório do MD.

    Padrão: /path/to/[nome]/[nome].md → /path/to/[nome]/[nome]_all_figures.yaml

    Args:
        md_path: Caminho para o arquivo MD de entrada

    Returns:
        Caminho para o YAML se existir, None caso contrário
    """
    md_path = Path(md_path)
    base_name = md_path.stem  # nome sem extensão
    yaml_name = f"{base_name}_all_figures.yaml"
    yaml_path = md_path.parent / yaml_name

    if yaml_path.exists():
        return str(yaml_path)
    return None


def load_tables_from_yaml(yaml_path: str) -> list[dict]:
    """Carrega apenas entries com image_type='table' do YAML.

    Args:
        yaml_path: Caminho para o arquivo YAML

    Returns:
        Lista de dicts com as tabelas, ordenadas por page_number
    """
    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    tables = []
    for fig in data.get('figures', []):
        chart_id = fig.get('chart_identification', {})
        if chart_id.get('image_type') == 'table':
            tables.append(fig)

    # Ordenar por page_number
    tables.sort(key=lambda t: t.get('chart_identification', {}).get('page_number', 0))
    return tables


def translate_to_portuguese(text: str) -> str:
    """Traduz texto em inglês para português.

    Usa dicionário de termos frequentes nos YAMLs de agroecologia.
    Usa regex para substituir apenas palavras completas quando necessário.

    Args:
        text: Texto a traduzir

    Returns:
        Texto traduzido (ou original se não houver tradução)
    """
    import re

    if not text:
        return text

    # Frases completas (substituição direta, ordem por tamanho)
    phrase_translations = [
        ("without laboratory tests", "sem testes laboratoriais"),
        ("specific soil problems", "problemas específicos do solo"),
        ("nutrient deficiencies", "deficiências de nutrientes"),
        ("should be applied at specific rates depending on the crop",
         "deve ser aplicado em taxas específicas dependendo da cultura"),
        ("indicator plants", "plantas indicadoras"),
        ("soil conditions", "condições do solo"),
        ("scientific names", "nomes científicos"),
        ("popular names", "nomes populares"),
        ("application rates", "taxas de aplicação"),
        ("helping farmers", "ajudando agricultores"),
        ("fruiting phase", "fase de frutificação"),
        ("compared to", "comparado a"),
        ("depending on", "dependendo da"),
        ("should be applied", "deve ser aplicado"),
        ("soil health", "saúde do solo"),
        ("The presence", "A presença"),
        ("the presence", "a presença"),
        ("can signal", "pode sinalizar"),
        ("castor bean", "mamona"),
        ("A table", "Uma tabela"),
        ("a table", "uma tabela"),
        ("such as", "como"),
        ("e.g.,", "ex:"),
    ]

    result = text
    for eng, pt in phrase_translations:
        result = result.replace(eng, pt)

    # Palavras individuais (usar regex para word boundaries)
    word_translations = {
        # Nutrientes
        "potassium": "potássio",
        "nitrogen": "nitrogênio",
        "molybdenum": "molibdênio",
        "magnesium": "magnésio",
        "phosphorus": "fósforo",
        "calcium": "cálcio",
        "copper": "cobre",
        "iron": "ferro",
        "zinc": "zinco",
        # Culturas
        "garlic": "alho",
        "strawberry": "morango",
        "cucumber": "pepino",
        "pepper": "pimentão",
        "tomato": "tomate",
        "tomatoes": "tomates",
        # Termos técnicos
        "biofertilizer": "biofertilizante",
        "compaction": "compactação",
        "characteristics": "características",
        "application": "aplicação",
        "applications": "aplicações",
        "frequency": "frequência",
        "recommended": "recomendado",
        "methods": "métodos",
        "enriched": "enriquecido",
        "different": "diferentes",
        "columns": "colunas",
        "instructions": "instruções",
        "higher": "maiores",
        "doses": "doses",
        "weekly": "semanais",
        "require": "requerem",
        "excesses": "excessos",
        "showing": "mostrando",
        "listing": "listando",
        "including": "incluindo",
        "diagnose": "diagnosticar",
        "dosage": "dosagem",
        "during": "durante",
        "rates": "taxas",
        "type": "tipo",
        # Palavras comuns
        "plants": "plantas",
        "plant": "planta",
        "crops": "culturas",
        "crop": "cultura",
        "table": "tabela",
        "soil": "solo",
        "species": "espécies",
        "specific": "específicas",
        "entries": "entradas",
        "includes": "inclui",
        "indicate": "indicam",
        "associated": "associados",
        "issues": "problemas",
        "certain": "certas",
        "their": "seus",
        "which": "que",
        "they": "elas",
        "with": "com",
        "like": "como",
        "The": "A",
        "the": "a",
        "and": "e",
        "for": "para",
        "of": "de",
        "or": "ou",
        "at": "em",
        "It": "Ela",
    }

    for eng, pt in word_translations.items():
        # Usar word boundary para evitar substituições parciais
        pattern = r'\b' + re.escape(eng) + r'\b'
        result = re.sub(pattern, pt, result)

    return result


def filter_text_labels(labels: list[str], key_elements: list[str], chart_title: str) -> list[str]:
    """Remove headers duplicados e itens irrelevantes dos text_labels.

    Args:
        labels: Lista de text_labels do YAML
        key_elements: Lista de key_elements (headers de coluna)
        chart_title: Título da tabela

    Returns:
        Lista filtrada de labels
    """
    if not labels:
        return []

    filtered = []
    # Normalizar termos a ignorar (lowercase para comparação)
    skip_terms_lower = {term.lower() for term in key_elements + [chart_title]}

    # Headers comuns de tabelas que devem ser ignorados
    common_headers = {
        "nome popular", "característica", "características", "cultura",
        "indicação", "biofertilizante", "quantidade", "dose", "dosagem",
        "ingrediente", "ingredientes", "espécie", "planta", "plantas",
        "plantar indicadoras de solo", "plantas indicadoras de solo",
    }
    skip_terms_lower.update(common_headers)

    for label in labels:
        label_lower = label.lower().strip()
        # Pular se for igual a um termo a ignorar (case-insensitive)
        if label_lower in skip_terms_lower:
            continue
        # Pular se for muito curto (provavelmente header ou símbolo)
        if len(label.strip()) < 3:
            continue
        # Pular se for apenas números
        if label.strip().isdigit():
            continue
        # Pular se for apenas um traço ou símbolo
        if label.strip() in ['-', '–', '—', '*', '•']:
            continue
        filtered.append(label)

    return filtered


def format_table_section(table: dict) -> str:
    """Converte dict do YAML em seção markdown otimizada para RAG.

    Formato de saída:
    §
    ### [Título]

    [Descrição traduzida]

    **Itens:**
    * item1
    * item2

    **Insight:** [Insight traduzido]

    Args:
        table: Dict com dados da tabela do YAML

    Returns:
        String markdown formatada
    """
    chart_id = table.get('chart_identification', {})
    visual = table.get('visual_content', {})

    title = chart_id.get('chart_title', 'Tabela')
    description = visual.get('content_description', '')
    key_insight = visual.get('key_insight', '')
    text_labels = visual.get('text_labels', [])
    key_elements = visual.get('key_elements', [])

    # Traduzir textos em inglês
    description = translate_to_portuguese(description)
    key_insight = translate_to_portuguese(key_insight)

    # Filtrar labels
    filtered_labels = filter_text_labels(text_labels, key_elements, title)

    # Montar seção
    lines = [
        "§",
        f"### {title}",
        "",
    ]

    if description:
        lines.append(description)
        lines.append("")

    if filtered_labels:
        lines.append("**Itens:**")
        for label in filtered_labels:
            lines.append(f"* {label}")

    if key_insight:
        lines.append("")
        lines.append(f"**Insight:** {key_insight}")

    return "\n".join(lines)


def inject_tables_in_body(body: str, tables: list[dict]) -> str:
    """Insere tabelas formatadas no final do body, antes do rodapé.

    As tabelas são inseridas antes de seções como "Referências bibliográficas"
    ou "Elaborador da ficha", mantendo a estrutura do documento.

    Args:
        body: Conteúdo do body do documento
        tables: Lista de dicts com tabelas do YAML

    Returns:
        Body com tabelas inseridas
    """
    if not tables:
        return body

    # Formatar todas as tabelas
    table_sections = []
    for table in tables:
        section = format_table_section(table)
        table_sections.append(section)

    tables_text = "\n\n".join(table_sections)

    # Encontrar ponto de inserção (antes de Referências ou rodapé)
    insert_markers = [
        "## Referências bibliográficas",
        "Referência bibliográfica:",
        "Referências bibliográficas:",
        "Elaborador da ficha:",
        "Elaboradores da ficha:",
    ]

    insert_pos = len(body)
    for marker in insert_markers:
        pos = body.find(marker)
        if pos != -1 and pos < insert_pos:
            insert_pos = pos

    # Inserir tabelas
    before = body[:insert_pos].rstrip()
    after = body[insert_pos:]

    if after:
        return f"{before}\n\n{tables_text}\n\n{after}"
    else:
        return f"{before}\n\n{tables_text}"
