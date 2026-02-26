# iaraa-ragflow

Pipeline de duas etapas para converter PDFs agrícolas brasileiros em Markdown otimizado para [RAGFlow](https://github.com/infiniflow/ragflow) (Retrieval-Augmented Generation).

## Documentos-alvo

- **Fichas Agroecológicas** — fichas técnicas do Ministério da Agricultura e Pecuária
- **Livros Técnicos** — livros completos em PDF convertidos para Markdown

## Arquitetura

```
PDF ──► conversao/ (DocMind)     ──► Markdown bruto + YAML
        Qwen-VL OCR + LLM            extração por página

    ──► processamento/           ──► Markdown otimizado para RAGFlow
        ficha_converter/              YAML frontmatter + headers ##/###
        book_converter/
```

### Etapa 1 — `conversao/` (DocMind)

Converte PDFs em Markdown + metadados YAML usando a API Qwen-VL (Alibaba).

**Pipeline:** split de PDFs grandes ➜ OCR (qwen-vl-plus) ➜ extração LLM (qwen-vl-max) ➜ merge de chunks ➜ pós-processamento ➜ relatório de qualidade.

**Características:**
- Janela de contexto de 3 páginas para referências cruzadas
- Balanceamento de múltiplas API keys com monitoramento de saúde
- Checkpoint/resume por página
- Processamento concorrente (30 PDFs simultâneos, 10 chamadas LLM por PDF)

**Critérios de qualidade:** taxa de inserção YAML ≥ 95%, confiança média ≥ 0.85, taxa de sucesso por página ≥ 95%.

### Etapa 2 — `processamento/`

Pós-processa o Markdown gerado pelo OCR para ficar pronto para o RAGFlow.

**Fichas Agroecológicas** (`ficha_converter/`) — pipeline regex de 6 fases:
1. Limpeza de artefatos OCR
2. Extração de metadados (título, autores, nº da ficha, resumo)
3. Geração de YAML frontmatter
4. Reestruturação com headers `##`/`###`, passos e bullets
4.5. Injeção de tabelas extraídas do YAML
5. Otimização RAGFlow (`join_paragraph_lines()`)

**Livros Técnicos** (`book_converter/`) — pipeline LLM de 6 fases:
1. Análise adaptativa via LLM (metadados, capítulos, seções a remover)
2. Remoção de seções (frontmatter, sumário, referências, figuras)
3. Limpeza de artefatos OCR (44+ padrões regex)
4. Inserção de headers `##` por busca de título + fallback ALL CAPS
5. Otimização RAGFlow (join linhas, bullets, espaçamento)
6. Montagem final com YAML frontmatter

## Uso

### Requisitos

```bash
# Python 3.10+
pip install dashscope pdf2image Pillow PyYAML PyPDF2 filelock psutil

# Dependência de sistema (para pdf2image)
sudo apt install poppler-utils   # Debian/Ubuntu
sudo dnf install poppler-utils   # Fedora
```

### Conversão de PDFs (Etapa 1)

```bash
cd conversao/

# Configurar API keys (uma por linha)
echo "sk-xxxx" > api/keys.txt

# Pipeline completo
./run.sh

# Verificar progresso
./run.sh --status

# Reprocessar páginas com falha
./run.sh --retry-failed

# Forçar reinício
./run.sh --restart
```

### Processamento de Fichas (Etapa 2)

```bash
cd processamento/

# Arquivo único
python -m ficha_converter "input.md" -o "output.md" -v

# Batch (diretório inteiro)
python -m ficha_converter "MD/MD systemRAG/" -o "MD/converted/" --batch -v

# Apenas limpeza OCR (Fase 1)
python -m ficha_converter "input.md" -o "output.md" --clean-only

# Preview sem gravar
python -m ficha_converter "input.md" -o "output.md" --dry-run -v

# Testar extração de metadados
python -m ficha_converter "MD/MD systemRAG/" --test-extract

# Testar geração de YAML
python -m ficha_converter "MD/MD systemRAG/" --test-yaml
```

### Processamento de Livros (Etapa 2)

Livros são processados via skill do [Claude Code](https://claude.ai/code):

```
/convert-book <input.md> [-o <output.md>] [-v]
```

## Formato de saída

Ambos os conversores produzem Markdown com:

**YAML frontmatter:**
```yaml
---
id: ficha_agroecologica_biofertilizante
titulo: Biofertilizante Vairo
autores: [C. D. Leite, A. L. Meira]
tags: [agroecologia, biofertilizante]
categoria: ficha_tecnica       # ou livro_tecnico
resumo: Técnica de produção...
---
```

**Corpo com headers Markdown:**
```markdown
# Título do Documento

> Autores: C. D. Leite e A. L. Meira

## Ingredientes

* Esterco bovino fresco (2 kg)
* Esterco de galinha (1 kg)

## Como Preparar

### 1º passo

Misturar os ingredientes...
```

## Integração com RAGFlow

O RAGFlow reconhece nativamente headers Markdown como delimitadores de chunk:

| Tipo de documento | Delimitador recomendado | Motivo |
|-------------------|------------------------|--------|
| Fichas | *(nenhum)* | Pequenas o suficiente para chunking automático por tokens |
| Livros | `## ` | Chunking por capítulo |

A função `join_paragraph_lines()` junta quebras de linha do OCR (largura da página do PDF) para evitar fragmentação de chunks.

## Estrutura do projeto

```
iaraa-ragflow/
├── conversao/                # Etapa 1: PDF → Markdown (DocMind)
│   ├── run.sh                # Orquestrador do pipeline
│   ├── requirements.txt
│   └── ...
├── processamento/            # Etapa 2: Markdown → RAGFlow
│   ├── ficha_converter/      # Fichas Agroecológicas (regex)
│   │   ├── cli.py            # CLI + orquestração
│   │   ├── config.py         # Padrões editáveis
│   │   ├── cleanup.py        # Limpeza OCR + otimização
│   │   ├── extraction.py     # Extração de metadados
│   │   ├── frontmatter.py    # Geração YAML
│   │   ├── restructure.py    # Reestruturação markdown
│   │   └── table_injector.py # Injeção de tabelas
│   └── .claude/skills/
│       └── convert-book/     # Livros Técnicos (LLM)
│           └── book_converter/
└── CLAUDE.md
```

## Configuração

### API keys (Etapa 1)

Prioridade: `api/keys.txt` > `.env` > variáveis de ambiente.

```bash
# Opção 1: arquivo de keys (recomendado)
echo "sk-xxxx" > conversao/api/keys.txt

# Opção 2: variável de ambiente
export DASHSCOPE_API_KEY="sk-xxxx"
```

### Padrões editáveis (Etapa 2)

O arquivo `processamento/ficha_converter/config.py` centraliza:
- `CLEANUP_PATTERNS` — regex para remoção de artefatos OCR
- `SECTION_PATTERNS` — padrões de seções (`##`)
- `SUBSECTION_PATTERNS` — padrões de subseções (`###`)
- `TAG_KEYWORDS` — palavras-chave para geração automática de tags
