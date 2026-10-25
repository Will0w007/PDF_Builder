"""Outils d'organisation : fusion, découpage, rotation, imposition…"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from .registry import Param, ToolError, tool
from .utils import MM, PAPER_CHOICES, PAPER_SIZES, make_upright, page_is_blank, parse_groups, parse_pages, safe_filename

PAGES_HELP = "Ex. : 1-3,5,8-fin · paires · impaires · vide = toutes"


def _pages_param(default: str = "", label: str = "Pages concernées") -> Param:
    return Param("pages", label, "pages", default, help=PAGES_HELP, placeholder="toutes")


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------
@tool(
    id="merge",
    name="Fusionner",
    category="organize",
    icon="🧩",
    description="Combine plusieurs PDF et images en un seul document, avec signets et sommaire cliquable.",
    mode="all",
    accepts="pdf+images",
    min_inputs=1,
    keywords="combiner joindre assembler concaténer merge",
    params=[
        Param("name", "Nom du fichier", "str", "fusion", placeholder="fusion"),
        Param(
            "bookmarks",
            "Signets",
            "choice",
            "files",
            choices=[
                ("files", "Un signet par fichier"),
                ("keep", "Un signet par fichier + signets d'origine"),
                ("original", "Conserver les signets d'origine"),
                ("none", "Aucun signet"),
            ],
        ),
        Param("toc_page", "Ajouter une page de sommaire cliquable", "bool", False),
        Param("blank_odd", "Ajouter une page blanche aux documents impairs (impression recto-verso)", "bool", False),
        Param("normalize", "Uniformiser le format des pages", "choice", "", choices=[("", "Non")] + PAPER_CHOICES),
    ],
)
def merge(paths: list[Path], p: dict, ctx) -> list[Path]:
    out = fitz.open()
    toc: list[list] = []
    starts: list[tuple[str, int]] = []
    for i, path in enumerate(paths):
        ctx.progress(i / len(paths), f"Ajout de {path.name}")
        src = make_upright(ctx.open(path))
        start = out.page_count
        src_toc = src.get_toc(simple=False) if p["bookmarks"] in ("keep", "original") else []
        out.insert_pdf(src)
        if p["blank_odd"] and src.page_count % 2 == 1 and i < len(paths) - 1:
            r = out[-1].rect
            out.new_page(width=r.width, height=r.height)
        title = path.stem
        starts.append((title, start))
        if p["bookmarks"] in ("files", "keep"):
            toc.append([1, title, start + 1])
        offset = 1 if p["bookmarks"] == "keep" else 0
        for entry in src_toc:
            lvl, t, pg = entry[0], entry[1], entry[2]
            if pg > 0:
                toc.append([lvl + offset, t, pg + start])
        src.close()

    if p.get("normalize"):
        out = _normalize(out, p["normalize"])

    shift = 0
    if p["toc_page"] and starts:
        shift = _insert_toc_pages(out, starts)
        toc = [[lvl, t, pg + shift] for lvl, t, pg in toc]
        toc.insert(0, [1, "Sommaire", 1])
        # Les niveaux doivent démarrer à 1 et ne pas sauter de niveau.
    if toc:
        out.set_toc(_fix_levels(toc))
    dest = ctx.output(paths[0], name=safe_filename(p.get("name") or "fusion"))
    ctx.save(out, dest)
    out.close()
    return [dest]


def _fix_levels(toc: list[list]) -> list[list]:
    fixed, prev = [], 0
    for lvl, title, page, *rest in toc:
        lvl = max(1, min(lvl, prev + 1))
        fixed.append([lvl, title, page, *rest])
        prev = lvl
    return fixed


def _insert_toc_pages(doc: fitz.Document, entries: list[tuple[str, int]]) -> int:
    """Insère au début un sommaire cliquable ; renvoie le nombre de pages ajoutées."""
    per_page = 28
    n_pages = (len(entries) + per_page - 1) // per_page
    w, h = PAPER_SIZES["A4"]
    for k in range(n_pages):
        doc.new_page(pno=k, width=w, height=h)
    for k in range(n_pages):
        page = doc[k]
        y = 90
        if k == 0:
            page.insert_text((60, 70), "Sommaire", fontsize=24, fontname="hebo", color=(0.15, 0.2, 0.45))
            page.draw_line((60, 80), (w - 60, 80), color=(0.3, 0.35, 0.8), width=1.2)
        y = 115
        for title, start in entries[k * per_page : (k + 1) * per_page]:
            target = start + n_pages
            label = title if len(title) < 70 else title[:67] + "…"
            page.insert_text((60, y), label, fontsize=12, fontname="helv", color=(0.1, 0.1, 0.1))
            num = str(target + 1)
            nw = fitz.get_text_length(num, "helv", 12)
            page.insert_text((w - 60 - nw, y), num, fontsize=12, fontname="helv", color=(0.1, 0.1, 0.1))
            lw = fitz.get_text_length(label, "helv", 12)
            page.draw_line((66 + lw, y), (w - 66 - nw, y), color=(0.7, 0.7, 0.7), width=0.5, dashes="[1 2] 0")
            page.insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(55, y - 13, w - 55, y + 4), "page": target, "to": fitz.Point(0, 0)})
            y += 24
    return n_pages


def _normalize(doc: fitz.Document, paper: str) -> fitz.Document:
    W, H = PAPER_SIZES[paper]
    out = fitz.open()
    make_upright(doc)
    for page in doc:
        r = page.rect
        w, h = (H, W) if r.width > r.height else (W, H)
        np_ = out.new_page(width=w, height=h)
        np_.show_pdf_page(np_.rect, doc, page.number)
    out.set_toc(doc.get_toc())
    doc.close()
    return out


# ---------------------------------------------------------------------------
# Découpage
# ---------------------------------------------------------------------------
@tool(
    id="split",
    name="Diviser",
    category="organize",
    icon="✂️",
    description="Découpe un PDF : toutes les N pages, à des pages précises, par signets, par taille ou aux pages blanches.",
    chainable=False,
    keywords="séparer découper scinder split éclater",
    output_kind="files",
    params=[
        Param(
            "mode",
            "Méthode",
            "choice",
            "every",
            choices=[
                ("every", "Toutes les N pages"),
                ("single", "Une page par fichier"),
                ("at", "Avant des pages précises"),
                ("ranges", "Selon des plages personnalisées"),
                ("bookmarks", "Selon les signets"),
                ("size", "Par taille maximale"),
                ("blank", "Aux pages blanches (séparateurs)"),
                ("oddeven", "Pages paires / impaires"),
            ],
        ),
        Param("n", "Nombre de pages par fichier", "int", 2, min=1, max=10000, visible_if={"mode": "every"}),
        Param("at", "Commencer un nouveau fichier aux pages", "str", "", placeholder="ex. 4, 9, 15", visible_if={"mode": "at"}),
        Param("ranges", "Plages (séparées par ;)", "str", "", placeholder="ex. 1-3 ; 4-10 ; 11-fin", visible_if={"mode": "ranges"}),
        Param("level", "Niveau de signet", "int", 1, min=1, max=6, visible_if={"mode": "bookmarks"}),
        Param("size_mb", "Taille maximale par fichier", "float", 5.0, min=0.1, max=10000, step=0.5, suffix=" Mo", visible_if={"mode": "size"}),
        Param("drop_blank", "Supprimer les pages séparatrices", "bool", True, visible_if={"mode": "blank"}),
        Param("name_from_bookmark", "Nommer les fichiers d'après les signets", "bool", True, visible_if={"mode": "bookmarks"}),
    ],
)
def split(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    n = doc.page_count
    groups: list[tuple[list[int], str]] = []
    mode = p["mode"]
    if mode == "every":
        k = max(1, int(p["n"]))
        groups = [(list(range(i, min(i + k, n))), "") for i in range(0, n, k)]
    elif mode == "single":
        groups = [([i], f"_page{i + 1}") for i in range(n)]
    elif mode == "at":
        cuts = sorted({c for c in parse_pages(p["at"], n) if c > 0})
        bounds = [0, *cuts, n]
        groups = [(list(range(a, b)), "") for a, b in zip(bounds, bounds[1:]) if b > a]
    elif mode == "ranges":
        groups = [(g, "") for g in parse_groups(p["ranges"], n) if g]
    elif mode == "bookmarks":
        lvl = int(p["level"])
        marks = [(e[2] - 1, e[1]) for e in doc.get_toc() if e[0] == lvl and e[2] > 0]
        if not marks:
            raise ToolError(f"Aucun signet de niveau {lvl} dans « {path.name} ».")
        marks.sort()
        if marks[0][0] > 0:
            marks.insert(0, (0, "début"))
        for (start, title), nxt in zip(marks, marks[1:] + [(n, "")]):
            if nxt[0] > start:
                label = "_" + safe_filename(title) if p["name_from_bookmark"] else ""
                groups.append((list(range(start, nxt[0])), label))
    elif mode == "size":
        limit = float(p["size_mb"]) * 1024 * 1024
        sizes = []
        for i in range(n):
            ctx.progress(i / n * 0.5, "Analyse de la taille des pages")
            one = fitz.open()
            one.insert_pdf(doc, from_page=i, to_page=i)
            sizes.append(len(one.tobytes(garbage=3, deflate=True)))
            one.close()
        current, acc = [], 0
        for i, s in enumerate(sizes):
            if current and acc + s > limit:
                groups.append((current, ""))
                current, acc = [], 0
            current.append(i)
            acc += s
        if current:
            groups.append((current, ""))
    elif mode == "blank":
        current: list[int] = []
        for i in range(n):
            ctx.progress(i / n * 0.5, "Recherche des pages blanches")
            if page_is_blank(doc[i]):
                if current:
                    groups.append((current, ""))
                current = [] if p["drop_blank"] else [i]
            else:
                current.append(i)
        if current:
            groups.append((current, ""))
    elif mode == "oddeven":
        groups = [(list(range(0, n, 2)), "_impaires"), (list(range(1, n, 2)), "_paires")]
    groups = [g for g in groups if g[0]]
    if not groups:
        raise ToolError("Aucune page à extraire avec ces réglages.")
    outputs = []
    width = len(str(len(groups)))
    for idx, (pages, label) in enumerate(groups, 1):
        ctx.progress(0.5 + idx / len(groups) * 0.5, f"Fichier {idx}/{len(groups)}")
        part = fitz.open()
        for pno in pages:
            part.insert_pdf(doc, from_page=pno, to_page=pno)
        suffix = label if label and mode in ("single", "oddeven", "bookmarks") else ""
        dest = ctx.output(path, f"_{idx:0{width}d}{suffix}" if mode != "single" and mode != "oddeven" else suffix)
        ctx.save(part, dest)
        part.close()
        outputs.append(dest)
    doc.close()
    return outputs


# ---------------------------------------------------------------------------
# Opérations simples sur les pages
# ---------------------------------------------------------------------------
@tool(
    id="extract_pages",
    name="Extraire des pages",
    category="organize",
    icon="📑",
    description="Crée un nouveau PDF ne contenant que les pages choisies, dans l'ordre indiqué.",
    chainable=True,
    keywords="sélectionner garder conserver pages",
    params=[
        Param("pages", "Pages à extraire", "pages", "1", help=PAGES_HELP + " · l'ordre est respecté (ex. 3,1,2)"),
        Param("separate", "Un fichier par page", "bool", False),
    ],
)
def extract_pages(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    pages = parse_pages(p["pages"], doc.page_count)
    if not pages:
        raise ToolError("Aucune page sélectionnée.")
    outputs = []
    if p["separate"]:
        for pno in pages:
            one = fitz.open()
            one.insert_pdf(doc, from_page=pno, to_page=pno)
            outputs.append(ctx.save(one, ctx.output(path, f"_page{pno + 1}")))
            one.close()
    else:
        doc.select(pages)
        outputs.append(ctx.save(doc, ctx.output(path, "_extrait")))
    doc.close()
    return outputs


@tool(
    id="delete_pages",
    name="Supprimer des pages",
    category="organize",
    icon="🗑️",
    description="Retire les pages indiquées du document.",
    chainable=True,
    keywords="enlever retirer effacer pages",
    params=[Param("pages", "Pages à supprimer", "pages", "1", help=PAGES_HELP)],
)
def delete_pages(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    pages = sorted(set(parse_pages(p["pages"], doc.page_count)))
    if len(pages) >= doc.page_count:
        raise ToolError("Impossible de supprimer toutes les pages du document.")
    doc.delete_pages(pages)
    dest = ctx.save(doc, ctx.output(path, "_modifié"))
    doc.close()
    return [dest]


@tool(
    id="rotate",
    name="Faire pivoter",
    category="organize",
    icon="🔃",
    description="Fait pivoter tout ou partie des pages de 90°, 180° ou 270°.",
    chainable=True,
    keywords="tourner rotation orientation paysage portrait",
    params=[
        Param("angle", "Rotation", "choice", "90", choices=[("90", "90° horaire ↻"), ("270", "90° antihoraire ↺"), ("180", "180°")]),
        _pages_param(),
        Param(
            "only",
            "Limiter aux pages",
            "choice",
            "all",
            choices=[("all", "Toutes les pages sélectionnées"), ("portrait", "En portrait seulement"), ("landscape", "En paysage seulement")],
        ),
    ],
)
def rotate(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    angle = int(p["angle"])
    for pno in set(parse_pages(p["pages"], doc.page_count)):
        page = doc[pno]
        r = page.rect
        if p["only"] == "portrait" and r.width > r.height:
            continue
        if p["only"] == "landscape" and r.width <= r.height:
            continue
        page.set_rotation((page.rotation + angle) % 360)
    dest = ctx.save(doc, ctx.output(path, "_pivoté"))
    doc.close()
    return [dest]


@tool(
    id="reorder",
    name="Réordonner / inverser",
    category="organize",
    icon="🔀",
    description="Inverse l'ordre des pages ou applique un nouvel ordre personnalisé.",
    chainable=True,
    keywords="ordre inverser trier ranger déplacer",
    params=[
        Param("mode", "Action", "choice", "reverse", choices=[("reverse", "Inverser l'ordre"), ("custom", "Ordre personnalisé"), ("oddeven", "Impaires puis paires")]),
        Param("order", "Nouvel ordre", "pages", "", placeholder="ex. 3,1,2,4-fin", visible_if={"mode": "custom"}),
    ],
)
def reorder(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    n = doc.page_count
    if p["mode"] == "reverse":
        order = list(range(n - 1, -1, -1))
    elif p["mode"] == "oddeven":
        order = list(range(0, n, 2)) + list(range(1, n, 2))
    else:
        order = parse_pages(p["order"], n)
    doc.select(order)
    dest = ctx.save(doc, ctx.output(path, "_réordonné"))
    doc.close()
    return [dest]


@tool(
    id="mix",
    name="Alterner (recto/verso)",
    category="organize",
    icon="🔁",
    description="Entrelace les pages de plusieurs PDF : idéal pour reconstituer un scan recto puis verso.",
    mode="all",
    min_inputs=2,
    keywords="entrelacer mélanger recto verso scan alterner mix",
    params=[
        Param("reverse_second", "Inverser le second document (verso scanné à l'envers)", "bool", True),
        Param("step_a", "Pages consécutives du 1er document", "int", 1, min=1, max=100),
        Param("step_b", "Pages consécutives des suivants", "int", 1, min=1, max=100),
        Param("name", "Nom du fichier", "str", "alterné"),
    ],
)
def mix(paths: list[Path], p: dict, ctx) -> list[Path]:
    docs = [ctx.open(x) for x in paths]
    orders = []
    for i, d in enumerate(docs):
        seq = list(range(d.page_count))
        if i == 1 and p["reverse_second"]:
            seq.reverse()
        orders.append(seq)
    out = fitz.open()
    pos = [0] * len(docs)
    while any(pos[i] < len(orders[i]) for i in range(len(docs))):
        for i, d in enumerate(docs):
            step = int(p["step_a"] if i == 0 else p["step_b"])
            for _ in range(step):
                if pos[i] < len(orders[i]):
                    pno = orders[i][pos[i]]
                    out.insert_pdf(d, from_page=pno, to_page=pno)
                    pos[i] += 1
    dest = ctx.save(out, ctx.output(paths[0], name=safe_filename(p["name"] or "alterné")))
    for d in docs:
        d.close()
    return [dest]


@tool(
    id="insert_pdf",
    name="Insérer un PDF",
    category="organize",
    icon="📥",
    description="Insère un autre PDF (ou une image) à une position donnée, éventuellement après chaque page.",
    chainable=True,
    keywords="ajouter insertion intercaler annexe",
    params=[
        Param("file", "Fichier à insérer", "file", "", file_filter="Documents (*.pdf *.png *.jpg *.jpeg)"),
        Param("position", "Insérer après la page (0 = au début)", "int", 0, min=0, max=100000),
        Param("at_end", "Insérer à la fin", "bool", False),
        Param("every", "Répéter toutes les N pages (0 = non)", "int", 0, min=0, max=10000),
    ],
)
def insert_pdf(path: Path, p: dict, ctx) -> list[Path]:
    if not p.get("file"):
        raise ToolError("Choisissez le fichier à insérer.")
    doc = ctx.open(path)
    ins = ctx.open(p["file"])
    n = doc.page_count
    if p["every"]:
        k = int(p["every"])
        positions = list(range(k, n + 1, k))
    else:
        positions = [n if p["at_end"] else min(int(p["position"]), n)]
    for pos in sorted(positions, reverse=True):
        doc.insert_pdf(ins, start_at=pos)
    dest = ctx.save(doc, ctx.output(path, "_inséré"))
    doc.close()
    ins.close()
    return [dest]


@tool(
    id="insert_blank",
    name="Ajouter des pages blanches",
    category="organize",
    icon="📄",
    description="Ajoute des pages blanches au début, à la fin, après chaque page ou à des positions précises.",
    chainable=True,
    keywords="vierge blanche ajouter intercalaire",
    params=[
        Param("where", "Position", "choice", "end", choices=[("end", "À la fin"), ("start", "Au début"), ("after_each", "Après chaque page"), ("after", "Après les pages…"), ("even", "Compléter à un nombre pair")]),
        Param("pages", "Après les pages", "pages", "1", visible_if={"where": "after"}),
        Param("count", "Nombre de pages blanches", "int", 1, min=1, max=100, visible_if={"where": ["end", "start", "after_each", "after"]}),
    ],
)
def insert_blank(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    n = doc.page_count
    where = p["where"]
    count = int(p.get("count") or 1)
    if where == "end":
        positions = [n] * count
    elif where == "start":
        positions = [0] * count
    elif where == "after_each":
        positions = [i + 1 for i in range(n) for _ in range(count)]
    elif where == "after":
        positions = [i + 1 for i in parse_pages(p["pages"], n) for _ in range(count)]
    else:
        positions = [n] if n % 2 else []
    for pos in sorted(positions, reverse=True):
        ref = doc[min(max(pos - 1, 0), doc.page_count - 1)].rect
        doc.new_page(pno=pos if pos < doc.page_count else -1, width=ref.width, height=ref.height)
    dest = ctx.save(doc, ctx.output(path, "_pages_blanches"))
    doc.close()
    return [dest]


@tool(
    id="remove_blank",
    name="Supprimer les pages blanches",
    category="organize",
    icon="🧽",
    description="Détecte et supprime automatiquement les pages vides, y compris dans les scans bruités.",
    chainable=True,
    keywords="vide blanche nettoyer scan détection",
    params=[Param("sensitivity", "Tolérance (% de pixels sombres)", "float", 0.3, min=0, max=10, step=0.1, suffix=" %")],
)
def remove_blank(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    blanks = []
    for i, page in enumerate(doc):
        ctx.progress(i / doc.page_count, f"Analyse page {i + 1}")
        if page_is_blank(page, float(p["sensitivity"])):
            blanks.append(i)
    if len(blanks) == doc.page_count:
        raise ToolError("Toutes les pages semblent blanches : rien n'a été supprimé.")
    doc.delete_pages(blanks)
    ctx.report(f"{path.name} : {len(blanks)} page(s) blanche(s) supprimée(s).")
    dest = ctx.save(doc, ctx.output(path, "_sans_blancs"))
    doc.close()
    return [dest]


# ---------------------------------------------------------------------------
# Mise en page
# ---------------------------------------------------------------------------
@tool(
    id="nup",
    name="Pages par feuille (N-up)",
    category="organize",
    icon="🔲",
    description="Place 2, 4, 6, 8, 9 ou 16 pages sur chaque feuille pour imprimer en économisant du papier.",
    chainable=True,
    keywords="imposition plusieurs pages feuille impression économiser nup",
    params=[
        Param("per_sheet", "Pages par feuille", "choice", "2", choices=[(str(v), str(v)) for v in (2, 4, 6, 8, 9, 16)]),
        Param("paper", "Format de la feuille", "choice", "A4", choices=PAPER_CHOICES),
        Param("border", "Tracer un cadre autour des pages", "bool", False),
        Param("margin", "Marge", "float", 5, min=0, max=50, suffix=" mm"),
    ],
)
def nup(path: Path, p: dict, ctx) -> list[Path]:
    src = make_upright(ctx.open(path))
    k = int(p["per_sheet"])
    cols, rows = {2: (2, 1), 4: (2, 2), 6: (3, 2), 8: (4, 2), 9: (3, 3), 16: (4, 4)}[k]
    W, H = PAPER_SIZES[p["paper"]]
    landscape = cols > rows
    if landscape:
        W, H = H, W
    m = float(p["margin"]) * MM
    out = fitz.open()
    cw, ch = (W - m * (cols + 1)) / cols, (H - m * (rows + 1)) / rows
    for i in range(0, src.page_count, k):
        ctx.progress(i / src.page_count, "Imposition")
        sheet = out.new_page(width=W, height=H)
        for j in range(k):
            if i + j >= src.page_count:
                break
            c, r = j % cols, j // cols
            cell = fitz.Rect(m + c * (cw + m), m + r * (ch + m), m + c * (cw + m) + cw, m + r * (ch + m) + ch)
            sheet.show_pdf_page(cell, src, i + j)
            if p["border"]:
                sheet.draw_rect(cell, color=(0.6, 0.6, 0.6), width=0.5)
    dest = ctx.save(out, ctx.output(path, f"_{k}par_feuille"))
    src.close()
    return [dest]


@tool(
    id="booklet",
    name="Livret",
    category="organize",
    icon="📖",
    description="Impose les pages pour imprimer un livret plié et agrafé (recto-verso, 2 pages par face).",
    chainable=True,
    keywords="brochure livret pliage imposition booklet",
    params=[
        Param("paper", "Format de la feuille", "choice", "A4", choices=PAPER_CHOICES),
        Param("binding", "Reliure", "choice", "left", choices=[("left", "À gauche (lecture occidentale)"), ("right", "À droite")]),
    ],
)
def booklet(path: Path, p: dict, ctx) -> list[Path]:
    src = make_upright(ctx.open(path))
    n = src.page_count
    total = (n + 3) // 4 * 4
    W, H = PAPER_SIZES[p["paper"]]
    W, H = H, W  # paysage
    out = fitz.open()
    half_l = fitz.Rect(0, 0, W / 2, H)
    half_r = fitz.Rect(W / 2, 0, W, H)
    for s in range(total // 4):
        front = (total - 1 - 2 * s, 2 * s)
        back = (2 * s + 1, total - 2 - 2 * s)
        for left, right in (front, back):
            if p["binding"] == "right":
                left, right = right, left
            sheet = out.new_page(width=W, height=H)
            for pno, rect in ((left, half_l), (right, half_r)):
                if pno < n:
                    sheet.show_pdf_page(rect, src, pno)
    dest = ctx.save(out, ctx.output(path, "_livret"))
    src.close()
    return [dest]


@tool(
    id="resize",
    name="Redimensionner les pages",
    category="organize",
    icon="📐",
    description="Met toutes les pages au même format (A4, A3, Letter…) en conservant les proportions.",
    chainable=True,
    keywords="format taille a4 letter échelle redimensionner",
    params=[
        Param("paper", "Format cible", "choice", "A4", choices=PAPER_CHOICES),
        Param("orientation", "Orientation", "choice", "auto", choices=[("auto", "Selon la page"), ("portrait", "Portrait"), ("landscape", "Paysage")]),
        Param("margin", "Marge", "float", 0, min=0, max=100, suffix=" mm"),
    ],
)
def resize(path: Path, p: dict, ctx) -> list[Path]:
    src = make_upright(ctx.open(path))
    W, H = PAPER_SIZES[p["paper"]]
    m = float(p["margin"]) * MM
    out = fitz.open()
    for page in src:
        r = page.rect
        land = r.width > r.height if p["orientation"] == "auto" else p["orientation"] == "landscape"
        w, h = (H, W) if land else (W, H)
        np_ = out.new_page(width=w, height=h)
        np_.show_pdf_page(fitz.Rect(m, m, w - m, h - m), src, page.number)
    out.set_toc(src.get_toc())
    dest = ctx.save(out, ctx.output(path, f"_{p['paper']}"))
    src.close()
    return [dest]


@tool(
    id="crop",
    name="Rogner les marges",
    category="organize",
    icon="🖼️",
    description="Rogne les marges de façon uniforme ou automatiquement autour du contenu.",
    chainable=True,
    keywords="recadrer rogner marges crop découper bords",
    params=[
        Param("mode", "Méthode", "choice", "auto", choices=[("auto", "Automatique (autour du contenu)"), ("manual", "Marges fixes")]),
        Param("padding", "Marge conservée autour du contenu", "float", 5, min=0, max=50, suffix=" mm", visible_if={"mode": "auto"}),
        Param("top", "Haut", "float", 10, min=0, max=500, suffix=" mm", visible_if={"mode": "manual"}),
        Param("bottom", "Bas", "float", 10, min=0, max=500, suffix=" mm", visible_if={"mode": "manual"}),
        Param("left", "Gauche", "float", 10, min=0, max=500, suffix=" mm", visible_if={"mode": "manual"}),
        Param("right", "Droite", "float", 10, min=0, max=500, suffix=" mm", visible_if={"mode": "manual"}),
        _pages_param(),
    ],
)
def crop(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    for pno in parse_pages(p["pages"], doc.page_count):
        page = doc[pno]
        base = page.cropbox  # repère non pivoté
        if p["mode"] == "auto":
            box = fitz.Rect()
            for _kind, bbox in page.get_bboxlog():
                r = fitz.Rect(bbox)
                if r.is_empty or r.is_infinite:
                    continue
                box |= r
            if box.is_empty:
                continue
            # get_bboxlog() renvoie des coordonnées non pivotées, comme cropbox.
            pad = float(p["padding"]) * MM
            new = fitz.Rect(box.x0 - pad, box.y0 - pad, box.x1 + pad, box.y1 + pad) & base
        else:
            vis = fitz.Rect(page.rect)
            vis = fitz.Rect(vis.x0 + float(p["left"]) * MM, vis.y0 + float(p["top"]) * MM, vis.x1 - float(p["right"]) * MM, vis.y1 - float(p["bottom"]) * MM)
            if vis.is_empty:
                raise ToolError("Les marges demandées sont plus grandes que la page.")
            new = (vis * page.derotation_matrix) & base
        if not new.is_empty and new.width > 10 and new.height > 10:
            page.set_cropbox(new)
    dest = ctx.save(doc, ctx.output(path, "_rogné"))
    doc.close()
    return [dest]


@tool(
    id="split_half",
    name="Couper les pages en deux",
    category="organize",
    icon="🪓",
    description="Sépare chaque page en deux (scans de doubles pages, livres ouverts).",
    chainable=True,
    keywords="double page scan livre moitié couper",
    params=[
        Param("direction", "Découpe", "choice", "vertical", choices=[("vertical", "Verticale (gauche | droite)"), ("horizontal", "Horizontale (haut / bas)")]),
        Param("rtl", "Lire de droite à gauche", "bool", False, visible_if={"direction": "vertical"}),
        Param("only_landscape", "Uniquement les pages en paysage", "bool", True),
    ],
)
def split_half(path: Path, p: dict, ctx) -> list[Path]:
    src = make_upright(ctx.open(path))
    out = fitz.open()
    for page in src:
        r = page.rect
        if p["only_landscape"] and p["direction"] == "vertical" and r.width <= r.height:
            out.insert_pdf(src, from_page=page.number, to_page=page.number)
            continue
        if p["direction"] == "vertical":
            halves = [fitz.Rect(0, 0, r.width / 2, r.height), fitz.Rect(r.width / 2, 0, r.width, r.height)]
            if p["rtl"]:
                halves.reverse()
        else:
            halves = [fitz.Rect(0, 0, r.width, r.height / 2), fitz.Rect(0, r.height / 2, r.width, r.height)]
        for clip in halves:
            np_ = out.new_page(width=clip.width, height=clip.height)
            np_.show_pdf_page(np_.rect, src, page.number, clip=clip)
    dest = ctx.save(out, ctx.output(path, "_coupé"))
    src.close()
    return [dest]
