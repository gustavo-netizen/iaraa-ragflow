#!/usr/bin/env python3
"""Gera relatório JSON com metadados de todas as cartilhas processadas."""

import json
import yaml
from pathlib import Path
from datetime import datetime

DIRETORIO_CARTILHAS = "/home/gustavo/Downloads/results_md_yaml/Cartilhas/Cartilhas_Processadas"
SAIDA_JSON = "/home/gustavo/Desktop/iaraa/relatorio_cartilhas.json"


def extrair_frontmatter(content: str) -> dict:
    """Extrai YAML frontmatter do conteúdo markdown."""
    if not content.startswith('---'):
        return {}
    end = content.find('---', 3)
    if end == -1:
        return {}
    yaml_content = content[3:end].strip()

    # Tentar parsing YAML normal primeiro
    try:
        return yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        pass

    # Fallback: parsing linha a linha para YAML mal formatado
    result = {}
    for line in yaml_content.split('\n'):
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()

        # Parsear listas simples [item1, item2]
        if value.startswith('[') and value.endswith(']'):
            items = value[1:-1].split(',')
            result[key] = [item.strip().strip('"\'') for item in items if item.strip()]
        # Parsear números
        elif value.isdigit():
            result[key] = int(value)
        # String normal
        else:
            result[key] = value

    return result


def processar_arquivo(path: Path) -> dict:
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
        "tamanho_bytes": path.stat().st_size,
        "metadados": extrair_frontmatter(content)
    }


def gerar_relatorio():
    """Gera relatório JSON de todas as cartilhas."""
    diretorio = Path(DIRETORIO_CARTILHAS)
    arquivos = sorted(diretorio.glob("*.md"))

    cartilhas = [processar_arquivo(f) for f in arquivos if not f.name.startswith('.')]

    relatorio = {
        "gerado_em": datetime.now().isoformat(),
        "total_arquivos": len(cartilhas),
        "diretorio": str(diretorio),
        "cartilhas": cartilhas
    }

    with open(SAIDA_JSON, 'w', encoding='utf-8') as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    print(f"Relatório gerado: {SAIDA_JSON}")
    print(f"Total de cartilhas: {len(cartilhas)}")


if __name__ == "__main__":
    gerar_relatorio()
