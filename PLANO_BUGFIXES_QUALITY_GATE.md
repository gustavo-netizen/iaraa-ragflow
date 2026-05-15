# Plano de Bugfixes — Quality Gate & Splitter (Stage 1)

**Branch:** `refactor/quality-gate`
**Data:** 2026-05-15
**Status:** ✅ Fases 1–5 concluídas (2026-05-15). Ver "Resultados" no fim do documento.
**Origem:** Investigação disparada por run real com 10 PDFs (`conversao/run_20260515_012050.log` em diante). 2 bugs reais + 1 enhancement validados por agentes contra a codebase. Plano elaborado por agente de planejamento.

---

## Contexto

A run completa de hoje (10 PDFs, 1 API key, ~104 min Stage 1) expôs três falhas latentes da arquitetura pós-Fase J:

1. **`Dissertação_Carvalho.pdf` foi descartado silenciosamente** no Step 1 (PDF malformado) sem qualquer alerta downstream — só descoberto inspecionando o relatório final.
2. **O KQI Quality Gate (Step 4.5) só validou os 3 PDFs diretos**, ignorando os 6 chunked (justamente os maiores e mais sujeitos a falhas). Em produção (H.1, ~96 books), o gate efetivamente nunca rodou.
3. Reparei o PDF rejeitado manualmente com `pikepdf` (libqpdf bindings) em segundos — sugere robustez parser-side em Python puro insuficiente.

A suite atual (`pytest tests/`, 202 passed, 0 xfail) **não cobre** nenhuma das três falhas. Os ADRs locked (0001–0004) não são tocados.

---

## Bug 1 — Splitter falha silenciosa em PDF malformado

### Diagnóstico

**Sintoma:** PDF que faz `pypdf.PdfReader(...)` lançar exceção (e.g. `Invalid Elementary Object`) é anotado em `split_mapping.json` com `status=error` e o pipeline segue como se nada tivesse acontecido. PDF sai da entrega final sem alarme.

**Causa raiz:** Três bugs combinados em `conversao/scripts/split_large_pdfs_smart.py`:

| # | Linha | Comportamento atual | Problema |
|---|---|---|---|
| a | 209–214 | `except Exception as e:` engole tudo, anota no `stats['pdfs'][name]`, segue loop | Sem propagação posterior |
| b | 230 | `progress_manager.set_step_status('split', 'completed')` **incondicional** | `progress.json` mente |
| c | 90, 251 | `main()` não tem `return`; `sys.exit(main())` exits **0** | rc=0 mesmo com erros |
| d | `orchestrator.py:355,387–391` | `rc \|= self._step1_split(opts)` mas rc=0 sempre | Sem curto-circuito |

**Bonus risk (chunk parcial):** `split_pdf()` (linhas 67–72) escreve `chunk_path` **antes** da exception eventualmente propagar dentro do mesmo PDF. Resultado: arquivo parcial em `input/split_pdfs/` que confunde reruns. Se o erro está no chunk 3 de 5, os chunks 1–2 sobrevivem como pseudo-válidos.

**Impacto:**
- Observado: 1/10 PDFs perdido sem alarme
- Produção (H.1 — 96 books, em sua maioria chunked): perda silenciosa não-detectada em qualquer PDF malformado
- Reruns: chunks parciais podem ser reusados como cache e perpetuar dados truncados

### Solução

**Mudanças em `scripts/split_large_pdfs_smart.py`:**

1. **`split_pdf()` (linhas 56–88):** escrever cada chunk em arquivo temporário `chunk_path.with_suffix(".pdf.tmp")` e usar `Path.rename` para o nome final só após `writer.write(f)` retornar. No `except` interno, limpar todos os `.tmp` antes de re-raise.
2. **`main()` loop (linha 209):** manter o `except Exception`, mas (a) logar em stderr estruturado (b) acumular contagem em novo `stats['error_pdfs']: int`.
3. **`main()` pós-loop (linha 230):** computar `had_errors = stats['error_pdfs'] > 0` e trocar `set_step_status('split', 'completed')` por `set_step_status('split', 'failed' if had_errors else 'completed')`.
4. **`main()` fim (~linha 248):** `return 1 if had_errors else 0`.

**Mudanças em `orchestrator.py`:**

5. **`_step1_split` (linhas 387–391):** após o subprocess, se `rc != 0`, retornar imediatamente sem chamar Steps 2-9 (não usar `rc |=`).
6. **Pre-Step-2 guard (novo):** ler `split_mapping_path` e abortar com mensagem clara se algum entry tem `status=='error'`. Defesa em profundidade contra rotas alternativas (manual edit do mapping, splitter rodado fora).

### Testes a adicionar

**`tests/test_split_large_pdfs.py` (novo):**
- `test_split_pdf_returns_nonzero_when_any_pdf_errors` — diretório com 1 válido + 1 com bytes corrompidos; exit=1; `stats['pdfs'][bad].status == 'error'`
- `test_split_step_status_set_to_failed_on_error` — `progress.json` recebe `steps.split.status == 'failed'`
- `test_split_pdf_does_not_leave_partial_chunks_on_failure` — mock `PdfWriter.write` para raise no chunk 2/3; nenhum `.tmp` ou parcial no destino

**`tests/test_orchestrator_run.py` (extensão):**
- `test_step1_failure_short_circuits_pipeline` — stub do subprocess Step 1 retornando rc=1; Steps 2–9 não chamados; `Pipeline.run()` retorna 1

### Risco de regressão

- O teste `test_orchestrator_run.py:303` (`assert cmd[1].endswith("split_large_pdfs_smart.py")`) só checa o command, não comportamento → não regride
- Mudança de semântica em `rc |=` (best-effort) → curto-circuito é decisão arquitetural; **registrar em ADR-0005** (ver Fase 4)
- 202 testes atuais não esperam rc=0 com erro de splitter → compatível

---

## Bug 2 — pikepdf como substituto de pypdf (enhancement)

### Diagnóstico

PyPDF2 (Python puro) é rígido com PDFs malformados. pikepdf (libqpdf C bindings) recupera silenciosamente. Hoje há **1 único call-site** no repo: `scripts/split_large_pdfs_smart.py:11`. `requirements.txt:11` declara `PyPDF2>=3.0.0` mas demais módulos (`docmind/document.py`, `merge_results_full.py`, `docmind/pipeline.py`) usam apenas `pdf2image` (poppler) — nada quebra se trocar.

**Decisão recomendada: substituição completa**, não fallback. Razões:
- Call-site único → diff trivial
- pikepdf é estritamente mais permissivo; não há comportamento de pypdf que pikepdf não cubra
- Higiene: reduzir para uma única dep de PDF
- Sistema já requer poppler (também C); libqpdf é peer

**Caminho alternativo (fallback)**: manter pypdf como primary, adicionar pikepdf no `except` (try pypdf → fallback pikepdf → marca error). Custo: dois call paths a manter. Aceitável se o time preferir conservadorismo.

### Solução

**Mudanças em `requirements.txt`:**
- Trocar `PyPDF2>=3.0.0` por `pikepdf>=8.0.0`

**Mudanças em `scripts/split_large_pdfs_smart.py`:**
- Linha 11: `from PyPDF2 import PdfReader, PdfWriter` → `import pikepdf`
- Reescrever `split_pdf()` (linhas 21–88) usando API pikepdf:
  - `reader = pikepdf.open(pdf_path)` + `len(reader.pages)`
  - Por chunk: `with pikepdf.Pdf.new() as writer: writer.pages.extend(reader.pages[start:end]); writer.save(chunk_path_tmp)`
- `main()` linha 166: `pikepdf.open(pdf_file)` para contagem; manter `try/except` largo (do Bug 1)

### Testes a adicionar

Reusa fixtures do Bug 1 em `tests/test_split_large_pdfs.py`:
- `test_split_pdf_handles_minor_corruption_via_pikepdf` — PDF com cross-ref truncada (gerável com pikepdf escrevendo mal de propósito); chunks gerados sem erro
- `test_split_pdf_still_errors_on_total_garbage` — arquivo `b"not a pdf"`; erro propagado e contado (regressão do Bug 1)

### Risco de regressão

- pikepdf requer libqpdf no sistema. Em CI sem libqpdf, `import pikepdf` quebra no `pytest collect`. Mitigação: `pytest.importorskip("pikepdf")` nos testes novos; doc em `README.md` ou nota no `requirements.txt`
- Output binário diferente entre `PdfWriter` e `pikepdf.save()` é aceitável (sem golden chunks) — validar no smoke teste

---

## Bug 3 — KQI gate (Step 4.5) cego nos PDFs chunked **[PRIORIDADE MÁXIMA]**

### Diagnóstico

**Sintoma:** Step 4.5 reporta apenas PDFs diretos. PDFs chunked nem aparecem (nem pass nem fail). Nenhum alerta.

**Causa raiz:**
- `orchestrator.py:527`: `self.output_dir.glob("*/*.validation.yaml")` só acha o que existe em `output/<pdf>/<pdf>.validation.yaml`
- `docmind/pipeline.py:555–564` emite `.validation.yaml` ao fim de cada chamada a `process_pdf_async`. PDFs diretos rodam isso uma vez em `output/<pdf>/`. **Chunks também rodam, mas em `output/chunks/<chunk>/`**
- `scripts/merge_results_full.py::merge_document` (linhas 28–169) escreve `merged_md_path`, `yaml_path` (figures), copia images, renumera YAMLs com `page_offset` — mas **NUNCA emite `<merged>.validation.yaml`** agregado

**Cadeia consequente:**
- `MarcoChecker._run_strict` (Step 8) lê os mesmos paths → também cego
- `--no-quality-gate` é teatro para chunked (já é noop)

**Impacto:**
- Observado: 6/9 PDFs entregues sem KQI check
- Produção H.1 (96 books): a maioria é chunked → gate efetivamente nunca rodou para nenhum
- Risco silencioso de qualidade em PDFs grandes, que são justamente os mais sujeitos a throttling/falhas

### Solução

**Mudanças em `scripts/merge_results_full.py::merge_document`** (após linha 149, antes do `return`):

1. Loop sobre cada `chunk`: ler `results_dir / chunk.name / f"{chunk.name}.validation.yaml"` se existir; acumular `page_statistics`, `kqi_metrics`, `failed_pages_detail`, `page_by_page_results` em listas locais; aplicar `page_offset` corrente aos `page` numbers de `failed_pages_detail` e `page_by_page_results`
2. Após loop, agregar:
   - `total_pages = sum(total_per_chunk)`, `successful_pages`, `failed_pages`, `success_rate = succ/total`
   - `yaml_insertion_rate` ponderado: `sum(yir_i * total_i) / sum(total_i)`
   - `average_confidence` ponderado pela mesma fórmula
   - `overall_quality_pass = (yir >= 0.95) and (avg_conf >= 0.85) and (psr >= 0.95)` (espelhar `docmind/pipeline.py:494–496`)
3. Escrever `document.output_dir / f"{document.original_name}.validation.yaml"` com **mesmo schema top-level** de `docmind/pipeline.py:481–553` (compat com `MarcoChecker` e `_step4_5_quality_gate`)
4. Se algum chunk não tem `.validation.yaml` (caso defensivo): emitir warning no log, **não** escrever o agregado (gate vai pegar via mismatch — passo 5)

**Mudanças em `orchestrator.py::_step4_5_quality_gate`** (após linha 527):

5. Comparar `len(validation_files)` com `_compute_expected_count(self.split_mapping_path)`. Se mismatch, abortar listando os PDFs sem `.validation.yaml`. Skip-friendly: se `expected is None` (sem mapping), preservar comportamento atual

**Opcional (limpeza):**
6. Refatorar agregação em função pura `aggregate_chunk_validations(chunks_data, page_offsets) -> dict` em `docmind/document.py` (mesmo módulo de `apply_page_offset`). Permite testar isolado sem fixtures de filesystem

### Testes a adicionar

**`tests/test_merge_validation_aggregation.py` (novo):**
- `test_merge_emits_aggregated_validation_yaml` — 2 chunks (3+2 páginas); `<merged>.validation.yaml` existe; `page_statistics.total_pages == 5`; `kqi_metrics.overall_quality_pass == True`
- `test_merge_aggregated_validation_applies_page_offset_to_failed_pages` — chunk 2 (offset=3) falha página 1; agregado tem `page=4`
- `test_merge_aggregated_validation_marks_failed_when_one_chunk_fails` — `psr_1=1.0`, `psr_2=0.5`; agregado tem `overall_quality_pass == False`
- `test_merge_skips_aggregation_when_chunk_validation_missing` — chunk sem `.validation.yaml`; merge retorna `success=True` com warning; agregado não emitido

**`tests/test_orchestrator_run.py` (extensão):**
- `test_quality_gate_aborts_when_validation_count_mismatch` — mapping espera 3, só 2 existem; rc != 0; Step 5 não chamado
- `test_quality_gate_reads_chunked_pdf_validation` — chunked com `<merged>.validation.yaml` com `overall_quality_pass=False`; gate aborta corretamente

### Risco de regressão

- `MarcoChecker._run_strict` consome o mesmo schema. **Agora vai avaliar PDFs chunked** (era cego). Pode acordar falhas previamente mascaradas — esse é o comportamento desejado, mas comunicar no commit message
- `test_orchestrator_run.py:201–205` e `test_validation_*` consomem `.validation.yaml` — manter top-level keys idênticos é mandatório
- Aggregation com chunks mistos (alguns com validation, outros sem) → decisão: emitir warning e **não** escrever agregado; gate detecta via mismatch (passo 5)

---

## Fases incrementais

Cada fase é um commit/PR independente. Cada fase precisa **`pytest tests/`** passando antes de commit.

### Fase 1 — Bug 3 (KQI gate aggregation) ✅ (2026-05-15, commit `a89a814`)

**Objetivo:** Pipeline emite `.validation.yaml` para PDFs chunked; gate detecta mismatch quando incompleto.

**Entregas:**
- [x] Helper `aggregate_chunk_validations(chunks_data, page_offsets)` em `docmind/document.py` (opcional mas recomendado)
- [x] `merge_results_full.py::merge_document` agrega + escreve `<merged>.validation.yaml`
- [x] `orchestrator._step4_5_quality_gate` valida `len(validation_files) == expected_count`
- [x] Suite nova `tests/test_merge_validation_aggregation.py` (4 testes acima — entregamos 8 incluindo unit puros da agregação)
- [x] 2 testes novos em `tests/test_orchestrator_run.py` (mismatch + chunked detection)
- [x] `pytest tests/` 100% passing (202 → 212, +10)

**Verificação manual:** rodar `python scripts/merge_results_full.py --mapping-file ... --results-dir output/chunks --output-dir output/` no checkout atual (já com chunks na disk de hoje); confirmar que `<merged>.validation.yaml` aparece com `overall_quality_pass=False` (porque rubric `medium`).

### Fase 2 — Bug 1 (splitter abort + tmp-write chunks) ✅ (2026-05-15, commit `4734023`)

**Objetivo:** Splitter falha cedo, ruidoso, e nunca deixa chunk parcial.

**Entregas:**
- [x] `split_pdf()` usa `*.pdf.tmp` + rename pattern
- [x] `main()` retorna rc=1 quando há erro; `set_step_status('split', 'failed')`
- [x] `orchestrator._step1_split` curto-circuita pipeline em rc != 0
- [x] Pre-Step-2 guard valida mapping (`_validate_split_mapping_or_abort`)
- [x] Suite nova `tests/test_split_large_pdfs.py` (3 testes + 1 baseline happy-path)
- [x] 2 testes novos em `tests/test_orchestrator_run.py` (curto-circuito + guard)
- [x] `pytest tests/` 100% passing (212 → 218, +6)

**Verificação manual:** rodar `./run.sh --restart` com `input/_broken_backups/Dissertação_Carvalho.pdf` (broken original) presente; confirmar Pipeline.run retorna 1 e progress.json tem `split=failed`.

### Fase 3 — Bug 2 (pikepdf migration) ✅ (2026-05-15, commit `9715b98`)

**Objetivo:** Splitter usa libqpdf via pikepdf; PDFs com headers fora de spec são processados sem intervenção manual.

**Entregas:**
- [x] `requirements.txt`: trocar `PyPDF2>=3.0.0` por `pikepdf>=8.0.0`
- [x] `split_large_pdfs_smart.py`: reescrita do `split_pdf()` com pikepdf API
- [x] 2 testes novos em `tests/test_split_large_pdfs.py` (corrupção menor + garbage total)
- [x] Nota em `conversao/CLAUDE.md` sobre dependência de libqpdf (seção "System Dependencies")
- [x] `pytest tests/` 100% passing (218 → 220, +2; PyPDF2 DeprecationWarning eliminado)

**Verificação manual:** rodar `./run.sh --restart` com `input/_broken_backups/Dissertação_Carvalho.pdf` (broken original) presente; **deve splitar normalmente sem fallback**.

### Fase 4 — Documentação & ADRs ✅ (2026-05-15, commit `cca8149`)

**Objetivo:** Decisões arquiteturais registradas; schema de mapping documentado.

**Entregas:**
- [x] **ADR-0005**: "Stage 1 splitter aborta pipeline quando qualquer PDF falha" — `docs/adr/0005-splitter-strict-mode.md`
- [x] **ADR-0006**: "Substituir PyPDF2 por pikepdf no splitter" — `docs/adr/0006-pikepdf-for-pdf-split.md`
- [x] Seção nova em `conversao/CLAUDE.md`: "Mapping Schema (`split_mapping.json`)" — `stats.pdfs` como ponto de verdade do pre-Step-2 guard (informativo + diagnóstico), `chunks[]/direct[]` canônicos para `Document.discover`. PDFs com `status='error'` só aparecem em `stats.pdfs`.
- [x] `PLANO_REFATORACAO.md` ganha Sprint 7 (post-J fixes) apontando para este plano

### Fase 5 — Smoke teste end-to-end ✅ (2026-05-15, 120m43s)

**Objetivo:** Validar comportamento integrado das 4 fases anteriores em pipeline real.

**Entregas:**
- [x] `./run.sh --restart` com os mesmos 10 PDFs + `_broken_backups/Dissertação_Carvalho.pdf` (original quebrado) — log: `conversao/logs/run_20260515_121204_task_20260515_121204.log`
- [x] Verificado:
  - ✅ Step 1 reabriu o PDF malformado via pikepdf (Bug 2) — 4 chunks gerados sem erro; `stats.error_pdfs == 0`
  - ✅ Step 4 emitiu `<merged>.validation.yaml` para todos os 7 PDFs chunked (Bug 3) — `find output -name "*.validation.yaml" -not -path "*/chunks/*"` retorna 10 arquivos (3 diretos + 7 chunked)
  - ✅ Step 4.5 reporta KQI para todos os 10 PDFs (não 3) — `❌ 10 de 10 PDFs falharam thresholds MARCO`
  - ⚠️ Gate falhou em `avg_confidence=0.60` em TODOS os 10 PDFs (issue sistêmico do rubric `medium`-only do Qwen-VL — **não regressão**, follow-up separado)
- [x] Nenhum behavior divergente — comportamento operacional do gate é exatamente o esperado pela arquitetura pós-Fase 1

**Diagnóstico KQI da smoke:**

| Métrica | Resultado | Status |
|---|---|---|
| YIR (yaml_insertion_rate) | 1.0000 em 10/10 | ✅ |
| PSR (page_success_rate) | 1.0 em 9/10 (Mariana_M_Alves: 0.9924 = 1/132 falhou) | ✅ |
| avg_confidence | **0.6000 exato em 10/10** | ⚠️ rubric medium-only |
| overall_quality_pass | False em 10/10 — gate funcionando corretamente | ✅ |

---

## Sequenciamento e dependências

```
Fase 1 (Bug 3) ─┬─► Fase 4 (Docs)
                │
Fase 2 (Bug 1) ─┤
                │
Fase 3 (Bug 2) ─┘
                └─► Fase 5 (Smoke)
```

- **Nenhuma fase técnica bloqueia outra** — as 3 podem ser PRs paralelos se múltiplas pessoas tocarem
- **Recomendado em série** para um único desenvolvedor (escolha mental simples, testes compartilham fixtures)
- **Fase 4** pode ir em paralelo às técnicas (basta saber a decisão tomada)
- **Fase 5** depende das 4 anteriores

---

## Issues sistêmicas fora do escopo deste plano

Identificadas durante a investigação mas **não tratadas aqui** — viram follow-up separado:

1. **Rubric `medium`-only do modelo** (Qwen-VL): todas as figuras vêm com `confidence: medium` (mapeia 0.60). Threshold KQI 0.85 é matematicamente inatingível com o prompt atual. Opções: ajustar threshold para 0.60, recalibrar rubric (mapping `medium→0.85`), ou refinar prompt do `qwen-vl-max` para emitir `high` quando aplicável. **Decisão de produto, não de bugfix.**
2. **H.1 chapter-title fix em produção** (mencionado no `CLAUDE.md` raiz): re-processing dos ~96 books continua sendo decisão de produto, mas agora com KQI gate funcional pós-Fase 1 a re-execução é segura.
3. **Schema de `split_mapping.json`** (H4 da investigação): só precisa doc na Fase 4, não é bug.

---

## Critérios de aceitação do plano

- [x] `pytest tests/` 100% passing após cada fase
- [x] Suite cresce de 202 para ~210+ testes (≈8 novos) — entregamos **+18** (220 testes)
- [x] Smoke `./run.sh --restart` em PDFs reais sem intervenção manual
- [x] `progress.json` reflete corretamente `failed` quando Step 1 falha (testes cobrem; smoke não disparou esse caminho porque pikepdf recuperou tudo)
- [x] Step 4.5 reporta KQI para 100% dos PDFs entregues (chunked e direct) — 10/10 no smoke
- [x] Nenhum ADR locked é violado (0001–0004); novos 0005 e 0006 acrescentados
- [x] Branch `refactor/quality-gate` mergeável em `main` após Fase 5

## Resultados

**Commits em `refactor/quality-gate`:**

| Commit | Fase | Suite |
|---|---|---|
| `a89a814` | Fase 1 — agrega validation.yaml em PDFs chunked | 202 → 212 |
| `4734023` | Fase 2 — splitter aborta em PDFs malformados | 212 → 218 |
| `9715b98` | Fase 3 — pikepdf substitui PyPDF2 | 218 → 220 |
| `cca8149` | Fase 4 — ADR-0005/0006 + mapping schema + plano-refator | 220 |

**Smoke da Fase 5 — 4 sinais validados:**

1. Step 1 splitou `Dissertação_Carvalho.pdf` (quebrado) via pikepdf — 4 chunks, sem erro
2. `stats.error_pdfs == 0` no `split_mapping.json`
3. 10 `.validation.yaml` em `output/<pdf>/` (3 diretos + 7 chunked merged)
4. Gate reportou `10 de 10 PDFs falharam thresholds MARCO` (antes via apenas 3)

## Follow-ups (fora deste plano)

1. **Rubric `medium`-only do Qwen-VL** (item 1 da seção "Issues sistêmicas"): após esta smoke ficou confirmado que **100% dos PDFs ficam em `avg_confidence=0.60`** independente do conteúdo. Threshold KQI 0.85 é matematicamente inatingível. Decisão de produto entre:
   - (a) reduzir `confidence_min` para 0.60 em `MarcoChecker` + `_step4_5_quality_gate`
   - (b) recalibrar mapping rubric (`medium → 0.85`) no parser de figuras
   - (c) refinar prompt do `qwen-vl-max` para emitir `high` quando aplicável
2. **H.1 chapter-title fix em produção** (re-processing dos ~96 books): agora seguro com KQI gate funcional, mas continua sendo decisão de produto.
