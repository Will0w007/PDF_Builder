"""Composants d'interface réutilisables."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.registry import Param, Tool
from ..core.utils import human_size

# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def button(text: str, name: str | None = None, slot=None, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def tool_button(text: str, tip: str, slot=None, checkable: bool = False) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setCursor(Qt.PointingHandCursor)
    b.setAutoRaise(True)
    if slot:
        b.clicked.connect(slot)
    return b


def make_toolbar() -> QToolBar:
    """Barre d'outils qui replie automatiquement les boutons qui ne tiennent pas (»)."""
    bar = QToolBar()
    bar.setObjectName("toolbar")
    bar.setMovable(False)
    bar.setFloatable(False)
    return bar


def spacer() -> QWidget:
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return w


def separator() -> QFrame:
    f = QFrame()
    f.setObjectName("separator")
    return f


def open_path(path: str | Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def reveal_in_folder(path: str | Path) -> None:
    path = Path(path)
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(path)])
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
            return
    except OSError:
        pass
    open_path(path if path.is_dir() else path.parent)


def pixmap_from_page(page: fitz.Page, zoom: float, dpr: float = 1.0, night: bool = False, alpha: bool = False) -> QPixmap:
    from PySide6.QtGui import QImage

    pix = page.get_pixmap(matrix=fitz.Matrix(zoom * dpr, zoom * dpr), alpha=alpha, annots=True)
    if night:
        pix.invert_irect()
    fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
    qp = QPixmap.fromImage(img)
    qp.setDevicePixelRatio(dpr)
    return qp


def emoji_icon(text: str, size: int = 64) -> QIcon:
    from PySide6.QtGui import QFont, QPainter

    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    f = QFont()
    f.setPixelSize(int(size * 0.8))
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, text)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# Disposition fluide (cartes qui passent à la ligne)
# ---------------------------------------------------------------------------
class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 12):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        visible = [i for i in self._items if not (i.widget() and i.widget().isHidden())]
        if not visible:
            return m.top() + m.bottom()
        hint_w = max(i.sizeHint().width() for i in visible)
        cols = max(1, (eff.width() + self._spacing) // (hint_w + self._spacing))
        col_w = (eff.width() - (cols - 1) * self._spacing) / cols
        x, y, row_h, col = eff.x(), eff.y(), 0, 0
        for item in visible:
            h = item.sizeHint().height()
            if col == cols:
                col = 0
                y += row_h + self._spacing
                row_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(int(x + col * (col_w + self._spacing)), y), QSize(int(col_w), h)))
            row_h = max(row_h, h)
            col += 1
        return y + row_h - rect.y() + m.bottom()


# ---------------------------------------------------------------------------
# Carte d'outil
# ---------------------------------------------------------------------------
class ToolCard(QFrame):
    clicked = Signal(str)

    def __init__(self, tool: Tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.setObjectName("toolCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tool.description)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)
        icon = label(tool.icon, "cardIcon")
        icon.setFixedSize(48, 48)
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(tool.name, "cardTitle"))
        desc = label(tool.description, "cardDesc", wrap=True)
        col.addWidget(desc)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.setMinimumHeight(86)

    def sizeHint(self):
        return QSize(290, 92)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.tool.id)
        super().mouseReleaseEvent(e)

    def matches(self, query: str) -> bool:
        q = query.lower().strip()
        if not q:
            return True
        hay = f"{self.tool.name} {self.tool.description} {self.tool.keywords}".lower()
        return all(part in hay for part in q.split())


# ---------------------------------------------------------------------------
# Zone de dépôt
# ---------------------------------------------------------------------------
class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self, text: str, sub: str = "", exts: set[str] | None = None, multiple: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.exts = exts
        self.multiple = multiple
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 24, 20, 24)
        icon = label("📂", "bigIcon")
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)
        t = label(text, "h3")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        if sub:
            s = label(sub, "muted", wrap=True)
            s.setAlignment(Qt.AlignCenter)
            lay.addWidget(s)

    def _set_active(self, on: bool):
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, e):
        self._set_active(False)

    def dropEvent(self, e):
        self._set_active(False)
        files = expand_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()], self.exts)
        if files:
            self.files_dropped.emit(files if self.multiple else files[:1])

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            filt = file_filter(self.exts)
            if self.multiple:
                files, _ = QFileDialog.getOpenFileNames(self, "Choisir des fichiers", app_settings().last_dir(), filt)
            else:
                f, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier", app_settings().last_dir(), filt)
                files = [f] if f else []
            if files:
                app_settings().remember_dir(files[0])
                self.files_dropped.emit(files)


def expand_paths(paths: list[str], exts: set[str] | None) -> list[str]:
    """Développe les dossiers déposés et filtre par extension."""
    out = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file() and (not exts or f.suffix.lower() in exts):
                    out.append(str(f))
        elif path.is_file() and (not exts or path.suffix.lower() in exts):
            out.append(str(path))
    return out


def file_filter(exts: set[str] | None) -> str:
    if not exts:
        return "Tous les fichiers (*)"
    pattern = " ".join(f"*{e}" for e in sorted(exts))
    if exts == {".pdf"}:
        return "Documents PDF (*.pdf)"
    return f"Fichiers compatibles ({pattern});;Tous les fichiers (*)"


_SETTINGS = None


def app_settings():
    global _SETTINGS
    if _SETTINGS is None:
        from .settings import Settings

        _SETTINGS = Settings()
    return _SETTINGS


# ---------------------------------------------------------------------------
# Liste de fichiers (glisser-déposer, réordonnable)
# ---------------------------------------------------------------------------
class FileList(QWidget):
    changed = Signal()

    def __init__(self, exts: set[str] | None = None, parent=None):
        super().__init__(parent)
        self.exts = exts
        self.max_files: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        bar = QHBoxLayout()
        self.title = label("Fichiers", "h3")
        bar.addWidget(self.title)
        bar.addStretch(1)
        self.count_label = label("", "badge")
        bar.addWidget(self.count_label)
        lay.addLayout(bar)

        self.list = _DropList(self)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setIconSize(QSize(34, 44))
        self.list.files_dropped.connect(self.add_files)
        self.list.model().rowsMoved.connect(lambda *a: self.changed.emit())
        self.list.itemDoubleClicked.connect(lambda it: open_path(it.data(Qt.UserRole)))
        lay.addWidget(self.list, 1)

        self.empty = QLabel("Glissez-déposez vos fichiers ici\nou cliquez sur « Ajouter »")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setParent(self.list.viewport())
        self.empty.setAttribute(Qt.WA_TransparentForMouseEvents)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        btns.addWidget(button("+ Ajouter…", slot=self.browse))
        self.up_btn = tool_button("▲", "Monter", self.move_up)
        self.down_btn = tool_button("▼", "Descendre", self.move_down)
        self.sort_btn = tool_button("A→Z", "Trier par nom", self.sort)
        btns.addWidget(self.up_btn)
        btns.addWidget(self.down_btn)
        btns.addWidget(self.sort_btn)
        btns.addStretch(1)
        btns.addWidget(button("Retirer", slot=self.remove_selected))
        btns.addWidget(button("Vider", slot=self.clear))
        lay.addLayout(btns)
        self._refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.empty.setGeometry(self.list.viewport().rect())

    def showEvent(self, e):
        super().showEvent(e)
        self.empty.setGeometry(self.list.viewport().rect())

    def set_exts(self, exts: set[str] | None):
        self.exts = exts

    def files(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def browse(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Ajouter des fichiers", app_settings().last_dir(), file_filter(self.exts))
        if files:
            app_settings().remember_dir(files[0])
            self.add_files(files)

    def add_files(self, files: list[str]):
        existing = set(self.files())
        for f in expand_paths(files, self.exts):
            if f in existing:
                continue
            if self.max_files and self.list.count() >= self.max_files:
                break
            self.list.addItem(self._make_item(f))
            existing.add(f)
        self._refresh()
        self.changed.emit()

    def _make_item(self, f: str) -> QListWidgetItem:
        p = Path(f)
        info = human_size(p.stat().st_size) if p.exists() else ""
        icon = None
        if p.suffix.lower() == ".pdf":
            try:
                with fitz.open(p) as d:
                    if d.needs_pass:
                        info += " · 🔒 protégé"
                    else:
                        info += f" · {d.page_count} page{'s' if d.page_count > 1 else ''}"
                        if d.page_count:
                            icon = QIcon(pixmap_from_page(d[0], 34 / max(d[0].rect.width, 1)))
            except Exception:  # noqa: BLE001
                info += " · ⚠️ illisible"
        elif p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}:
            pm = QPixmap(str(p))
            if not pm.isNull():
                icon = QIcon(pm.scaled(34, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        item = QListWidgetItem(f"{p.name}\n{info}")
        item.setData(Qt.UserRole, str(p))
        item.setToolTip(str(p))
        if icon:
            item.setIcon(icon)
        return item

    def remove_selected(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self._refresh()
        self.changed.emit()

    def clear(self):
        self.list.clear()
        self._refresh()
        self.changed.emit()

    def move_up(self):
        self._move(-1)

    def move_down(self):
        self._move(1)

    def _move(self, d: int):
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        if not rows:
            return
        if d > 0:
            rows.reverse()
        for r in rows:
            nr = r + d
            if 0 <= nr < self.list.count():
                it = self.list.takeItem(r)
                self.list.insertItem(nr, it)
                it.setSelected(True)
        self.changed.emit()

    def sort(self):
        files = sorted(self.files(), key=lambda f: Path(f).name.lower())
        self.list.clear()
        for f in files:
            self.list.addItem(self._make_item(f))
        self.changed.emit()

    def _refresh(self):
        n = self.list.count()
        self.count_label.setText(f"{n} fichier{'s' if n > 1 else ''}")
        self.count_label.setVisible(n > 0)
        self.empty.setVisible(n == 0)


class _DropList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self, owner):
        super().__init__(owner)
        self.setAcceptDrops(True)

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
            self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


# ---------------------------------------------------------------------------
# Formulaire de paramètres généré automatiquement
# ---------------------------------------------------------------------------
class ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, value: str = "#000000"):
        super().__init__()
        self._value = value
        self.setFixedWidth(120)
        self.clicked.connect(self._pick)
        self._update()

    def value(self) -> str:
        return self._value

    def set_value(self, v: str):
        self._value = v or "#000000"
        self._update()

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._value), self, "Choisir une couleur")
        if c.isValid():
            self.set_value(c.name())
            self.changed.emit()

    def _update(self):
        c = QColor(self._value)
        fg = "#000" if c.lightness() > 140 else "#fff"
        self.setText(self._value.upper())
        self.setStyleSheet(f"QPushButton {{ background: {self._value}; color: {fg}; border-radius: 8px; }}")


class PathField(QWidget):
    changed = Signal()

    def __init__(self, kind: str, file_filter: str = "", placeholder: str = ""):
        super().__init__()
        self.kind = kind
        self.filter = file_filter or "Tous les fichiers (*)"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder or ("Aucun dossier" if kind == "folder" else "Aucun fichier"))
        self.edit.textChanged.connect(self.changed)
        lay.addWidget(self.edit, 1)
        lay.addWidget(button("Parcourir…", slot=self._browse))
        self._files: list[str] = []

    def _browse(self):
        start = app_settings().last_dir()
        if self.kind == "folder":
            d = QFileDialog.getExistingDirectory(self, "Choisir un dossier", start)
            if d:
                self.edit.setText(d)
        elif self.kind == "files":
            files, _ = QFileDialog.getOpenFileNames(self, "Choisir des fichiers", start, self.filter)
            if files:
                self._files = files
                self.edit.setText("; ".join(files))
        else:
            f, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier", start, self.filter)
            if f:
                app_settings().remember_dir(f)
                self.edit.setText(f)

    def value(self):
        text = self.edit.text().strip()
        if self.kind == "files":
            return [t.strip() for t in text.split(";") if t.strip()]
        return text

    def set_value(self, v):
        if isinstance(v, (list, tuple)):
            v = "; ".join(v)
        self.edit.setText(v or "")


class PasswordField(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.textChanged.connect(self.changed)
        lay.addWidget(self.edit, 1)
        eye = tool_button("👁", "Afficher / masquer", checkable=True)
        eye.toggled.connect(lambda on: self.edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        lay.addWidget(eye)

    def value(self):
        return self.edit.text()

    def set_value(self, v):
        self.edit.setText(v or "")


class ParamForm(QWidget):
    changed = Signal()

    def __init__(self, params: list[Param], values: dict | None = None, parent=None):
        super().__init__(parent)
        self.params = params
        self.widgets: dict[str, QWidget] = {}
        self.rows: dict[str, tuple[QWidget, QWidget | None]] = {}
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(10)
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        for p in params:
            w = self._make(p)
            self.widgets[p.key] = w
            if p.kind == "bool":
                container = w
                self.form.addRow(container)
                self.rows[p.key] = (container, None)
            else:
                lab = QLabel(p.label)
                lab.setToolTip(p.help)
                if p.help:
                    box = QWidget()
                    v = QVBoxLayout(box)
                    v.setContentsMargins(0, 0, 0, 0)
                    v.setSpacing(2)
                    v.addWidget(w)
                    h = label(p.help, "muted", wrap=True)
                    h.setStyleSheet("font-size: 8.5pt;")
                    v.addWidget(h)
                    container = box
                else:
                    container = w
                self.form.addRow(lab, container)
                self.rows[p.key] = (container, lab)
        if values:
            self.set_values(values)
        self._update_visibility()

    def _make(self, p: Param) -> QWidget:
        k = p.kind
        if k == "bool":
            w = QCheckBox(p.label)
            w.setChecked(bool(p.default))
            w.setToolTip(p.help)
            w.toggled.connect(self._on_change)
        elif k == "int":
            w = QSpinBox()
            w.setRange(int(p.min if p.min is not None else -10**9), int(p.max if p.max is not None else 10**9))
            w.setValue(int(p.default or 0))
            if p.step:
                w.setSingleStep(int(p.step))
            if p.suffix:
                w.setSuffix(p.suffix)
            w.valueChanged.connect(self._on_change)
        elif k == "float":
            w = QDoubleSpinBox()
            w.setDecimals(2)
            w.setRange(float(p.min if p.min is not None else -1e9), float(p.max if p.max is not None else 1e9))
            w.setSingleStep(float(p.step or 1))
            w.setValue(float(p.default or 0))
            if p.suffix:
                w.setSuffix(p.suffix)
            w.valueChanged.connect(self._on_change)
        elif k == "choice":
            w = QComboBox()
            for value, text in p.choices or []:
                w.addItem(text, value)
            idx = w.findData(p.default)
            w.setCurrentIndex(max(0, idx))
            w.currentIndexChanged.connect(self._on_change)
        elif k == "text":
            w = QPlainTextEdit()
            w.setPlaceholderText(p.placeholder)
            w.setPlainText(p.default or "")
            w.setFixedHeight(84)
            w.textChanged.connect(self._on_change)
        elif k == "color":
            w = ColorButton(p.default or "#000000")
            w.changed.connect(self._on_change)
        elif k == "password":
            w = PasswordField()
            w.set_value(p.default)
            w.changed.connect(self._on_change)
        elif k in ("file", "files", "folder"):
            w = PathField(k, p.file_filter, p.placeholder)
            w.set_value(p.default)
            w.changed.connect(self._on_change)
        else:  # str, pages
            w = QLineEdit()
            w.setPlaceholderText(p.placeholder or ("toutes les pages" if k == "pages" else ""))
            w.setText(str(p.default or ""))
            w.textChanged.connect(self._on_change)
        w.setToolTip(p.help or p.label)
        return w

    def _on_change(self, *args):
        self._update_visibility()
        self.changed.emit()

    def _update_visibility(self):
        vals = self.values()
        for p in self.params:
            container, lab = self.rows[p.key]
            vis = p.is_visible(vals)
            container.setVisible(vis)
            if lab:
                lab.setVisible(vis)

    def values(self) -> dict:
        out = {}
        for p in self.params:
            w = self.widgets[p.key]
            if p.kind == "bool":
                out[p.key] = w.isChecked()
            elif p.kind in ("int", "float"):
                out[p.key] = w.value()
            elif p.kind == "choice":
                out[p.key] = w.currentData()
            elif p.kind == "text":
                out[p.key] = w.toPlainText()
            elif p.kind in ("color", "password", "file", "files", "folder"):
                out[p.key] = w.value()
            else:
                out[p.key] = w.text()
        return out

    def set_values(self, values: dict):
        for p in self.params:
            if p.key not in values:
                continue
            v = values[p.key]
            w = self.widgets[p.key]
            w.blockSignals(True)
            try:
                if p.kind == "bool":
                    w.setChecked(bool(v))
                elif p.kind == "int":
                    w.setValue(int(v))
                elif p.kind == "float":
                    w.setValue(float(v))
                elif p.kind == "choice":
                    idx = w.findData(v)
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                elif p.kind == "text":
                    w.setPlainText(v or "")
                elif p.kind in ("color", "password", "file", "files", "folder"):
                    w.set_value(v)
                else:
                    w.setText(str(v or ""))
            finally:
                w.blockSignals(False)
        self._update_visibility()


# ---------------------------------------------------------------------------
# Panneau de résultats
# ---------------------------------------------------------------------------
class ResultPanel(QFrame):
    open_in_editor = Signal(str)
    use_as_input = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("resultPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.title = label("", "h3")
        head.addWidget(self.title)
        head.addStretch(1)
        self.chain_btn = button("↪ Continuer avec ces fichiers", slot=lambda: self.use_as_input.emit(self.outputs))
        self.chain_btn.setToolTip("Utiliser les fichiers produits comme entrée d'un autre outil")
        head.addWidget(self.chain_btn)
        self.folder_btn = button("📁 Ouvrir le dossier", slot=self._open_folder)
        head.addWidget(self.folder_btn)
        lay.addLayout(head)
        self.report = label("", None, wrap=True)
        self.report.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.report.setStyleSheet("font-family: 'Consolas','Menlo','DejaVu Sans Mono',monospace; font-size: 9pt;")
        lay.addWidget(self.report)
        self.list = QListWidget()
        self.list.setMaximumHeight(170)
        self.list.itemDoubleClicked.connect(lambda it: open_path(it.data(Qt.UserRole)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list)
        hint = label("Double-cliquez pour ouvrir · clic droit pour plus d'options", "muted")
        hint.setStyleSheet("font-size: 8.5pt;")
        lay.addWidget(hint)
        self.hint = hint
        self.outputs: list[str] = []
        self.hide()

    def show_success(self, outputs: list[str], reports: list[str]):
        self.outputs = outputs
        n = len(outputs)
        self.title.setText(f"✅ Terminé — {n} fichier{'s' if n > 1 else ''} créé{'s' if n > 1 else ''}" if n else "✅ Terminé")
        self.title.setStyleSheet("")
        self.report.setText("\n".join(reports))
        self.report.setVisible(bool(reports))
        self.list.clear()
        for o in outputs:
            p = Path(o)
            size = human_size(p.stat().st_size) if p.exists() else ""
            it = QListWidgetItem(f"📄 {p.name}   ·   {size}")
            it.setData(Qt.UserRole, o)
            it.setToolTip(o)
            self.list.addItem(it)
        self.list.setVisible(bool(outputs))
        self.hint.setVisible(bool(outputs))
        self.folder_btn.setVisible(bool(outputs))
        self.chain_btn.setVisible(any(o.lower().endswith(".pdf") for o in outputs))
        self.show()

    def show_error(self, message: str):
        self.outputs = []
        self.title.setText("❌ Une erreur est survenue")
        self.report.setText(message)
        self.report.show()
        self.list.hide()
        self.hint.hide()
        self.folder_btn.hide()
        self.chain_btn.hide()
        self.show()

    def _open_folder(self):
        if self.outputs:
            reveal_in_folder(self.outputs[0])

    def _menu(self, pos):
        from PySide6.QtWidgets import QMenu

        it = self.list.itemAt(pos)
        if not it:
            return
        path = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction("Ouvrir", lambda: open_path(path))
        if path.lower().endswith(".pdf"):
            m.addAction("Ouvrir dans l'éditeur PDF Builder", lambda: self.open_in_editor.emit(path))
        m.addAction("Afficher dans le dossier", lambda: reveal_in_folder(path))
        m.exec(self.list.mapToGlobal(pos))


# ---------------------------------------------------------------------------
# Notification éphémère
# ---------------------------------------------------------------------------
class Toast(QLabel):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWordWrap(True)
        self.setMaximumWidth(460)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, ms: int = 3200):
        self.setText(text)
        self.adjustSize()
        p = self.parentWidget()
        self.move(p.width() - self.width() - 24, p.height() - self.height() - 40)
        self.raise_()
        self.show()
        self._timer.start(ms)


def hsizer(*widgets, stretch_first: bool = False, spacing: int = 8) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    for i, w in enumerate(widgets):
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w, 1 if (stretch_first and i == 0) else 0)
    return lay


def expanding(w: QWidget) -> QWidget:
    w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return w

