"""Construit un exécutable autonome avec PyInstaller.

Usage :  python build_executable.py
Résultat : dist/PDF Builder/ (Windows : « PDF Builder.exe », macOS : « PDF Builder.app »).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
icon = ROOT / "pdf_builder" / "assets" / ("icon.ico" if sys.platform.startswith("win") else "icon.png")
sep = ";" if sys.platform.startswith("win") else ":"

cmd = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--windowed",
    "--name",
    "PDF Builder",
    "--icon",
    str(icon),
    "--add-data",
    f"{ROOT / 'pdf_builder' / 'assets'}{sep}pdf_builder/assets",
    "--collect-all",
    "pymupdf",
    "--collect-all",
    "pyhanko",
    "--collect-all",
    "pyhanko_certvalidator",
    "--collect-data",
    "pptx",
    "--collect-submodules",
    "pdf_builder",
    "--hidden-import",
    "pymupdf4llm",
    str(ROOT / "run_pdf_builder.py"),
]
print(" ".join(cmd))
sys.exit(subprocess.call(cmd, cwd=ROOT))
