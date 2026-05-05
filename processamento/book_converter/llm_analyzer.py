"""
Análise de estrutura de livros usando LLM.

Este módulo contém o prompt para análise adaptativa de estrutura de livros
e funções para parsear a resposta JSON do LLM.
"""

import json
import re
from dataclasses import dataclass, field
from .models import BookMetadata, ChapterBoundary


@dataclass
class AnalysisResult:
    """Resultado da análise LLM."""
    metadata: BookMetadata
    chapters: list[ChapterBoundary]
    sections_to_remove: dict[str, list[tuple[int, int]]] = field(default_factory=dict)


def build_analysis_prompt(content: str, max_lines: int = 500) -> str:
    """
    Constrói prompt para análise de estrutura de livro.

    Args:
        content: Conteúdo MD do livro
        max_lines: Número máximo de linhas a incluir na amostra

    Returns:
        Prompt formatado para enviar ao LLM
    """
    lines = content.split('\n')
    sample_lines = lines[:max_lines]
    sample = '\n'.join(sample_lines)
    total_lines = len(lines)

    return f"""Analise este documento Markdown (livro técnico convertido de PDF via OCR) e extraia estrutura e metadados.

## Instruções

1. **Metadados** - Extraia do início do documento (folha de rosto, ficha catalográfica):
   - titulo: Título completo do livro (não o nome do arquivo)
   - autores: Lista de autores/organizadores (formato: ["Nome Sobrenome", ...])
   - editora: Lista de editoras (formato: ["Embrapa", ...])
   - ano: Ano de publicação (4 dígitos, número inteiro)
   - isbn: ISBN se presente (string com hífens)

2. **Capítulos** - Identifique a estrutura de capítulos:
   - titulo: Nome do capítulo (sem número, ex: "CONTEXTUALIZAÇÃO" não "1. CONTEXTUALIZAÇÃO")
   - linha_inicio: Número da linha onde o título do capítulo aparece (1-indexed)
   - nivel: "part" para partes/seções principais, "chapter" para capítulos

   Dicas para identificar capítulos:
   - Títulos em MAIÚSCULAS isolados em uma linha
   - Padrões como "Capítulo X", "PARTE X", números romanos
   - Títulos precedidos de números (1., 2., I., II.)
   - Contexto semântico (introdução, conclusão, referências)

3. **Seções para remover** - Identifique ranges de linhas para remoção:
   - figuras: Blocos com "### Fig", "![...](...)", descrições em itálico "*...*"
   - toc: Bloco de SUMÁRIO/ÍNDICE (NÃO remover "SUMÁRIO EXECUTIVO" que é conteúdo)
   - referencias: Seções de REFERÊNCIAS/BIBLIOGRAFIA (pode haver múltiplas por capítulo)

## Formato de Resposta

Responda APENAS com JSON válido, sem texto adicional:

```json
{{
  "metadados": {{
    "titulo": "Título do Livro",
    "autores": ["Autor 1", "Autor 2"],
    "editora": ["Editora"],
    "ano": 2020,
    "isbn": "978-85-0000-000-0"
  }},
  "capitulos": [
    {{"titulo": "INTRODUÇÃO", "linha_inicio": 45, "nivel": "chapter"}},
    {{"titulo": "CONTEXTUALIZAÇÃO", "linha_inicio": 120, "nivel": "chapter"}}
  ],
  "remover": {{
    "figuras": [[10, 15], [50, 55]],
    "toc": [30, 44],
    "referencias": [[200, 250], [400, 450]]
  }}
}}
```

Notas:
- Se um campo não for encontrado, use null para valores únicos ou [] para listas
- linha_inicio é 1-indexed (primeira linha = 1)
- Ranges de remoção são [linha_inicio, linha_fim] inclusivos

---

## Amostra do Documento ({total_lines} linhas totais, mostrando primeiras {len(sample_lines)}):

```
{sample}
```"""


def parse_llm_response(response: str) -> AnalysisResult:
    """
    Parseia resposta JSON do LLM.

    Args:
        response: Resposta do LLM (pode conter texto além do JSON)

    Returns:
        AnalysisResult com metadados, capítulos e seções para remover

    Raises:
        ValueError: Se a resposta não contiver JSON válido
    """
    # Extrair JSON da resposta (pode estar entre ```json ... ```)
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Tentar encontrar objeto JSON diretamente
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            raise ValueError("Resposta do LLM não contém JSON válido")
        json_str = json_match.group()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON inválido na resposta: {e}")

    # Extrair metadados
    meta = data.get('metadados', {})

    # Tratar editora como lista
    editora = meta.get('editora')
    if editora is None:
        editora = []
    elif isinstance(editora, str):
        editora = [editora] if editora else []

    # Tratar autores como lista
    autores = meta.get('autores')
    if autores is None:
        autores = []
    elif isinstance(autores, str):
        autores = [autores] if autores else []

    metadata = BookMetadata(
        titulo=meta.get('titulo') or '',
        autores=autores,
        editora=editora,
        ano=meta.get('ano'),
        isbn=meta.get('isbn'),
        palavras_chave=meta.get('tags', [])
    )

    # Extrair capítulos
    chapters = []
    for ch in data.get('capitulos', []):
        if not ch.get('titulo') or not ch.get('linha_inicio'):
            continue
        chapters.append(ChapterBoundary(
            title=ch['titulo'],
            start_pos=ch['linha_inicio'],
            end_pos=None,
            level=ch.get('nivel', 'chapter')
        ))

    # Extrair seções para remover
    remover = data.get('remover', {})
    sections_to_remove = {}

    # Processar figuras
    figuras = remover.get('figuras', [])
    if figuras:
        sections_to_remove['figuras'] = [tuple(r) for r in figuras if len(r) == 2]

    # Processar TOC
    toc = remover.get('toc')
    if toc and len(toc) == 2:
        sections_to_remove['toc'] = tuple(toc)

    # Processar referências
    referencias = remover.get('referencias', [])
    if referencias:
        sections_to_remove['referencias'] = [tuple(r) for r in referencias if len(r) == 2]

    # Processar frontmatter institucional
    frontmatter = remover.get('frontmatter')
    if frontmatter and len(frontmatter) == 2:
        sections_to_remove['frontmatter'] = tuple(frontmatter)

    return AnalysisResult(
        metadata=metadata,
        chapters=chapters,
        sections_to_remove=sections_to_remove
    )


def format_analysis_summary(result: AnalysisResult) -> str:
    """
    Formata um resumo da análise para exibição.

    Args:
        result: Resultado da análise LLM

    Returns:
        String formatada com resumo
    """
    meta = result.metadata

    lines = [
        "Análise LLM concluída:",
        "",
        "Metadados:",
        f"  - Título: {meta.titulo or '(não encontrado)'}",
        f"  - Autores: {', '.join(meta.autores) if meta.autores else '(não encontrado)'}",
        f"  - Editora: {', '.join(meta.editora) if meta.editora else '(não encontrada)'}",
        f"  - Ano: {meta.ano or '(não encontrado)'}",
        f"  - ISBN: {meta.isbn or '(não encontrado)'}",
        "",
        f"Capítulos identificados: {len(result.chapters)}",
    ]

    for ch in result.chapters[:10]:
        level_marker = "PARTE" if ch.level == 'part' else "Cap"
        lines.append(f"  - [{level_marker}] {ch.title} (linha {ch.start_pos})")

    if len(result.chapters) > 10:
        lines.append(f"  ... e mais {len(result.chapters) - 10} capítulos")

    lines.append("")
    lines.append("Seções para remover:")

    if 'figuras' in result.sections_to_remove:
        n_figs = len(result.sections_to_remove['figuras'])
        lines.append(f"  - Figuras: {n_figs} blocos")

    if 'toc' in result.sections_to_remove:
        toc = result.sections_to_remove['toc']
        lines.append(f"  - TOC/Sumário: linhas {toc[0]}-{toc[1]}")

    if 'referencias' in result.sections_to_remove:
        n_refs = len(result.sections_to_remove['referencias'])
        lines.append(f"  - Referências: {n_refs} seções")

    if not result.sections_to_remove:
        lines.append("  (nenhuma seção identificada para remoção)")

    return '\n'.join(lines)
