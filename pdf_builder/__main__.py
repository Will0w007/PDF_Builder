"""Point d'entrée : ``python -m pdf_builder``.

Ce module reste volontairement minimal : le processus de travail (worker) est
lancé en mode « spawn » et ré-importe ce fichier ; aucun import Qt ne doit donc
avoir lieu au niveau du module.
"""

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from pdf_builder.ui.app import run

    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
