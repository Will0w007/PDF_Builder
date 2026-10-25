"""Déclaration des outils, de leurs paramètres et exécution des tâches.

Chaque outil est une fonction pure (sans Qt) décrite par un objet :class:`Tool`.
L'interface génère automatiquement le formulaire de paramètres à partir de la
liste de :class:`Param`, et le moteur d'automatisation peut enchaîner les
outils marqués ``chainable``.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pymupdf as fitz

from .utils import unique_path

CATEGORIES = [
    ("organize", "Organiser", "🗂️"),
    ("edit", "Éditer & annoter", "✏️"),
    ("convert", "Convertir", "🔄"),
    ("security", "Sécurité", "🔒"),
    ("optimize", "Optimiser", "⚡"),
    ("extract", "Extraire & analyser", "🔎"),
]

PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".jxr", ".pnm", ".jpx"}
OFFICE_EXT = {".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp", ".csv"}
TEXT_EXT = {".txt", ".md", ".markdown", ".html", ".htm"}


class ToolError(Exception):
    """Erreur présentée telle quelle à l'utilisateur."""


class PasswordRequired(ToolError):
    def __init__(self, path: Path):
        super().__init__(f"Le fichier « {Path(path).name} » est protégé par un mot de passe.")
        self.path = str(path)


class Cancelled(ToolError):
    def __init__(self):
        super().__init__("Opération annulée.")


@dataclass
class Param:
    key: str
    label: str
    kind: str = "str"  # str, text, int, float, bool, choice, pages, color, password, file, files, folder
    default: Any = None
    choices: list[tuple[str, str]] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    help: str = ""
    placeholder: str = ""
    visible_if: dict[str, Any] | None = None  # {"cle": valeur | [valeurs]}
    file_filter: str = ""
    suffix: str = ""

    def is_visible(self, values: dict) -> bool:
        if not self.visible_if:
            return True
        for k, expected in self.visible_if.items():
            v = values.get(k)
            if isinstance(expected, (list, tuple, set)):
                if v not in expected:
                    return False
            elif v != expected:
                return False
        return True


@dataclass
class Tool:
    id: str
    name: str
    category: str
    icon: str
    description: str
    func: Callable
    params: list[Param] = field(default_factory=list)
    mode: str = "each"  # "each" : un appel par fichier ; "all" : un seul appel avec tous les fichiers
    accepts: str = "pdf"  # pdf, images, office, text, any
    min_inputs: int = 1
    max_inputs: int | None = None
    chainable: bool = False  # PDF → PDF, utilisable dans un flux de travail
    keywords: str = ""
    output_kind: str = "pdf"  # pdf, files, folder, report

    def defaults(self) -> dict:
        return {p.key: p.default for p in self.params}

    def extensions(self) -> set[str]:
        return {
            "pdf": PDF_EXT,
            "images": IMAGE_EXT,
            "office": OFFICE_EXT,
            "text": TEXT_EXT,
            "pdf+images": PDF_EXT | IMAGE_EXT,
            "any": PDF_EXT | IMAGE_EXT | OFFICE_EXT | TEXT_EXT,
            "none": set(),
        }.get(self.accepts, PDF_EXT)


REGISTRY: dict[str, Tool] = {}


def tool(**kwargs):
    """Décorateur d'enregistrement d'un outil."""

    def deco(func):
        t = Tool(func=func, **kwargs)
        REGISTRY[t.id] = t
        return func

    return deco


def load_all() -> dict[str, Tool]:
    """Importe tous les modules d'outils (enregistrement par effet de bord)."""
    from . import (  # noqa: F401
        tools_convert,
        tools_edit,
        tools_extract,
        tools_optimize,
        tools_organize,
        tools_security,
    )

    return REGISTRY


def get_tool(tool_id: str) -> Tool:
    load_all()
    try:
        return REGISTRY[tool_id]
    except KeyError as exc:
        raise ToolError(f"Outil inconnu : {tool_id}") from exc


class Context:
    """Contexte d'exécution transmis aux fonctions d'outil."""

    def __init__(
        self,
        out_dir: str | Path | None = None,
        passwords: dict[str, str] | None = None,
        progress: Callable[[float, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        settings: dict | None = None,
    ):
        self.out_dir = Path(out_dir) if out_dir else None
        self.passwords = dict(passwords or {})
        self._progress = progress or (lambda f, m: None)
        self._is_cancelled = is_cancelled or (lambda: False)
        self.settings = settings or {}
        self.reports: list[str] = []
        self._base = 0.0
        self._span = 1.0

    # -- progression -------------------------------------------------
    def progress(self, fraction: float, message: str = "") -> None:
        if self._is_cancelled():
            raise Cancelled()
        self._progress(self._base + self._span * max(0.0, min(1.0, fraction)), message)

    def sub(self, index: int, total: int) -> None:
        """Restreint la progression à la tranche ``index``/``total``."""
        self._base = index / max(1, total)
        self._span = 1 / max(1, total)

    def check(self) -> None:
        if self._is_cancelled():
            raise Cancelled()

    def report(self, text: str) -> None:
        self.reports.append(text)

    # -- fichiers ----------------------------------------------------
    def open(self, path: str | Path) -> fitz.Document:
        path = Path(path)
        if not path.exists():
            raise ToolError(f"Fichier introuvable : {path}")
        try:
            doc = fitz.open(path)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Impossible d'ouvrir « {path.name} » : {exc}") from exc
        if doc.needs_pass:
            pw = self.passwords.get(str(path)) or self.passwords.get("*")
            if not pw or not doc.authenticate(pw):
                doc.close()
                raise PasswordRequired(path)
        if not doc.is_pdf:
            # Images, EPUB, XPS… : conversion transparente en PDF.
            data = doc.convert_to_pdf()
            doc.close()
            doc = fitz.open("pdf", data)
        return doc

    def output(self, src: str | Path | None, suffix: str = "", ext: str = ".pdf", name: str | None = None) -> Path:
        """Chemin de sortie unique, à côté de la source ou dans le dossier choisi."""
        src = Path(src) if src else None
        folder = self.out_dir or (src.parent if src else Path.cwd())
        folder.mkdir(parents=True, exist_ok=True)
        if name:
            filename = name if Path(name).suffix else name + ext
        else:
            stem = src.stem if src else "document"
            filename = f"{stem}{suffix}{ext}"
        return unique_path(folder / filename)

    def output_dir(self, src: str | Path | None, suffix: str) -> Path:
        src = Path(src) if src else None
        folder = self.out_dir or (src.parent if src else Path.cwd())
        stem = src.stem if src else "document"
        target = unique_path(folder / f"{stem}{suffix}")
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def save(doc: fitz.Document, path: str | Path, **kwargs) -> Path:
        opts = dict(garbage=3, deflate=True)
        opts.update(kwargs)
        doc.save(str(path), **opts)
        return Path(path)


def execute(tool_id: str, inputs: list[str], params: dict | None, ctx: Context) -> list[Path]:
    """Exécute un outil sur ses entrées et renvoie la liste des fichiers produits."""
    t = get_tool(tool_id)
    values = t.defaults()
    values.update(params or {})
    paths = [Path(p) for p in inputs]
    if len(paths) < t.min_inputs:
        raise ToolError(
            f"« {t.name} » nécessite au moins {t.min_inputs} fichier{'s' if t.min_inputs > 1 else ''}."
        )
    if t.max_inputs and len(paths) > t.max_inputs:
        raise ToolError(f"« {t.name} » accepte au plus {t.max_inputs} fichiers.")
    outputs: list[Path] = []
    if t.mode == "all":
        ctx.sub(0, 1)
        res = t.func(paths, values, ctx)
        outputs.extend(res or [])
    else:
        for i, p in enumerate(paths):
            ctx.sub(i, len(paths))
            ctx.progress(0, f"{p.name}")
            res = t.func(p, values, ctx)
            outputs.extend(res or [])
    ctx.sub(0, 1)
    ctx.progress(1, "Terminé")
    return [Path(o) for o in outputs]


def execute_workflow(steps: list[dict], inputs: list[str], ctx: Context, final_suffix: str = "_traité") -> list[Path]:
    """Applique une suite d'outils PDF→PDF à chaque fichier d'entrée.

    ``steps`` : ``[{"tool": "compress", "params": {...}}, ...]``.
    """
    if not steps:
        raise ToolError("Le flux de travail ne contient aucune étape.")
    for s in steps:
        t = get_tool(s["tool"])
        if not t.chainable:
            raise ToolError(f"L'outil « {t.name} » ne peut pas être utilisé dans un flux de travail.")
    results: list[Path] = []
    final_ctx_dir = ctx.out_dir
    total = len(inputs) * len(steps)
    for fi, src in enumerate(inputs):
        src = Path(src)
        tmp = Path(tempfile.mkdtemp(prefix="pdfbuilder_wf_"))
        try:
            current = [src]
            for si, step in enumerate(steps):
                sub_ctx = Context(
                    out_dir=tmp / f"step{si}",
                    passwords=ctx.passwords,
                    progress=lambda f, m, k=fi * len(steps) + si: ctx.progress((k + f) / total, m),
                    is_cancelled=ctx._is_cancelled,
                    settings=ctx.settings,
                )
                produced = execute(step["tool"], [str(c) for c in current], step.get("params", {}), sub_ctx)
                ctx.reports.extend(sub_ctx.reports)
                if not produced:
                    raise ToolError(f"L'étape « {get_tool(step['tool']).name} » n'a produit aucun fichier.")
                current = produced
                # Les mots de passe ne sont plus nécessaires après la première étape.
            folder = final_ctx_dir or src.parent
            folder.mkdir(parents=True, exist_ok=True)
            for j, c in enumerate(current):
                extra = f"_{j + 1}" if len(current) > 1 else ""
                dest = unique_path(folder / f"{src.stem}{final_suffix}{extra}{c.suffix}")
                shutil.move(str(c), dest)
                results.append(dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    ctx.progress(1, "Terminé")
    return results
