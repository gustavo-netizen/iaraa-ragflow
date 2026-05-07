# ADR-0004 — Footnotes em sidecar YAML separado

**Status:** Accepted
**Data:** 2026-05-07
**Decisores:** gustavo@the-syllabus.com

## Contexto

Stage 1 (DocMind, `conversao/docmind/pipeline.py:376-382`) emite footnotes inline no body Markdown como bloco:

```
---

**Footnotes:**

[^1]: <texto>
[^2]: <texto>
```

Stage 2 limpa **mal** por dois bugs combinados em `processamento/shared/ocr_patterns.py` (resolvidos em J.0):

1. **Pattern-ordering** — o separador genérico (`^---\s*\n(?=\s*\n)`, linha 37) come o `---` antes do pattern do label rodar, deixando `**Footnotes:**` órfão no body.
2. **Filtro indiscriminado** — o pattern `^\[\^\d+\]:.*\n` deletava TODOS os items, perdendo translator notes / definições / DOIs.

J.0 corrigiu o legado. Resta a pergunta arquitetural: **onde devem morar os footnotes para novos PDFs processados?**

Estado atual: 4 livros de smoke (`conversao/ragflow-ready/`) + ~96 livros legacy em produção. **Não vamos reprocessar** os 96 — J.0 cobre. Forward, queremos:

- Body MD sem nenhum ruído de footnote (label + items).
- Footnotes preservados em formato estruturado, paralelo ao `_all_figures.yaml` que já existe.
- Consumer (book_converter) decide se renderiza `## Notas` no MD final.

A separação espelha um padrão arquitetural já estabelecido: Stage 1 escreve `<name>_all_figures.yaml` ao lado do `<name>.md` (`pipeline.py:408-427`), e o `ficha_converter` consome via `table_injector.py` na Phase 4.5. Footnotes ganham o mesmo tratamento.

## Decisão

**Stage 1 deixa de inlinar footnotes no body MD e passa a emitir um sidecar `<name>.footnotes.yaml`.**

### Schema canônico

```yaml
version: "1.0"
pdf_name: Darnton.cultura.civilidade
total_pages: 10
notes:
  - {page: 3, id: 1, text: "³⁵"}
  - {page: 6, id: 1, text: "³⁵"}
  - {page: 8, id: 1, text: "*Tournois refere-se à livre tournois..."}
```

### Pontos travados

1. **Lista flat** (`notes: [{page, id, text}]`), não dict page-keyed. Espelha `_all_figures.yaml:figures` (também flat). Preserva ordem de inserção; YAML loaders agnósticos; `is_substantive_footnote(text)` pode varrer linearmente.

2. **Emissão incondicional.** PDF sem footnotes ainda emite o sidecar com `notes: []`. A existência do arquivo torna-se signal não-ambíguo "doc passou por Stage 1 pós-J.2" — necessário para distinguir doc novo (sem footnotes legítimos) de doc legado (footnotes inlinados, sem sidecar).

3. **Marker redundante no body.** `pipeline.py` ganha uma linha `*Footnotes: sidecar*` no metadata header (~linha 400), análoga aos `*Statistics:*` e `*Model:*` já existentes. Funciona como signal duplicado caso o `.md` se separe do `.yaml` em algum ponto da entrega.

4. **Callout markers OCR são glifos, não markdown.** Os superscritos `³⁵`, `¹` que aparecem inline no body são *glifos tipográficos* extraídos pelo OCR — não são `[^N]` markers Markdown. J.2 não toca neles; permanecem como hoje, casados visualmente com os items do sidecar pelo `text` do `id` correspondente.

5. **`book_converter` ganha flag `inline_notes`** (na Fase J.3) com três modos: `"none"` (default — body limpo, sidecar fica para outras integrações), `"useful"` (renderiza apenas notes que passam `is_substantive_footnote`), `"all"` (renderiza tudo). Schema do sidecar não muda entre modos.

## Consequências

**Positivas**
- Body MD do livro pós-J.2 fica 100% livre de ruído de footnote — bom para o chunking do RAGFlow.
- Notas substantivas viram dado estruturado em vez de string mal-tipada no meio do texto. Re-render configurável via `inline_notes`; reuso futuro (ex: índice de notas, exportação separada) sem reparsing.
- Padrão arquitetural consistente com `_all_figures.yaml`: Stage 1 emite sidecars, Stage 2 consome opcionalmente. Operadores reconhecem a forma.
- Filtragem heurística (`processamento/shared/footnote_filter.py`, criado em J.0) é a mesma fonte para legado (J.0) e novo (J.3) — uma só implementação.

**Negativas / custos**
- Mais um arquivo por PDF entregue (`<name>.footnotes.yaml`). O orchestrator já copia `*_all_figures.yaml` em `_step5_final_delivery_copy`; J.4 adiciona análoga linha. Custo desprezível.
- Stage 1 não tem snapshot test estabelecido; J.2 toca `pipeline.py:250-427`. Mitigado por testes-unidade focados (`tests/test_pipeline_footnotes_sidecar.py`) + smoke `./run.sh --restart` em PDF pequeno antes do commit.
- Livros legacy continuam sem sidecar; consumer precisa lidar com `footnotes_yaml_path=None` (path inexistente). J.3 cobre via early return + fallback no cleanup de J.0.

**Critério para reabrir esta decisão**
- Caso de uso aparecer onde footnotes precisam de schema mais rico (ex: tipo de nota, autor da nota, link bidirecional para callout) — registrar ADR-0005 evoluindo o schema, não revertendo o sidecar.
- Volume de footnotes por documento crescer a ponto do parsing virar gargalo (improvável dado o tamanho dos livros atuais).

## Decisões descartadas

- **Manter inline `[^N]:` no body** com filtragem heurística inline. Não resolve o ruído estrutural — RAGFlow ainda chunkificaria notas junto com texto principal. Perde a chance de tornar dado estruturado.
- **Schema page-keyed** (`notes: {3: [...], 6: [...]}`). Perde ordem de inserção, dificulta iteração linear, diverge de `_all_figures.yaml`. Sem ganho concreto.
- **Sidecar condicional** (só emitir se houver footnotes). Cria ambiguidade: doc sem sidecar pode ser pós-J.2-sem-footnotes ou pré-J.2-legacy. Custo de emitir lista vazia é zero.
- **Inline `## Notas` por padrão**. Perde controle do consumer; força decisão de UX no Stage 1. `inline_notes="none"` default deixa explícito que a flag existe.
