"""Détection des programmes externes optionnels (LibreOffice, Tesseract)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _candidates_soffice() -> list[str]:
    if sys.platform.startswith("win"):
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
        return [str(Path(r) / "LibreOffice" / "program" / "soffice.exe") for r in roots if r]
    if sys.platform == "darwin":
        return ["/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    return ["/usr/bin/soffice", "/usr/bin/libreoffice", "/snap/bin/libreoffice", "/opt/libreoffice/program/soffice"]


def find_soffice(custom: str | None = None) -> str | None:
    if custom and Path(custom).exists():
        return custom
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for c in _candidates_soffice():
        if Path(c).exists():
            return c
    return None


def find_ghostscript(custom: str | None = None) -> str | None:
    if custom and Path(custom).exists():
        return custom
    for name in ("gswin64c", "gswin32c", "gs"):
        found = shutil.which(name)
        if found:
            return found
    if sys.platform.startswith("win"):
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            for exe in sorted(Path(root, "gs").glob("gs*/bin/gswin*c.exe"), reverse=True):
                return str(exe)
    return None


def find_tessdata(custom: str | None = None) -> str | None:
    """Renvoie le dossier ``tessdata`` de Tesseract s'il est trouvé."""
    candidates = [custom, os.environ.get("TESSDATA_PREFIX")]
    if sys.platform.startswith("win"):
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("LOCALAPPDATA", "")):
            if root:
                candidates.append(str(Path(root) / "Tesseract-OCR" / "tessdata"))
                candidates.append(str(Path(root) / "Programs" / "Tesseract-OCR" / "tessdata"))
    elif sys.platform == "darwin":
        candidates += ["/opt/homebrew/share/tessdata", "/usr/local/share/tessdata"]
    else:
        candidates += [
            "/usr/share/tesseract-ocr/5/tessdata",
            "/usr/share/tesseract-ocr/4.00/tessdata",
            "/usr/share/tessdata",
            "/usr/local/share/tessdata",
        ]
    for c in candidates:
        if c and Path(c).is_dir() and any(Path(c).glob("*.traineddata")):
            return str(c)
    try:
        import pymupdf

        found = pymupdf.get_tessdata()
        if found and Path(found).is_dir():
            return str(found)
    except Exception:  # noqa: BLE001
        pass
    return None


def tesseract_languages(tessdata: str | None) -> list[str]:
    if not tessdata:
        return []
    return sorted(p.stem for p in Path(tessdata).glob("*.traineddata") if p.stem != "osd")


def office_to_pdf(src: Path, out_dir: Path, soffice: str, timeout: int = 180) -> Path:
    """Convertit un document bureautique en PDF avec LibreOffice (mode sans interface)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = out_dir / ".lo_profile"
    cmd = [
        soffice,
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--headless",
        "--norestore",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir),
        str(src),
    ]
    flags = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW
    subprocess.run(cmd, check=False, capture_output=True, timeout=timeout, creationflags=flags)
    shutil.rmtree(profile, ignore_errors=True)
    result = out_dir / (src.stem + ".pdf")
    if not result.exists():
        raise RuntimeError("LibreOffice n'a pas pu convertir ce fichier.")
    return result
