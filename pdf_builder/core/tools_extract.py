"""Extraction (images, pièces jointes), analyse et comparaison de documents."""

from __future__ import annotations

import difflib
import re
from collections import Counter
from pathlib import Path

import pymupdf as fitz

from .registry import Param, ToolError, tool
from .utils import human_size, make_upright, safe_filename, unique_path


@tool(
    id="extract_images",
    name="Extraire les images",
    category="extract",
    icon="🏞️",
    description="Récupère toutes les images intégrées au PDF dans leur qualité d'origine.",
    keywords="images photos extraire récupérer logos",
    output_kind="folder",
    params=[
        Param("min_size", "Ignorer les images de moins de (pixels)", "int", 64, min=0, max=5000),
        Param("format", "Format", "choice", "original", choices=[("original", "Format d'origine"), ("png", "Tout en PNG")]),
    ],
)
def extract_images(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    folder = ctx.output_dir(path, "_images_extraites")
    seen: set[int] = set()
    outputs = []
    min_size = int(p["min_size"])
    for page in doc:
        ctx.progress(page.number / doc.page_count, f"Page {page.number + 1}")
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                info = doc.extract_image(xref)
            except Exception:  # noqa: BLE001
                continue
            if not info or info.get("width", 0) < min_size or info.get("height", 0) < min_size:
                continue
            ext = info.get("ext", "png")
            data = info["image"]
            smask = img[1]
            if p["format"] == "png" or smask or ext in ("jbig2", "jpx", "jb2"):
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if smask:
                        mask = fitz.Pixmap(doc, smask)
                        pix = fitz.Pixmap(pix, mask)
                    if pix.n - pix.alpha >= 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    data, ext = pix.tobytes("png"), "png"
                except Exception:  # noqa: BLE001
                    pass
            dest = folder / f"page{page.number + 1:03d}_img{len(outputs) + 1:03d}.{ext}"
            dest.write_bytes(data)
            outputs.append(dest)
    doc.close()
    if not outputs:
        folder.rmdir()
        ctx.report(f"{path.name} : aucune image trouvée.")
        return []
    ctx.report(f"{path.name} : {len(outputs)} image(s) extraite(s).")
    return outputs


@tool(
    id="attachments",
    name="Pièces jointes",
    category="extract",
    icon="📎",
    description="Ajoute des fichiers joints au PDF, ou extrait ceux qu'il contient.",
    keywords="pièces jointes fichiers joints attachement intégrer embarquer",
    params=[
        Param("mode", "Action", "choice", "extract", choices=[("extract", "Extraire les pièces jointes"), ("add", "Joindre des fichiers")]),
        Param("files", "Fichiers à joindre", "files", [], visible_if={"mode": "add"}),
    ],
)
def attachments(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    if p["mode"] == "add":
        files = p.get("files") or []
        if not files:
            raise ToolError("Choisissez au moins un fichier à joindre.")
        for f in files:
            f = Path(f)
            doc.embfile_add(f.name, f.read_bytes(), filename=f.name, desc=f.name)
        dest = ctx.save(doc, ctx.output(path, "_avec_pj"))
        doc.close()
        return [dest]
    names = doc.embfile_names()
    if not names:
        doc.close()
        ctx.report(f"{path.name} : aucune pièce jointe.")
        return []
    folder = ctx.output_dir(path, "_pieces_jointes")
    outputs = []
    for name in names:
        info = doc.embfile_info(name)
        fname = safe_filename(info.get("filename") or name)
        dest = unique_path(folder / fname)
        dest.write_bytes(doc.embfile_get(name))
        outputs.append(dest)
    doc.close()
    ctx.report(f"{path.name} : {len(outputs)} pièce(s) jointe(s) extraite(s).")
    return outputs


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------
def analyze(doc: fitz.Document, path: Path | None = None) -> dict:
    """Statistiques complètes d'un document (utilisées par l'inspecteur)."""
    info: dict = {}
    meta = doc.metadata or {}
    info["meta"] = {k: v for k, v in meta.items() if v}
    info["pages"] = doc.page_count
    info["size"] = path.stat().st_size if path and path.exists() else None
    sizes = Counter()
    words = 0
    chars = 0
    images = 0
    scanned = 0
    fonts: dict[str, bool] = {}
    annots = Counter()
    links = 0
    for page in doc:
        r = page.rect
        sizes[_paper_name(r.width, r.height)] += 1
        text = page.get_text("text")
        w = len(text.split())
        words += w
        chars += len(text)
        imgs = page.get_images()
        images += len(imgs)
        if w < 5 and imgs:
            scanned += 1
        for f in page.get_fonts():
            name = f[3] or f[4]
            embedded = f[1] not in ("n/a", "") and f[0] > 0
            fonts[name.split("+")[-1]] = fonts.get(name.split("+")[-1], False) or embedded
        for a in page.annots():
            annots[a.type[1]] += 1
        links += len(page.get_links())
    info.update(
        words=words,
        chars=chars,
        images=images,
        scanned_pages=scanned,
        fonts=fonts,
        annots=dict(annots),
        links=links,
        formats=dict(sizes),
        toc=len(doc.get_toc()),
        encrypted=doc.is_encrypted,
        permissions=doc.permissions,
        form_fields=sum(1 for page in doc for _ in page.widgets()),
        attachments=doc.embfile_count(),
        signed=doc.get_sigflags() > 0 if hasattr(doc, "get_sigflags") else False,
        version=meta.get("format", ""),
        reading_minutes=max(1, round(words / 230)) if words else 0,
    )
    info["language"] = guess_language(doc)
    return info


def _paper_name(w: float, h: float) -> str:
    from .utils import PAPER_SIZES

    a, b = sorted((w, h))
    for name, (pw, ph) in PAPER_SIZES.items():
        if abs(a - pw) < 4 and abs(b - ph) < 4:
            return f"{name} {'paysage' if w > h else 'portrait'}"
    return f"{w / 72 * 25.4:.0f} × {h / 72 * 25.4:.0f} mm"


def guess_language(doc: fitz.Document) -> str:
    sample = " ".join(doc[i].get_text("text") for i in range(min(5, doc.page_count))).lower()
    tokens = re.findall(r"[a-zàâçéèêëîïôûùüÿñæœäöß]+", sample)
    if len(tokens) < 20:
        return "indéterminée"
    profiles = {
        "Français": {"le", "la", "les", "de", "des", "et", "est", "un", "une", "pour", "dans", "que", "qui", "sur", "pas", "par", "au", "du"},
        "Anglais": {"the", "and", "of", "to", "is", "in", "that", "for", "it", "with", "as", "on", "be", "this", "are"},
        "Allemand": {"der", "die", "und", "das", "ist", "nicht", "mit", "den", "von", "zu", "ein", "eine", "auf", "sich"},
        "Espagnol": {"el", "la", "de", "que", "y", "en", "los", "las", "por", "un", "una", "para", "con", "es", "del"},
        "Italien": {"il", "di", "che", "la", "e", "per", "un", "una", "non", "sono", "del", "della", "con", "gli"},
    }
    counts = Counter(tokens)
    scores = {lang: sum(counts[w] for w in words) for lang, words in profiles.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > len(tokens) * 0.05 else "indéterminée"


def format_report(info: dict, name: str) -> str:
    perms = info["permissions"]
    lines = [
        f"📄 {name}",
        f"   Pages : {info['pages']}  ·  Taille : {human_size(info['size']) if info['size'] else '—'}  ·  Version : {info['version'] or '—'}",
        "   Formats : " + ", ".join(f"{k} ({v})" for k, v in info["formats"].items()),
        f"   Texte : {info['words']:,} mots · lecture ≈ {info['reading_minutes']} min · langue : {info['language']}".replace(",", " "),
        f"   Images : {info['images']}  ·  Pages scannées (sans texte) : {info['scanned_pages']}",
        f"   Signets : {info['toc']}  ·  Liens : {info['links']}  ·  Champs de formulaire : {info['form_fields']}  ·  Pièces jointes : {info['attachments']}",
        f"   Chiffré : {'oui' if info['encrypted'] else 'non'}  ·  Signé : {'oui' if info['signed'] else 'non'}"
        + (f"  ·  Impression : {'oui' if perms & fitz.PDF_PERM_PRINT else 'non'}, copie : {'oui' if perms & fitz.PDF_PERM_COPY else 'non'}" if perms != -1 else ""),
    ]
    if info["annots"]:
        lines.append("   Annotations : " + ", ".join(f"{k} ({v})" for k, v in info["annots"].items()))
    if info["fonts"]:
        not_emb = [f for f, e in info["fonts"].items() if not e]
        lines.append(f"   Polices : {len(info['fonts'])}" + (f" (non incorporées : {', '.join(not_emb[:6])})" if not_emb else " (toutes incorporées)"))
    meta = info["meta"]
    for key, label in (("title", "Titre"), ("author", "Auteur"), ("subject", "Sujet"), ("keywords", "Mots-clés"), ("creator", "Créé avec"), ("producer", "Producteur")):
        if meta.get(key):
            lines.append(f"   {label} : {meta[key]}")
    tips = []
    if info["scanned_pages"]:
        tips.append("utilisez l'OCR pour rendre les pages scannées cherchables")
    if info["size"] and info["pages"] and info["size"] / info["pages"] > 400_000:
        tips.append("le fichier est lourd : la compression devrait fortement le réduire")
    if not info["toc"] and info["pages"] > 10:
        tips.append("ajoutez des signets automatiques pour faciliter la navigation")
    if meta.get("author") or meta.get("creator"):
        tips.append("pensez à assainir les métadonnées avant diffusion externe")
    if tips:
        lines.append("   💡 Conseils : " + " ; ".join(tips) + ".")
    return "\n".join(lines)


@tool(
    id="inspect",
    name="Inspecteur de PDF",
    category="extract",
    icon="🩺",
    description="Analyse complète : pages, polices, images, sécurité, langue, temps de lecture, et conseils d'optimisation.",
    keywords="analyse informations propriétés diagnostic statistiques inspecter",
    output_kind="report",
    params=[],
)
def inspect(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    ctx.report(format_report(analyze(doc, path), path.name))
    doc.close()
    return []


# ---------------------------------------------------------------------------
# Comparaison
# ---------------------------------------------------------------------------
def _words(page: fitz.Page) -> list[tuple]:
    return [w for w in page.get_text("words", sort=True) if w[4].strip()]


def compare_documents(doc_a: fitz.Document, doc_b: fitz.Document, progress=None) -> dict:
    """Compare deux documents mot à mot ; renvoie rectangles modifiés par page et statistiques."""
    words_a = [(pno, w) for pno in range(doc_a.page_count) for w in _words(doc_a[pno])]
    words_b = [(pno, w) for pno in range(doc_b.page_count) for w in _words(doc_b[pno])]
    seq_a = [w[4] for _, w in words_a]
    seq_b = [w[4] for _, w in words_b]
    if progress:
        progress(0.3, "Comparaison du texte…")
    sm = difflib.SequenceMatcher(None, seq_a, seq_b, autojunk=False)
    removed: dict[int, list[fitz.Rect]] = {}
    added: dict[int, list[fitz.Rect]] = {}
    changes = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        for pno, w in words_a[i1:i2]:
            removed.setdefault(pno, []).append(fitz.Rect(w[:4]))
        for pno, w in words_b[j1:j2]:
            added.setdefault(pno, []).append(fitz.Rect(w[:4]))
        changes.append(
            {
                "type": {"replace": "modifié", "delete": "supprimé", "insert": "ajouté"}[tag],
                "old": " ".join(seq_a[i1:i2])[:200],
                "new": " ".join(seq_b[j1:j2])[:200],
                "page_a": words_a[i1][0] + 1 if i1 < len(words_a) and i2 > i1 else None,
                "page_b": words_b[j1][0] + 1 if j1 < len(words_b) and j2 > j1 else None,
            }
        )
    visual = []
    if progress:
        progress(0.6, "Comparaison visuelle…")
    for pno in range(min(doc_a.page_count, doc_b.page_count)):
        pa = doc_a[pno].get_pixmap(dpi=30, colorspace=fitz.csGRAY)
        pb = doc_b[pno].get_pixmap(dpi=30, colorspace=fitz.csGRAY)
        if (pa.width, pa.height) != (pb.width, pb.height):
            visual.append(pno)
            continue
        diff = sum(1 for x, y in zip(pa.samples, pb.samples) if abs(x - y) > 40)
        if diff > len(pa.samples) * 0.002:
            visual.append(pno)
    ratio = sm.ratio() if seq_a or seq_b else 1.0
    return {"removed": removed, "added": added, "changes": changes, "similarity": ratio, "visual": visual, "pages": (doc_a.page_count, doc_b.page_count)}


@tool(
    id="compare",
    name="Comparer deux PDF",
    category="extract",
    icon="🆚",
    description="Met en évidence les différences de texte entre deux versions (côte à côte, rouge = supprimé, vert = ajouté).",
    mode="all",
    min_inputs=2,
    max_inputs=2,
    keywords="comparer différences versions diff contrat révision",
    params=[Param("name", "Nom du rapport", "str", "comparaison")],
)
def compare(paths: list[Path], p: dict, ctx) -> list[Path]:
    a, b = make_upright(ctx.open(paths[0])), make_upright(ctx.open(paths[1]))
    res = compare_documents(a, b, ctx.progress)
    out = build_compare_report(a, b, res, paths[0].name, paths[1].name)
    dest = ctx.save(out, ctx.output(paths[0], name=safe_filename(p.get("name") or "comparaison")))
    n = len(res["changes"])
    ctx.report(f"Similarité : {res['similarity'] * 100:.1f} % · {n} différence(s) de texte · {len(res['visual'])} page(s) visuellement différente(s).")
    a.close()
    b.close()
    out.close()
    return [dest]


def build_compare_report(a: fitz.Document, b: fitz.Document, res: dict, name_a: str, name_b: str) -> fitz.Document:
    RED, GREEN = (0.9, 0.2, 0.2), (0.15, 0.7, 0.3)
    work_a, work_b = fitz.open(), fitz.open()
    work_a.insert_pdf(a)
    work_b.insert_pdf(b)
    for work, key, color in ((work_a, "removed", RED), (work_b, "added", GREEN)):
        for pno, rects in res[key].items():
            page = work[pno]  # garder une référence : l'annotation est liée à l'objet page
            for r in rects:
                annot = page.add_highlight_annot(r)
                annot.set_colors(stroke=color)
                annot.update()
    work_a.bake()
    work_b.bake()
    out = fitz.open()
    W, H = 842, 595
    # Page de synthèse
    page = out.new_page(width=W, height=H)
    page.insert_text((40, 60), "Rapport de comparaison", fontsize=24, fontname="hebo", color=(0.2, 0.2, 0.5))
    page.insert_text((40, 90), f"A : {name_a}  ({res['pages'][0]} pages)", fontsize=11)
    page.insert_text((40, 106), f"B : {name_b}  ({res['pages'][1]} pages)", fontsize=11)
    page.insert_text((40, 130), f"Similarité du texte : {res['similarity'] * 100:.1f} %  ·  {len(res['changes'])} différence(s)", fontsize=12, fontname="hebo")
    page.draw_rect(fitz.Rect(40, 142, 52, 154), color=RED, fill=RED)
    page.insert_text((58, 153), "Supprimé (dans A)", fontsize=10)
    page.draw_rect(fitz.Rect(170, 142, 182, 154), color=GREEN, fill=GREEN)
    page.insert_text((188, 153), "Ajouté (dans B)", fontsize=10)
    y = 185
    for ch in res["changes"][:22]:
        label = f"[{ch['type']}] "
        if ch["old"]:
            label += f"« {ch['old'][:60]} » (p.{ch['page_a']})"
        if ch["old"] and ch["new"]:
            label += " → "
        if ch["new"]:
            label += f"« {ch['new'][:60]} » (p.{ch['page_b']})"
        page.insert_text((40, y), label[:150], fontsize=9, color=(0.2, 0.2, 0.2))
        y += 16
    if len(res["changes"]) > 22:
        page.insert_text((40, y), f"… et {len(res['changes']) - 22} autre(s) différence(s).", fontsize=9, color=(0.4, 0.4, 0.4))
    # Pages côte à côte
    n = max(work_a.page_count, work_b.page_count)
    for i in range(n):
        sheet = out.new_page(width=W, height=H)
        sheet.insert_text((20, 20), f"A – page {i + 1}" if i < work_a.page_count else "A – (absente)", fontsize=9, color=RED)
        sheet.insert_text((W / 2 + 10, 20), f"B – page {i + 1}" if i < work_b.page_count else "B – (absente)", fontsize=9, color=GREEN)
        sheet.draw_line((W / 2, 10), (W / 2, H - 10), color=(0.7, 0.7, 0.7), width=0.5)
        if i < work_a.page_count:
            sheet.show_pdf_page(fitz.Rect(10, 28, W / 2 - 10, H - 10), work_a, i)
        if i < work_b.page_count:
            sheet.show_pdf_page(fitz.Rect(W / 2 + 10, 28, W - 10, H - 10), work_b, i)
        if i in res["visual"]:
            sheet.insert_text((W - 170, 20), "● différence visuelle", fontsize=9, color=(0.9, 0.5, 0))
    out.set_toc([[1, "Synthèse", 1]] + [[1, f"Page {i + 1}", i + 2] for i in range(n)])
    work_a.close()
    work_b.close()
    return out


# ---------------------------------------------------------------------------
# Recherche dans un dossier (utilisée par la page « Rechercher »)
# ---------------------------------------------------------------------------
def search_folder(folder: str, query: str, regex: bool = False, case: bool = False, recursive: bool = True, progress=None, limit: int = 2000):
    root = Path(folder)
    if not root.is_dir():
        raise ToolError("Dossier introuvable.")
    files = sorted(root.rglob("*.pdf") if recursive else root.glob("*.pdf"))
    flags = 0 if case else re.IGNORECASE
    try:
        pattern = re.compile(query if regex else re.escape(query), flags)
    except re.error as exc:
        raise ToolError(f"Expression invalide : {exc}") from exc
    results = []
    for i, f in enumerate(files):
        if progress:
            progress(i / max(1, len(files)), f.name)
        try:
            doc = fitz.open(f)
        except Exception:  # noqa: BLE001
            continue
        if doc.needs_pass:
            doc.close()
            continue
        for page in doc:
            text = page.get_text("text")
            for m in pattern.finditer(text):
                start, end = max(0, m.start() - 60), min(len(text), m.end() + 60)
                snippet = text[start:end].replace("\n", " ")
                results.append({"file": str(f), "page": page.number + 1, "match": m.group(0), "snippet": snippet})
                if len(results) >= limit:
                    doc.close()
                    return results
        doc.close()
    return results
