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

### Fase B — Extract `processamento/shared/` (~5h, dep: 0.1, ADR-0001)

#### B.1 Mover book_converter (~30min)

`.claude/skills/convert-book/book_converter/` → `processamento/book_converter/`.

Atualizar `.claude/skills/convert-book/SKILL.md`: trocar `from book_converter.llm_pipeline` por `from processamento.book_converter.llm_pipeline`.

**Verify manual:** `/convert-book` num livro pequeno; output bate com snapshot.

#### B.2 Criar `processamento/shared/` (~3h)

```
processamento/shared/
├── __init__.py
├── ragflow.py         # join_paragraph_lines, format_bullets, normalize_spacing
├── yaml_writer.py     # generate_id, format_yaml_value, format_yaml_list, format_authors_display
└── ocr_patterns.py    # CLEANUP_PATTERNS unificado + remove_artifacts(content, patterns)
```

**Decisões:**
- `join_paragraph_lines`: adotar versão book (trata listas numeradas); confirmar via snapshot que ficha não regride.
- `generate_id`: implementação canônica per ADR-0001. Recomendação: ASCII transliterado + slug, sem prefixo. Pipelines passam `tipo` em campo separado do frontmatter.
- `CLEANUP_PATTERNS`: união de Marco + DocMind + page headers PT/EN.
- `format_authors_display`: confirmar que ficha (SOBRENOME, I.) e book usam mesmo formato.

#### B.3 Refator `ficha_converter` (~45min)

- `cleanup.py` importa de `shared.ocr_patterns`, `shared.ragflow`. Remove implementações locais.
- `restructure.py` importa `format_bullets`, `format_authors_display` de shared.
- `frontmatter.py` importa `generate_id`, `format_yaml_value` de shared. Adiciona `tipo: ficha_agroecologica` no frontmatter.
- `config.py` mantém só constantes específicas (TAG_KEYWORDS, SECTION_PATTERNS).

#### B.4 Refator `book_converter` (~45min)

- `ocr_cleanup.py` importa `remove_artifacts` de `shared.ocr_patterns`. Mantém specifics (book-title-aware header removal).
- `ragflow_optimize.py` importa de `shared.ragflow`.
- `assembler.py` importa de `shared.yaml_writer`. Adiciona `tipo: livro_tecnico` no frontmatter.

**Verify:** `pytest tests/test_snapshot.py` passa; goldens atualizados se decisão de ID schema (ADR-0001) mudar IDs anteriores.

---

### Fase C — `AppConfig` enxuto (~2h, dep: nada, melhor após A)

**Files:**
- `conversao/scripts/config.py` — NOVO.
- `conversao/scripts/docmind_converter.py` — consume.
- `conversao/scripts/retry_failed_pages.py` — consume.

```python
@dataclass(frozen=True)
class AppConfig:
    ocr_model: str = "qwen3-vl-plus-2025-12-19"
    llm_model: str = "qwen-vl-max-latest"
    retry_max_attempts: int = 5
    retry_base_delay: float = 2.0
    retry_jitter: float = 0.5
    health_disable_after: int = 5         # consecutive failures
    health_disable_duration: int = 300    # seconds (5min)
    request_timeout: int = 120

    @classmethod
    def from_env(cls) -> "AppConfig": ...
```

**Não centralizar:** paths, semaphore, chunk size — já vêm de CLI/env. Sem singleton: `AppConfig` passada explicitamente.

Hardcodes em `docmind_converter.py:287, 693` lêem de `AppConfig.ocr_model`. Se ainda houver hardcode, fail.

**Verify:** docmind_converter executa um chunk pequeno end-to-end; output bate com snapshot.

---

### Fase D — Split `docmind_converter.py` (~2-3 dias, dep: 0.1, C)

**Branch separada.** Não mergear sem 0.1 passar.

```
conversao/docmind/
├── __init__.py
├── api_key_pool.py      # APIKeyHealthMonitor + APIKeyHealth + load from env
├── retry.py             # RetryConfig + jitter + should_retry
├── qwen_client.py       # chamadas qwen-vl-plus / qwen-vl-max via dashscope
├── page_processor.py    # process_single_page_with_context, 3-page window, prompt builder
└── pipeline.py          # orquestração, paralelismo PDF-level, integração progress
```

**Mapping de linhas (de docmind_converter.py atual):**

| Origem | Destino |
|---|---|
| `RetryConfig` (l.36–53) | `retry.py` |
| `APIKeyHealth`, `APIKeyHealthMonitor` (l.56–271) | `api_key_pool.py` |
| `get_next_api_key`, async coordinators (l.544–558) | `api_key_pool.py` |
| `process_single_page_with_context` + prompt builders (l.273–541) | `page_processor.py` |
| Cliente dashscope (espalhado) | `qwen_client.py` |
| `process_pdf_async`, `process_all_pdfs_parallel` (l.600+) | `pipeline.py` |

**Padrões:**
- `qwen_client` recebe `api_key_pool` e `retry` por construtor.
- `page_processor` recebe `qwen_client`.
- `pipeline` recebe `page_processor`, `progress_manager`, `AppConfig`.
- Modelo lido de `AppConfig.ocr_model` em `qwen_client`. Hardcode quebra build.

`docmind_converter.py` original vira **shim** que importa `pipeline.run` e expõe a CLI atual. Compatibilidade com `run.sh` preservada. Pode ser deletado em G.

**Verify:**
- `tests/test_retry.py` exercita backoff sem rede.
- `tests/test_snapshot.py` passa.
- Smoke: `./run.sh --restart` em 1 PDF pequeno produz output idêntico.

---

### Fase E — `Document` (Stage-1) (~2-3 dias, dep: D)

**Escopo narrow.** Não cria hierarquia `Document/Ficha/Book` (descartado em ADR-0002 raciocínio). Cria `Document` que representa **1 PDF da Stage 1** com seus chunks/pages/yaml/progress.

**File:** `conversao/docmind/document.py` (NOVO):

```python
@dataclass
class Document:
    pdf_path: Path
    original_name: str
    chunks: list[Chunk]            # subset de split_mapping.json
    output_dir: Path               # output/{name}/
    yaml_path: Path                # output/{name}/{name}_all_figures.yaml
    validation_path: Path          # output/{name}/{name}.validation.yaml

    @classmethod
    def discover(cls, root: Path, mapping: Path) -> list["Document"]: ...
    def is_complete(self) -> bool: ...
    def failed_pages(self) -> list[FailedPage]: ...
    def merged_md(self) -> Path: ...
```

**Refatores:**
- `merge_results_full.py` consome `Document`. As 3 `adjust_md_*` (l.15–55) viram métodos de `Document`.
- `progress_manager.py` consome `Document.is_complete()` em vez de manter state paralelo.
- `final_delivery_check.py` consome `Document.failed_pages()`.

**Não fazer em E:** `FichaDocument` / `BookDocument` em Stage 2. Ficha e Livro continuam com dataclasses paralelos (`FichaMetadata` novo + `BookMetadata` existente — apenas igualar a inconsistência dataclass-vs-dict).

**Verify:** snapshot passa; `--status` produz output equivalente; `merge_results_full` produz mesmo output.

---

### Fase F — Consolidar validação (~3 dias, dep: E)

#### F.1 Inventário (~1 dia)

Catalogar checagens em:
- `final_delivery_check.py` (377 linhas)
- `final_data_validation.py` (501 linhas)
- `generate_quality_report.py` (754 linhas)
- `generate_report.py` (436 linhas)

**Output:** tabela `nome_check | scripts | semântica | sobreposições | dead?`. Aprovar com user antes de F.2.

#### F.2 Consolidar (~2 dias)

```
conversao/validation/
├── __init__.py
├── checkers.py          # FolderChecker, FileChecker, YamlChecker, MarkdownChecker, QualityChecker
├── pipeline.py          # ValidationPipeline.run(documents) -> ValidationReport
└── report.py            # ValidationReport, JSON + console
```

CLIs antigas viram thin wrappers chamando `validation.pipeline.run(...)` com checker subsets.

**Verify:** snapshot dos relatórios JSON antigos vs. consolidados — mesmas seções `failed_pages_detail`, mesmas métricas KQI.

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
| 2 | B (todas) | pendente | 1 dia |
| 3 | C → D | pendente | 4 dias |
| 4 | E → F.1 + review F.1 | pendente | 3 dias |
| 5 | F.2 → G → H | pendente | 4 dias |

**Total:** ~13 dias focados (~3 semanas com interrupções). Sprint 1 acelerou — A.3 paralelizada em outro terminal pelo user.

## Open questions — RESOLVIDAS (2026-05-04)

1. **ADR-0001 schema de ID** — ✅ **slug puro + campo `tipo` separado**. `generate_id` canônico usa ACCENT_MAP (transliteração via versão da ficha). Goldens da Fase 0.1 capturam comportamento atual; rebase de IDs ocorre em commit separado durante Fase B com justificativa.
2. **A.3 — `merge_split_pdfs.py` é dead?** — ✅ **DEAD, deletar**. Audit confirmou: não chamado por `run.sh`, comentários em chinês, sobreposto por `merge_results_full.py` (canônico, l.394 do run.sh). Atualizar `conversao/README.md` removendo referência.
3. **B.1 — quebra de skill** — ✅ **OK**. `SKILL.md` será atualizado para `from processamento.book_converter` em B.1.
4. **D — async test strategy** — ✅ **snapshot é suficiente**. Sem race-condition tests dedicados; smoke `./run.sh --restart` em PDF pequeno valida concorrência empiricamente.
