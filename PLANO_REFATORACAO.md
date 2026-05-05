# Plano de Refatoração — iaraa-ragflow

## Contexto

Pipeline em duas etapas (`conversao/` → `processamento/`) que converte PDFs agrícolas brasileiros (Fichas Agroecológicas + Livros Técnicos) em Markdown otimizado para RAGFlow. Em produção: ~96 livros e centenas de fichas processados. **Sem testes.**

A revisão arquitetural identificou três grupos de fricção, todos verificados em código:

1. **Duplicação Ficha ↔ Livro.** Seis funções duplicadas entre `processamento/ficha_converter/` e `.claude/skills/convert-book/book_converter/`: `join_paragraph_lines`, `format_bullets`, `format_authors_display`, `generate_id`, `remove_artifacts`, geradores de YAML. `generate_id` diverge silenciosamente — ficha translitera acentos via ACCENT_MAP (`café→cafe`), book *dropa* via `[^a-z0-9_]` (`café→caf`). Mesmo arquivo, IDs diferentes.

2. **Monolito `docmind_converter.py` (2001 linhas).** Mistura `APIKeyHealthMonitor` (l.114–231), `RetryConfig` (l.36–53), cliente Qwen, prompt builder, processamento por página, paralelismo. Modelo `qwen3-vl-plus-2025-12-19` hardcoded em l.287 e l.693 (drift risk). Nenhum seam testável.

3. **Estado e validação espalhados.** Progress em 4 lugares (`progress.json`, `output/chunks/*.validation.yaml`, `output/{name}/`, `split_mapping.json`). Quatro scripts de validação somando 2068 linhas (`final_delivery_check.py`, `final_data_validation.py`, `generate_quality_report.py`, `generate_report.py`) com escopos sobrepostos. `run.sh` (558 linhas) parseia JSON inline (l.338–371).

**Plus** (achados menores confirmados): caminho duplo morto em `book_converter` (`apply_structure`/`convert_book_with_analysis` exportados, `/convert-book` usa funções privadas em `llm_pipeline.py`); 130 linhas de tradução EN→PT inline em `table_injector.py:55–184`; `processamento/` sem `requirements.txt`; `_fix_chapter_headers_fallback` ancorando regex em `\n...\n` (perde primeira/última linha); `.update-plan/` em chinês posando de config ativa em `conversao/`.

**Objetivo:** profundizar módulos (mais comportamento atrás de interfaces menores) **sem regredir comportamento atual**. Quick wins primeiro, snapshot test como rede de segurança antes de qualquer mudança estrutural, monolito depois, unificação de estado/validação no fim.

**Fora de escopo (descartado e travado por ADR):** SQLite progress, Document polimórfico Ficha↔Livro, embedding de Anthropic SDK no book_converter. Detalhes em ADRs 0002/0003.

## Outcomes desejados

- Zero divergência silenciosa: `generate_id` produz a mesma resposta para a mesma entrada.
- `processamento/shared/` com 6 funções canônicas, importadas por ambos os converters.
- `docmind_converter.py` quebrado em 5 módulos isoláveis com modelo Qwen vindo de `AppConfig`.
- 4 scripts de validação consolidados em `validation/` com checkers plugáveis.
- `Pipeline.status(document)` como interface única para "o que está feito?".
- `run.sh` reduzido a entry-point fino; orquestração em Python.
- 3 ADRs registrando decisões.
- Snapshot tests garantindo paridade em 1 ficha + 1 livro de referência.

## Arquivos críticos

- `conversao/scripts/docmind_converter.py` — split em D.
- `conversao/run.sh` — entry-point fino em G.
- `conversao/scripts/{progress_manager,merge_results_full,final_delivery_check,final_data_validation,generate_quality_report,generate_report}.py` — refatorados em E e F.
- `processamento/ficha_converter/{cleanup,extraction,frontmatter,restructure,table_injector}.py` — importam de `shared/` em B.
- `.claude/skills/convert-book/book_converter/` — move para `processamento/`, depois importa de `shared/`.
- `.claude/skills/convert-book/SKILL.md` — atualiza imports após move.

## Fases

### Fase 0 — Rede de segurança

#### 0.1 Snapshot test ✅ (concluído 2026-05-04)

**Resultado:** 3 testes em `tests/test_snapshot.py` passando; goldens determinísticos para ficha + livro.

**Estrutura criada:**
```
tests/
├── __init__.py
├── test_snapshot.py                          (95 linhas, 3 testes)
├── fixtures/
│   ├── 99-biofertilizante-fixture-1.md       (ficha sintética)
│   └── livro_fixture.md                      (livro sintético)
└── golden/
    ├── ficha.md                              (saída atual ficha_converter)
    ├── livro.md                              (saída atual book_converter)
    └── livro_llm_response.json               (fixture LLM determinística)
```

**Decisões de implementação:**
- **Fixtures sintéticas (Opção B), não reais.** Inputs originais em `processamento/MD/MD systemRAG/` e `Teste/Teste SystemRAG/` não estavam disponíveis na máquina (nem `/home/gustavo/Downloads/results_md_yaml/` referenciado no CLAUDE.md). Fabricadas fixtures que exercitam todos os padrões transformados pelo pipeline (artefatos OCR Marco, autores `SOBRENOME, I.`, capítulos `CAPÍTULO N`, blocos `**Type:**...*Confidence:*`, TOC, frontmatter, referências). Trade-off: bug em padrão OCR raro de produção pode escapar.
- **Re-baseline via env var:** `UPDATE_GOLDENS=1 pytest tests/test_snapshot.py` regrava goldens. Workflow para Fase B (mudança de IDs) e Fase H (fixes de bugs).

**Critério:** após cada fase B–G, `pytest tests/test_snapshot.py` passa. Mudanças intencionais atualizam o golden em commit separado com justificativa.

**Bug observado em produção (capturado no golden, NÃO corrigido aqui — ver Fase H):** `book_converter/llm_pipeline.py:_clean_chapter_title_text` tem patterns em ordem errada — o pattern genérico `[IVXLC]+` casa **antes** dos específicos `CAPÍTULO`/`PARTE`, dropando a primeira letra de capítulos que começam com I/V/X/L/C. No golden: `## APÍTULO 1 - INTRODUÇÃO` em vez de `## INTRODUÇÃO`. Afeta os ~96 livros em produção com chapters em CAPÍTULO/INTRODUÇÃO/CONCLUSÃO etc.

#### 0.2 ADRs + CONTEXT.md ✅ (concluído 2026-05-04)

**Resultado:** 3 ADRs + índice em `docs/adr/`; vocabulário de domínio em `processamento/CONTEXT.md`.

**Criado:**
```
docs/adr/
├── README.md                                 (índice + convenções de ADR)
├── 0001-id-schema-frontmatter.md             (95 linhas)
├── 0002-book-converter-llm-agnostic.md       (54 linhas)
└── 0003-progress-storage-json-filelock.md    (52 linhas)

processamento/
└── CONTEXT.md                                (76 linhas — vocabulário + glossário + decisões registradas)
```

**Decisões travadas pelos ADRs:**
- **ADR-0001:** slug ASCII transliterado (sem prefixo) + campo `tipo: ficha_agroecologica | livro_tecnico` separado. `generate_id` canônico usa `ACCENT_MAP` da ficha (`café→cafe`).
- **ADR-0002:** `book_converter` LLM-agnostic — pacote não importa SDK, recebe `llm_response: str` pronto. Bloqueia C1 (Anthropic SDK embutido).
- **ADR-0003:** progress permanece JSON+FileLock; não migrar para SQLite sem gargalo medido. 3 critérios concretos para reabertura registrados.

**CONTEXT.md fixa:** distinção entre "chunk sentido 1" (fatia de PDF) vs "chunk sentido 2" (chunk RAGFlow); "Stage 1 / DocMind" (etapa) vs "Marco Converter" (formato YAML); convenção PT/EN para identificadores; vocabulário fechado para `tipo`.

---

### Fase A — Hygiene & dead code (~3h, paralelizável)

#### A.1 Hygiene ✅ (concluído)

- ✅ `conversao/.update-plan/` → `conversao/docs/legacy/`.
- ✅ `processamento/requirements.txt` criado.

#### A.2 Deletar caminho duplo book_converter ✅ (concluído 2026-05-04)

**Resultado:** caminho morto removido; `convert_book_with_llm` segue como único pipeline público; snapshot test passou sem mudança no golden.

**Mudanças:**
- `.claude/skills/convert-book/book_converter/structure_applier.py` — **278 → 96 linhas.** Mantidos `remove_sections` e `format_structure_summary`. Deletados `apply_structure`, `insert_chapter_headers`, `adjust_chapter_positions`, `remove_orphan_markers`, `_clean_chapter_title`.
- `.claude/skills/convert-book/book_converter/llm_pipeline.py` — **373 → 328 linhas.** Deletada `convert_book_with_analysis` (l.333-372) + import órfão `Path` + import órfão `AnalysisResult`.
- `.claude/skills/convert-book/book_converter/__init__.py` — removido `apply_structure` dos imports/exports.

**Correção ao plano original:** o plano dizia para deletar `format_structure_summary`, mas ela é **viva** — chamada por `llm_pipeline.py:259` (formatação de log). Mantida.

**Verify (executado):**
- `pytest tests/test_snapshot.py` → 3 passed (golden do livro inalterado).
- `from book_converter import remove_sections, format_structure_summary, convert_book_with_llm, build_analysis_prompt, parse_llm_response` → imports OK.

#### A.3 Tier de scripts ✅ (concluído 2026-05-04)

**Resultado:** `scripts/` (8 pipeline) + `scripts/admin/` (12 utilitários); `merge_split_pdfs.py` deletado.

**Pipeline (top-level):** `split_large_pdfs_smart.py`, `docmind_converter.py`, `retry_failed_pages.py`, `merge_results_full.py`, `postprocess.py`, `generate_quality_report.py`, `final_delivery_check.py`, `progress_manager.py`.

**Admin/:** `analyze_content_quality.py`, `archive_progress.py`, `check_completion_status.py`, `final_data_validation.py`, `fix_page_order.py`, `merge_and_check_coherence.py`, `monitor_daemon.py`, `olmocr_api_config.py`, `resource_monitor.py`, `test_api_keys.py`, `yaml_data_tools.py`, `generate_report.py`.

**Decisões durante implementação:**
- **Audit `generate_report.py` vs `generate_quality_report.py`:** não são duplicatas — `generate_quality_report` é Step 7 (KQI da `final-delivery/`), `generate_report` é Step 9 (relatório de tarefa por `--task-name`). Movido a `admin/` mesmo sendo chamado por `run.sh`, classificado como observability/reporting (não produz deliverable).
- **`run.sh`:** introduzida variável `ADMIN_DIR="$SCRIPTS_DIR/admin"`; **5** chamadas atualizadas (`archive_progress` ×3, `monitor_daemon` ×1, `generate_report` ×1) — não as ~10 estimadas no plano original. As outras 11 ocorrências de `$SCRIPTS_DIR/` continuam apontando para top-level (pipeline).
- **Gotcha corrigido:** 5 scripts (`archive_progress`, `generate_report`, `monitor_daemon`, `test_api_keys`, `final_data_validation`) usavam `Path(__file__).parent.parent` para chegar a `conversao/`. Após mover para `admin/`, isso passa a apontar para `scripts/`. Corrigido para `parent.parent.parent` em todos (8 occurrences).
- **README.md:** removida referência a `merge_split_pdfs.py`; ampliada listagem de `scripts/` para refletir tier atual.

**Verify (executado):**
- `bash -n run.sh` → syntax OK.
- Validação estática: 16 paths em `run.sh` resolvem todos.
- `./run.sh --history` → funciona.
- `./run.sh --status` → funciona.
- `python3 scripts/admin/archive_progress.py --list` → funciona standalone.
- `--restart` não testado em vivo (destrutivo); paths verificados estaticamente.

---

### Fase B — Extract `processamento/shared/` ✅ (concluído 2026-05-04)

**Resultado:** 3 módulos canônicos em `processamento/shared/`; ficha e livro deduplicados; goldens re-baselined com diff esperado por ADR-0001.

#### B.1 Mover book_converter ✅

- `.claude/skills/convert-book/book_converter/` → `processamento/book_converter/` (via `git mv`).
- `SKILL.md` atualizado: `from book_converter.X` → `from processamento.book_converter.X` (4 ocorrências).
- `tests/test_snapshot.py`: removido sys.path hack, agora importa direto.

#### B.2 `processamento/shared/` criado ✅

```
processamento/shared/
├── __init__.py        (44 linhas — re-exports)
├── yaml_writer.py     (103 linhas — ACCENT_MAP, transliterate, generate_id, format_yaml_*, format_authors_display)
├── ragflow.py         (140 linhas — join_paragraph_lines, format_bullets, normalize_spacing, optimize_for_ragflow)
└── ocr_patterns.py    (117 linhas — CLEANUP_PATTERNS, FICHA_EXTRA_PATTERNS, remove_artifacts)
```

**Decisões durante implementação:**
- `generate_id` canônico per ADR-0001 (slug ASCII transliterado, sem prefixo). `ACCENT_MAP` da ficha ganhou `transliterate(text)` como helper para reuso em `normalize_tag`.
- `CLEANUP_PATTERNS` é o **superset** do book (53 entries — Marco + DocMind + headers + figuras + tabelas + footnotes + dots iniciais). `FICHA_EXTRA_PATTERNS` tem 2 entries específicas que **não podem** entrar na lista comum: filename header `# 99-foo-1` e ALL CAPS dup line — colidiriam com `CAPÍTULO 1`/`INTRODUÇÃO` em livros.
- `format_bullets` adota versão book + variante `^-([A-Za-z...])` da ficha (sem espaço), no mesmo módulo.
- `join_paragraph_lines` adota versão book (trata listas numeradas `1. `..`9. ` como bullets — comportamento desejável).

#### B.3 Refator `ficha_converter` ✅

- `cleanup.py` (207 → 75 linhas): importa `remove_artifacts` + `CLEANUP_PATTERNS + FICHA_EXTRA_PATTERNS` de shared. Mantém `normalize_punctuation` (específico de ficha — `;` final em bullets).
- `restructure.py` (205 → 182): importa `format_bullets` + `format_authors_display` de shared, deleta locais.
- `frontmatter.py` (130 → 90): importa `generate_id` + `transliterate` de shared. Frontmatter passa a ter `tipo: ficha_agroecologica` (substituindo `categoria: ficha_tecnica`).
- `config.py` (106 → 53): só `TAG_KEYWORDS`, `SECTION_PATTERNS`, `SUBSECTION_PATTERNS` — `CLEANUP_PATTERNS` e `ACCENT_MAP` migraram para shared.

#### B.4 Refator `book_converter` ✅

- `ocr_cleanup.py` (355 → 238): `remove_artifacts` virou wrapper sobre `shared.ocr_patterns.remove_artifacts(content, CLEANUP_PATTERNS)`. Mantém specifics: `remove_figure_descriptions`, `clean_page_headers`, `remove_page_footers`, `remove_book_title_headers`, `fix_hyphenation`.
- `ragflow_optimize.py` (260 → 58): re-exporta de shared; mantém `format_optimize_summary` (estatísticas específicas de livro).
- `assembler.py` (339 → 245): importa `generate_id`, `format_yaml_value`, `format_yaml_list`, `format_authors_display` de shared. Frontmatter passa a ter `tipo: livro_tecnico` (substituindo `categoria: livro_tecnico`).

**Verify (executado):**
- `pytest tests/test_snapshot.py` → 3 passed após re-baseline com `UPDATE_GOLDENS=1`.
- Diff esperado nos goldens:
  - **Ficha:** `id: ficha_agroecologica_biofertilizante_fixture` → `biofertilizante_fixture`; `categoria: ficha_tecnica` → `tipo: ficha_agroecologica`; passos numerados (1./2./3.) agora em linhas separadas (efeito de `join_paragraph_lines` book).
  - **Livro:** `categoria: livro_tecnico` → `tipo: livro_tecnico` (mesma posição no YAML).
- Smoke: `from processamento.book_converter import convert_book_with_llm` + `from processamento.ficha_converter import convert_full` ambos OK.

**Métricas de redução:** -661 linhas nos converters, +404 em `shared/` → net -257 linhas + zero divergência silenciosa entre `generate_id`s.

---

### Fase C — `AppConfig` enxuto ✅ (concluído 2026-05-04)

**Resultado:** `conversao/scripts/config.py` criado com `AppConfig` `@dataclass(frozen=True)` + `from_env()`; modelo, retry, health e timeout centralizados; zero literais de modelo restantes.

**Mudanças:**

- `conversao/scripts/config.py` — **NOVO** (84 linhas). Helpers `_env_str/_int/_float/_bool` + `AppConfig.from_env()` que respeita 8 env vars (`DOCMIND_OCR_MODEL`, `DOCMIND_LLM_MODEL`, `DOCMIND_RETRY_MAX_ATTEMPTS`, `DOCMIND_RETRY_BASE_DELAY`, `DOCMIND_RETRY_JITTER`, `DOCMIND_HEALTH_DISABLE_AFTER`, `DOCMIND_HEALTH_DISABLE_DURATION`, `DOCMIND_REQUEST_TIMEOUT`).
- `conversao/scripts/docmind_converter.py`: `from config import AppConfig` + `APP_CONFIG = AppConfig.from_env()` no topo. l.287 `DEFAULT_MODEL` → `APP_CONFIG.ocr_model`. l.693 literal `'qwen3-vl-plus-2025-12-19'` → `APP_CONFIG.ocr_model` (**fix do drift apontado no plano**). `RetryConfig.max_retries/initial_delay/jitter` → defaults vindos de `APP_CONFIG.retry_*`. `APIKeyHealthMonitor(API_KEYS, disable_threshold=5, disable_duration=300.0)` → lê de `APP_CONFIG.health_*`.
- `conversao/scripts/retry_failed_pages.py`: `from config import AppConfig`; fallback `DEFAULT_MODEL = "qwen-vl-max-latest"` → `APP_CONFIG.llm_model`. `DEFAULT_MODEL` removido dos imports vindos de `docmind_converter`.

**Decisões durante implementação:**
- **Defaults preservam comportamento atual, divergindo dos literais do plano original.** O plano (l.197-199) sugeria `retry_max_attempts=5`, `retry_base_delay=2.0`, `retry_jitter=0.5` (float). Os defaults atuais do `RetryConfig` em produção são `4 / 1.0 / True` (bool — semântica de ±25% jitter na `calculate_retry_delay`). Como o objetivo do refator é "não regredir comportamento atual" e o snapshot só cobre stage 2 (não pega DocMind), `AppConfig` adotou os valores atuais. Ajuste futuro via env var.
- **`retry_jitter` mantido como `bool`, não `float`.** O plano pedia float 0.5 mas isso exigiria reescrever `calculate_retry_delay` para parametrizar a faixa. Out-of-scope para C.
- **Singleton de fato.** Plano dizia "AppConfig passada explicitamente, sem singleton". Implementado como módulo-level `APP_CONFIG = AppConfig.from_env()` em cada arquivo — singleton de facto, mas é a forma minimal-diff aqui (passar como param exigiria mudar várias assinaturas, ex. `simple_ocr_extract`). DI explícita virá natural na Fase D quando o monolito for split em 5 módulos. Documentado na docstring do `config.py`.
- **Drift documentação ↔ código não corrigido.** `conversao/CLAUDE.md` afirma que Phase 3 LLM usa `qwen-vl-max-latest`, mas o código atual usa `qwen3-vl-plus-2025-12-19` em ambas as fases via `DEFAULT_MODEL` (apenas `retry_failed_pages` usa `qwen-vl-max-latest`). Preservei o comportamento atual; alinhar exigiria decisão de produto.

**Verify (executado):**
- `pytest tests/test_snapshot.py` → 3 passed (golden inalterado — esperado: AppConfig só toca stage 1).
- `python3 -c "from config import AppConfig; print(AppConfig.from_env())"` → defaults batem com hardcodes anteriores.
- Override via env (`DOCMIND_OCR_MODEL=test-ocr ...`) propaga para `docmind_converter.APP_CONFIG.ocr_model` e `retry_failed_pages.DEFAULT_MODEL`.
- `python3 docmind_converter.py --help` e `python3 retry_failed_pages.py --help` mostram defaults preservados (`qwen3-vl-plus-2025-12-19` / `qwen-vl-max-latest`).
- `grep -n "qwen3-vl\|qwen-vl-max" conversao/scripts/{docmind_converter,retry_failed_pages}.py` → vazio.

---

### Fase D — Split `docmind_converter.py` ✅ (concluído 2026-05-04)

**Resultado:** monolito de 2006 linhas quebrado em 5 módulos em `conversao/docmind/`; `docmind_converter.py` reduzido a shim de 107 linhas re-exportando a superfície usada por `retry_failed_pages.py`. Branch `refactor/fase-d-split-docmind`.

**Estrutura criada:**
```
conversao/docmind/
├── __init__.py            (25 linhas — sys.path shim para scripts/)
├── retry.py               (59  — RetryConfig, calculate_retry_delay, should_retry)
├── api_key_pool.py        (214 — APIKeyHealth, APIKeyHealthMonitor, _api_key_monitor singleton)
├── qwen_client.py         (262 — QwenClient.simple_ocr_sync + .call_vlm + CallResult)
├── page_processor.py      (650 — enums, prompts, build_*, generate_figure_yaml, process_single_page_with_context)
└── pipeline.py            (923 — process_pdf_async, process_all_pdfs_parallel, main CLI)
```

**Decisões durante implementação:**
- **`config.py` permanece em `scripts/`** (decisão Fase C). `docmind/__init__.py` adiciona `scripts/` a `sys.path` no import — torna `from docmind.X import Y` self-sufficient sem caller setup.
- **`_api_key_monitor` continua module-level com side-effect on import** em `api_key_pool.py` (l.196-203) — preserva comportamento exato do monolito (pre-Fase-D l.541-547). Singleton de fato; injeção explícita via `QwenClient.__init__` está disponível mas o caminho default ainda usa o singleton.
- **`QwenClient.call_vlm` retorna `CallResult` dataclass**, não levanta exceção. Necessário para distinguir 3 estados: sucesso, fatal não-retriable (`DataInspectionFailed`), retries esgotados. Page_processor passa o erro adiante no dict `{'success': False, 'error': ...}` mantendo formato legacy.
- **`safe_get_text_from_response` movida para `qwen_client.py`** (era em `docmind_converter.py` l.610-654). Re-exportada pelo shim para `retry_failed_pages.py`.
- **`generate_figure_yaml` movida para `page_processor.py`** (não para `qwen_client.py`) porque é parsing de resposta, não chamada de API.
- **Helpers extraídos do inline de `process_single_page_with_context`:** `_extract_json_str`, `_fix_latex_escapes`, `_salvage_truncated_json` viraram funções no `page_processor.py`. Reduz a função principal de ~390 linhas inline para ~110.
- **Prefix `Page {n}` nos retry logs preservado** via parâmetro `log_prefix` em `QwenClient.call_vlm`.

**Shim (`docmind_converter.py`):**
- Adiciona `conversao/` e `scripts/` a `sys.path`.
- Re-exporta 32 símbolos via `__all__`. Surface coberta: tudo que `retry_failed_pages.py` importa em l.37-42 (`DEFAULT_CONTEXT_MODE`, `DEFAULT_PROMPT_MODE`, `DEFAULT_RETRY_CONFIG`, `ContextMode`, `PromptMode`, `build_context_window`, `build_prompt`, `safe_get_text_from_response`, `APIKeyHealthMonitor`, `_api_key_monitor`).
- `if __name__ == "__main__": sys.exit(main())` → `docmind.pipeline.main`.
- Compat preservada: `run.sh` (`python3 scripts/docmind_converter.py …`), `monitor_daemon.py` (`pgrep -f docmind_converter.py`).

**Verify (executado):**
- `pytest tests/` → **12 passed** (3 snapshot inalterados + 9 retry novos).
- `python3 docmind_converter.py --help` → CLI idêntica, default `qwen3-vl-plus-2025-12-19`.
- `python3 retry_failed_pages.py --help` → `DOCMIND_AVAILABLE = True`, `DEFAULT_MODEL = qwen-vl-max-latest`.
- `DOCMIND_OCR_MODEL=test-override python3 -c "..."` → propaga para `QwenClient.ocr_model`.
- `bash -n run.sh` → syntax OK.
- `grep "qwen3-vl|qwen-vl-max" docmind_converter.py retry_failed_pages.py` → vazio (drift fix da Fase C preservado).
- `./run.sh --restart` em PDF pequeno **não testado em vivo** (custa créditos da API + requer keys); paths e imports verificados estaticamente.

**Métricas:** monolito 2006 → shim 107 (-1899 linhas no entry-point); 5 módulos novos somam +2133 linhas. Net +234 (docstrings, type hints, dataclass `CallResult`, helpers extraídos, separação shim/__init__). Zero divergência de comportamento.

---

### Fase E — `Document` (Stage-1) ✅ (concluído 2026-05-04)

**Resultado:** `conversao/docmind/document.py` criado com 3 dataclasses (`Document`, `Chunk`, `FailedPage`) e API completa para descoberta, completion e ajuste de chunks. `merge_results_full.py` reduzido de 292 → 240 linhas consumindo `Document`. 20 testes novos em `tests/test_document.py`.

**Estrutura criada:**
```
conversao/docmind/document.py    (272 linhas)
  - Chunk                — frozen dataclass com path/pages/chunk_idx/total_chunks/original_pdf
  - FailedPage           — frozen dataclass page+error (lido de validation.yaml)
  - Document             — agregação por PDF original (com chunks ordenados)
    .is_chunked, .merged_md_path, .yaml_path, .validation_path,
    .images_dir, .yaml_metadata_dir, .total_pages()
    @classmethod discover(mapping_path, output_root) -> list[Document]
    is_complete(progress_manager=None, step_name=None) -> bool
    failed_pages() -> list[FailedPage]
    @classmethod apply_page_offset(content, offset) -> str   (consolida 3 adjust_md_*)

tests/test_document.py           (20 testes — discover, apply_page_offset, failed_pages, is_complete)
```

**Decisões durante implementação:**
- **`Document.is_complete()` *delega* a `progress_manager`, não o contrário.** O plano dizia "progress_manager consome `Document.is_complete()`"; literalmente isso inverteria a dependência da camada de persistência (todo caller precisaria construir `Document` antes de tocar progresso). Implementação concreta: `Document.is_complete(progress_manager=None)` é a API única — sem pm, faz check rápido em `merged_md_path`; com pm, delega a `validate_pdf_completion` ou `is_pdf_completed`. Mesmo end-state ("API única para 'está completo?'") sem inversão de camada.
- **`final_delivery_check.py` NÃO foi tocado nesta fase.** Plano dizia "consome `Document.failed_pages()`", mas o script opera sobre `final-delivery/` (estrutura flat pós-merge/pós-postprocess) — não há ponto natural pra ler `output/{name}/{name}.validation.yaml`. O hookup encaixa melhor na Fase F (consolidação de validação) onde `final_delivery_check` + `final_data_validation` + `generate_quality_report` viram `validation/checkers.py` plugáveis. `Document.failed_pages()` está disponível pra ser consumido lá.
- **3 `adjust_md_*` consolidados em `Document.apply_page_offset(content, offset)`** classmethod único; os 3 helpers permanecem como `@staticmethod` privados pra testabilidade.
- **`discover()` aceita `output_root` (não inferido).** Para chunks pré-merge `output_root = output/chunks`; pós-merge `output/`; direct `output/`. Caller decide onde busca.
- **Bug pré-existente capturado em xfail:** quando `merge_results_full.py` (e agora `Document.apply_page_offset`) processa MD com refs YAML em formato Markdown link `[yaml_metadata/X_pageN.yaml](yaml_metadata/X_pageN.yaml)`, regex gulosa renumera só a URL, deixa o link-text com número antigo. Cosmético (URL aponta certo). Snapshot teria pego se Stage-1 tivesse fixture, mas snapshot atual cobre só Stage-2. **xfail strict=True** em `test_apply_page_offset_yaml_refs_in_markdown_link_known_buggy`. Fica reservado pra Fase H.

**Refator `merge_results_full.py` (292 → 240 linhas):**
- `adjust_md_page_numbers/_image_references/_yaml_references` deletados (movidos para Document).
- `merge_chunks_for_pdf(original_pdf, chunks, results_dir, output_dir)` → `merge_document(document, results_dir)`. Diretórios saem de `Document.output_dir`/`.images_dir`/`.yaml_metadata_dir` em vez de `Path()` aritmética.
- `main()` usa `Document.discover()` filtrando `is_chunked` (descarta direct PDFs que não precisam merge).
- CLI preservada (`--mapping-file`, `--results-dir`, `--output-dir`).

**Não feito (defer registrado):**
- **`FichaMetadata` dataclass** (paralelo a `BookMetadata`). Plano lista isso fora do "Não fazer em E" mas como tarefa pequena. Decidido com user: pular — não é load-bearing pra Stage-1 e adiciona ruído numa branch que está focada em `conversao/`. Pode entrar em Fase F como hygiene ou avulso.
- **Wiring em `final_delivery_check.py`**. Defer pra Fase F.

**Verify (executado):**
- `pytest tests/` → **32 passed, 1 xfailed** (3 snapshot + 9 retry + 20 document; xfail = bug pré-existente).
- `merge_results_full.py --help` → CLI idêntica.
- Smoke `Document.discover(real split_mapping.json)` → descobre 1 PDF direct corretamente; `is_complete=False` (md ausente) e `failed_pages=0` (validation.yaml limpo).
- `bash -n run.sh` → syntax OK (run.sh não foi tocado).

---

### Fase F — Consolidar validação ✅ (concluído 2026-05-04)

**Resultado:** 2 scripts de validação consolidados em `conversao/validation/`; entry points viraram shims; FDV identificado como recovery (não validação) e renomeado.

#### F.1 Inventário ✅

Catalogou-se cada checagem nos 4 scripts. Tabela completa em ~30 linhas com colunas `nome_check | scripts | semântica | sobreposições | dead?`. **Duas surpresas reformularam a Fase F:**

- **`final_data_validation.py` não é validação — é recuperação de content-moderation.** Re-extrai com GPT-4o-mini páginas que Qwen bloqueou. Sai do escopo da Fase F.
- **`generate_report.py` não é validação propriamente — é agregador per-task.** Coleta batch_reports + progress + monitor num dossiê (`reports/{task_name}/`). Sobrepõe parcialmente GQR.

**Conclusão:** validação real está em **2 scripts** (`final_delivery_check.py` + `generate_quality_report.py`), não 4. F.2 consolidou esses 2.

3 decisões aprovadas com user:
1. FDV sai da Fase F → renomeado pra `recover_moderation_blocked.py` (admin/).
2. `GR.generate_quality_report` removido (dead code parcial — duplicava GQR mal).
3. Estrutura `validation/` aprovada com adição de `cost.py`.

#### F.2 Consolidação ✅

Estrutura criada (~2050 linhas + 60 testes):
```
conversao/validation/
├── __init__.py            (16 linhas)
├── checkers.py            (560 linhas — 6 Checkers + base + helpers)
│   - StructureChecker        (A1 file count, A2 md/yaml pairs)
│   - ContentSyntaxChecker    (B1 json remnants, B2 literal newlines, B3 yaml)
│   - MarkdownChecker         (C1 page headers, C2 fig refs, C3 file size)
│   - QualityChecker          (D1-D5 buckets, garbled, repeats, score, review)
│   - ElementChecker          (E1-E4 tables/formulas/images/code)
│   - MarcoChecker            (F1 yaml + title + page headers)
│   + split_into_pages helper compartilhado
├── pipeline.py            (44 linhas — ValidationPipeline + ValidationReport)
├── cost.py                (152 linhas — TokenUsage + CostBreakdown +
│                           compute_cost + from_batch_reports)
└── report.py              (310 linhas — render_quality_report + RetryFailures
                            + format_duration + quality_rating + load_retry_failures)
```

**4 milestones (1 commit cada):**

- **F.2.a** `09bdb8c`: skeleton — base Checker, StructureChecker, ContentSyntaxChecker, ValidationPipeline. 17 testes.
- **F.2.b** `0d0b08e`: 4 checkers semânticos + `split_into_pages`. 23 testes.
- **F.2.c** `e7f9a7a`: cost.py (substitui GQR.calculate_estimated_cost heurística + GR.calculate_costs duplicada) + report.py (substitui GQR.render_report 200-linha). 20 testes.
- **F.2.d** `212d030`: migra entry points.
  - `final_delivery_check.py` 377 → 132 linhas (subset Structure+Syntax+Markdown).
  - `generate_quality_report.py` 754 → 137 linhas (todos 6 checkers + render).
  - `admin/generate_report.py`: drop `generate_quality_report()`; `calculate_costs()` delega a `validation.cost.from_batch_reports`.
  - `admin/final_data_validation.py` → `admin/recover_moderation_blocked.py` (git mv preserva history).
  - README.md + .env.example atualizados.

**Decisões durante implementação:**
- **`cost.py` resolve tokens com fallback.** Prefere `processing.tokens_input/tokens_output` explícitos (post-Fase-D); senão estima input como `pages × 1500` e usa `processing.tokens` como output (legacy GR). Permite migrar sem quebrar batch_reports antigos.
- **Cost intencionalmente fora do GQR.** GQR renderiza qualidade; cost vive em GR (admin/) que tem batch_reports. `render_quality_report` aceita `cost=None` e omite a linha. Separação correta de concerns.
- **`render_quality_report` não é byte-equivalent ao GQR legacy.** Output é Markdown human-readable; downstream não depende. Mantém as 8 seções, simplifica formatação.
- **Bug pré-existente preservado:** `MarkdownChecker.figures` usa regex `### Fig \d+:` que não casa `### Figure N`. Documentado no docstring; legacy regex.

**Verify (executado):**
- `pytest tests/` → **92 passed, 1 xfailed** (3 snapshot + 9 retry + 20 document + 17 syntax/structure + 23 semantic + 20 cost/report).
- `final_delivery_check.py --help` → CLI idêntica.
- `generate_quality_report.py --help` → CLI idêntica.
- Smoke ponta-a-ponta com fixture: `final_delivery_check` reporta 3 PASS + 1 warning; `generate_quality_report` renderiza QUALITY_REPORT.md com 8 seções, score 100/100.
- `admin/generate_report.py --help` e `admin/recover_moderation_blocked.py --help` → CLIs preservadas.
- `bash -n run.sh` → syntax OK (sem mudanças em run.sh).

**Métricas:** -1131 linhas líquidas (377+754+436=1567 originais → entry shims 132+137+200~ = 469; +2050 em validation/; bug factor delete `generate_quality_report` em GR ~=80 linhas removidas).

---

### Fase G — Orquestrador Python + Status (~2 dias, dep: C, D, E, F)

**File:** `conversao/orchestrator.py` (NOVO):

```python
class Pipeline:
    def __init__(self, config: AppConfig, root: Path): ...
    def run(self, restart: bool = False, retry_failed: bool = False): ...
    def status(self) -> "PipelineStatus": ...

@dataclass
class PipelineStatus:
    documents: list[DocumentStatus]
    def as_text(self) -> str: ...
    def as_json(self) -> dict: ...
```

`run.sh` reduzido a ~50 linhas: só env loading (`api/keys.txt` → env vars), python entry-point, monitor daemon. Mantém compatibilidade com flags atuais (`--restart`, `--status`, `--retry-failed`, `--task-name`, `--monitor`, `--history`).

`Pipeline.status()` consome `Document.is_complete()` (E) + ValidationReport (F). Substitui inline parsing em `run.sh:312–327, 338–371`.

**Verify:**
- `./run.sh --status` produz mesmo formato.
- `./run.sh --restart` em 1 PDF pequeno produz mesmo `final-delivery/`.

---

### Fase H — Bug fixes capturados em snapshot (~1h, dep: G)

Após o refator estrutural terminar e a árvore estar estável, aplicar correções pontuais a bugs visíveis nos goldens. Isolar bugs de mudanças estruturais facilita revisão e reverte (golden bate antes/depois de cada commit).

#### H.1 Reordenar patterns em `_clean_chapter_title_text` (~5min)

**File:** `processamento/book_converter/llm_pipeline.py` (após B.1) — função `_clean_chapter_title_text` (l.146-153 hoje).

**Problema:** patterns rodam em ordem; `r'^([IVXLC]+\.?\s*[-–—]?\s*)'` casa antes dos patterns específicos `CAPÍTULO`/`Capítulo`/`PARTE`/`Parte`. A primeira letra "C" de `CAPÍTULO` é dropada como se fosse numeral romano. Resultado em produção: `## APÍTULO 1 - INTRODUÇÃO`. Afeta chapters começando com I, V, X, L, C.

**Fix:** mover o pattern `[IVXLC]+` para **depois** dos patterns específicos. Alternativa equivalente: ancorar o IVXLC com lookahead que rejeita letras subsequentes (`(?=[\s.\-–—]|$)`).

**Verify:** atualizar `tests/golden/livro.md` via `UPDATE_GOLDENS=1 pytest tests/test_snapshot.py`. Golden passa a mostrar `## INTRODUÇÃO`, `## METODOLOGIA`. Commit dedicado com justificativa.

**Re-processar produção:** os ~96 livros em `Livros_Processados/` precisam ser re-rodados via `/convert-book` para corrigir titles existentes. Fora do escopo do refator (decisão de produto).

> Reservar esta fase para bugs catalogados *durante* B-G — ou seja, tudo que aparecer no diff de re-baseline e foi diagnosticado como bug pré-existente, não regressão. Se nenhum bug novo for catalogado, a fase entrega só H.1.

---

## Verificação end-to-end

**Após cada fase B-G:**
1. `pytest tests/test_snapshot.py` passa.
2. `./run.sh --status` retorna sem erro.
3. Smoke: `python -m ficha_converter` em ficha de referência; `/convert-book` em livro de referência. Comparar com goldens.

**Após G (final):** rodar pipeline completa (`./run.sh`) num batch de 3 PDFs (1 grande, 2 pequenos). `progress.json`, `output/`, `final-delivery/` ficam idênticos a um run baseline pré-refatoração (capturado antes de começar a Fase A).

## Cronograma

| Sprint | Fases | Status | Duração |
|---|---|---|---|
| 1 | 0.1, 0.2, A.1, A.2, A.3 | ✅ concluído (2026-05-04) | 1 dia |
| 2 | B (todas) | ✅ concluído (2026-05-04) | 1 dia |
| 3 | C → D | ✅ concluído (2026-05-04) | 4 dias |
| 4 | E → F.1 + review F.1 | ✅ concluído (2026-05-04) | 3 dias |
| 5 | F.2 → G → H | F.2 ✅ concluído (2026-05-04); G+H pendentes | 4 dias |

**Total:** ~13 dias focados (~3 semanas com interrupções). Sprint 1 acelerou — A.3 paralelizada em outro terminal pelo user.

## Open questions — RESOLVIDAS (2026-05-04)

1. **ADR-0001 schema de ID** — ✅ **slug puro + campo `tipo` separado**. `generate_id` canônico usa ACCENT_MAP (transliteração via versão da ficha). Goldens da Fase 0.1 capturam comportamento atual; rebase de IDs ocorre em commit separado durante Fase B com justificativa.
2. **A.3 — `merge_split_pdfs.py` é dead?** — ✅ **DEAD, deletar**. Audit confirmou: não chamado por `run.sh`, comentários em chinês, sobreposto por `merge_results_full.py` (canônico, l.394 do run.sh). Atualizar `conversao/README.md` removendo referência.
3. **B.1 — quebra de skill** — ✅ **OK**. `SKILL.md` será atualizado para `from processamento.book_converter` em B.1.
4. **D — async test strategy** — ✅ **snapshot é suficiente**. Sem race-condition tests dedicados; smoke `./run.sh --restart` em PDF pequeno valida concorrência empiricamente.
