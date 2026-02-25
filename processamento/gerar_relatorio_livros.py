#!/usr/bin/env python3
"""Gera relatório JSON unificado dos livros processados."""

import json
import yaml
from pathlib import Path
from datetime import datetime

DIRETORIOS = {
    "lote1": "/home/gustavo/Downloads/results_md_yaml/Livros/Livros_Processados",
    "lote2": "/home/gustavo/Downloads/results_md_yaml/Livros_2/Livros_Processados_2.1"
}
SAIDA_JSON = "/home/gustavo/Desktop/iaraa/relatorio_livros.json"


def extrair_frontmatter(content: str) -> dict:
    """Extrai YAML frontmatter do conteúdo markdown."""
    # Verificar se começa com ---
    if not content.lstrip().startswith('---'):
        return {}

    content = content.lstrip()
    end = content.find('---', 3)
    if end == -1:
        return {}

    yaml_content = content[3:end].strip()

    try:
        return yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        pass

    # Fallback: parsing linha a linha
    result = {}
    for line in yaml_content.split('\n'):
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()

        if value.startswith('[') and value.endswith(']'):
            items = value[1:-1].split(',')
            result[key] = [item.strip().strip('"\'') for item in items if item.strip()]
        elif value.isdigit():
            result[key] = int(value)
        else:
            result[key] = value.strip('"\'')

    return result


def processar_arquivo(path: Path, lote: str) -> dict:
    """Processa um arquivo e retorna seus metadados."""
    # Tentar múltiplos encodings
    for encoding in ['utf-8', 'latin-1', 'cp1252']:
        try:
            content = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        content = path.read_text(encoding='utf-8', errors='replace')

    return {
        "arquivo": path.name,
        "lote": lote,
        "tamanho_bytes": path.stat().st_size,
        "metadados": extrair_frontmatter(content)
    }


def gerar_relatorio():
    """Gera relatório JSON unificado de todos os livros."""
    livros = []

    for lote, diretorio in DIRETORIOS.items():
        path = Path(diretorio)
        if not path.exists():
            print(f"AVISO: Diretório não encontrado: {diretorio}")
            continue

        arquivos = sorted(path.glob("*.md"))
        for f in arquivos:
            if f.name.startswith('.'):
                continue
            livros.append(processar_arquivo(f, lote))
            print(f"  {lote}: {f.name}")

    relatorio = {
        "gerado_em": datetime.now().isoformat(),
        "total_livros": len(livros),
        "diretorios": DIRETORIOS,
        "livros": livros
    }

    with open(SAIDA_JSON, 'w', encoding='utf-8') as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    print(f"\nRelatório gerado: {SAIDA_JSON}")
    print(f"Total de livros: {len(livros)}")


if __name__ == "__main__":
    gerar_relatorio()
