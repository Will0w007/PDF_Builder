from __future__ import annotations

import io
from pathlib import Path

import pymupdf as fitz
import pytest

from pdf_builder.core.registry import Context


def make_text_pdf(path: Path, pages: int = 6, title: str = "Rapport", rotate_last: bool = False) -> Path:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        if i % 3 == 0:
            page.insert_text((72, 90), f"Chapitre {i // 3 + 1} : Introduction générale", fontsize=22, fontname="hebo")
        page.insert_text((72, 140), f"Section {i + 1}.1 Contexte", fontsize=15, fontname="hebo")
        body = (
            f"Ceci est le texte de la page {i + 1}. Contact : jean.dupont@example.com, "
            "tél. 06 12 34 56 78. IBAN FR76 3000 6000 0112 3456 7890 189."
        )
        page.insert_textbox(fitz.Rect(72, 160, 520, 400), body * 2, fontsize=11)
        page.draw_rect(fitz.Rect(72, 420, 300, 520), color=(0, 0, 1), fill=(0.8, 0.8, 1))
    if rotate_last:
        doc[-1].set_rotation(90)
    doc.set_metadata({"title": title, "author": "Testeur"})
    doc.save(path)
    doc.close()
    return path


def make_image(path: Path, color=(200, 30, 30), size=(400, 300), text: str | None = None) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", size, color)
    if text:
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 48)
        except OSError:
            font = ImageFont.load_default()
        draw.text((30, 100), text, fill=(0, 0, 0), font=font)
    img.save(path)
    return path


def make_form_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    for i, name in enumerate(("nom", "prenom", "ville")):
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.rect = fitz.Rect(100, 100 + i * 40, 350, 125 + i * 40)
        page.add_widget(w)
    cb = fitz.Widget()
    cb.field_name = "accord"
    cb.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    cb.rect = fitz.Rect(100, 260, 115, 275)
    page.add_widget(cb)
    doc.save(path)
    doc.close()
    return path


def make_scan_pdf(path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 56)
    except OSError:
        font = ImageFont.load_default()
    draw.text((120, 200), "Bonjour le monde", fill="black", font=font)
    draw.text((120, 320), "Facture numero 2024", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def ctx(tmp_path):
    return Context(out_dir=tmp_path / "out")


@pytest.fixture
def sample(tmp_path):
    return make_text_pdf(tmp_path / "sample.pdf")


@pytest.fixture
def sample2(tmp_path):
    return make_text_pdf(tmp_path / "second.pdf", pages=3, title="Second")
