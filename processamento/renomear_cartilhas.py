#!/usr/bin/env python3
"""Renomeia cartilhas processadas para seus títulos originais."""

import json
import re
from pathlib import Path

RELATORIO = "relatorio_cartilhas.json"
DIRETORIO = "/home/gustavo/Downloads/results_md_yaml/Cartilhas/Cartilhas_Processadas"


def sanitizar_nome(titulo: str, max_len: int = 100) -> str:
    """Converte título para nome de arquivo válido."""
    # Remover/substituir caracteres inválidos
    nome = re.sub(r'[/\\:*?"<>|]', '_', titulo)
    # Normalizar espaços
    nome = ' '.join(nome.split())
    # Limitar tamanho
    if len(nome) > max_len:
        nome = nome[:max_len].rsplit(' ', 1)[0]
    return nome


def nome_arquivo_para_titulo(filename: str) -> str:
    """Converte nome de arquivo em título legível."""
    # Remover extensão
    nome = filename.rsplit('.', 1)[0]
    # Remover prefixo numérico (ex: "19-" ou "Editado-")
    nome = re.sub(r'^(\d+-|Editado-)', '', nome)
    # Remover sufixo "-1" comum
    nome = re.sub(r'-1$', '', nome)
    # Substituir hífens e underscores por espaços
    nome = nome.replace('-', ' ').replace('_', ' ')
    # Title case
    nome = nome.title()
    # Corrigir artigos/preposições em português
    for palavra in ['De', 'Do', 'Da', 'Dos', 'Das', 'E', 'Em', 'Com', 'Para', 'Por']:
        nome = nome.replace(f' {palavra} ', f' {palavra.lower()} ')
    return nome.strip()


def renomear_cartilhas(dry_run: bool = False):
    """Renomeia arquivos baseado no relatório JSON."""
    with open(RELATORIO) as f:
        data = json.load(f)

    diretorio = Path(DIRETORIO)
    nomes_usados = set()
    renomeados = 0
    mantidos = 0

    for cartilha in data['cartilhas']:
        arquivo_atual = cartilha['arquivo']
        titulo = cartilha['metadados'].get('titulo')

        if not titulo:
            titulo = nome_arquivo_para_titulo(arquivo_atual)
            print(f"DERIVAR: {arquivo_atual} -> título: '{titulo}'")

        novo_nome = sanitizar_nome(titulo) + '.md'

        # Evitar colisões
        base_nome = novo_nome
        contador = 2
        while novo_nome.lower() in nomes_usados:
            novo_nome = f"{base_nome[:-3]} ({contador}).md"
            contador += 1
        nomes_usados.add(novo_nome.lower())

        if novo_nome == arquivo_atual:
            print(f"IGUAL: {arquivo_atual}")
            mantidos += 1
            continue

        path_atual = diretorio / arquivo_atual
        path_novo = diretorio / novo_nome

        if dry_run:
            print(f"RENOMEAR: {arquivo_atual} -> {novo_nome}")
        else:
            path_atual.rename(path_novo)
            print(f"OK: {arquivo_atual} -> {novo_nome}")
        renomeados += 1

    print(f"\nTotal: {renomeados} renomeados, {mantidos} mantidos")


if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== MODO DRY-RUN (sem alterações) ===\n")
    renomear_cartilhas(dry_run=dry_run)
