"""
Interface de linha de comando para o ficha_converter.

Uso:
    python -m ficha_converter input.md -o output.md [opções]
"""

import argparse
from pathlib import Path

from .cleanup import clean_all, optimize_for_ragflow
from .extraction import extract_all, format_extraction_summary
from .frontmatter import generate_frontmatter, generate_tags, test_frontmatter
from .restructure import (
    restructure_sections,
    format_steps,
    format_bullets,
    extract_body,
    assemble_document,
)
from .table_injector import find_yaml_file, load_tables_from_yaml, inject_tables_in_body


def convert_full(content: str, filename: str, verbose: bool = False,
                 input_path: str = None) -> str:
    """
    Pipeline completo de conversão (Fases 1-6) otimizado para RAGFlow.

    1. Limpa artefatos do systemRAG
    2. Extrai metadados (título, autores, etc.)
    3. Gera YAML frontmatter
    4. Reestrutura conteúdo e monta documento final
    4.5. Injeta tabelas do YAML (se disponível)
    5. Otimiza para RAGFlow (junta parágrafos)
    6. Insere marcadores de seção

    Args:
        content: Conteúdo do arquivo de entrada
        filename: Nome do arquivo
        verbose: Se True, mostra warnings
        input_path: Caminho do arquivo de entrada (para buscar YAML)

    Returns:
        Documento convertido
    """
    # Fase 1: Limpeza
    cleaned = clean_all(content)

    # Fase 2: Extração de dados
    # Nota: título é extraído do conteúdo ORIGINAL porque clean_all()
    # remove linhas ALL CAPS (que incluem o título)
    from .extraction import extract_title
    title = extract_title(content)  # Do original, antes de remover ALL CAPS
    data = extract_all(cleaned, filename, verbose=verbose)
    if not title:
        title = data['title']  # Fallback para extração do conteúdo limpo
    elif verbose and not data['title']:
        pass  # Não mostrar warning se já extraímos do original
    authors = data['authors']
    ficha_number = data['ficha_number']
    resumo = data['resumo']

    # Fase 3: YAML frontmatter
    tags = generate_tags(title, cleaned)
    frontmatter = generate_frontmatter(filename, title, authors, ficha_number, tags, resumo)

    # Fase 4: Reestruturação
    body = extract_body(cleaned, title)
    body = restructure_sections(body)
    body = format_steps(body)
    body = format_bullets(body)

    # Fase 4.5: Injetar tabelas do YAML
    if input_path:
        yaml_path = find_yaml_file(input_path)
        if yaml_path:
            tables = load_tables_from_yaml(yaml_path)
            if tables:
                if verbose:
                    print(f"  Encontradas {len(tables)} tabela(s) no YAML")
                body = inject_tables_in_body(body, tables)

    # Fase 5-6: Otimização para RAGFlow
    body = optimize_for_ragflow(body)

    # Montar documento final
    return assemble_document(frontmatter, title, authors, ficha_number, body)


def process_file(input_path: Path, output_path: Path, verbose: bool = False,
                 full_conversion: bool = True, dry_run: bool = False) -> bool:
    """
    Processa um único arquivo.

    Args:
        input_path: Caminho do arquivo de entrada
        output_path: Caminho do arquivo de saída
        verbose: Se True, mostra informações detalhadas
        full_conversion: Se True, executa pipeline completo (Fases 1-6).
                        Se False, apenas limpeza (Fase 1).
        dry_run: Se True, não escreve o arquivo (apenas preview)

    Returns:
        True se sucesso, False se erro
    """
    try:
        content = input_path.read_text(encoding='utf-8')

        if verbose:
            print(f"Processando: {input_path.name}")
            print(f"  Tamanho original: {len(content):,} caracteres")

        if full_conversion:
            # Pipeline completo (Fases 1-6)
            result = convert_full(content, input_path.name, verbose=verbose,
                                  input_path=str(input_path))
            if verbose:
                print("  Conversão completa (Fases 1-6)")
        else:
            # Apenas limpeza (Fase 1)
            result = clean_all(content)
            if verbose:
                print("  Apenas limpeza (Fase 1)")

        if verbose:
            print(f"  Tamanho final: {len(result):,} caracteres")

        # Dry-run: apenas mostra o que seria feito
        if dry_run:
            print(f"[DRY-RUN] Escreveria {len(result):,} caracteres em {output_path}")
            if full_conversion:
                data = extract_all(clean_all(content), input_path.name)
                print(f"  Título: {data['title'] or '(não encontrado)'}")
                print(f"  Autores: {len(data['authors'])} encontrado(s)")
            return True

        # Criar diretório de saída se necessário
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Salvar resultado
        result_with_newline = result if result.endswith('\n') else result + '\n'
        output_path.write_text(result_with_newline, encoding='utf-8')

        if verbose:
            print(f"  Salvo em: {output_path}")

        return True

    except Exception as e:
        print(f"Erro ao processar {input_path}: {e}")
        import traceback
        if verbose:
            traceback.print_exc()
        return False


def process_directory(input_dir: Path, output_dir: Path, verbose: bool = False,
                      full_conversion: bool = True, dry_run: bool = False) -> tuple[int, int]:
    """
    Processa todos os arquivos .md em um diretório.

    Args:
        input_dir: Diretório de entrada
        output_dir: Diretório de saída
        verbose: Se True, mostra informações detalhadas
        full_conversion: Se True, executa pipeline completo (Fases 1-6)
        dry_run: Se True, não escreve arquivos (apenas preview)

    Returns:
        Tupla (sucesso, falhas)
    """
    success = 0
    failed = 0

    md_files = list(input_dir.glob('*.md'))

    if not md_files:
        print(f"Nenhum arquivo .md encontrado em {input_dir}")
        return 0, 0

    print(f"Encontrados {len(md_files)} arquivos .md")
    if full_conversion:
        print("Modo: Conversão completa (Fases 1-6)")
    else:
        print("Modo: Apenas limpeza (Fase 1)")
    if dry_run:
        print("Modo: DRY-RUN (sem escrita)")
    print()

    for input_path in md_files:
        output_path = output_dir / input_path.name

        if process_file(input_path, output_path, verbose, full_conversion, dry_run):
            success += 1
        else:
            failed += 1

    print(f"\nResultado: {success} sucesso, {failed} falhas")
    return success, failed


def test_extraction_cmd(input_path: Path, verbose: bool = False) -> bool:
    """
    Testa a extração de metadados (Fase 2).
    """
    try:
        if input_path.is_dir():
            files = list(input_path.glob('*.md'))
        else:
            files = [input_path]

        print(f"Testando extração em {len(files)} arquivo(s)...\n")
        print("=" * 80)

        for f in files:
            content = f.read_text(encoding='utf-8')
            cleaned = clean_all(content)
            data = extract_all(cleaned, f.name, verbose=verbose)
            print(format_extraction_summary(data, f.name))
            print("-" * 80)

        return True

    except Exception as e:
        print(f"Erro: {e}")
        return False


def test_yaml_cmd(input_path: Path, verbose: bool = False) -> bool:
    """
    Testa a geração de YAML frontmatter (Fase 3).
    """
    try:
        if input_path.is_dir():
            files = list(input_path.glob('*.md'))
        else:
            files = [input_path]

        print(f"Testando geração de YAML em {len(files)} arquivo(s)...\n")

        for f in files:
            content = f.read_text(encoding='utf-8')
            cleaned = clean_all(content)
            frontmatter = test_frontmatter(cleaned, f.name)

            print(f"=== {f.name} ===")
            print(frontmatter)
            print()

        return True

    except Exception as e:
        print(f"Erro: {e}")
        return False


def main() -> int:
    """Entry point do CLI."""
    parser = argparse.ArgumentParser(
        description='Converte MD systemRAG para formato estruturado',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Exemplos de uso:
  # Converter arquivo único (pipeline completo)
  python -m ficha_converter "MD/MD systemRAG/10-biofertilizante-vairo-1.md" -o "output.md"

  # Converter diretório inteiro
  python -m ficha_converter "MD/MD systemRAG/" -o "MD/converted/" --batch -v

  # Apenas limpeza (sem reestruturação)
  python -m ficha_converter "arquivo.md" -o "saida.md" --clean-only

  # Preview sem escrever (dry-run)
  python -m ficha_converter "arquivo.md" -o "saida.md" --dry-run -v

  # Testar extração de dados
  python -m ficha_converter "MD/MD systemRAG/" --test-extract

  # Testar geração de YAML
  python -m ficha_converter "MD/MD systemRAG/" --test-yaml
'''
    )
    parser.add_argument('input', help='Arquivo ou diretório de entrada')
    parser.add_argument('-o', '--output', help='Arquivo ou diretório de saída')
    parser.add_argument('--batch', action='store_true', help='Processar diretório inteiro')
    parser.add_argument('-v', '--verbose', action='store_true', help='Output detalhado')
    parser.add_argument('--clean-only', action='store_true',
                        help='Apenas limpeza (Fase 1), sem reestruturação')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview sem escrever arquivos')
    parser.add_argument('--test-extract', action='store_true',
                        help='Testar extração de dados (Fase 2)')
    parser.add_argument('--test-yaml', action='store_true',
                        help='Testar geração de YAML frontmatter (Fase 3)')

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Erro: {input_path} não existe")
        return 1

    # Modo de teste de YAML (Fase 3)
    if args.test_yaml:
        success = test_yaml_cmd(input_path, args.verbose)
        return 0 if success else 1

    # Modo de teste de extração (Fase 2)
    if args.test_extract:
        success = test_extraction_cmd(input_path, args.verbose)
        return 0 if success else 1

    # Modo normal (requer output)
    if not args.output:
        print("Erro: -o/--output é obrigatório (exceto com --test-extract ou --test-yaml)")
        return 1

    output_path = Path(args.output)
    full_conversion = not args.clean_only

    if args.batch:
        if not input_path.is_dir():
            print(f"Erro: {input_path} não é um diretório")
            return 1
        process_directory(input_path, output_path, args.verbose, full_conversion, args.dry_run)
    else:
        if not input_path.is_file():
            print(f"Erro: {input_path} não é um arquivo")
            return 1
        process_file(input_path, output_path, args.verbose, full_conversion, args.dry_run)

    return 0


if __name__ == '__main__':
    exit(main())
