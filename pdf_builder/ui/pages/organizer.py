"""Organiseur visuel : miniatures glisser-déposer, multi-documents."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QPixmap, QShortcut, QTransform
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..theme import color
from ..widgets import DropZone, app_settings, button, make_toolbar, pixmap_from_page, spacer, tool_button

ROLE_DATA = Qt.UserRole + 1
SOURCE_COLORS = ["#4F46E5", "#059669", "#D97706", "#DC2626", "#0891B2", "#7C3AED", "#DB2777", "#65A30D"]


class ThumbDelegate(QStyledItemDelegate):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def sizeHint(self, option, index):
        s = self.owner.thumb_size
        return QSize(s + 28, int(s * 1.414) + 46)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(5, 5, -5, -5)
        selected = option.state & QStyle.State_Selected
        hover = option.state & QStyle.State_MouseOver
        if selected or hover:
            painter.setPen(QPen(color("accent"), 2 if selected else 1))
            painter.setBrush(color("accent_soft") if selected else color("surface2"))
            painter.drawRoundedRect(rect, 10, 10)
        data = index.data(ROLE_DATA) or {}
        pm: QPixmap | None = index.data(Qt.DecorationRole)
        area = QRect(rect.x() + 9, rect.y() + 9, rect.width() - 18, rect.height() - 40)
        if isinstance(pm, QPixmap) and not pm.isNull():
            if data.get("rot"):
                pm = pm.transformed(QTransform().rotate(data["rot"]), Qt.SmoothTransformation)
            size = pm.size() / pm.devicePixelRatio()
            size.scale(area.size(), Qt.KeepAspectRatio)
            target = QRect(area.x() + (area.width() - size.width()) // 2, area.y() + (area.height() - size.height()) // 2, size.width(), size.height())
            painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
            painter.setBrush(Qt.white)
            painter.drawRect(target.adjusted(-1, -1, 1, 1))
            painter.drawPixmap(target, pm)
        else:
            painter.setPen(QPen(color("border"), 1, Qt.DashLine))
            painter.setBrush(Qt.white)
            h = area.height()
            w = int(h / 1.414)
            painter.drawRect(area.x() + (area.width() - w) // 2, area.y(), w, h)
        # Libellé
        src_color = QColor(SOURCE_COLORS[data.get("src", 0) % len(SOURCE_COLORS)]) if data.get("src") is not None else color("muted")
        painter.setPen(Qt.NoPen)
        painter.setBrush(src_color)
        painter.drawEllipse(rect.x() + 10, rect.bottom() - 21, 9, 9)
        painter.setPen(color("text"))
        text = f"{index.row() + 1}"
        sub = data.get("label", "")
        painter.drawText(QRect(rect.x() + 24, rect.bottom() - 28, rect.width() - 30, 22), Qt.AlignVCenter | Qt.AlignLeft, f"{text}  ·  {sub}")
        painter.restore()


class PageGrid(QListWidget):
    files_dropped = Signal(list, int)

    def __init__(self, owner):
        super().__init__(owner)
        self.thumb_size = 130
        self.setViewMode(QListView.ListMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setMouseTracking(True)
        self.setItemDelegate(ThumbDelegate(self))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            idx = self.indexAt(e.position().toPoint())
            row = idx.row() if idx.isValid() else self.count()
            self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()], row)
            e.acceptProposedAction()
            return
        super().dropEvent(e)


class OrganizerPage(QWidget):
    status_message = Signal(str)
    open_in_editor = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.sources: list[tuple[Path, fitz.Document]] = []
        self.history: list[list[dict]] = []
        self._render_queue: list[int] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = make_toolbar()
        bar.addWidget(tool_button("+ Ajouter", "Ajouter des PDF ou des images", self.browse))
        bar.addSeparator()
        bar.addWidget(tool_button("↺", "Pivoter à gauche", lambda: self.rotate(-90)))
        bar.addWidget(tool_button("↻", "Pivoter à droite (Ctrl+R)", lambda: self.rotate(90)))
        bar.addWidget(tool_button("⧉", "Dupliquer", self.duplicate))
        bar.addWidget(tool_button("📄", "Insérer une page blanche", self.insert_blank))
        bar.addWidget(tool_button("🗑️", "Supprimer (Suppr)", self.delete))
        bar.addSeparator()
        bar.addWidget(tool_button("⇅", "Inverser l'ordre des pages sélectionnées (ou de toutes)", self.reverse))
        bar.addWidget(tool_button("⇄ Recto/verso", "Entrelacer : 1re moitié = rectos, 2e moitié = versos inversés", self.interleave))
        bar.addWidget(tool_button("Sélection…", "Sélectionner par numéros (ex. paires, 1-5) — Ctrl+A : tout", self.select_by_range))
        self.undo_btn = tool_button("↶", "Annuler (Ctrl+Z)", self.undo)
        bar.addWidget(self.undo_btn)
        bar.addWidget(spacer())
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(80, 260)
        self.slider.setValue(130)
        self.slider.setFixedWidth(100)
        self.slider.setToolTip("Taille des miniatures")
        self.slider.valueChanged.connect(self._resize_thumbs)
        bar.addWidget(self.slider)
        bar.addSeparator()
        bar.addWidget(button("Vider", slot=self.clear))
        bar.addWidget(button("✏️ Éditer", slot=self.send_to_editor, tip="Ouvrir le résultat dans l'éditeur"))
        bar.addWidget(button("💾 Enregistrer", "primary", self.save))
        root.addWidget(bar)

        self.legend = QLabel("")
        self.legend.setObjectName("muted")
        self.legend.setContentsMargins(16, 6, 16, 0)
        self.legend.setWordWrap(True)
        root.addWidget(self.legend)

        body = QWidget()
        bl2 = QVBoxLayout(body)
        bl2.setContentsMargins(12, 8, 12, 12)
        self.grid = PageGrid(self)
        self.grid.files_dropped.connect(self.add_files)
        self.grid.model().rowsMoved.connect(lambda *a: self._after_change(push=False))
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._menu)
        self.grid.itemDoubleClicked.connect(self._preview)
        self.drop = DropZone(
            "Organisez vos pages visuellement",
            "Déposez un ou plusieurs PDF (ou images) : réordonnez par glisser-déposer, pivotez, supprimez, dupliquez, mélangez plusieurs documents…",
            {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"},
        )
        self.drop.files_dropped.connect(lambda f: self.add_files(f, -1))
        bl2.addWidget(self.drop)
        bl2.addWidget(self.grid, 1)
        root.addWidget(body, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(5)
        self._timer.timeout.connect(self._render_some)
        self._last_state: list[dict] = []
        for seq, fn in ((QKeySequence.Delete, self.delete), (QKeySequence.Undo, self.undo), (QKeySequence("Ctrl+R"), lambda: self.rotate(90))):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self._refresh_state()

    # ------------------------------------------------------------------
    def browse(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Ajouter des documents", app_settings().last_dir(), "Documents (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)")
        if files:
            app_settings().remember_dir(files[0])
            self.add_files(files, -1)

    def add_files(self, files: list[str], row: int = -1):
        self._push()
        insert_at = self.grid.count() if row < 0 else row
        for f in files:
            p = Path(f)
            try:
                doc = fitz.open(p)
                if doc.needs_pass:
                    pw, ok = QInputDialog.getText(self, "Document protégé", f"Mot de passe de « {p.name} » :", QLineEdit.Password)
                    if not ok or not doc.authenticate(pw):
                        continue
                if not doc.is_pdf:
                    doc = fitz.open("pdf", doc.convert_to_pdf())
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Fichier ignoré", f"« {p.name} » n'a pas pu être ouvert :\n{exc}")
                continue
            src = len(self.sources)
            self.sources.append((p, doc))
            letter = chr(ord("A") + src % 26)
            for i in range(doc.page_count):
                item = self._make_item({"src": src, "page": i, "rot": 0, "label": f"{letter}{i + 1}"})
                self.grid.insertItem(insert_at, item)
                insert_at += 1
        self._after_change(push=False)

    def _make_item(self, data: dict) -> QListWidgetItem:
        it = QListWidgetItem()
        it.setData(ROLE_DATA, dict(data))
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
        if data.get("src") is not None:
            it.setToolTip(f"{self.sources[data['src']][0].name} — page {data['page'] + 1}")
        else:
            it.setToolTip("Page blanche")
        return it

    def _state(self) -> list[dict]:
        return [dict(self.grid.item(i).data(ROLE_DATA)) for i in range(self.grid.count())]

    def _push(self):
        self.history.append(self._state())
        if len(self.history) > 50:
            self.history.pop(0)

    def _after_change(self, push: bool = False):
        if push:
            self._push()
        elif self._last_state and self._last_state != self._state() and (not self.history or self.history[-1] != self._last_state):
            self.history.append(self._last_state)
        self._refresh_state()
        self._render_queue = [i for i in range(self.grid.count()) if self.grid.item(i).data(Qt.DecorationRole) is None]
        self._timer.start()
        self.grid.viewport().update()

    def _refresh_state(self):
        self._last_state = self._state()
        empty = self.grid.count() == 0
        self.drop.setVisible(empty)
        self.grid.setVisible(not empty)
        self.undo_btn.setEnabled(bool(self.history))
        if self.sources:
            parts = [f"<span style='color:{SOURCE_COLORS[i % len(SOURCE_COLORS)]}'>●</span> {chr(65 + i % 26)} = {p.name}" for i, (p, _d) in enumerate(self.sources)]
            self.legend.setText(f"{self.grid.count()} page(s)  ·  " + "   ".join(parts) + "   ·  Glissez les miniatures pour réordonner, double-clic pour agrandir.")
        else:
            self.legend.setText("")

    def _render_some(self):
        for _ in range(3):
            if not self._render_queue:
                self._timer.stop()
                return
            row = self._render_queue.pop(0)
            if row >= self.grid.count():
                continue
            it = self.grid.item(row)
            d = it.data(ROLE_DATA)
            if d.get("src") is None:
                it.setData(Qt.DecorationRole, QPixmap())
                continue
            page = self.sources[d["src"]][1][d["page"]]
            z = 260 / max(page.rect.width, page.rect.height)
            it.setData(Qt.DecorationRole, pixmap_from_page(page, z, self.devicePixelRatioF()))

    def _resize_thumbs(self, v: int):
        self.grid.thumb_size = v
        self.grid.setGridSize(QSize())
        self.grid.doItemsLayout()

    # ------------------------------------------------------------------ actions
    def _selected_rows(self) -> list[int]:
        return sorted(self.grid.row(i) for i in self.grid.selectedItems())

    def rotate(self, angle: int):
        rows = self._selected_rows()
        if not rows:
            self.status_message.emit("Sélectionnez d'abord une ou plusieurs pages")
            return
        self._push()
        for r in rows:
            it = self.grid.item(r)
            d = it.data(ROLE_DATA)
            d["rot"] = (d.get("rot", 0) + angle) % 360
            it.setData(ROLE_DATA, d)
        self._after_change()

    def delete(self):
        rows = self._selected_rows()
        if not rows:
            return
        self._push()
        for r in reversed(rows):
            self.grid.takeItem(r)
        self._after_change()

    def duplicate(self):
        rows = self._selected_rows()
        if not rows:
            return
        self._push()
        for k, r in enumerate(rows):
            src = self.grid.item(r + k)
            it = self._make_item(src.data(ROLE_DATA))
            it.setData(Qt.DecorationRole, src.data(Qt.DecorationRole))
            self.grid.insertItem(r + k + 1, it)
        self._after_change()

    def insert_blank(self):
        self._push()
        rows = self._selected_rows()
        at = rows[-1] + 1 if rows else self.grid.count()
        self.grid.insertItem(at, self._make_item({"src": None, "page": 0, "rot": 0, "label": "blanche"}))
        self._after_change()

    def reverse(self):
        rows = self._selected_rows() or list(range(self.grid.count()))
        if len(rows) < 2:
            return
        self._push()
        state = self._state()
        values = [state[r] for r in rows][::-1]
        for r, v in zip(rows, values):
            state[r] = v
        self._apply_state(state)

    def interleave(self):
        state = self._state()
        n = len(state)
        if n < 2:
            return
        self._push()
        half = (n + 1) // 2
        rectos, versos = state[:half], state[half:][::-1]
        out = []
        for i in range(half):
            out.append(rectos[i])
            if i < len(versos):
                out.append(versos[i])
        self._apply_state(out)
        self.status_message.emit("⇄ Pages entrelacées (rectos puis versos inversés)")

    def select_by_range(self):
        from ...core.utils import PageRangeError, parse_pages

        text, ok = QInputDialog.getText(self, "Sélectionner", "Pages à sélectionner (ex. 1-5, paires, impaires, 3,7,fin) :")
        if not ok:
            return
        try:
            rows = parse_pages(text, self.grid.count())
        except PageRangeError as exc:
            QMessageBox.warning(self, "Sélection", str(exc))
            return
        self.grid.clearSelection()
        for r in rows:
            self.grid.item(r).setSelected(True)

    def _apply_state(self, state: list[dict]):
        pixmaps = {}
        for i in range(self.grid.count()):
            d = self.grid.item(i).data(ROLE_DATA)
            pixmaps[(d.get("src"), d.get("page"))] = self.grid.item(i).data(Qt.DecorationRole)
        self.grid.clear()
        for d in state:
            it = self._make_item(d)
            pm = pixmaps.get((d.get("src"), d.get("page")))
            if pm is not None:
                it.setData(Qt.DecorationRole, pm)
            self.grid.addItem(it)
        self._last_state = self._state()
        self._after_change()

    def undo(self):
        if not self.history:
            return
        state = self.history.pop()
        self._last_state = []
        self._apply_state(state)
        if self.history and self.history[-1] == self._state():
            self.history.pop()
        self._refresh_state()

    def clear(self):
        if self.grid.count() and QMessageBox.question(self, "Vider", "Retirer toutes les pages ?") != QMessageBox.Yes:
            return
        self.grid.clear()
        for _p, d in self.sources:
            d.close()
        self.sources.clear()
        self.history.clear()
        self._refresh_state()

    # ------------------------------------------------------------------ export
    def build(self) -> fitz.Document | None:
        state = self._state()
        if not state:
            QMessageBox.information(self, "Organiser", "Ajoutez d'abord des pages.")
            return None
        out = fitz.open()
        last_rect = fitz.Rect(0, 0, 595, 842)
        for d in state:
            if d.get("src") is None:
                out.new_page(width=last_rect.width, height=last_rect.height)
            else:
                src = self.sources[d["src"]][1]
                out.insert_pdf(src, from_page=d["page"], to_page=d["page"])
                last_rect = src[d["page"]].rect
            if d.get("rot"):
                page = out[-1]
                page.set_rotation((page.rotation + d["rot"]) % 360)
        return out

    def save(self):
        out = self.build()
        if out is None:
            return
        first = self.sources[0][0] if self.sources else Path(app_settings().last_dir()) / "document.pdf"
        start = str(first.with_name(first.stem + "_organisé.pdf"))
        f, _ = QFileDialog.getSaveFileName(self, "Enregistrer le PDF", start, "Documents PDF (*.pdf)")
        if not f:
            return
        if not f.lower().endswith(".pdf"):
            f += ".pdf"
        if any(Path(f).resolve() == p.resolve() for p, _d in self.sources if p.exists()):
            data = out.tobytes(garbage=3, deflate=True)
            Path(f).write_bytes(data)
        else:
            out.save(f, garbage=3, deflate=True)
        out.close()
        self.status_message.emit(f"💾 PDF enregistré : {Path(f).name}")

    def send_to_editor(self):
        out = self.build()
        if out is None:
            return
        tmp = Path(tempfile.mkdtemp(prefix="pdfb_org_")) / "document_organisé.pdf"
        out.save(tmp, garbage=3, deflate=True)
        out.close()
        self.open_in_editor.emit(str(tmp))

    # ------------------------------------------------------------------
    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("↺ Pivoter à gauche", lambda: self.rotate(-90))
        m.addAction("↻ Pivoter à droite", lambda: self.rotate(90))
        m.addAction("⧉ Dupliquer", self.duplicate)
        m.addAction("📄 Page blanche après", self.insert_blank)
        m.addAction("⇅ Inverser la sélection", self.reverse)
        m.addSeparator()
        m.addAction("🗑️ Supprimer", self.delete)
        m.exec(self.grid.mapToGlobal(pos))

    def _preview(self, item: QListWidgetItem):
        d = item.data(ROLE_DATA)
        if d.get("src") is None:
            return
        page = self.sources[d["src"]][1][d["page"]]
        from PySide6.QtWidgets import QDialog, QScrollArea

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Aperçu — {d.get('label')}")
        lay = QVBoxLayout(dlg)
        area = QScrollArea()
        lab = QLabel()
        pm = pixmap_from_page(page, 1.4, self.devicePixelRatioF())
        if d.get("rot"):
            pm = pm.transformed(QTransform().rotate(d["rot"]), Qt.SmoothTransformation)
        lab.setPixmap(pm)
        area.setWidget(lab)
        lay.addWidget(area)
        dlg.resize(min(1000, int(pm.width() / pm.devicePixelRatio()) + 60), 820)
        dlg.exec()

    def has_pages(self) -> bool:
        return self.grid.count() > 0
