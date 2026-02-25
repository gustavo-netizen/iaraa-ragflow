#!/usr/bin/env python3
"""
Wrapper script para o book_converter.

Permite executar o conversor diretamente:
    python book_converter.py input.md -o output.md

Equivalente a:
    python -m book_converter input.md -o output.md

O módulo book_converter está em .claude/skills/convert-book/book_converter/
"""

import sys
from pathlib import Path

# Adicionar .claude/skills/convert-book ao path para encontrar o módulo
skills_path = Path(__file__).parent / '.claude' / 'skills' / 'convert-book'
sys.path.insert(0, str(skills_path))

from book_converter.cli import main

if __name__ == '__main__':
    exit(main())
