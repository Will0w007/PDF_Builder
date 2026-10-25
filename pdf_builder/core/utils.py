"""Fonctions utilitaires partagées par les outils PDF."""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import pymupdf as fitz

PAPER_SIZES = {
    "A3": (842, 1191),
    "A4": (595, 842),
    "A5": (420, 595),
    "Letter": (612, 792),
    "Legal": (612, 1008),
}

PAPER_CHOICES = [(k, k) for k in PAPER_SIZES]

MM = 72 / 25.4

FONT_CHOICES = [
    ("helv", "Helvetica"),
    ("hebo", "Helvetica gras"),
    ("tiro", "Times"),
    ("tibo", "Times gras"),
    ("cour", "Courier"),
    ("cobo", "Courier gras"),
]

POSITION_CHOICES = [
    ("top-left", "En haut à gauche"),
    ("top-center", "En haut au centre"),
    ("top-right", "En haut à droite"),
    ("center", "Centre"),
    ("bottom-left", "En bas à gauche"),
    ("bottom-center", "En bas au centre"),
    ("bottom-right", "En bas à droite"),
]


class PageRangeError(ValueError):
    pass


def parse_pages(spec: str | None, count: int) -> list[int]:
    """Convertit une expression de pages (1-based) en indices 0-based.

    Syntaxe acceptée : ``""``/``tout``/``all`` → toutes les pages ; ``1-3,5,8-``,
    ``-4`` (jusqu'à 4), ``fin``/``last``/``n`` (dernière page), ``fin-2``,
    ``paires``/``even``, ``impaires``/``odd``. Les doublons sont conservés dans
    l'ordre indiqué (utile pour réorganiser) sauf pour les mots-clés.
    """
    if count <= 0:
        return []
    s = (spec or "").strip().lower()
    if s in ("", "tout", "toutes", "all", "*"):
        return list(range(count))
    if s in ("paires", "pair", "even"):
        return list(range(1, count, 2))
    if s in ("impaires", "impair", "odd"):
        return list(range(0, count, 2))

    def num(token: str) -> int:
        token = token.strip()
        m = re.fullmatch(r"(fin|last|n|end|z)(?:\s*-\s*(\d+))?", token)
        if m:
            return count - int(m.group(2) or 0)
        if not token.isdigit():
            raise PageRangeError(f"Numéro de page invalide : « {token} »")
        return int(token)

    result: list[int] = []
    for part in re.split(r"[,;\s]+", s):
        if not part:
            continue
        m = re.fullmatch(r"((?:fin|last|n|end|z)(?:-\d+)?|\d*)\s*(-|:|à|to)?\s*((?:fin|last|n|end|z)(?:-\d+)?|\d*)", part)
        if not m or (not m.group(1) and not m.group(3)):
            raise PageRangeError(f"Plage invalide : « {part} »")
        a, sep, b = m.group(1), m.group(2), m.group(3)
        if sep:
            start = num(a) if a else 1
            end = num(b) if b else count
        else:
            start = end = num(a)
        if start < 1 or start > count:
            raise PageRangeError(f"La page {start} n'existe pas (le document en compte {count}).")
        end = max(1, min(end, count))
        step = 1 if end >= start else -1
        result.extend(i - 1 for i in range(start, end + step, step))
    return result


def parse_groups(spec: str, count: int) -> list[list[int]]:
    """Plusieurs groupes de plages séparés par ``;`` ou ``|`` → liste de listes."""
    groups = [g for g in re.split(r"[;|]", spec or "") if g.strip()]
    return [parse_pages(g.replace(" ", ","), count) for g in groups]


def parse_color(value, default=(0, 0, 0)) -> tuple[float, float, float]:
    """Accepte ``#RRGGBB``, ``RRGGBB`` ou un tuple (0-1 ou 0-255)."""
    if value is None or value == "":
        return default
    if isinstance(value, (tuple, list)):
        vals = [float(v) for v in value[:3]]
        if any(v > 1 for v in vals):
            vals = [v / 255 for v in vals]
        return tuple(vals)  # type: ignore[return-value]
    s = str(value).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        return default
    return tuple(int(s[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def unique_path(path: Path) -> Path:
    """Renvoie un chemin libre en ajoutant `` (2)``, `` (3)``… si nécessaire."""
    path = Path(path)
    if not path.exists():
        return path
    i = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def human_size(n: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if abs(n) < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} Go"


def safe_filename(name: str, fallback: str = "document") -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(name)).strip(" .")
    return name[:150] or fallback


def expand_vars(template: str, *, n: int = 1, total: int = 1, filename: str = "", title: str = "", author: str = "") -> str:
    """Remplace les variables ``{n}``, ``{total}``, ``{date}``, ``{heure}``, ``{fichier}``…"""
    now = _dt.datetime.now()
    values = {
        "n": str(n),
        "page": str(n),
        "total": str(total),
        "date": now.strftime("%d/%m/%Y"),
        "heure": now.strftime("%H:%M"),
        "time": now.strftime("%H:%M"),
        "fichier": filename,
        "file": filename,
        "titre": title,
        "title": title,
        "auteur": author,
        "author": author,
    }

    def repl(m: re.Match) -> str:
        key = m.group(1).lower()
        return values.get(key, m.group(0))

    return re.sub(r"\{(\w+)\}", repl, template)


def anchor_point(rect: fitz.Rect, position: str, w: float, h: float, margin: float) -> fitz.Point:
    """Coin supérieur gauche d'une boîte ``w``×``h`` placée selon ``position``."""
    vert, _, horiz = position.partition("-")
    if position == "center":
        vert, horiz = "middle", "center"
    if horiz == "left":
        x = rect.x0 + margin
    elif horiz == "right":
        x = rect.x1 - margin - w
    else:
        x = rect.x0 + (rect.width - w) / 2
    if vert == "top":
        y = rect.y0 + margin
    elif vert == "bottom":
        y = rect.y1 - margin - h
    else:
        y = rect.y0 + (rect.height - h) / 2
    return fitz.Point(x, y)


def page_is_blank(page: fitz.Page, sensitivity: float = 0.3) -> bool:
    """Détecte une page blanche (y compris un scan légèrement bruité).

    ``sensitivity`` est le pourcentage maximal de pixels sombres toléré.
    """
    if page.get_text("text").strip():
        return False
    pix = page.get_pixmap(dpi=24, colorspace=fitz.csGRAY, alpha=False)
    samples = pix.samples
    if not samples:
        return True
    table = bytes(1 if b < 180 else 0 for b in range(256))
    dark = samples.translate(table).count(1)
    return dark / len(samples) * 100 <= sensitivity


def fit_rect(content_w: float, content_h: float, box: fitz.Rect) -> fitz.Rect:
    """Rectangle centré dans ``box`` respectant les proportions du contenu."""
    if content_w <= 0 or content_h <= 0:
        return fitz.Rect(box)
    scale = min(box.width / content_w, box.height / content_h)
    w, h = content_w * scale, content_h * scale
    x0 = box.x0 + (box.width - w) / 2
    y0 = box.y0 + (box.height - h) / 2
    return fitz.Rect(x0, y0, x0 + w, y0 + h)


def make_upright(doc: fitz.Document) -> fitz.Document:
    """Supprime la rotation des pages *en mémoire* en conservant leur apparence.

    ``show_pdf_page`` ignore la rotation de la page source ; on la « cuit » donc
    dans le contenu avant toute imposition.
    """
    for page in doc:
        if page.rotation:
            page.remove_rotation()
    return doc
