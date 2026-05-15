# ADR-0006 — pikepdf (libqpdf) substitui PyPDF2 no splitter

**Status:** Accepted
**Data:** 2026-05-15
**Decisores:** gustavo@the-syllabus.com

## Contexto

`conversao/scripts/split_large_pdfs_smart.py` era o único call-site de PyPDF2 no repo. PyPDF2 é um parser de PDF em **Python puro** e rejeita arquivos com trailer/xref ligeiramente fora de spec — comportamento "estrito" que cobre o leitor da exceção em runtime mas falha em produção com PDFs do mundo real.

No run de 2026-05-15, `Dissertação_Carvalho.pdf` (PDF brasileiro digitalizado, header válido, xref deslocada por bytes a mais no preâmbulo) lançou `PyPDF2.errors.PdfReadError: Invalid Elementary Object`. Reabri o arquivo manualmente com `pikepdf` em segundos:

```python
import pikepdf
with pikepdf.open("Dissertação_Carvalho.pdf") as pdf:
    pdf.save("repaired.pdf")
```

A saída foi processada normalmente pelo resto do pipeline. `pikepdf` usa as bindings C de [libqpdf](https://qpdf.sourceforge.io/), que tem heurísticas de recovery (reconstrói xref a partir do body quando o trailer está corrompido, releva discrepâncias de offset, etc.). PyPDF2 não tem equivalente — a [própria documentação](https://pypi.org/project/PyPDF2/) está marcada como deprecated em favor de `pypdf` desde 2023.

Inventário de call-sites no repo (auditoria 2026-05-15):

```
$ grep -rn "from PyPDF2\|import PyPDF2\|from pypdf\|import pypdf" --include="*.py"
conversao/scripts/split_large_pdfs_smart.py:11:from PyPDF2 import PdfReader, PdfWriter
```

Único call-site. `conversao/docmind/{document,pipeline}.py` e `conversao/scripts/merge_results_full.py` usam apenas `pdf2image` (poppler bindings). Nenhum outro módulo toca PDF lib.

`libqpdf` já está disponível no sistema (`/lib64/libqpdf.so.30`); `pikepdf>=8.0.0` instala bindings sem build de C. Em CI sem `libqpdf`, `import pikepdf` quebra no `pytest collect` — não há `.github/workflows/` neste repo (auditoria 2026-05-15), mas se um for adicionado precisa de `apt install libqpdf-dev` antes de `pip install`.

## Decisão

**Substituir PyPDF2 por pikepdf como única dependência de manipulação de PDF no splitter.** Substituição completa, **não fallback**.

### Implementação

- `requirements.txt`: `PyPDF2>=3.0.0` → `pikepdf>=8.0.0`. Comentário do header lista `libqpdf` como peer obrigatório do `poppler`.
- `split_large_pdfs_smart.py:11`: `from PyPDF2 import PdfReader, PdfWriter` → `import pikepdf`.
- `split_pdf()`: `pikepdf.open(pdf_path)` em context manager para o reader. Para cada chunk, `with pikepdf.Pdf.new() as new_pdf: new_pdf.pages.extend(reader.pages[start:end]); new_pdf.save(tmp_path)`. Padrão tmp+rename + cleanup do `except` preservado (ADR-0005).
- `main()` loop: `with pikepdf.open(pdf_file) as reader: total_pages = len(reader.pages)`.
- `conversao/CLAUDE.md`: nova seção "System Dependencies" documentando poppler + libqpdf como peers C-side.

## Consequências

**Positivas**
- PDFs com trailer/xref ligeiramente fora de spec processam sem intervenção manual. `Dissertação_Carvalho.pdf` (e perfis similares) entram no fluxo normal.
- Uma única lib de PDF no repo (higiene).
- PyPDF2 `DeprecationWarning` eliminado da suite.
- `libqpdf` já é par do `poppler` que o pipeline depende — não introduz nova classe de dependência de sistema.

**Negativas / custos**
- **Nova dependência C-side em ambientes novos.** Quem clona o repo em macOS precisa de `brew install qpdf`; em Linux, `apt install libqpdf-dev`. Documentado em `conversao/CLAUDE.md`. Se um CI for adicionado, o setup precisa instalar libqpdf antes do `pip install`.
- **pikepdf recupera mais agressivamente** que PyPDF2. Há cenário teórico em que aceita um PDF que deveria ser rejeitado — mas pikepdf ainda lança em garbage total (testado em `test_split_pdf_still_errors_on_total_garbage`). Como o splitter agora aborta no primeiro erro (ADR-0005), um falso aceite causaria erro adiante no OCR, não silêncio.
- **Output binário diferente** entre `PdfWriter.write` e `pikepdf.Pdf.save`. Não há golden de chunks PDF na suite, então não regride testes. Validar em smoke real (Fase 5 do `PLANO_BUGFIXES_QUALITY_GATE.md`).

## Decisões descartadas

- **Manter PyPDF2 + fallback pikepdf no `except`:** dois call paths a manter sem ganho. Se pikepdf cobre PyPDF2 (e cobre, com folga), a coexistência é dívida técnica.
- **Migrar para `pypdf` (sucessor puro-Python do PyPDF2):** mesmo problema arquitetural — parser estrito em Python puro. Não resolve o caso `Dissertação_Carvalho.pdf`.
- **Manter PyPDF2 e exigir reparo manual upstream:** o operador já paga o custo de auditar; jogar pikepdf na operação não escala.
