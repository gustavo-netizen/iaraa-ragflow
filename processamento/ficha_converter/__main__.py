"""
Entry point para execução como módulo.

Uso:
    python -m ficha_converter [argumentos]
"""

from .cli import main

if __name__ == '__main__':
    exit(main())
