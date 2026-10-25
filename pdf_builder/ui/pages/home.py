"""Page d'accueil : recherche d'outils, dépôt intelligent, fichiers récents."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ...core.registry import CATEGORIES, IMAGE_EXT, OFFICE_EXT, PDF_EXT, REGISTRY, TEXT_EXT
from ..widgets import DropZone, FlowLayout, ToolCard, app_settings, button, label

ALL_EXT = PDF_EXT | IMAGE_EXT | OFFICE_EXT | TEXT_EXT


def suggest(files: list[str]) -> list[tuple[str, str]]:
    """Propose les actions les plus pertinentes pour les fichiers déposés.

    Renvoie une liste de ``(identifiant, raison)`` ; l'identifiant est un outil
    ou une action spéciale (``@editor``, ``@organizer``, ``@compare``).
    """
    exts = {Path(f).suffix.lower() for f in files}
    pdfs = [f for f in files if Path(f).suffix.lower() == ".pdf"]
    out: list[tuple[str, str]] = []
    if exts and exts <= IMAGE_EXT:
        return [("images_to_pdf", "Assembler les images en PDF"), ("merge", "Fusionner avec d'autres documents")]
    if exts & OFFICE_EXT:
        out.append(("office_to_pdf", "Convertir les documents Office en PDF"))
    if exts & TEXT_EXT:
        out.append(("text_to_pdf", "Mettre en page en PDF"))
    if len(pdfs) >= 2:
        out.append(("merge", f"Fusionner les {len(pdfs)} PDF"))
        if len(pdfs) == 2:
            out.append(("@compare", "Comparer les deux versions"))
            out.append(("mix", "Alterner les pages (scan recto / verso)"))
        out.append(("@organizer", "Réorganiser les pages visuellement"))
        out.append(("compress", "Compresser tous les fichiers"))
        out.append(("bates", "Numérotation Bates continue"))
    elif len(pdfs) == 1:
        path = Path(pdfs[0])
        info = _quick_info(path)
        if info.get("encrypted"):
            out.append(("unlock", "Ce PDF est protégé : retirer le mot de passe"))
        out.append(("@editor", "Ouvrir dans l'éditeur (annoter, signer, modifier)"))
        if info.get("scanned"):
            out.append(("ocr", "Ce PDF semble scanné : le rendre cherchable (OCR)"))
        if info.get("forms"):
            out.append(("@editor", "Ce PDF contient un formulaire : le remplir"))
        if info.get("size", 0) > 3 * 1024 * 1024:
            out.append(("compress", "Fichier volumineux : le compresser"))
        out.append(("@organizer", "Réorganiser, pivoter, supprimer des pages"))
        out.append(("to_word", "Convertir en Word modifiable"))
        out.append(("split", "Diviser le document"))
        if not info.get("toc") and info.get("pages", 0) > 8:
            out.append(("bookmarks", "Générer des signets automatiquement"))
        out.append(("protect", "Protéger par mot de passe"))
        out.append(("inspect", "Analyser le document"))
    seen, uniq = set(), []
    for tid, why in out:
        if tid not in seen:
            seen.add(tid)
            uniq.append((tid, why))
    return uniq[:7]


def _quick_info(path: Path) -> dict:
    info = {"size": path.stat().st_size if path.exists() else 0}
    try:
        with fitz.open(path) as d:
            info["encrypted"] = d.needs_pass
            if d.needs_pass:
                return info
            info["pages"] = d.page_count
            info["toc"] = bool(d.get_toc())
            sample = range(min(3, d.page_count))
            info["scanned"] = all(len(d[i].get_text().strip()) < 10 and d[i].get_images() for i in sample) if d.page_count else False
            info["forms"] = any(True for i in sample for _ in d[i].widgets())
    except Exception:  # noqa: BLE001
        pass
    return info


class HomePage(QWidget):
    tool_requested = Signal(str, list)  # identifiant, fichiers
    action_requested = Signal(str, list)  # @editor, @organizer, @compare…

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self._pending_files: list[str] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("page")
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(36, 28, 36, 36)
        lay.setSpacing(18)

        hour = dt.datetime.now().hour
        hello = "Bonjour" if 5 <= hour < 18 else "Bonsoir"
        lay.addWidget(label(f"{hello} 👋  Que voulez-vous faire aujourd'hui ?", "h1"))
        lay.addWidget(label("Déposez un fichier pour obtenir des suggestions, ou cherchez parmi plus de 50 outils. Astuce : Ctrl+K ouvre la palette de commandes.", "muted", wrap=True))

        top = QHBoxLayout()
        top.setSpacing(18)
        self.drop = DropZone("Déposez vos fichiers ici", "PDF, images, Word, Excel, PowerPoint, texte… ou cliquez pour parcourir", ALL_EXT)
        self.drop.setMinimumHeight(170)
        self.drop.files_dropped.connect(self.show_suggestions)
        top.addWidget(self.drop, 3)

        self.recent_box = QFrame()
        self.recent_box.setObjectName("card")
        rlay = QVBoxLayout(self.recent_box)
        rlay.setContentsMargins(16, 14, 16, 14)
        rlay.addWidget(label("🕘 Récemment ouverts", "h3"))
        self.recent_list = QVBoxLayout()
        self.recent_list.setSpacing(2)
        rlay.addLayout(self.recent_list)
        rlay.addStretch(1)
        top.addWidget(self.recent_box, 2)
        lay.addLayout(top)

        self.suggest_box = QFrame()
        self.suggest_box.setObjectName("suggestion")
        slay = QVBoxLayout(self.suggest_box)
        slay.setContentsMargins(18, 14, 18, 16)
        head = QHBoxLayout()
        self.suggest_title = label("", "h3")
        head.addWidget(self.suggest_title)
        head.addStretch(1)
        head.addWidget(button("✕", slot=self.suggest_box.hide))
        slay.addLayout(head)
        self.suggest_flow = FlowLayout(spacing=8)
        holder = QWidget()
        holder.setLayout(self.suggest_flow)
        slay.addWidget(holder)
        self.suggest_box.hide()
        lay.addWidget(self.suggest_box)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("🔍  Rechercher un outil : fusionner, compresser, signer, word, ocr…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        lay.addWidget(self.search)

        self.sections: list[tuple[QWidget, list[ToolCard]]] = []
        for cat_id, cat_name, cat_icon in CATEGORIES:
            tools = [t for t in REGISTRY.values() if t.category == cat_id]
            if not tools:
                continue
            sec = QWidget()
            sl = QVBoxLayout(sec)
            sl.setContentsMargins(0, 8, 0, 0)
            sl.setSpacing(10)
            sl.addWidget(label(f"{cat_icon}  {cat_name}", "h2"))
            flow = FlowLayout(spacing=12)
            cards = []
            for t in tools:
                card = ToolCard(t)
                card.clicked.connect(self._card_clicked)
                flow.addWidget(card)
                cards.append(card)
            holder = QWidget()
            holder.setLayout(flow)
            sl.addWidget(holder)
            lay.addWidget(sec)
            self.sections.append((sec, cards))
        self.no_result = label("Aucun outil ne correspond à votre recherche.", "muted")
        self.no_result.hide()
        lay.addWidget(self.no_result)
        lay.addStretch(1)
        self.refresh_recent()

    def _card_clicked(self, tid: str):
        files = self._pending_files if self.suggest_box.isVisible() else []
        self.tool_requested.emit(tid, files)

    def filter(self, text: str):
        any_visible = False
        for sec, cards in self.sections:
            vis = 0
            for c in cards:
                m = c.matches(text)
                c.setVisible(m)
                vis += m
            sec.setVisible(vis > 0)
            sec.layout().itemAt(1).widget().layout().invalidate()
            any_visible |= vis > 0
        self.no_result.setVisible(not any_visible)

    def refresh_recent(self):
        while self.recent_list.count():
            it = self.recent_list.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        recent = app_settings().recent()[:6]
        if not recent:
            self.recent_list.addWidget(label("Aucun fichier récent.\nLes documents ouverts dans l'éditeur apparaîtront ici.", "muted", wrap=True))
        for f in recent:
            b = QPushButton(f"📄  {Path(f).name}")
            b.setObjectName("link")
            b.setToolTip(f)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, f=f: self.action_requested.emit("@editor", [f]))
            self.recent_list.addWidget(b)

    def show_suggestions(self, files: list[str]):
        while self.suggest_flow.count():
            it = self.suggest_flow.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        names = ", ".join(Path(f).name for f in files[:3]) + ("…" if len(files) > 3 else "")
        self.suggest_title.setText(f"✨ Suggestions pour {names}")
        for tid, why in suggest(files):
            icon = {"@editor": "✏️", "@organizer": "🗂️", "@compare": "🆚"}.get(tid) or (REGISTRY[tid].icon if tid in REGISTRY else "•")
            b = QPushButton(f"{icon}  {why}")
            b.setCursor(Qt.PointingHandCursor)
            if tid.startswith("@"):
                b.clicked.connect(lambda _=False, t=tid: self.action_requested.emit(t, files))
            else:
                b.clicked.connect(lambda _=False, t=tid: self.tool_requested.emit(t, files))
            self.suggest_flow.addWidget(b)
        other = QPushButton("🧰  Choisir un autre outil…")
        other.clicked.connect(lambda: (self.search.setFocus(), self.search.selectAll()))
        self.suggest_flow.addWidget(other)
        self._pending_files = files
        self.suggest_box.show()
