# Architecture Decision Records

Decisões arquiteturais do projeto **iaraa-ragflow** registradas no formato leve de Michael Nygard (Status / Context / Decision / Consequences).

Um ADR existe para travar uma decisão que afeta o futuro do código — não para documentar como o código está hoje (isso vai em `CLAUDE.md` / `CONTEXT.md`). Sempre que uma proposta tentar reabrir uma decisão registrada aqui, releia o ADR antes de decidir reverter.

## Índice

| # | Título | Status |
|---|---|---|
| [0001](0001-id-schema-frontmatter.md) | Schema de ID no frontmatter — slug ASCII + campo `tipo` separado | Accepted |
| [0002](0002-book-converter-llm-agnostic.md) | `book_converter` é LLM-agnostic — recebe resposta pré-computada | Accepted |
| [0003](0003-progress-storage-json-filelock.md) | Progress storage permanece JSON + FileLock (não SQLite) | Accepted |

## Convenções

- Numeração sequencial, zero-padded a 4 dígitos (`0001`, `0002`...).
- Arquivo nomeado `NNNN-titulo-em-kebab-case.md`.
- Status possíveis: `Proposed`, `Accepted`, `Superseded by NNNN`, `Deprecated`.
- ADR substituído por outro nunca é deletado — só marcado `Superseded`.
