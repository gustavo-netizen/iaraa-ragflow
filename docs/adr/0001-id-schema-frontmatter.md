# ADR-0001 — Schema de ID no frontmatter

**Status:** Accepted
**Data:** 2026-05-04
**Decisores:** gustavo@the-syllabus.com

## Contexto

Cada documento processado (Ficha Agroecológica ou Livro Técnico) recebe um campo `id` no YAML frontmatter, usado pelo RAGFlow como identificador estável do chunk pai. Hoje existem **duas implementações divergentes** de `generate_id`:

**`processamento/ficha_converter/frontmatter.py:28`**
```python
def generate_id(filename: str) -> str:
    name = re.sub(r'^\d+-', '', filename)
    name = re.sub(r'-\d+\.md$', '', name)
    name = re.sub(r'\.md$', '', name)
    name = name.replace('-', '_')
    return f'ficha_agroecologica_{name}'
```
- **Prefixa** o tipo no próprio ID.
- Translitera acentos via `ACCENT_MAP` (em `config.py:98`): `café → cafe`, `ação → acao`.

**`.claude/skills/convert-book/book_converter/assembler.py:15`**
```python
def generate_id(filename: str) -> str:
    name = Path(filename).stem
    name = name.lower()
    name = re.sub(r'[\s\-]+', '_', name)
    name = re.sub(r'[^a-z0-9_]', '', name)  # dropa acentos
    name = re.sub(r'_+', '_', name)
    return name.strip('_')
```
- **Não prefixa** o tipo.
- **Dropa** caracteres não-ASCII em vez de transliterar: `café → caf`, `ação → ao`.

Resultado: o mesmo arquivo (ex: `cafe-agroecologico.md`) gera IDs diferentes dependendo do conversor que o processa. Pior: livros com palavras acentuadas no nome viram IDs ilegíveis (`introducao_a_acao_climatica` vs `introduo_a_ao_climatica`).

A divergência também esconde uma decisão de modelagem: o tipo do documento (ficha vs livro) está acoplado ao ID em um lado, ausente no outro. Para a Fase B (`processamento/shared/`), precisamos de **um** `generate_id` canônico — e precisamos decidir onde mora a informação de tipo.

## Decisão

1. **Slug ASCII transliterado, sem prefixo de tipo.**

   `generate_id` canônico (a viver em `processamento/shared/yaml_writer.py`) adota a estratégia da ficha: lowercase + `ACCENT_MAP` para transliteração + remoção de não-alfanuméricos + colapso de underscores. Acentos são **transliterados**, não dropados (`café → cafe`).

   ```python
   def generate_id(filename: str) -> str:
       name = Path(filename).stem.lower()
       for old, new in ACCENT_MAP.items():
           name = name.replace(old, new)
       name = re.sub(r'^\d+[-_]', '', name)
       name = re.sub(r'[-_]\d+$', '', name)
       name = re.sub(r'[\s\-]+', '_', name)
       name = re.sub(r'[^a-z0-9_]', '', name)
       name = re.sub(r'_+', '_', name)
       return name.strip('_')
   ```

2. **Tipo do documento mora em campo separado `tipo`.**

   No frontmatter de toda saída:
   ```yaml
   id: cafe_agroecologico
   tipo: ficha_agroecologica   # ou: livro_tecnico
   ```

   `ficha_converter` injeta `tipo: ficha_agroecologica`; `book_converter` injeta `tipo: livro_tecnico`. Vocabulário fechado a esses dois valores até surgir um terceiro tipo de documento.

3. **`ACCENT_MAP` torna-se compartilhado.**

   Movido para `processamento/shared/yaml_writer.py` na Fase B. Hoje vive em `processamento/ficha_converter/config.py:98` — book_converter passa a importar de `shared`.

## Consequências

**Positivas**
- Mesmo arquivo produz mesmo ID, independente do conversor.
- IDs continuam legíveis (`cafe`) em vez de mutilados (`caf`).
- Filtro por tipo no RAGFlow vira query estruturada (`tipo: livro_tecnico`) em vez de regex em prefixo.
- `processamento/shared/yaml_writer.py` ganha uma única fonte de verdade.

**Negativas / custos**
- **IDs mudam para documentos já produzidos.** ~96 livros e centenas de fichas em produção têm IDs no formato antigo. Os arquivos não são re-processados automaticamente; novos runs gerarão IDs novos. Se o RAGFlow já indexou IDs antigos, há risco de duplicação na re-ingestão.
- A mitigação é **não migrar retroativamente**: documentos antigos mantêm seus IDs até serem re-processados explicitamente. Re-ingestão no RAGFlow deve limpar a coleção antes.
- `tipo` adiciona uma linha ao YAML de cada documento. Custo desprezível.

**Plano de implementação**
- Fase 0.1 captura goldens **antes** da unificação (preserva comportamento atual).
- Fase B aplica o `generate_id` canônico em `processamento/shared/`.
- Goldens são atualizados em commit separado após B com mensagem explicando a quebra de IDs.

## Decisões descartadas

- **Manter prefixo (`ficha_agroecologica_X`):** acopla metadado ao ID, polui filtros, dificulta reuso entre tipos.
- **Dropar acentos sem transliterar:** continua produzindo IDs ilegíveis.
- **Hash do filename (UUID/SHA):** quebra legibilidade humana, que hoje é útil em logs e debug.
