#!/usr/bin/env python3
"""
Remove seções SUMÁRIO/ÍNDICE de arquivos Markdown processados.
Uso: python remove_sumario.py <diretório>
"""

import re
import os
import sys
from pathlib import Path


def is_toc_header(line: str) -> bool:
    """Verifica se a linha é um cabeçalho de sumário/índice."""
    line_clean = line.strip().upper()
    # Ignorar "SUMÁRIO EXECUTIVO" (é conteúdo, não navegação)
    if 'SUMÁRIO EXECUTIVO' in line_clean or 'SUMARIO EXECUTIVO' in line_clean:
        return False
    # Detectar cabeçalhos de sumário
    patterns = [
        r'^##?\s*(SUMÁRIO|ÍNDICE|SUMARIO|INDICE)\s*$',
        r'^(SUMÁRIO|ÍNDICE|SUMARIO|INDICE)\s*$',
        r'^##?\s*ÍNDICE\s+ONOMÁSTICO',
        r'^ÍNDICE\s+ONOMÁSTICO',
    ]
    for pattern in patterns:
        if re.match(pattern, line.strip(), re.IGNORECASE):
            return True
    return False


def is_toc_content(line: str) -> bool:
    """Verifica se a linha parece ser conteúdo de sumário (lista de capítulos)."""
    line_stripped = line.strip()
    if not line_stripped:
        return True  # Linhas em branco dentro do sumário
    # Padrões típicos de sumário:
    # - Linhas com ... e números de página
    # - Linhas com | e números
    # - Linhas começando com número e título em CAPS
    # - Linhas com seções numeradas (1.1, 2.3, etc)
    patterns = [
        r'\.{2,}\s*\d+',           # "CAPÍTULO 1...........17"
        r'\d+\s*\|',               # "06 | APRESENTAÇÃO"
        r'^\d+[\.\s].*\d+\s*$',    # "1 INTRODUÇÃO 17"
        r'^\d+\.\d+',              # "2.1 METODOLOGIA"
        r'^\*\*.*\*\*\s*$',        # "**Capítulo 1: ...**"
    ]
    for pattern in patterns:
        if re.search(pattern, line_stripped):
            return True
    return False


def is_toc_end(line: str) -> bool:
    """Verifica se a linha indica fim do sumário e início do conteúdo."""
    line_upper = line.strip().upper()
    # Palavras que indicam início do conteúdo real
    end_markers = [
        'PRÓLOGO', 'PROLOGO', 'PREFÁCIO', 'PREFACIO',
        'INTRODUÇÃO', 'INTRODUCAO', 'APRESENTAÇÃO', 'APRESENTACAO',
        'CAPÍTULO', 'CAPITULO', 'PARTE I', 'PARTE 1',
    ]
    # Linha começa com um desses marcadores (não é entrada de sumário)
    for marker in end_markers:
        if line_upper.startswith(marker) and '...' not in line and not re.search(r'\d+\s*$', line.strip()):
            return True
    # Header markdown
    if re.match(r'^§?\s*\n?##?\s+[A-Z]', line) and '...' not in line:
        return True
    return False


def remove_sumario(content: str) -> tuple[str, int]:
    """
    Remove seções SUMÁRIO/ÍNDICE do conteúdo.
    Retorna: (conteúdo_limpo, quantidade_removida)
    """
    original_len = len(content)
    lines = content.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if is_toc_header(line):
            # Encontrou cabeçalho de sumário, pular até o fim
            i += 1
            while i < len(lines):
                current = lines[i]
                # Verifica se chegou ao fim do sumário
                if is_toc_end(current):
                    break
                # Verifica se ainda é conteúdo de sumário
                if not is_toc_content(current) and current.strip():
                    # Linha com conteúdo real (não é sumário)
                    # Mas precisamos de pelo menos 3 linhas de conteúdo real
                    # para ter certeza que saímos do sumário
                    lookahead = 0
                    for j in range(i, min(i + 5, len(lines))):
                        if not is_toc_content(lines[j]) and lines[j].strip():
                            lookahead += 1
                    if lookahead >= 3:
                        break
                i += 1
            # Não incrementar i aqui - o loop while externo vai continuar do ponto certo
            continue
        else:
            result.append(line)
        i += 1

    new_content = '\n'.join(result)

    # Limpar linhas em branco excessivas
    new_content = re.sub(r'\n{4,}', '\n\n\n', new_content)

    removed = original_len - len(new_content)
    return new_content, removed


def process_directory(dir_path: str) -> dict:
    """Processa todos os arquivos .md no diretório."""
    results = {
        'processed': 0,
        'modified': 0,
        'total_removed': 0,
        'files': []
    }

    path = Path(dir_path)
    for file_path in sorted(path.glob('*.md')):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        new_content, removed = remove_sumario(content)

        if removed > 0:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            results['modified'] += 1
            results['total_removed'] += removed
            results['files'].append((file_path.name, removed))

        results['processed'] += 1

    return results


def main():
    if len(sys.argv) != 2:
        print("Uso: python remove_sumario.py <diretório>")
        sys.exit(1)

    dir_path = sys.argv[1]
    if not os.path.isdir(dir_path):
        print(f"Erro: {dir_path} não é um diretório válido")
        sys.exit(1)

    print(f"=== Removendo SUMÁRIO/ÍNDICE de {dir_path} ===\n")

    results = process_directory(dir_path)

    print(f"Arquivos processados: {results['processed']}")
    print(f"Arquivos modificados: {results['modified']}")
    print(f"Total removido: {results['total_removed']:,} caracteres")

    if results['files']:
        print("\nArquivos modificados:")
        for name, removed in results['files']:
            print(f"  - {name}: {removed:,} chars removidos")


if __name__ == '__main__':
    main()
