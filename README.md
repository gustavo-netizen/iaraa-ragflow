# iaraa-ragflow

Pipeline de duas etapas para converter PDFs agrícolas brasileiros em Markdown otimizado para [RAGFlow](https://github.com/infiniflow/ragflow) (Retrieval-Augmented Generation).

## Documentos-alvo

- **Fichas Agroecológicas** — fichas técnicas do Ministério da Agricultura e Pecuária
- **Livros Técnicos** — livros completos em PDF convertidos para Markdown

## Arquitetura

```
PDF ──► conversao/ (DocMind)        ──► Markdown bruto + YAML
        Qwen-VL OCR + LLM               extração por página

    ──► processamento/              ──► Markdown otimizado para RAGFlow
        ficha_converter/  (regex)       YAML frontmatter + headers ##/###
        book_converter/   (LLM)
        shared/                         (helpers canônicos: generate_id, join_paragraph_lines, …)
```

### Etapa 1 — `conversao/` (DocMind)

Converte PDFs em Markdown + metadados YAML usando a API Qwen-VL (Alibaba).

**Pipeline (Steps 1–9):** split de PDFs grandes ➜ OCR (qwen-vl-plus) ➜ extração LLM (qwen-vl-max) ➜ retry de páginas com falha ➜ merge de chunks ➜ pós-processamento ➜ relatório de qualidade ➜ delivery check.

A orquestração é em Python (`conversao/orchestrator.py`, Fase G). `run.sh` é um wrapper fino que carrega API keys, sobe o monitor daemon e delega ao `python orchestrator.py run [...]`.

**Características:**
- Janela de contexto de 3 páginas para referências cruzadas
- Pool de múltiplas API keys com health-check (auto-disable após 5 falhas)
- Checkpoint/resume por página (`progress.json` + `filelock`)
- Processamento concorrente (30 PDFs simultâneos, 10 chamadas LLM por PDF)
- `AppConfig.from_env()` (Fase C) — modelo, retry, health e timeout via env vars

**Layout dos módulos** (pós-refactor Fases C–F):
- `conversao/orchestrator.py` — entry-point Python (`Pipeline.status()` / `Pipeline.run()`)
- `conversao/docmind/` — `retry.py`, `api_key_pool.py`, `qwen_client.py`, `page_processor.py`, `pipeline.py`, `document.py`
- `conversao/scripts/` — scripts de pipeline (split, merge, postprocess, retry, quality, delivery) + `scripts/admin/` para utilitários
- `conversao/validation/` — Checkers plugáveis (`StructureChecker`, `ContentSyntaxChecker`, `MarkdownChecker`, `QualityChecker`, `ElementChecker`, `MarcoChecker`) + `cost.py` + `report.py`

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
3. Limpeza de artefatos OCR
4. Inserção de headers `##` por busca de título + fallback ALL CAPS
4.5. (opcional, Fase J) Renderização de `## Notas` a partir do sidecar `<name>.footnotes.yaml`
5. Otimização RAGFlow (join linhas, bullets, espaçamento)
6. Montagem final com YAML frontmatter

O pacote `book_converter` é **LLM-agnóstico** (ADR-0002): nunca importa SDK de LLM — recebe `llm_response: str` do driver da skill `/convert-book`.

**Footnotes (Fase J / ADR-0004):** Stage 1 emite `<pdf_name>.footnotes.yaml` ao lado do `_all_figures.yaml`. Body MD pós-J.2 não contém mais blocos `**Footnotes:**`. `book_converter.convert_book_with_llm` aceita `footnotes_yaml_path` + `inline_notes: "none"|"useful"|"all"` (default `"none"` — body limpo). A heurística `is_substantive_footnote` (`<5` chars alfabéticos = ruído) mora em `processamento/shared/footnote_filter.py` e é reusada pelo cleanup de J.0 (livros legacy pré-J.2) e pelo render de J.3.

**Helpers canônicos** (`shared/`):
- `yaml_writer.py` — `generate_id()` (slug ASCII puro, transliteração via `ACCENT_MAP`), `transliterate()`, `format_authors_display()`, formatadores YAML
- `ragflow.py` — `join_paragraph_lines()`, `format_bullets()`, `optimize_for_ragflow()`
- `ocr_patterns.py` — `CLEANUP_PATTERNS` (superset usado por ambos os converters) + `remove_artifacts()`
- `footnote_filter.py` — `is_substantive_footnote`, `filter_footnote_items` (Fase J)

## Uso

### Requisitos

```bash
# Python 3.10+
pip install -r conversao/requirements.txt
pip install -r processamento/requirements.txt   # PyYAML

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

# Pular o gate de qualidade MARCO (Step 5.5) — entrega mesmo com PDFs abaixo do threshold
./run.sh --no-quality-gate

# Bypass do run.sh (útil para tooling/JSON status)
python orchestrator.py status [--json]
python orchestrator.py run [--restart] [--retry-failed] [--no-quality-gate] [-t TASK_NAME]
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

A skill é definida em `.claude/skills/convert-book/SKILL.md` (driver + prompt LLM); o pacote Python que ela invoca vive em `processamento/book_converter/` e é importado como `from processamento.book_converter import ...`.

### Testes

```bash
pytest tests/                                   # Suite completa (202 passed, 0 xfail)
pytest tests/test_snapshot.py                   # Goldens da Etapa 2 (ficha + livro)
UPDATE_GOLDENS=1 pytest tests/test_snapshot.py  # Re-baseline goldens (exige justificativa no commit)
```

## Formato de saída

Ambos os conversores produzem Markdown com:

**YAML frontmatter** (schema travado por ADR-0001):
```yaml
---
id: biofertilizante_vairo                # slug ASCII puro, sem prefixo de tipo
tipo: ficha_agroecologica                # vocabulário fechado: ficha_agroecologica | livro_tecnico
titulo: Biofertilizante Vairo
autores: [C. D. Leite, A. L. Meira]
tags: [agroecologia, biofertilizante]
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

## Decisões arquiteturais (ADRs)

Decisões travadas em `docs/adr/` — não reabrir sem novo ADR:

- **[ADR-0001](docs/adr/0001-id-schema-frontmatter.md)** — schema de `id` (slug ASCII puro, sem prefixo `tipo_`) + campo `tipo` como vocabulário fechado.
- **[ADR-0002](docs/adr/0002-book-converter-llm-agnostic.md)** — `book_converter` é LLM-agnóstico (recebe `str`, não importa SDK).
- **[ADR-0003](docs/adr/0003-progress-storage-json-filelock.md)** — storage de progresso permanece JSON + FileLock (não migra para SQLite).
- **[ADR-0004](docs/adr/0004-footnotes-sidecar-yaml.md)** — Footnotes em sidecar YAML (`<name>.footnotes.yaml`); body MD limpo; `inline_notes` flag controla render de `## Notas`.

## Estrutura do projeto

```
iaraa-ragflow/
├── CLAUDE.md                          # Guia para Claude Code (root)
├── PLANO_REFATORACAO.md               # Roadmap das Fases 0–J
├── README.md                          # Este arquivo
│
├── conversao/                         # Etapa 1: PDF → Markdown (DocMind)
│   ├── CLAUDE.md
│   ├── run.sh                         # Wrapper fino (env + monitor daemon)
│   ├── orchestrator.py                # Pipeline.status() / Pipeline.run()
│   ├── requirements.txt
│   ├── docmind/                       # Stage-1 core (Fase D)
│   │   ├── retry.py
│   │   ├── api_key_pool.py
│   │   ├── qwen_client.py
│   │   ├── page_processor.py
│   │   ├── pipeline.py
│   │   └── document.py
│   ├── scripts/                       # Steps 1–9 + admin
│   │   ├── config.py                  # AppConfig (Fase C)
│   │   ├── docmind_converter.py       # shim re-exporta docmind.*
│   │   └── admin/
│   ├── validation/                    # Checkers + cost + report (Fase F)
│   └── docs/                          # MARCO_QUALITY_SPECIFICATION + legacy
│
├── processamento/                     # Etapa 2: Markdown → RAGFlow
│   ├── CLAUDE.md
│   ├── CONTEXT.md                     # Vocabulário de domínio
│   ├── ficha_converter/               # Fichas Agroecológicas (regex)
│   ├── book_converter/                # Livros Técnicos (LLM-agnóstico)
│   └── shared/                        # generate_id, join_paragraph_lines, …
│
├── .claude/skills/
│   └── convert-book/                  # Skill driver — código real em processamento/book_converter/
│       └── SKILL.md
│
├── docs/
│   └── adr/                           # 0001, 0002, 0003
│
└── tests/                             # pytest (202 passed, 0 xfail)
    ├── fixtures/
    ├── golden/                        # Snapshots (ficha + livro)
    └── test_*.py
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

### Tuning via env vars (Etapa 1, Fase C)

```bash
DOCMIND_OCR_MODEL=qwen3-vl-plus-2025-12-19
DOCMIND_LLM_MODEL=qwen-vl-max-latest
DOCMIND_RETRY_MAX_ATTEMPTS=4
DOCMIND_RETRY_BASE_DELAY=1.0
DOCMIND_RETRY_JITTER=true
DOCMIND_HEALTH_DISABLE_AFTER=5
DOCMIND_HEALTH_DISABLE_DURATION=300
DOCMIND_REQUEST_TIMEOUT=120
```

### Padrões editáveis (Etapa 2)

- `processamento/ficha_converter/config.py` — apenas `SECTION_PATTERNS`, `SUBSECTION_PATTERNS`, `TAG_KEYWORDS` (específicos da ficha)
- `processamento/shared/ocr_patterns.py` — `CLEANUP_PATTERNS` e `ACCENT_MAP` (compartilhados entre ficha e livro)
