# ADR-0003 — Progress storage permanece JSON + FileLock

**Status:** Accepted
**Data:** 2026-05-04
**Decisores:** gustavo@the-syllabus.com

## Contexto

O DocMind (Stage 1) processa PDFs em paralelo, página a página, com checkpoint/resume. O estado vive em `conversao/progress.json` e é coordenado por `progress_manager.py`, que usa `filelock.FileLock` em `progress.json.lock` (timeout de 10s) para serializar escritas concorrentes.

```python
# progress_manager.py:12,33,43
from filelock import FileLock
self.progress_file = self.base_dir / "progress.json"
return FileLock(self.lock_file, timeout=10)
```

A proposta de refatoração original sugeria migrar para SQLite, citando "concurrent writes" e "consultas estruturadas" como motivações. A questão é: **vale o custo da migração?**

Em produção: ~96 livros e centenas de fichas processados sem incidente atribuído ao storage. Não há gargalo medido — a queixa é teórica ("JSON não escala"), não empírica.

## Decisão

**Progress storage permanece em JSON + FileLock.**

- `progress.json` continua sendo a fonte de verdade do estado de execução do pipeline DocMind.
- `progress_manager.py` continua coordenando acesso via `FileLock(timeout=10)`.
- Não migrar para SQLite, Redis, ou qualquer outro backend até que exista **gargalo medido** justificando.

## Consequências

**Positivas**
- Zero custo de migração. Migração de schema, dual-write durante transição, scripts de validação cruzada — tudo evitado.
- `progress.json` é inspecionável com `cat` / `jq`. Útil em debug e em `./run.sh --status`.
- `FileLock` resolve o cenário atual (poucos writers concorrentes em escala de PDFs por máquina).
- Python stdlib + `filelock` (já dependência) — sem novo runtime.

**Negativas / custos**
- Se o número de PDFs concorrentes crescer 10×, contention no lock pode virar gargalo. Mitigação: medir antes de migrar.
- Queries estruturadas ("quantos PDFs falharam na última semana") exigem parsing do JSON. Aceitável dado o volume atual.
- Corrupção de JSON por crash mid-write é teoricamente possível; `FileLock` reduz a janela mas não elimina. Mitigação: `progress_manager.py` escreve via tmpfile + rename atômico se ainda não fizer (verificar em A.3).

**Critério para reabrir esta decisão**
- Throughput observado < esperado **e** profile aponta o lock como gargalo.
- Corrupção de `progress.json` em produção (registrar incidente).
- Necessidade de queries multi-PDF analíticas que JSON parsing torne inviável.

## Decisões descartadas

- **Migrar para SQLite especulativamente:** sem gargalo medido, é refator caro e arriscado durante uma rodada de limpeza arquitetural. Pode entrar como ADR futuro se uma das condições de reabertura ocorrer.
- **Substituir FileLock por advisory lock no próprio JSON (`fcntl.flock`):** ganho marginal, perde portabilidade Windows, complica testes. `filelock` já abstrai isso.
- **Distribuir progress entre múltiplos JSONs (um por PDF):** quebra `--status` global, sem ganho mensurável. Reabrir só se contention virar problema.
