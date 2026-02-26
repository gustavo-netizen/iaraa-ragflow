---
name: convert-book
description: Converte livros em Markdown (gerados por OCR via DocMind/Marco Converter) para formato otimizado para RAGFlow. Usa análise LLM para extrair metadados, identificar capítulos, e remover TOC/referências. Invoque com /convert-book <arquivo.md>
allowed-tools: Read, Glob, Write, Bash(python*:*)
---

# Skill: /convert-book

Converte livros em Markdown (gerados por OCR via DocMind/Marco Converter) para formato otimizado para RAGFlow.

## Uso

```
/convert-book <input.md> [-o <output.md>] [-v]
```

**Argumentos:**
- `<input.md>` - Caminho do arquivo MD de entrada (obrigatório)
- `-o <output.md>` - Caminho do arquivo de saída (opcional, default: `Processado_<input>.md`)
- `-v` - Modo verbose (mostra log detalhado)

## Pipeline de Conversão

```
┌─────────────────────────────────────────────────────────────┐
│  FASE 1 (LLM) - Análise Adaptativa                          │
│  ├─ Extrair metadados (título, autores, ISBN, ano, editora) │
│  ├─ Identificar estrutura de capítulos com posições         │
│  └─ Detectar seções para remover (figuras, TOC, refs)       │
├─────────────────────────────────────────────────────────────┤
│  FASE 2 (Código) - Remoção de Seções                        │
│  └─ Remover frontmatter, TOC, refs (por linhas do JSON)     │
├─────────────────────────────────────────────────────────────┤
│  FASE 3 (Código) - Limpeza OCR                              │
│  ├─ Remover artefatos Marco/DocMind                         │
│  ├─ Remover descrições de figuras (**Type:**...*Confidence*)│
│  └─ Remover headers/footers com título do livro             │
├─────────────────────────────────────────────────────────────┤
│  FASE 4 (Código) - Inserir Headers                          │
│  ├─ Inserir ## headers nos capítulos por busca de título    │
│  └─ Fallback: detectar CAPÍTULO/PARTE/APRESENTAÇÃO/etc.     │
├─────────────────────────────────────────────────────────────┤
│  FASE 5 (Código) - RAGFlow Optimization                     │
│  ├─ join_paragraph_lines(), format_bullets()                │
│  └─ insert_section_markers() (§)                            │
├─────────────────────────────────────────────────────────────┤
│  FASE 6 (Código) - Assembly                                 │
│  ├─ Gerar YAML frontmatter + documento final                │
│  └─ Sugerir nome de arquivo baseado no título               │
└─────────────────────────────────────────────────────────────┘
```

## Correções Automáticas

O pipeline inclui correções automáticas que não requerem intervenção:

| Correção | Descrição |
|----------|-----------|
| **Descrições de figuras** | Blocos `**Type:**`...`*Confidence:*` removidos automaticamente |
| **Headers de capítulos** | Fallback detecta CAPÍTULO/PARTE/APRESENTAÇÃO/PREFÁCIO/etc. |
| **Marcadores § duplicados** | Removidos automaticamente após inserção |
| **Nome do arquivo** | `get_output_filename()` sugere nome baseado no título extraído |

## Instruções de Execução

### Passo 1: Ler o arquivo de entrada

```python
from pathlib import Path

input_path = Path("<input.md>")
content = input_path.read_text(encoding='utf-8')
filename = input_path.name
```

### Passo 2: Gerar prompt e analisar com LLM

O módulo está em `.claude/skills/convert-book/book_converter/`. Adicionar ao path:

```python
import sys
sys.path.insert(0, '.claude/skills/convert-book')

from book_converter.llm_analyzer import build_analysis_prompt

prompt = build_analysis_prompt(content, max_lines=500)
```

O prompt solicita extração de:
- **Metadados**: título, autores, editora, ano, isbn
- **Capítulos**: título, linha_inicio (1-indexed), nivel (part/chapter)
- **Seções para remover**: figuras, toc, referencias (ranges de linhas)

**IMPORTANTE:** Você (Claude) deve analisar o documento e responder ao prompt com JSON no formato:

```json
{
  "metadados": {
    "titulo": "Título do Livro",
    "autores": ["Autor 1", "Autor 2"],
    "editora": ["Editora"],
    "ano": 2020,
    "isbn": "978-85-0000-000-0"
  },
  "capitulos": [
    {"titulo": "INTRODUÇÃO", "linha_inicio": 45, "nivel": "chapter"},
    {"titulo": "CONTEXTUALIZAÇÃO", "linha_inicio": 120, "nivel": "chapter"}
  ],
  "remover": {
    "figuras": [[10, 15], [50, 55]],
    "toc": [30, 44],
    "referencias": [[200, 250], [400, 450]]
  }
}
```

**Dicas para análise:**
- Metadados geralmente estão nas primeiras 100 linhas (folha de rosto, ficha catalográfica)
- Capítulos: procurar títulos em MAIÚSCULAS, numeração (1., I., Capítulo X)
- TOC: bloco com "SUMÁRIO" ou "ÍNDICE" (NÃO remover "SUMÁRIO EXECUTIVO")
- Figuras: blocos com `### Fig`, `![...]`, descrições em itálico
- Referências: seções com "Referências", "Bibliografia" (pode haver múltiplas)

### Passo 3: Executar pipeline de conversão

```python
from book_converter.llm_pipeline import convert_book_with_llm

# llm_response é o JSON que você gerou no passo anterior
document, log = convert_book_with_llm(
    content=content,
    filename=filename,
    llm_response=llm_response,
    chunk_level=2,
    include_frontmatter=True,
    verbose=True
)
```

### Passo 4: Salvar arquivo de saída

```python
from book_converter.assembler import get_output_filename
from book_converter.llm_analyzer import parse_llm_response

# Obter metadados para gerar nome do arquivo
analysis = parse_llm_response(llm_response)

# Gerar nome baseado no título (se disponível)
suggested_name = get_output_filename(analysis.metadata, filename)

output_path = Path("<output.md>")  # ou usar suggested_name
output_path.write_text(document, encoding='utf-8')
```

Se `-o` não foi especificado, usar o título extraído:
```python
output_path = input_path.parent / suggested_name
# Ex: "Um Testamento Agrícola.md" em vez de "um-testamento-2018.md"
```

### Passo 5: Reportar resultado

Mostrar resumo:
- Tamanho original vs final
- Metadados extraídos
- Número de capítulos identificados
- Número de seções removidas
- Caminho do arquivo de saída

## Exemplo Completo

```
Usuário: /convert-book "/home/user/livro.md" -o "/home/user/output.md" -v

Claude:
1. Lê o arquivo livro.md
2. Analisa as primeiras 500 linhas
3. Gera JSON com metadados, capítulos e seções para remover
4. Executa convert_book_with_llm()
5. Salva em output.md
6. Mostra resumo da conversão
```

## Validação do Output

O documento final deve conter:
- [ ] YAML frontmatter com id, titulo, autores, editora, ano, isbn
- [ ] `# Título do Livro` como H1
- [ ] `## Capítulo` para cada capítulo identificado
- [ ] Marcadores `§` antes de cada `##` para chunking RAGFlow
- [ ] Parágrafos unidos (sem quebras de linha do OCR)
- [ ] Bullets padronizados com `*`
- [ ] Figuras, TOC e referências removidos

## Tratamento de Erros

- **Arquivo não encontrado**: Informar usuário e abortar
- **JSON inválido**: Re-analisar documento ou pedir correção
- **Nenhum capítulo identificado**: Avisar e continuar sem headers
- **Metadados incompletos**: Usar valores vazios/null e avisar
