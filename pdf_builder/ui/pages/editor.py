"""Éditeur visuel : lecture, annotations, texte, signature, formulaires, signets."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QColor, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.overlay import stamp
from ...core.registry import REGISTRY
from ...core.tools_optimize import detect_headings
from ..dialogs import FormDialog, SignatureDialog, TextDialog
from ..viewer import PdfView
from ..widgets import ColorButton, DropZone, app_settings, button, label, make_toolbar, pixmap_from_page, spacer, tool_button

MAX_UNDO = 30

# (identifiant, icône, info-bulle, mode de saisie de la visionneuse)
EDIT_TOOLS = [
    ("pan", "✋", "Naviguer (H)", "pan"),
    ("select_text", "🔤", "Copier du texte : tracez un cadre", "rect"),
    ("edit_text", "✏️", "Modifier un texte existant : cliquez dessus", "point"),
    ("add_text", "🅣", "Ajouter du texte : cliquez à l'endroit voulu", "point"),
    ("highlight", "🖍️", "Surligner : tracez un cadre sur le texte", "rect"),
    ("underline", "U̲", "Souligner", "rect"),
    ("strike", "S̶", "Barrer", "rect"),
    ("rect", "▭", "Rectangle", "rect"),
    ("ellipse", "◯", "Ellipse", "rect"),
    ("arrow", "↗", "Flèche", "line"),
    ("ink", "〰️", "Dessin à main levée", "path"),
    ("note", "🗒️", "Note (commentaire)", "point"),
    ("image", "🖼️", "Insérer une image : tracez la zone", "rect"),
    ("signature", "✍️", "Apposer ma signature : tracez la zone", "rect"),
    ("link", "🔗", "Lien : tracez la zone cliquable", "rect"),
    ("whiteout", "⬜", "Effacer une zone (blanco définitif)", "rect"),
    ("redact", "⬛", "Caviarder une zone (noir définitif)", "rect"),
    ("eraser", "🧽", "Gomme : cliquez sur une annotation pour la supprimer", "point"),
    ("field_text", "🔲", "Créer un champ de formulaire texte : tracez la zone", "rect"),
    ("field_check", "☑️", "Créer une case à cocher : tracez la zone", "rect"),
]


def _rgb(qcolor: QColor) -> tuple[float, float, float]:
    return (qcolor.redF(), qcolor.greenF(), qcolor.blueF())


def _span_font(span: dict) -> str:
    flags = span.get("flags", 0)
    font = (span.get("font") or "").lower()
    bold = bool(flags & 16) or "bold" in font
    italic = bool(flags & 2) or "italic" in font or "oblique" in font
    if flags & 8 or "courier" in font or "mono" in font:
        base = "co"
    elif flags & 4 or "times" in font or "serif" in font and "sans" not in font:
        base = "ti"
    else:
        base = "he"
    suffix = "bi" if bold and italic else "bo" if bold else "it" if italic else ""
    if not suffix:
        return {"he": "helv", "ti": "tiro", "co": "cour"}[base]
    return base + suffix


class EditorPage(QWidget):
    status_message = Signal(str)
    run_tool = Signal(str, list)
    document_opened = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.doc: fitz.Document | None = None
        self.path: Path | None = None
        self.modified = False
        self.undo_stack: list[bytes] = []
        self.redo_stack: list[bytes] = []
        self.current_tool = "pan"
        self.signature_path: str | None = None
        self.image_path: str | None = None
        self.search_hits: list[tuple[int, fitz.Rect]] = []
        self.search_index = -1
        self._thumb_queue: list[int] = []
        self._tts = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_tools())

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setContentsMargins(80, 60, 80, 60)
        el.addStretch(1)
        el.addWidget(label("✏️ Éditeur PDF", "h1"), 0, Qt.AlignHCenter)
        el.addWidget(label("Lisez, annotez, signez, remplissez et modifiez vos PDF.", "muted"), 0, Qt.AlignHCenter)
        el.addSpacing(16)
        drop = DropZone("Ouvrir un PDF", "Glissez-déposez un fichier ou cliquez pour parcourir", {".pdf", ".png", ".jpg", ".jpeg", ".xps", ".epub"}, multiple=False)
        drop.setMaximumWidth(640)
        drop.files_dropped.connect(lambda f: self.open_file(f[0]))
        el.addWidget(drop, 0, Qt.AlignHCenter)
        el.addStretch(2)
        self.stack.addWidget(empty)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        split.addWidget(self._build_side())
        self.view = PdfView()
        self.view.pageChanged.connect(self._on_page_changed)
        self.view.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{z * 100:.0f} %"))
        self.view.rectSelected.connect(self._on_rect)
        self.view.pointClicked.connect(self._on_point)
        self.view.pathDrawn.connect(self._on_path)
        self.view.lineDrawn.connect(self._on_line)
        self.view.filesDropped.connect(self._on_files_dropped)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([200, 900])
        self.stack.addWidget(split)

        self._thumb_timer = QTimer(self)
        self._thumb_timer.setInterval(10)
        self._thumb_timer.timeout.connect(self._render_thumbs)

        for seq, fn in (
            (QKeySequence.Save, self.save),
            (QKeySequence("Ctrl+Shift+S"), self.save_as),
            (QKeySequence.Undo, self.undo),
            (QKeySequence.Redo, self.redo),
            (QKeySequence.Find, lambda: (self.search_edit.setFocus(), self.search_edit.selectAll())),
            (QKeySequence.ZoomIn, lambda: self.view.set_zoom(self.view.zoom * 1.2)),
            (QKeySequence.ZoomOut, lambda: self.view.set_zoom(self.view.zoom / 1.2)),
            (QKeySequence("Ctrl+P"), self.print_doc),
            (QKeySequence("Escape"), lambda: self.set_tool("pan")),
            (QKeySequence("PgDown"), lambda: self.view.go_to_page(self.view.current_page() + 1)),
            (QKeySequence("PgUp"), lambda: self.view.go_to_page(self.view.current_page() - 1)),
        ):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self._update_actions()

    # ================================================================ interface
    def _build_toolbar(self) -> QWidget:
        bar = make_toolbar()
        bar.addWidget(tool_button("📂 Ouvrir", "Ouvrir un PDF (Ctrl+O)", self.browse))
        self.save_btn = tool_button("💾 Enregistrer", "Enregistrer (Ctrl+S)", self.save)
        bar.addWidget(self.save_btn)
        self.saveas_btn = tool_button("📑 Copie…", "Enregistrer sous / une copie (Ctrl+Maj+S)", self.save_as)
        bar.addWidget(self.saveas_btn)
        self.print_btn = tool_button("🖨️", "Imprimer (Ctrl+P)", self.print_doc)
        bar.addWidget(self.print_btn)
        bar.addSeparator()
        self.undo_btn = tool_button("↶", "Annuler (Ctrl+Z)", self.undo)
        self.redo_btn = tool_button("↷", "Rétablir (Ctrl+Y)", self.redo)
        bar.addWidget(self.undo_btn)
        bar.addWidget(self.redo_btn)
        bar.addSeparator()
        bar.addWidget(tool_button("◀", "Page précédente", lambda: self.view.go_to_page(self.view.current_page() - 1)))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setFixedWidth(70)
        self.page_spin.editingFinished.connect(lambda: self.view.go_to_page(self.page_spin.value() - 1))
        bar.addWidget(self.page_spin)
        self.page_total = QLabel("/ 0")
        bar.addWidget(self.page_total)
        bar.addWidget(tool_button("▶", "Page suivante", lambda: self.view.go_to_page(self.view.current_page() + 1)))
        bar.addSeparator()
        bar.addWidget(tool_button("−", "Zoom arrière (Ctrl+-)", lambda: self.view.set_zoom(self.view.zoom / 1.2)))
        self.zoom_label = QLabel("100 %")
        self.zoom_label.setFixedWidth(52)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        bar.addWidget(self.zoom_label)
        bar.addWidget(tool_button("+", "Zoom avant (Ctrl++)", lambda: self.view.set_zoom(self.view.zoom * 1.2)))
        bar.addWidget(tool_button("↔", "Ajuster à la largeur", lambda: self.view.fit_width()))
        bar.addWidget(tool_button("⤢", "Page entière", lambda: self.view.fit_page()))
        bar.addWidget(spacer())
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Rechercher (Ctrl+F)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(190)
        self.search_edit.returnPressed.connect(self.search_next)
        self.search_edit.textChanged.connect(self._search_reset)
        bar.addWidget(self.search_edit)
        self.search_info = QLabel("")
        bar.addWidget(self.search_info)
        bar.addSeparator()
        self.night_btn = tool_button("🌙", "Lecture nocturne (couleurs inversées)", checkable=True)
        self.night_btn.toggled.connect(self.view_night)
        bar.addWidget(self.night_btn)
        self.tts_btn = tool_button("🔊", "Lire la page à voix haute", self.read_aloud)
        bar.addWidget(self.tts_btn)
        self.more_btn = QToolButton()
        self.more_btn.setText("🧰 Outils ▾")
        self.more_btn.setToolTip("Appliquer un outil à ce document")
        self.more_btn.setPopupMode(QToolButton.InstantPopup)
        self.more_btn.setMenu(self._tools_menu())
        bar.addWidget(self.more_btn)
        return bar

    def _tools_menu(self) -> QMenu:
        from ...core.registry import CATEGORIES

        menu = QMenu(self)
        for cat_id, cat_name, icon in CATEGORIES:
            sub = menu.addMenu(f"{icon} {cat_name}")
            for t in REGISTRY.values():
                if t.category == cat_id and t.accepts not in ("none", "images", "office", "text"):
                    sub.addAction(f"{t.icon} {t.name}", lambda tid=t.id: self._send_to_tool(tid))
        return menu

    def _build_tools(self) -> QWidget:
        bar = make_toolbar()
        self.tool_buttons: dict[str, QToolButton] = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for tid, icon, tip, _mode in EDIT_TOOLS:
            b = tool_button(icon, tip, checkable=True)
            b.setMinimumWidth(34)
            b.clicked.connect(lambda _=False, t=tid: self.set_tool(t))
            self.tool_buttons[tid] = b
            bar.addWidget(b)
            if tid in ("pan", "edit_text", "strike", "ink", "signature", "redact", "eraser"):
                bar.addSeparator()
        self.tool_buttons["pan"].setChecked(True)
        bar.addSeparator()
        self.color_btn = ColorButton("#E11D48")
        self.color_btn.setFixedWidth(80)
        self.color_btn.setToolTip("Couleur des annotations")
        self.color_btn.changed.connect(lambda: setattr(self.view, "draw_color", QColor(self.color_btn.value())))
        bar.addWidget(self.color_btn)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 20)
        self.width_spin.setValue(2)
        self.width_spin.setSuffix(" pt")
        self.width_spin.setFixedWidth(72)
        self.width_spin.setToolTip("Épaisseur du trait")
        bar.addWidget(self.width_spin)
        bar.addWidget(spacer())
        self.form_btn = button("📋 Formulaire", slot=self.fill_form)
        bar.addWidget(self.form_btn)
        bar.addWidget(tool_button("↻", "Pivoter la page courante", self.rotate_page))
        bar.addWidget(tool_button("+📄", "Insérer une page blanche après la page courante", self.insert_blank))
        bar.addWidget(tool_button("🗑️", "Supprimer la page courante", self.delete_page))
        return bar

    def _build_side(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidePanel")
        side.setMinimumWidth(150)
        side.setMaximumWidth(320)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(6, 6, 6, 6)
        tabs = QTabWidget()
        self.side_tabs = tabs
        lay.addWidget(tabs)

        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setFlow(QListWidget.TopToBottom)
        self.thumbs.setWrapping(False)
        self.thumbs.setIconSize(QSize(120, 160))
        self.thumbs.setSpacing(6)
        self.thumbs.setMovement(QListWidget.Static)
        self.thumbs.setResizeMode(QListWidget.Adjust)
        self.thumbs.setUniformItemSizes(True)
        self.thumbs.itemClicked.connect(lambda it: self.view.go_to_page(self.thumbs.row(it)))
        self.thumbs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)
        tabs.addTab(self.thumbs, "Pages")

        bm = QWidget()
        bl = QVBoxLayout(bm)
        bl.setContentsMargins(0, 4, 0, 0)
        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderHidden(True)
        self.toc_tree.itemClicked.connect(self._toc_clicked)
        self.toc_tree.itemDoubleClicked.connect(self._toc_rename)
        bl.addWidget(self.toc_tree, 1)
        row = QHBoxLayout()
        row.addWidget(tool_button("＋", "Ajouter un signet sur la page courante", self.add_bookmark))
        row.addWidget(tool_button("✎", "Renommer", lambda: self._toc_rename(self.toc_tree.currentItem())))
        row.addWidget(tool_button("🗑", "Supprimer le signet", self.delete_bookmark))
        row.addWidget(tool_button("✨", "Générer automatiquement depuis les titres", self.auto_bookmarks))
        row.addStretch(1)
        bl.addLayout(row)
        tabs.addTab(bm, "Signets")

        info = QWidget()
        il = QVBoxLayout(info)
        self.info_label = label("", None, wrap=True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_label.setAlignment(Qt.AlignTop)
        il.addWidget(self.info_label, 1)
        tabs.addTab(info, "Infos")
        self._info_dirty = True
        tabs.currentChanged.connect(lambda i: self._reload_info() if i == 2 and self._info_dirty else None)
        return side

    # ================================================================ fichiers
    def browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Ouvrir un document", app_settings().last_dir(), "Documents (*.pdf *.xps *.epub *.png *.jpg *.jpeg);;Tous les fichiers (*)")
        if f:
            app_settings().remember_dir(f)
            self.open_file(f)

    def _on_files_dropped(self, files: list[str]):
        if files:
            self.open_file(files[0])

    def open_file(self, path: str, page: int = 0, search: str | None = None) -> bool:
        if not self.confirm_discard():
            return False
        p = Path(path)
        try:
            data = p.read_bytes()
            doc = fitz.open(stream=data, filetype=p.suffix.lstrip(".").lower() or "pdf")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Ouverture impossible", f"Impossible d'ouvrir « {p.name} » :\n{exc}")
            return False
        if doc.needs_pass:
            while True:
                pw, ok = QInputDialog.getText(self, "Document protégé", f"« {p.name} » est protégé.\nMot de passe :", QLineEdit.Password)
                if not ok:
                    return False
                if doc.authenticate(pw):
                    break
                QMessageBox.warning(self, "Mot de passe incorrect", "Le mot de passe est incorrect, réessayez.")
        if not doc.is_pdf:
            doc = fitz.open("pdf", doc.convert_to_pdf())
            p = p.with_suffix(".pdf")
            self.modified = True
        else:
            self.modified = False
        self.doc = doc
        self.path = p
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.stack.setCurrentIndex(1)
        self.view.set_document(doc)
        QTimer.singleShot(0, lambda: (self.view.fit_width(), self.view.go_to_page(0)))
        self._reload_side()
        self._update_actions()
        if path.lower().endswith(".pdf"):
            app_settings().add_recent(str(path))
            self.document_opened.emit(str(path))
        if page:
            QTimer.singleShot(60, lambda: self.view.go_to_page(page))
        if search:
            self.search_edit.setText(search)
            QTimer.singleShot(120, self.search_next)
        return True

    def confirm_discard(self) -> bool:
        if not self.doc or not self.modified:
            return True
        r = QMessageBox.question(
            self,
            "Modifications non enregistrées",
            f"Enregistrer les modifications de « {self.path.name if self.path else 'document'} » ?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def save(self) -> bool:
        if not self.doc:
            return False
        if not self.path or not self.path.exists() or self.path.suffix.lower() != ".pdf":
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        if not self.doc:
            return False
        start = str(self.path.with_name(self.path.stem + "_modifié.pdf")) if self.path else app_settings().last_dir()
        f, _ = QFileDialog.getSaveFileName(self, "Enregistrer sous", start, "Documents PDF (*.pdf)")
        if not f:
            return False
        if not f.lower().endswith(".pdf"):
            f += ".pdf"
        if self._write(Path(f)):
            self.path = Path(f)
            app_settings().add_recent(f)
            return True
        return False

    def _write(self, target: Path) -> bool:
        try:
            data = self.doc.tobytes(garbage=3, deflate=True)
            fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=str(target.parent))
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Enregistrement impossible", f"Impossible d'enregistrer :\n{exc}")
            return False
        self.modified = False
        self._update_actions()
        self.status_message.emit(f"💾 Enregistré : {target.name}")
        return True

    def _send_to_tool(self, tool_id: str):
        if not self.doc:
            return
        if self.modified and not self.save():
            return
        self.run_tool.emit(tool_id, [str(self.path)])

    # ================================================================ historique
    def _snapshot(self):
        self.undo_stack.append(self.doc.tobytes())
        if len(self.undo_stack) > MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _changed(self, pages: list[int] | None = None, structure: bool = False):
        self.modified = True
        if structure:
            self.view.set_document(self.doc, keep_position=True)
            self._reload_side()
        else:
            for p in pages or []:
                self.view.refresh_page(p)
                self._queue_thumb(p)
        self._update_actions()

    def _restore(self, data: bytes):
        self.doc = fitz.open("pdf", data)
        self.view.set_document(self.doc, keep_position=True)
        self._reload_side()
        self.modified = True
        self._update_actions()

    def undo(self):
        if not self.undo_stack or not self.doc:
            return
        self.redo_stack.append(self.doc.tobytes())
        self._restore(self.undo_stack.pop())
        self.status_message.emit("↶ Action annulée")

    def redo(self):
        if not self.redo_stack or not self.doc:
            return
        self.undo_stack.append(self.doc.tobytes())
        self._restore(self.redo_stack.pop())

    def _update_actions(self):
        has = self.doc is not None
        for w in (self.save_btn, self.saveas_btn, self.print_btn, self.more_btn, self.form_btn, self.night_btn, self.tts_btn, self.search_edit):
            w.setEnabled(has)
        for b in self.tool_buttons.values():
            b.setEnabled(has)
        self.undo_btn.setEnabled(bool(self.undo_stack))
        self.redo_btn.setEnabled(bool(self.redo_stack))
        if has:
            self.page_spin.setMaximum(self.doc.page_count)
            self.page_total.setText(f"/ {self.doc.page_count}")
            title = (self.path.name if self.path else "Sans titre") + (" •" if self.modified else "")
            self.window().setWindowTitle(f"{title} — PDF Builder") if self.isVisible() else None
        self.save_btn.setText("💾 Enregistrer" + (" •" if self.modified else ""))

    # ================================================================ panneau latéral
    def _reload_side(self):
        self.thumbs.clear()
        if not self.doc:
            return
        placeholder = QIcon()
        for i in range(self.doc.page_count):
            it = QListWidgetItem(placeholder, str(i + 1))
            it.setTextAlignment(Qt.AlignHCenter)
            it.setSizeHint(QSize(140, 190))
            self.thumbs.addItem(it)
        self._thumb_queue = list(range(self.doc.page_count))
        self._thumb_timer.start()
        self._reload_toc()
        # L'analyse complète peut être longue sur un gros document : calcul à la demande.
        self._info_dirty = True
        if self.side_tabs.currentIndex() == 2:
            self._reload_info()

    def _queue_thumb(self, i: int):
        if i not in self._thumb_queue:
            self._thumb_queue.insert(0, i)
        self._thumb_timer.start()

    def _render_thumbs(self):
        if not self.doc or not self._thumb_queue:
            self._thumb_timer.stop()
            return
        for _ in range(2):
            if not self._thumb_queue:
                break
            i = self._thumb_queue.pop(0)
            if i >= self.doc.page_count or i >= self.thumbs.count():
                continue
            page = self.doc[i]
            z = min(120 / page.rect.width, 160 / page.rect.height)
            pm = pixmap_from_page(page, z, self.devicePixelRatioF())
            icon = QIcon(pm)
            icon.addPixmap(pm, QIcon.Selected)  # pas de teinte de sélection sur la miniature
            self.thumbs.item(i).setIcon(icon)

    def _thumb_menu(self, pos):
        it = self.thumbs.itemAt(pos)
        if not it:
            return
        idx = self.thumbs.row(it)
        self.view.go_to_page(idx)
        m = QMenu(self)
        m.addAction("↻ Pivoter de 90°", self.rotate_page)
        m.addAction("＋ Page blanche après", self.insert_blank)
        m.addAction("⧉ Dupliquer la page", self.duplicate_page)
        m.addAction("📤 Extraire cette page…", self.extract_page)
        m.addSeparator()
        m.addAction("🗑️ Supprimer la page", self.delete_page)
        m.exec(self.thumbs.mapToGlobal(pos))

    def _reload_toc(self):
        self.toc_tree.clear()
        if not self.doc:
            return
        parents: dict[int, QTreeWidgetItem] = {}
        for k, (lvl, title, page, *_rest) in enumerate(self.doc.get_toc(simple=False)):
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.UserRole, k)
            item.setToolTip(0, f"Page {page}")
            parent = parents.get(lvl - 1)
            if parent is not None:
                parent.addChild(item)
            else:
                self.toc_tree.addTopLevelItem(item)
            parents[lvl] = item
        self.toc_tree.expandToDepth(0)

    def _toc_clicked(self, item):
        toc = self.doc.get_toc(simple=False)
        k = item.data(0, Qt.UserRole)
        if k is not None and k < len(toc):
            entry = toc[k]
            y = None
            if len(entry) > 3 and isinstance(entry[3], dict) and entry[3].get("to") is not None:
                to = entry[3]["to"]
                y = getattr(to, "y", None)
            self.view.go_to_page(entry[2] - 1, y)

    def _toc_rename(self, item):
        if not item:
            return
        toc = self.doc.get_toc(simple=False)
        k = item.data(0, Qt.UserRole)
        text, ok = QInputDialog.getText(self, "Renommer le signet", "Titre :", text=toc[k][1])
        if ok and text.strip():
            self._snapshot()
            toc[k][1] = text.strip()
            self.doc.set_toc(toc)
            self._reload_toc()
            self._changed()

    def add_bookmark(self):
        if not self.doc:
            return
        page = self.view.current_page()
        text, ok = QInputDialog.getText(self, "Nouveau signet", f"Titre du signet (page {page + 1}) :")
        if ok and text.strip():
            self._snapshot()
            toc = self.doc.get_toc(simple=True)
            toc.append([1, text.strip(), page + 1])
            toc.sort(key=lambda e: e[2]) if all(e[0] == 1 for e in toc) else None
            self.doc.set_toc(toc)
            self._reload_toc()
            self._changed()

    def delete_bookmark(self):
        item = self.toc_tree.currentItem()
        if not item:
            return
        self._snapshot()
        toc = self.doc.get_toc(simple=False)
        k = item.data(0, Qt.UserRole)
        lvl = toc[k][0]
        end = k + 1
        while end < len(toc) and toc[end][0] > lvl:
            end += 1
        del toc[k:end]
        self.doc.set_toc(toc)
        self._reload_toc()
        self._changed()

    def auto_bookmarks(self):
        if not self.doc:
            return
        toc = detect_headings(self.doc)
        if not toc:
            QMessageBox.information(self, "Signets", "Aucun titre n'a été détecté dans ce document.")
            return
        self._snapshot()
        self.doc.set_toc(toc)
        self._reload_toc()
        self._changed()
        self.status_message.emit(f"✨ {len(toc)} signets générés")

    def _reload_info(self):
        from ...core.tools_extract import analyze, format_report

        if not self.doc:
            return
        self._info_dirty = False

        try:
            info = analyze(self.doc, self.path if self.path and self.path.exists() else None)
            self.info_label.setText(format_report(info, self.path.name if self.path else "Document").replace("   ", ""))
        except Exception as exc:  # noqa: BLE001
            self.info_label.setText(str(exc))

    def _on_page_changed(self, idx: int):
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(idx + 1)
        self.page_spin.blockSignals(False)
        if idx < self.thumbs.count():
            self.thumbs.setCurrentRow(idx)

    # ================================================================ outils d'édition
    def set_tool(self, tid: str):
        if tid == "signature":
            dlg = SignatureDialog(self)
            if not dlg.exec() or not dlg.result_path:
                tid = "pan"
            else:
                self.signature_path = dlg.result_path
                self.status_message.emit("✍️ Tracez la zone où apposer votre signature")
        elif tid == "image":
            f, _ = QFileDialog.getOpenFileName(self, "Choisir une image", app_settings().last_dir(), "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
            if not f:
                tid = "pan"
            else:
                self.image_path = f
                self.status_message.emit("🖼️ Tracez la zone où placer l'image")
        self.current_tool = tid
        for k, b in self.tool_buttons.items():
            b.setChecked(k == tid)
        mode = next(m for t, _i, _tip, m in EDIT_TOOLS if t == tid)
        self.view.set_mode(mode)
        self.view.draw_color = QColor(self.color_btn.value())
        tip = next(tip for t, _i, tip, _m in EDIT_TOOLS if t == tid)
        if tid != "pan":
            self.status_message.emit(tip)

    def _unrot(self, page: fitz.Page, obj):
        return obj * page.derotation_matrix

    def _on_rect(self, index: int, r: fitz.Rect):
        page = self.doc[index]
        ur = self._unrot(page, r).normalize()
        col = _rgb(QColor(self.color_btn.value()))
        width = self.width_spin.value()
        t = self.current_tool
        if t == "select_text":
            text = page.get_text("text", clip=ur, sort=True).strip()
            if text:
                QGuiApplication.clipboard().setText(text)
                self.status_message.emit(f"📋 {len(text)} caractères copiés dans le presse-papiers")
            else:
                self.status_message.emit("Aucun texte dans cette zone (page scannée ? utilisez l'OCR)")
            return
        self._snapshot()
        if t in ("highlight", "underline", "strike"):
            words = [w for w in page.get_text("words") if fitz.Rect(w[:4]).intersects(ur)]
            if words:
                quads = [fitz.Rect(w[:4]).quad for w in words]
                fn = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot, "strike": page.add_strikeout_annot}[t]
                annot = fn(quads)
                annot.set_colors(stroke=col if t != "highlight" or self.color_btn.value().upper() != "#E11D48" else (1, 0.85, 0.1))
                annot.update()
            else:
                annot = page.add_rect_annot(ur)
                annot.set_colors(stroke=None, fill=(1, 0.9, 0.2))
                annot.set_opacity(0.35)
                annot.update()
        elif t in ("rect", "ellipse"):
            annot = page.add_rect_annot(ur) if t == "rect" else page.add_circle_annot(ur)
            annot.set_colors(stroke=col)
            annot.set_border(width=width)
            annot.update()
        elif t == "image" and self.image_path:
            path = self.image_path
            stamp(page, lambda op: op.insert_image(r, filename=path, keep_proportion=True))
        elif t == "signature" and self.signature_path:
            path = self.signature_path
            stamp(page, lambda op: op.insert_image(r, filename=path, keep_proportion=True))
            self.status_message.emit("✍️ Signature apposée. Pour une signature certifiée, utilisez « Signer numériquement ».")
        elif t == "link":
            target, ok = QInputDialog.getText(self, "Lien", "Adresse web (https://…) ou numéro de page :")
            if not ok or not target.strip():
                self.undo_stack.pop()
                return
            target = target.strip()
            if target.isdigit():
                page.insert_link({"kind": fitz.LINK_GOTO, "from": ur, "page": max(0, min(int(target) - 1, self.doc.page_count - 1)), "to": fitz.Point(0, 0)})
            else:
                if "://" not in target and not target.startswith("mailto:"):
                    target = ("mailto:" + target) if "@" in target else "https://" + target
                page.insert_link({"kind": fitz.LINK_URI, "from": ur, "uri": target})
            annot = page.add_rect_annot(ur)
            annot.set_colors(stroke=(0.2, 0.4, 0.9))
            annot.set_border(width=0.6, dashes=[2, 2])
            annot.update()
        elif t in ("field_text", "field_check"):
            existing = {w.field_name for p in self.doc for w in p.widgets()}
            base = "texte" if t == "field_text" else "case"
            k = 1
            while f"{base}_{k}" in existing:
                k += 1
            name, ok = QInputDialog.getText(self, "Nouveau champ", "Nom du champ (utilisé pour l'export et le publipostage) :", text=f"{base}_{k}")
            if not ok or not name.strip():
                self.undo_stack.pop()
                return
            w = fitz.Widget()
            w.field_name = name.strip()
            w.field_type = fitz.PDF_WIDGET_TYPE_TEXT if t == "field_text" else fitz.PDF_WIDGET_TYPE_CHECKBOX
            if t == "field_check":
                side = min(ur.width, ur.height)
                ur = fitz.Rect(ur.x0, ur.y0, ur.x0 + side, ur.y0 + side)
            else:
                w.text_fontsize = 0  # taille automatique
            w.rect = ur
            w.border_color = (0.45, 0.47, 0.6)
            w.fill_color = (0.95, 0.96, 1)
            page.add_widget(w)
            self.status_message.emit(f"📋 Champ « {w.field_name} » créé — remplissez-le avec le bouton Formulaire")
        elif t in ("whiteout", "redact"):
            fill = (1, 1, 1) if t == "whiteout" else (0, 0, 0)
            page.add_redact_annot(ur, fill=fill)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)
        else:
            self.undo_stack.pop()
            return
        self._changed([index])

    def _on_point(self, index: int, pt: fitz.Point):
        page = self.doc[index]
        upt = self._unrot(page, pt)
        t = self.current_tool
        if t == "add_text":
            dlg = TextDialog(self, color_hex=self.color_btn.value() if self.color_btn.value().upper() != "#E11D48" else "#000000")
            if not dlg.exec():
                return
            v = dlg.values()
            if not v["text"].strip():
                return
            self._snapshot()
            from ...core.utils import parse_color

            c = parse_color(v["color"])

            def draw(op):
                op.insert_text((pt.x, pt.y + v["size"] * 0.8), v["text"], fontsize=v["size"], fontname=v["font"], color=c, lineheight=1.25)

            stamp(page, draw)
            self._changed([index])
        elif t == "edit_text":
            self._edit_text_at(page, upt)
        elif t == "note":
            text, ok = QInputDialog.getMultiLineText(self, "Note", "Votre commentaire :")
            if ok and text.strip():
                self._snapshot()
                annot = page.add_text_annot(upt, text.strip(), icon="Comment")
                annot.set_colors(stroke=_rgb(QColor(self.color_btn.value())))
                annot.set_info(title=os.environ.get("USERNAME") or os.environ.get("USER") or "PDF Builder")
                annot.update()
                self._changed([index])
        elif t == "eraser":
            for annot in page.annots():
                if annot.rect.contains(upt) or annot.rect.intersects(fitz.Rect(upt.x - 3, upt.y - 3, upt.x + 3, upt.y + 3)):
                    self._snapshot()
                    page.delete_annot(annot)
                    self._changed([index])
                    return
            for link in page.get_links():
                if fitz.Rect(link["from"]).contains(upt):
                    self._snapshot()
                    page.delete_link(link)
                    self._changed([index])
                    return
            self.status_message.emit("Aucune annotation à cet endroit (le contenu d'origine se modifie avec ✏️ ou ⬜)")
        elif t in ("image", "signature"):
            # Simple clic : taille par défaut centrée sur le point.
            w = 160 if t == "signature" else 200
            self._on_rect(index, fitz.Rect(pt.x - w / 2, pt.y - w / 6, pt.x + w / 2, pt.y + w / 6) & page.rect)
        elif t in ("highlight", "underline", "strike", "select_text", "rect", "ellipse", "link", "whiteout", "redact"):
            self.status_message.emit("Maintenez le bouton et faites glisser pour tracer une zone")

    def _edit_text_at(self, page: fitz.Page, upt: fitz.Point):
        target = None
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for span in line["spans"]:
                    if fitz.Rect(span["bbox"]).contains(upt) and span["text"].strip():
                        target = span
                        break
        if not target:
            self.status_message.emit("Cliquez précisément sur un texte (les pages scannées doivent d'abord passer par l'OCR)")
            return
        c = target.get("color", 0)
        hexcol = f"#{c:06X}"
        dlg = TextDialog(self, "Modifier le texte", target["text"], target["size"], hexcol, _span_font(target))
        if not dlg.exec():
            return
        v = dlg.values()
        self._snapshot()
        bbox = fitz.Rect(target["bbox"])
        page.add_redact_annot(bbox)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        from ...core.utils import parse_color

        if v["text"]:
            origin = fitz.Point(target["origin"])
            # Le texte d'origine est horizontal dans le repère non pivoté : on l'y réécrit.
            page.insert_text(origin, v["text"], fontsize=v["size"], fontname=v["font"], color=parse_color(v["color"]))
        self._changed([page.number])

    def _on_path(self, index: int, pts: list):
        page = self.doc[index]
        self._snapshot()
        upts = [self._unrot(page, p) for p in pts[:: max(1, len(pts) // 400)]]
        annot = page.add_ink_annot([[(p.x, p.y) for p in upts]])
        annot.set_colors(stroke=_rgb(QColor(self.color_btn.value())))
        annot.set_border(width=self.width_spin.value())
        annot.update()
        self._changed([index])

    def _on_line(self, index: int, a: fitz.Point, b: fitz.Point):
        page = self.doc[index]
        self._snapshot()
        annot = page.add_line_annot(self._unrot(page, a), self._unrot(page, b))
        annot.set_colors(stroke=_rgb(QColor(self.color_btn.value())))
        annot.set_border(width=self.width_spin.value())
        annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_OPEN_ARROW)
        annot.update()
        self._changed([index])

    # ================================================================ pages
    def rotate_page(self):
        if not self.doc:
            return
        self._snapshot()
        page = self.doc[self.view.current_page()]
        page.set_rotation((page.rotation + 90) % 360)
        self._changed(structure=True)

    def insert_blank(self):
        if not self.doc:
            return
        self._snapshot()
        i = self.view.current_page()
        r = self.doc[i].rect
        self.doc.new_page(pno=i + 1 if i + 1 < self.doc.page_count else -1, width=r.width, height=r.height)
        self._changed(structure=True)

    def duplicate_page(self):
        if not self.doc:
            return
        self._snapshot()
        i = self.view.current_page()
        self.doc.fullcopy_page(i, i + 1 if i + 1 < self.doc.page_count else -1)
        self._changed(structure=True)

    def delete_page(self):
        if not self.doc:
            return
        if self.doc.page_count <= 1:
            QMessageBox.information(self, "Supprimer", "Un document doit contenir au moins une page.")
            return
        self._snapshot()
        self.doc.delete_page(self.view.current_page())
        self._changed(structure=True)

    def extract_page(self):
        if not self.doc:
            return
        i = self.view.current_page()
        start = str(self.path.with_name(f"{self.path.stem}_page{i + 1}.pdf")) if self.path else ""
        f, _ = QFileDialog.getSaveFileName(self, "Extraire la page", start, "Documents PDF (*.pdf)")
        if f:
            out = fitz.open()
            out.insert_pdf(self.doc, from_page=i, to_page=i)
            out.save(f, garbage=3, deflate=True)
            self.status_message.emit(f"📤 Page {i + 1} extraite")

    # ================================================================ divers
    def fill_form(self):
        if not self.doc:
            return
        dlg = FormDialog(self.doc, self)
        if dlg.editors and dlg.exec():
            self._snapshot()
            n = dlg.apply()
            self._changed(list(range(self.doc.page_count)))
            self.status_message.emit(f"📋 {n} champ(s) mis à jour")

    def view_night(self, on: bool):
        self.view.set_night(on)

    def _search_reset(self, *_):
        self.search_hits = []
        self.search_index = -1
        self.search_info.setText("")
        self.view.clear_search()

    def search_next(self):
        q = self.search_edit.text().strip()
        if not self.doc or not q:
            return
        if not self.search_hits:
            for page in self.doc:
                for r in page.search_for(q):
                    self.search_hits.append((page.number, r * page.rotation_matrix))
            if not self.search_hits:
                self.search_info.setText("Aucun résultat")
                return
        self.search_index = (self.search_index + 1) % len(self.search_hits)
        pno, r = self.search_hits[self.search_index]
        self.view.show_search(self.search_hits, self.search_index)
        self.view.go_to_page(pno, max(0, r.y0 - 80))
        self.search_info.setText(f"{self.search_index + 1}/{len(self.search_hits)}")

    def read_aloud(self):
        if not self.doc:
            return
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
        except ImportError:
            QMessageBox.information(self, "Lecture à voix haute", "La synthèse vocale n'est pas disponible sur ce système.")
            return
        if self._tts is None:
            self._tts = QTextToSpeech(self)
            for loc in self._tts.availableLocales():
                if loc.name().startswith("fr"):
                    self._tts.setLocale(loc)
                    break
        if self._tts.state() == QTextToSpeech.Speaking:
            self._tts.stop()
            return
        text = self.doc[self.view.current_page()].get_text("text", sort=True)
        if text.strip():
            self._tts.say(text)
        else:
            self.status_message.emit("Cette page ne contient pas de texte lisible")

    def print_doc(self):
        if not self.doc:
            return
        from PySide6.QtGui import QPainter
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.HighResolution)
        printer.setFromTo(1, self.doc.page_count)
        dlg = QPrintDialog(printer, self)
        dlg.setMinMax(1, self.doc.page_count)
        if not dlg.exec():
            return
        first = max(1, printer.fromPage() or 1)
        last = min(self.doc.page_count, printer.toPage() or self.doc.page_count)
        painter = QPainter()
        if not painter.begin(printer):
            return
        dpi = min(printer.resolution(), 300)
        for k, pno in enumerate(range(first - 1, last)):
            if k:
                printer.newPage()
            page = self.doc[pno]
            pm = pixmap_from_page(page, dpi / 72)
            target = painter.viewport()
            size = pm.size()
            size.scale(target.size(), Qt.KeepAspectRatio)
            painter.setViewport(target.x(), target.y(), size.width(), size.height())
            painter.setWindow(pm.rect())
            painter.drawPixmap(0, 0, pm)
            painter.setViewport(target)
        painter.end()
        self.status_message.emit("🖨️ Document envoyé à l'imprimante")

    def has_document(self) -> bool:
        return self.doc is not None
