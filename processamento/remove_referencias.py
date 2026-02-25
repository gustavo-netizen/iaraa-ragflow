#!/usr/bin/env python3
"""
Remove TODAS as seções de REFERÊNCIAS/BIBLIOGRAFIA de arquivos Markdown processados.
Uso: python remove_referencias.py <diretório>
"""

import re
import os
import sys
from pathlib import Path


def is_ref_header(line: str) -> bool:
    """Verifica se a linha é um cabeçalho de referências/bibliografia."""
    line_stripped = line.strip()

    # Ignorar entradas de sumário (linhas que terminam com pontos ou números de página)
    if re.search(r'\.{3,}\s*\d*\s*$', line_stripped):
        return False

    # Padrões de cabeçalho de referências
    patterns = [
        # Padrão exato: ## Referências (fim da linha)
        r'^§?\s*##\s*(Referências|Referencias|Bibliografia|Referências bibliográficas|Referencias bibliograficas|Bibliografia citada)\s*$',
        # Padrão com subtítulo: ## Referências: Quer saber mais?
        r'^§?\s*##\s*(Referências|Referencias|Bibliografia|Referências bibliográficas|Referencias bibliograficas|Bibliografia citada)\s*:',
        # Padrão sem markdown
        r'^(Referências|Referencias|Bibliografia|Referências bibliográficas|Referencias bibliograficas|Bibliografia citada)\s*$',
    ]
    for pattern in patterns:
        if re.match(pattern, line_stripped, re.IGNORECASE):
            return True
    return False


def is_ref_end(line: str) -> bool:
    """Verifica se a linha indica fim da seção de referências."""
    line_stripped = line.strip()
    # Próximo § seguido de ## indica nova seção
    if line_stripped == '§':
        return True
    # Header markdown de nível 2 (não referências)
    if re.match(r'^##\s+(?!Referências|Referencias|Bibliografia)', line_stripped, re.IGNORECASE):
        return True
    # Header de nível 1
    if re.match(r'^#\s+[^#]', line_stripped):
        return True
    return False


def remove_referencias(content: str) -> tuple[str, int, int]:
    """
    Remove TODAS as seções de REFERÊNCIAS/BIBLIOGRAFIA.
    Retorna: (conteúdo_limpo, caracteres_removidos, seções_removidas)
    """
    original_len = len(content)
    lines = content.split('\n')
    result = []
    sections_removed = 0
    i = 0
    in_section_marker = False  # Track if previous line was §

    while i < len(lines):
        line = lines[i]

        # Check if this line or previous § + this line is a ref header
        check_line = line
        if in_section_marker and result and result[-1].strip() == '§':
            # Previous line was §, check if current is ref header
            if is_ref_header(line):
                # Remove the § we just added
                result.pop()
                sections_removed += 1
                i += 1
                # Skip until end of references section
                while i < len(lines):
                    if is_ref_end(lines[i]):
                        break
                    i += 1
                in_section_marker = False
                continue

        if is_ref_header(line):
            sections_removed += 1
            i += 1
            # Skip until end of references section
            while i < len(lines):
                if is_ref_end(lines[i]):
                    break
                i += 1
            in_section_marker = False
            continue

        # Track § markers
        in_section_marker = line.strip() == '§'
        result.append(line)
        i += 1

    new_content = '\n'.join(result)

    # Limpar linhas em branco excessivas
    new_content = re.sub(r'\n{4,}', '\n\n\n', new_content)

    # Remover § órfãos no final do arquivo
    new_content = re.sub(r'\n§\s*\n*$', '\n', new_content)

    # Remover § duplicados
    new_content = re.sub(r'§\s*\n\s*§', '§', new_content)

    removed = original_len - len(new_content)
    return new_content, removed, sections_removed


def process_directory(dir_path: str) -> dict:
    """Processa todos os arquivos .md no diretório."""
    results = {
        'processed': 0,
        'modified': 0,
        'total_removed': 0,
        'total_sections': 0,
        'files': []
    }

    path = Path(dir_path)
    for file_path in sorted(path.glob('*.md')):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        new_content, removed, sections = remove_referencias(content)

        if removed > 0:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            results['modified'] += 1
            results['total_removed'] += removed
            results['total_sections'] += sections
            results['files'].append((file_path.name, removed, sections))

        results['processed'] += 1

    return results


def main():
    if len(sys.argv) != 2:
        print("Uso: python remove_referencias.py <diretório>")
        sys.exit(1)

    dir_path = sys.argv[1]
    if not os.path.isdir(dir_path):
        print(f"Erro: {dir_path} não é um diretório válido")
        sys.exit(1)

    print(f"=== Removendo REFERÊNCIAS de {dir_path} ===\n")

    results = process_directory(dir_path)

    print(f"Arquivos processados: {results['processed']}")
    print(f"Arquivos modificados: {results['modified']}")
    print(f"Seções removidas: {results['total_sections']}")
    print(f"Total removido: {results['total_removed']:,} caracteres")

    if results['files']:
        print("\nArquivos modificados:")
        for name, removed, sections in results['files']:
            print(f"  - {name}: {sections} seções, {removed:,} chars")


if __name__ == '__main__':
    main()
