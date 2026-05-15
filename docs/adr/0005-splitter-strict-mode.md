# ADR-0005 — Splitter aborta o pipeline quando qualquer PDF falha

**Status:** Accepted
**Data:** 2026-05-15
**Decisores:** gustavo@the-syllabus.com

## Contexto

Stage 1 começa em `conversao/scripts/split_large_pdfs_smart.py`, que itera os PDFs em `input/`, divide os grandes em chunks e escreve `split_mapping.json` para os Steps 2–4 consumirem. Até esta decisão, o splitter era **best-effort**: qualquer PDF que falhasse no parse era anotado em `stats.pdfs[name].status = 'error'`, o loop seguia, e o script retornava rc=0. `progress_manager.set_step_status('split', 'completed')` era chamado **incondicionalmente** na linha 230.

No run de 2026-05-15 (10 PDFs, 1 API key, ~104 min de Stage 1), `Dissertação_Carvalho.pdf` faltou de pereiro lançar `Invalid Elementary Object` em `PyPDF2.PdfReader`. O splitter engoliu a exceção, o orchestrator continuou — `Pipeline.run()` usa `rc |= self._step1_split(opts)` (rc=0 do splitter) — e o pipeline marcou `progress.json` como completed. O PDF perdido só foi descoberto inspecionando manualmente o relatório final. Nenhum alarme, nenhum gate, nenhum log de erro estruturado em uma fase visível.

Quatro componentes contribuíram:

| # | Local | Comportamento |
|---|---|---|
| a | `split_large_pdfs_smart.py:209-214` | `except Exception` engole tudo, anota stats, segue loop |
| b | `split_large_pdfs_smart.py:230` | `set_step_status('split', 'completed')` **incondicional** |
| c | `split_large_pdfs_smart.py:90,251` | `main()` sem `return`; `sys.exit(main())` exits **0** |
| d | `orchestrator.py:355` | `rc \|= self._step1_split(opts)` — bitwise OR sem curto-circuito |

A consequência operacional é grave em produção: a maioria dos livros é grande o suficiente para precisar de split. Um PDF malformado entre eles desapareceria silenciosamente até alguém auditar manualmente a entrega.

A política inversa — **abortar cedo em qualquer erro** — força o operador a reparar (com `pikepdf`, ver ADR-0006) ou remover o arquivo antes de reentregar API keys e horas de processamento.

## Decisão

**Stage 1 trata qualquer PDF que falhe no parse como erro de pipeline. O splitter retorna `rc=1`, o orchestrator curto-circuita antes do Step 2, e `progress.json` permanece `in_progress`.**

### Implementação

1. **`split_large_pdfs_smart.py::main()`** acumula `stats['error_pdfs']`, escreve no log estruturado em stderr, troca `set_step_status('split', 'completed')` por `'failed' if had_errors else 'completed'`, e retorna `1 if had_errors else 0`.

2. **`split_pdf()`** escreve cada chunk em `<chunk>.pdf.tmp` e usa `Path.replace` para renomear só após `Pdf.save()` retornar. No `except` interno, faz `unlink` de todos os `.tmp` antes de re-raise. Reruns nunca reusam chunks parciais como cache.

3. **`orchestrator.Pipeline.run()`** substitui `rc |= self._step1_split(opts)` por curto-circuito explícito: se `step1_rc != 0`, abortar antes do Step 2. Nenhum step downstream roda; `_print_summary` ainda é chamado para preservar relato.

4. **Pre-Step-2 guard** (`_validate_split_mapping_or_abort`) abre `split_mapping.json` e aborta se algum entry em `stats.pdfs` tem `status == 'error'`, mesmo se o splitter retornou rc=0. Defesa em profundidade contra rotas alternativas: mapping editado manualmente, splitter rodado fora desta sessão, ou versões antigas do script.

5. **`split_mapping.json::stats.pdfs`** torna-se **informativo + ponto de verdade do guard**: o orchestrator lê esse dicionário para detectar erros, mesmo que `chunks[]` e `direct[]` (consumidos por `Document.discover`) já tenham sido construídos. Ver seção "Mapping Schema" em `conversao/CLAUDE.md`.

## Consequências

**Positivas**
- Operador descobre PDFs problemáticos em segundos, não em horas de OCR desperdiçadas.
- `progress.json` deixa de mentir: `split=failed` é estado terminal que invalida reruns parciais.
- Chunks parciais (tmp+rename) não corrompem reruns.
- KQI gate (Step 5.5, ADR implícita) deixa de ter PDFs "fantasmas" passando despercebidos pelo flow downstream.

**Negativas / custos**
- **1 PDF problemático no lote inteiro bloqueia o pipeline.** Era best-effort; agora é all-or-nothing. Operador precisa intervir manualmente: remover o arquivo, ou repará-lo (pikepdf cobre boa parte dos casos via ADR-0006), antes de rodar novamente.
- **Sem flag `--allow-partial`** no escopo desta ADR. Se aparecer um caso de uso legítimo (smoke run, exploração), abre-se ADR sucessora; até lá, manter pressão por strict.

**Plano de migração**
- Mudança aplicada em commit único na branch `refactor/quality-gate` (Fase 2 do `PLANO_BUGFIXES_QUALITY_GATE.md`).
- Suite ganhou `tests/test_split_large_pdfs.py` (4 testes) + 2 testes em `tests/test_orchestrator_run.py` cobrindo curto-circuito e guard.
- Smoke real (`./run.sh --restart` com o lote de hoje + `Dissertação_Carvalho.pdf` quebrado) é Fase 5 do mesmo plano.

## Decisões descartadas

- **Manter best-effort + adicionar warning no relatório final:** o relatório final só aparece após ~horas de OCR. Não resolve o problema operacional.
- **Flag `--strict` opt-in (default best-effort):** preserva o sintoma. O sintoma é a default; quem precisar de partial pede explicitamente.
- **Detectar via gate downstream apenas:** o gate KQI da Fase 1 já agrega chunked PDFs (ver `PLANO_BUGFIXES_QUALITY_GATE.md`), mas só vê o que chegou à validação. Splitter falho não produz nada para o gate ver.
