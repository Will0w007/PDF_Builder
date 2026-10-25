"""Optimisation : compression, réparation, OCR, métadonnées, signets."""

from __future__ import annotations

import os
import shutil
from collections import Counter
from pathlib import Path

import pymupdf as fitz

from .external import find_tessdata, tesseract_languages
from .registry import Param, ToolError, tool
from .utils import human_size, parse_pages

LEVELS = {
    # niveau: (seuil dpi, dpi cible, qualité jpeg)
    "light": (300, 220, 85),
    "medium": (200, 150, 72),
    "strong": (150, 110, 58),
    "extreme": (110, 72, 42),
}


@tool(
    id="compress",
    name="Compresser",
    category="optimize",
    icon="🗜️",
    description="Réduit fortement la taille du PDF (images, polices, objets inutiles) avec 4 niveaux de compression.",
    chainable=True,
    keywords="compresser réduire alléger taille poids optimiser email",
    params=[
        Param(
            "level",
            "Niveau",
            "choice",
            "medium",
            choices=[
                ("light", "Léger – qualité maximale"),
                ("medium", "Recommandé – bon équilibre"),
                ("strong", "Fort – idéal pour l'e-mail"),
                ("extreme", "Extrême – taille minimale"),
            ],
        ),
        Param("gray", "Convertir les images en niveaux de gris", "bool", False),
        Param("fonts", "Optimiser les polices (sous-ensembles)", "bool", True),
        Param("strip", "Supprimer métadonnées et miniatures", "bool", False),
        Param("linearize", "Optimiser pour le Web (affichage rapide)", "bool", False),
    ],
)
def compress(path: Path, p: dict, ctx) -> list[Path]:
    before = path.stat().st_size
    doc = ctx.open(path)
    thr, target, quality = LEVELS[p["level"]]
    ctx.progress(0.1, "Recompression des images…")
    try:
        doc.rewrite_images(dpi_threshold=thr, dpi_target=target, quality=quality, lossy=True, lossless=True, bitonal=True, color=True, gray=True, set_to_gray=bool(p["gray"]))
    except Exception as exc:  # noqa: BLE001
        ctx.report(f"Images non recompressées : {exc}")
    if p["fonts"]:
        ctx.progress(0.5, "Optimisation des polices…")
        try:
            doc.subset_fonts()
        except Exception:  # noqa: BLE001
            pass
    if p["strip"]:
        doc.scrub(metadata=True, xml_metadata=True, thumbnails=True, attached_files=False, embedded_files=False, clean_pages=False, hidden_text=False, javascript=False, redactions=False, remove_links=False, reset_fields=False, reset_responses=False)
    ctx.progress(0.7, "Écriture du fichier…")
    dest = ctx.output(path, "_compressé")
    doc.save(str(dest), garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True, use_objstms=1)
    doc.close()
    if p["linearize"]:
        _linearize(dest)
    after = dest.stat().st_size
    if after >= before:
        shutil.copyfile(path, dest)
        after = before
        ctx.report(f"{path.name} : déjà optimisé ({human_size(before)}), copie conservée sans perte.")
    else:
        gain = (1 - after / before) * 100
        ctx.report(f"{path.name} : {human_size(before)} → {human_size(after)} (−{gain:.0f} %)")
    return [dest]


def _linearize(path: Path) -> None:
    try:
        import pikepdf
    except ImportError:
        return
    tmp = path.with_suffix(".lin.pdf")
    with pikepdf.open(path) as pdf:
        pdf.save(tmp, linearize=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    os.replace(tmp, path)


@tool(
    id="repair",
    name="Réparer",
    category="optimize",
    icon="🩹",
    description="Tente de récupérer un PDF endommagé ou qui ne s'ouvre pas correctement.",
    chainable=True,
    keywords="réparer corrompu endommagé récupérer erreur",
    params=[],
)
def repair(path: Path, p: dict, ctx) -> list[Path]:
    dest = ctx.output(path, "_réparé")
    errors = []
    try:
        doc = ctx.open(path)
        doc.save(str(dest), garbage=4, deflate=True, clean=True)
        doc.close()
        ctx.report(f"{path.name} : reconstruit avec MuPDF.")
        return [dest]
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    try:
        import pikepdf

        with pikepdf.open(path, attempt_recovery=True) as pdf:
            pdf.save(dest)
        ctx.report(f"{path.name} : reconstruit avec qpdf.")
        return [dest]
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    raise ToolError("Impossible de réparer ce fichier :\n" + "\n".join(errors))


@tool(
    id="metadata",
    name="Propriétés du document",
    category="optimize",
    icon="🏷️",
    description="Modifie titre, auteur, sujet, mots-clés et options d'affichage à l'ouverture.",
    chainable=True,
    keywords="métadonnées propriétés titre auteur mots-clés informations",
    params=[
        Param("title", "Titre", "str", "", placeholder="(inchangé)"),
        Param("author", "Auteur", "str", "", placeholder="(inchangé)"),
        Param("subject", "Sujet", "str", "", placeholder="(inchangé)"),
        Param("keywords", "Mots-clés", "str", "", placeholder="(inchangé)"),
        Param("creator", "Application de création", "str", "", placeholder="(inchangé)"),
        Param("clear", "Effacer d'abord toutes les métadonnées", "bool", False),
        Param("layout", "Affichage à l'ouverture", "choice", "", choices=[("", "(inchangé)"), ("SinglePage", "Page simple"), ("OneColumn", "Défilement continu"), ("TwoPageLeft", "Deux pages"), ("TwoPageRight", "Deux pages (couverture)")]),
    ],
)
def metadata(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    meta = {} if p["clear"] else dict(doc.metadata or {})
    if p["clear"]:
        doc.del_xml_metadata()
    for key in ("title", "author", "subject", "keywords", "creator"):
        if (p.get(key) or "").strip():
            meta[key] = p[key].strip()
    meta.pop("format", None)
    meta.pop("encryption", None)
    doc.set_metadata(meta)
    if p.get("layout"):
        doc.set_pagelayout(p["layout"])
    dest = ctx.save(doc, ctx.output(path, "_propriétés"))
    doc.close()
    return [dest]


@tool(
    id="bookmarks",
    name="Signets automatiques",
    category="optimize",
    icon="🔖",
    description="Génère une table des matières cliquable à partir des titres détectés dans le document.",
    chainable=True,
    keywords="signets sommaire table des matières titres navigation bookmarks",
    params=[
        Param("mode", "Action", "choice", "auto", choices=[("auto", "Détecter les titres"), ("pages", "Un signet par page"), ("remove", "Supprimer tous les signets")]),
        Param("levels", "Niveaux de titres", "int", 3, min=1, max=6, visible_if={"mode": "auto"}),
        Param("min_ratio", "Taille minimale d'un titre (× texte courant)", "float", 1.15, min=1.0, max=3.0, step=0.05, visible_if={"mode": "auto"}),
        Param("bold", "Considérer les lignes courtes en gras comme titres", "bool", True, visible_if={"mode": "auto"}),
    ],
)
def bookmarks(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    if p["mode"] == "remove":
        doc.set_toc([])
    elif p["mode"] == "pages":
        doc.set_toc([[1, f"Page {i + 1}", i + 1] for i in range(doc.page_count)])
    else:
        toc = detect_headings(doc, int(p["levels"]), float(p["min_ratio"]), bool(p["bold"]), ctx)
        if not toc:
            raise ToolError("Aucun titre n'a pu être détecté (document scanné ? essayez d'abord l'OCR).")
        doc.set_toc(toc)
        ctx.report(f"{path.name} : {len(toc)} signet(s) créé(s).")
    dest = ctx.save(doc, ctx.output(path, "_signets"))
    doc.close()
    return [dest]


def detect_headings(doc: fitz.Document, levels: int = 3, min_ratio: float = 1.15, bold: bool = True, ctx=None) -> list[list]:
    sizes: Counter = Counter()
    lines = []
    for page in doc:
        if ctx:
            ctx.progress(page.number / doc.page_count * 0.8, f"Analyse page {page.number + 1}")
        for b in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]:
            for line in b.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = " ".join(s["text"].strip() for s in spans).strip()
                size = round(max(s["size"] for s in spans), 1)
                is_bold = all(s["flags"] & 16 or "bold" in s["font"].lower() for s in spans)
                for s in spans:
                    sizes[round(s["size"], 1)] += len(s["text"])
                lines.append((page.number, line["bbox"][1], text, size, is_bold))
    if not sizes:
        return []
    body = sizes.most_common(1)[0][0]
    candidates = []
    for pno, y, text, size, is_bold in lines:
        if len(text) > 120 or len(text) < 2 or text.replace(".", "").replace(" ", "").isdigit():
            continue
        if size >= body * min_ratio or (bold and is_bold and size >= body and len(text) < 80 and text[-1:] not in ".,;:"):
            candidates.append((pno, y, text, size if size >= body * min_ratio else body * min_ratio - 0.01))
    if not candidates:
        return []
    # Ignore les tailles qui reviennent sur presque toutes les pages (en-têtes répétés).
    seen = Counter(t for _, _, t, _ in candidates)
    candidates = [c for c in candidates if seen[c[2]] < max(3, doc.page_count * 0.5)]
    distinct = sorted({round(c[3]) for c in candidates}, reverse=True)[:levels]
    level_of = {s: i + 1 for i, s in enumerate(distinct)}
    toc, prev = [], 0
    merged: list[tuple] = []
    for c in candidates:
        lvl = level_of.get(round(c[3]))
        if not lvl:
            continue
        # Fusionne les titres découpés sur deux lignes consécutives.
        if merged and merged[-1][0] == c[0] and merged[-1][3] == lvl and 0 < c[1] - merged[-1][1] < c[3] * 1.6:
            pno, y, t, l = merged[-1]
            merged[-1] = (pno, c[1], t + " " + c[2], l)
            continue
        merged.append((c[0], c[1], c[2], lvl))
    for pno, y, text, lvl in merged:
        lvl = min(lvl, prev + 1)
        toc.append([lvl, text[:150], pno + 1, {"kind": fitz.LINK_GOTO, "page": pno, "to": fitz.Point(0, max(0, y - 10))}])
        prev = lvl
    return toc


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
OCR_LANGS = [
    ("fra", "Français"),
    ("eng", "Anglais"),
    ("fra+eng", "Français + anglais"),
    ("deu", "Allemand"),
    ("spa", "Espagnol"),
    ("ita", "Italien"),
    ("por", "Portugais"),
    ("nld", "Néerlandais"),
    ("ara", "Arabe"),
]


@tool(
    id="ocr",
    name="OCR – Rendre cherchable",
    category="optimize",
    icon="👁️",
    description="Reconnaît le texte des scans et photos : le PDF devient cherchable, sélectionnable et copiable.",
    chainable=True,
    keywords="ocr reconnaissance texte scan numérisé cherchable tesseract",
    params=[
        Param("lang", "Langue du document", "choice", "fra", choices=OCR_LANGS),
        Param("mode", "Pages à traiter", "choice", "auto", choices=[("auto", "Seulement les pages sans texte (recommandé)"), ("all", "Toutes les pages")]),
        Param("dpi", "Résolution d'analyse", "int", 300, min=150, max=600, step=50),
        Param("pages", "Pages", "pages", ""),
    ],
)
def ocr(path: Path, p: dict, ctx) -> list[Path]:
    tessdata = find_tessdata(ctx.settings.get("tessdata"))
    if not tessdata:
        raise ToolError(
            "Le moteur OCR Tesseract est introuvable.\n"
            "• Windows : installez « Tesseract OCR » (UB Mannheim) avec la langue française.\n"
            "• macOS : brew install tesseract tesseract-lang\n"
            "• Linux : sudo apt install tesseract-ocr tesseract-ocr-fra\n"
            "Puis indiquez le dossier « tessdata » dans les Paramètres si nécessaire."
        )
    available = tesseract_languages(tessdata)
    langs = [lang for lang in p["lang"].split("+") if lang in available]
    if not langs:
        raise ToolError(f"La langue « {p['lang']} » n'est pas installée pour Tesseract. Langues disponibles : {', '.join(available) or 'aucune'}.")
    lang = "+".join(langs)
    doc = ctx.open(path)
    targets = set(parse_pages(p["pages"], doc.page_count))
    out = fitz.open()
    done = 0
    dpi = int(p["dpi"])
    for page in doc:
        ctx.progress(page.number / doc.page_count, f"OCR page {page.number + 1}/{doc.page_count}")
        has_text = len(page.get_text("text").strip()) > 20
        if page.number not in targets or (p["mode"] == "auto" and has_text):
            out.insert_pdf(doc, from_page=page.number, to_page=page.number)
            continue
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        pix.set_dpi(dpi, dpi)
        try:
            ocr_pdf = fitz.open("pdf", pix.pdfocr_tobytes(compress=True, language=lang, tessdata=tessdata))
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Échec de l'OCR : {exc}") from exc
        np_ = out.new_page(width=page.rect.width, height=page.rect.height)
        np_.show_pdf_page(np_.rect, ocr_pdf, 0)
        ocr_pdf.close()
        done += 1
    out.set_toc(doc.get_toc())
    out.set_metadata({k: v for k, v in (doc.metadata or {}).items() if k not in ("format", "encryption")})
    ctx.report(f"{path.name} : {done} page(s) reconnue(s) par OCR ({lang}).")
    dest = ctx.save(out, ctx.output(path, "_ocr"), garbage=4)
    doc.close()
    out.close()
    return [dest]
