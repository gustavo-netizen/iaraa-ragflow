# CONTEXT.md — Vocabulário do domínio

Este documento fixa os termos do domínio usados em `processamento/`. Existe para que **um** termo refira-se a **um** conceito em código, comentários, prompts LLM, mensagens de log, e nomes de arquivo. Drift de vocabulário é o primeiro sintoma de drift arquitetural.

Quando um termo novo aparecer no código, registre aqui. Quando um termo aqui mudar de significado, atualize aqui antes de mudar o código.

## Documentos de entrada

### Ficha Agroecológica
Folheto técnico curto (1-4 páginas) publicado pelo Ministério da Agricultura brasileiro com receitas/práticas agroecológicas concretas (ex: biofertilizante, compostagem, manejo). Estrutura padronizada: título em CAIXA ALTA, autores no formato `SOBRENOME, I. I.`, número de ficha, resumo, seções nomeadas, referências bibliográficas. Processada por `ficha_converter/` via pipeline regex.

**Não confundir com:** "ficha catalográfica" (página de copyright de um livro).

### Livro Técnico
PDF de livro inteiro (dezenas a centenas de páginas) sobre temas agroecológicos. Estrutura variável: capa, ficha catalográfica, prefácio, capítulos com subseções, referências, índice remissivo. Processado por `book_converter/` via pipeline LLM (skill `/convert-book`).

**Não confundir com:** capítulo individual extraído de um livro (não é um caso de uso suportado hoje).

## Estágios e artefatos

### Stage 1 — DocMind / Marco Converter
Etapa de OCR + extração estruturada que transforma PDF em Markdown bruto + YAML de metadados. Roda em `conversao/` orquestrado por `run.sh`. Usa Qwen-VL (`qwen3-vl-plus` para OCR, `qwen-vl-max` para extração).

Sinônimos no código: "DocMind" (nome interno do tooling), "Marco Converter" (referência ao formato de YAML de metadados — *não* à etapa). Quando falar da etapa, prefira **Stage 1** ou **DocMind**.

### Stage 2 — Processamento RAGFlow
Etapa que pega a saída do Stage 1 e a otimiza para ingestão no RAGFlow. Vive em `processamento/`. Dois conversores, um por tipo de documento:
- `ficha_converter/` (regex, 6 fases)
- `book_converter/` (LLM, 6 fases — em B.1 será movido de `.claude/skills/convert-book/` para `processamento/book_converter/`)

### Página
Unidade atômica do Stage 1: uma página do PDF original. O DocMind processa cada página com janela de contexto de 3 páginas (anterior + atual + próxima) para resolver referências cruzadas.

### Chunk (sentido 1) — fatia de PDF
PDFs grandes são quebrados em "chunks" (10-20 páginas) antes do OCR para caber no contexto do LLM. Mapping em `split_mapping.json`. **Não é** o chunk do RAGFlow.

### Chunk (sentido 2) — chunk do RAGFlow
Bloco indexável que o RAGFlow gera a partir do Markdown final. Delimitado por headers `##` / `###` (configurável). É o que volta numa busca semântica.

**Convenção:** ao escrever código novo, prefira `pdf_chunk` para sentido 1 e `rag_chunk` para sentido 2 quando o contexto não desambiguar. No código atual, `chunk` quase sempre = sentido 1.

### Frontmatter
Bloco YAML delimitado por `---` no topo do Markdown final, com metadados estruturados (`id`, `tipo`, `titulo`, `autores`, `ano`, `tags`, `resumo`). Reconhecido por RAGFlow como contexto do documento.

Schema canônico do `id` definido em [ADR-0001](../docs/adr/0001-id-schema-frontmatter.md). Campo `tipo` ∈ `{ficha_agroecologica, livro_tecnico}`.

### Footnote (sidecar)
Arquivo `<name>.footnotes.yaml` emitido pelo Stage 1 ao lado do `<name>.md` e do `<name>_all_figures.yaml`. A partir de J.2, footnotes deixam de ser inlinadas no body MD e passam a viver aqui. Schema canônico travado por [ADR-0004](../docs/adr/0004-footnotes-sidecar-yaml.md):

```yaml
version: "1.0"
pdf_name: Darnton.cultura.civilidade
total_pages: 10
notes:
  - {page: 3, id: 1, text: "³⁵"}
  - {page: 8, id: 1, text: "*Tournois refere-se à livre tournois..."}
```

Lista flat (espelha `_all_figures.yaml:figures`); emissão incondicional (`notes: []` quando vazio); marker `*Footnotes: sidecar*` no metadata header do MD como signal redundante.

**Não confundir com:** *callout markers* — os superscritos `³⁵`, `¹` que aparecem inline no body são glifos tipográficos extraídos pelo OCR, não markers Markdown `[^N]`. Permanecem no body para casamento visual com `text` dos items do sidecar.

### Document (Stage 1)
Conceito introduzido na Fase E do refator: representa **um PDF** do Stage 1 com seus chunks (sentido 1), pages, YAML de metadados e estado de progresso. Tipo Python a ser criado em `conversao/docmind/document.py`.

**Não é** uma hierarquia polimórfica `Document/Ficha/Book` — descartado por [ADR-0002](../docs/adr/0002-book-converter-llm-agnostic.md) (raciocínio análogo: o boundary natural está antes do polimorfismo). Ficha e Livro mantêm dataclasses paralelos no Stage 2 (`FichaMetadata`, `BookMetadata`).

## Operações canônicas

### `generate_id`
Gera `id` ASCII slug a partir do nome de arquivo. **Uma única implementação** em `processamento/shared/yaml_writer.py` (após Fase B). Translitera acentos via `ACCENT_MAP` (`café → cafe`). Spec em [ADR-0001](../docs/adr/0001-id-schema-frontmatter.md).

### `join_paragraph_lines`
Une linhas que são continuação de parágrafo OCR (começam com minúscula, `(` ou `[`). Preserva headers, listas, blank lines, linhas que começam com maiúscula. Implementação canônica em `processamento/shared/ragflow.py` (após Fase B).

### `format_authors_display`
Formata lista de autores no padrão `SOBRENOME, I. I.` para exibição. Mesmo formato em ficha e livro.

### `remove_artifacts`
Remove metadados de OCR / processamento que vazam para o Markdown (carimbos do DocMind, headers de página repetidos, descrições de figuras tipo `**Type:**...*Confidence:*`). Padrões em `processamento/shared/ocr_patterns.py:CLEANUP_PATTERNS` (após Fase B).

## Convenções de nomenclatura

- **Tipo de documento** (campo `tipo`): vocabulário fechado — `ficha_agroecologica`, `livro_tecnico`. Não inventar variantes.
- **Português vs inglês:** termos do domínio (ficha, livro, página, capítulo) ficam em **português** no código quando voltados a usuário (CLI, logs em PT, frontmatter). Termos técnicos genéricos (chunk, retry, lock, pipeline) ficam em **inglês**. Não misturar dentro do mesmo identificador (`chunk_pagina` é ruim; `pdf_chunk` ou `rag_chunk` ou `pagina` são bons).
- **Snake case** para Python; **kebab case** para nomes de arquivo Markdown originais; **snake_case** após `generate_id` (slug de ID).

## Decisões registradas

- [ADR-0001](../docs/adr/0001-id-schema-frontmatter.md) — Schema do campo `id` e introdução do campo `tipo`.
- [ADR-0002](../docs/adr/0002-book-converter-llm-agnostic.md) — `book_converter` não importa SDK de LLM.
- [ADR-0003](../docs/adr/0003-progress-storage-json-filelock.md) — Progress permanece JSON+FileLock.
- [ADR-0004](../docs/adr/0004-footnotes-sidecar-yaml.md) — Footnotes em sidecar YAML (`<name>.footnotes.yaml`).
