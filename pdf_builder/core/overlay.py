"""Dessin dans le repère *visuel* d'une page (rotation de page prise en compte).

Le contenu est dessiné sur une page temporaire aux dimensions visibles de la page
cible, puis incrusté avec ``show_pdf_page``. Ainsi, un tampon placé « en bas à
droite » reste en bas à droite même si la page est pivotée.
"""

from __future__ import annotations

import io
from typing import Callable

import pymupdf as fitz


def stamp(page: fitz.Page, draw: Callable[[fitz.Page], None], overlay: bool = True) -> None:
    tmp = fitz.open()
    op = tmp.new_page(width=page.rect.width, height=page.rect.height)
    draw(op)
    target = page.rect * page.derotation_matrix
    page.show_pdf_page(target, tmp, 0, rotate=page.rotation, overlay=overlay)
    tmp.close()


def visual_to_page(page: fitz.Page, obj):
    """Convertit un point/rectangle du repère visuel vers le repère PDF non pivoté."""
    return obj * page.derotation_matrix


def text_width(text: str, fontname: str, fontsize: float) -> float:
    return max(fitz.get_text_length(line, fontname=fontname, fontsize=fontsize) for line in text.split("\n") or [""])


def draw_text_box(
    op: fitz.Page,
    text: str,
    topleft: fitz.Point,
    fontsize: float,
    fontname: str = "helv",
    color=(0, 0, 0),
    opacity: float = 1.0,
    angle: float = 0,
    pivot: fitz.Point | None = None,
    lineheight: float = 1.2,
) -> fitz.Rect:
    """Écrit un texte (multi-ligne) dont la boîte commence en ``topleft``."""
    lines = text.split("\n")
    w = text_width(text, fontname, fontsize)
    h = fontsize * lineheight * len(lines)
    morph = None
    if angle:
        morph = (pivot or fitz.Point(topleft.x + w / 2, topleft.y + h / 2), fitz.Matrix(angle))  # angle > 0 : sens antihoraire
    for i, line in enumerate(lines):
        lw = fitz.get_text_length(line, fontname=fontname, fontsize=fontsize)
        x = topleft.x + (w - lw) / 2
        y = topleft.y + fontsize * (0.85 + i * lineheight)
        op.insert_text(
            (x, y),
            line,
            fontsize=fontsize,
            fontname=fontname,
            color=color,
            fill_opacity=opacity,
            stroke_opacity=opacity,
            morph=morph,
        )
    return fitz.Rect(topleft.x, topleft.y, topleft.x + w, topleft.y + h)


def image_with_opacity(path_or_bytes, opacity: float) -> bytes:
    """Renvoie un PNG (bytes) avec la transparence demandée."""
    from PIL import Image

    if isinstance(path_or_bytes, (bytes, bytearray)):
        img = Image.open(io.BytesIO(path_or_bytes))
    else:
        img = Image.open(path_or_bytes)
    img = img.convert("RGBA")
    if opacity < 1:
        alpha = img.getchannel("A").point(lambda a: int(a * max(0.0, opacity)))
        img.putalpha(alpha)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def image_size(data: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        return img.size
