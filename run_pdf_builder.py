"""Lanceur de PDF Builder (utilisé aussi comme point d'entrée PyInstaller)."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from pdf_builder.ui.app import run

    sys.exit(run(sys.argv))
