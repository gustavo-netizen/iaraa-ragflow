# ADR-0002 — `book_converter` é LLM-agnostic

**Status:** Accepted
**Data:** 2026-05-04
**Decisores:** gustavo@the-syllabus.com

## Contexto

O `book_converter` (hoje em `.claude/skills/convert-book/book_converter/`, movido em B.1 para `processamento/book_converter/`) usa análise LLM na Fase 1 do pipeline para extrair metadados, identificar capítulos e detectar seções a remover. A pergunta é: **onde mora a chamada ao LLM?**

Hoje o pacote já é, na prática, agnóstico: `llm_pipeline.convert_book_with_llm()` recebe `llm_response: str` pronto, e quem chama o LLM é a skill `/convert-book` (instruções em `SKILL.md` orientam o Claude Code rodando a skill a fazer a chamada via tool use).

A proposta de refatoração original sugeria embutir o SDK da Anthropic dentro do pacote (versão "C1"), o que tornaria o `book_converter` chamável fora da skill como uma biblioteca standalone.

## Decisão

**O `book_converter` permanece LLM-agnostic.** A interface pública é:

```python
from processamento.book_converter.llm_pipeline import convert_book_with_llm
from processamento.book_converter.llm_analyzer import build_analysis_prompt, parse_llm_response

prompt = build_analysis_prompt(content, max_lines=500)
llm_response = "..."   # responsabilidade do chamador (skill, teste, script)
document, log = convert_book_with_llm(
    content=content,
    filename="livro.md",
    llm_response=llm_response,
)
```

- O pacote **gera** o prompt e **parseia** a resposta JSON.
- O pacote **não** importa `anthropic`, `openai`, `dashscope`, ou qualquer SDK de LLM.
- A chamada ao modelo acontece **fora** do pacote: na skill `/convert-book` (via Claude Code), em scripts de teste (com fixture JSON), ou em integrações futuras (com qualquer LLM).

## Consequências

**Positivas**
- **Testabilidade.** Snapshot tests da Fase 0.1 alimentam um `llm_response` capturado de produção. Pipelines determinísticos a partir daí — sem chamar API durante testes.
- **Decoupling de provedor.** Trocar Claude por outro LLM exige só editar a skill (ou o script chamador), não o pacote.
- **Sem dependência transitiva pesada.** `anthropic` SDK puxa httpx, pydantic, etc. Quem só quer rodar o pipeline com uma resposta capturada não paga esse custo.
- **Skill já é o boundary natural.** `/convert-book` roda dentro do Claude Code, que já tem o cliente LLM. Reusar é mais simples que importar SDK.

**Negativas / custos**
- Quem quiser usar o pacote standalone (CLI puro fora do Claude Code) tem que escrever ~20 linhas chamando o SDK. Aceitável — o caso de uso primário é a skill.
- Documentação tem que deixar claro que `convert_book_with_llm` exige `llm_response` pronto. Hoje `processamento/CLAUDE.md` e `SKILL.md` já cobrem.

**Não-consequências**
- Isso **não** impede um wrapper futuro tipo `book_converter.cli:main` que importa o SDK e chama `convert_book_with_llm`. Esse wrapper viveria fora do pacote core, em `processamento/book_converter/cli.py` ou similar — desde que `cli.py` seja opcional e não importado por `__init__.py`.

## Decisões descartadas

- **Embutir SDK da Anthropic no pacote (proposta C1):** acopla pacote a um provedor, infla dependências, dificulta testes determinísticos, duplica responsabilidade que a skill já tem.
- **Abstrair atrás de uma interface `LLMClient`:** premature abstraction. Hoje há um único caller (a skill); a abstração só ganha valor quando aparecer um segundo.
