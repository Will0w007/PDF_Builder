"""Boîtes de dialogue : texte, signature, formulaire, paramètres d'étape."""

from __future__ import annotations

import time
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.registry import get_tool
from ..core.utils import FONT_CHOICES
from .widgets import ColorButton, ParamForm, app_settings, button, label


class TextDialog(QDialog):
    """Saisie d'un texte à insérer (ou à remplacer) avec police, taille et couleur."""

    def __init__(self, parent=None, title="Ajouter du texte", text="", size=12.0, color_hex="#000000", font="helv"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(text)
        self.edit.setPlaceholderText("Votre texte…")
        self.edit.setMinimumHeight(110)
        lay.addWidget(self.edit)
        form = QFormLayout()
        self.font = QComboBox()
        for v, t in FONT_CHOICES:
            self.font.addItem(t, v)
        self.font.setCurrentIndex(max(0, self.font.findData(font)))
        form.addRow("Police", self.font)
        self.size = QSpinBox()
        self.size.setRange(4, 200)
        self.size.setValue(int(round(size)))
        form.addRow("Taille", self.size)
        self.color = ColorButton(color_hex)
        form.addRow("Couleur", self.color)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.edit.setFocus()

    def values(self) -> dict:
        return {"text": self.edit.toPlainText(), "font": self.font.currentData(), "size": self.size.value(), "color": self.color.value()}


class SignaturePad(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(520, 200)
        self.strokes: list[list[QPointF]] = []
        self.pen_color = QColor("#0B2A6F")
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: white; border: 1px dashed #9AA; border-radius: 10px;")

    def clear(self):
        self.strokes = []
        self.update()
        self.changed.emit()

    def mousePressEvent(self, e):
        self.strokes.append([e.position()])

    def mouseMoveEvent(self, e):
        if self.strokes:
            self.strokes[-1].append(e.position())
            self.update()

    def mouseReleaseEvent(self, e):
        self.changed.emit()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#CCD"), 1, Qt.DashLine))
        y = self.height() * 0.72
        p.drawLine(20, int(y), self.width() - 20, int(y))
        p.setPen(QPen(self.pen_color, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for stroke in self.strokes:
            if len(stroke) < 2:
                continue
            path = QPainterPath(stroke[0])
            for pt in stroke[1:]:
                path.lineTo(pt)
            p.drawPath(path)
        if not self.strokes:
            p.setPen(QColor("#99A"))
            p.drawText(self.rect(), Qt.AlignCenter, "Signez ici avec la souris, le pavé tactile ou un stylet")

    def to_png(self, path: Path) -> bool:
        pts = [pt for s in self.strokes for pt in s]
        if len(pts) < 2:
            return False
        xs, ys = [p.x() for p in pts], [p.y() for p in pts]
        x0, y0, x1, y1 = min(xs) - 6, min(ys) - 6, max(xs) + 6, max(ys) + 6
        scale = 3
        img = QImage(int((x1 - x0) * scale), int((y1 - y0) * scale), QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(scale, scale)
        p.translate(-x0, -y0)
        p.setPen(QPen(self.pen_color, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for stroke in self.strokes:
            if len(stroke) < 2:
                continue
            qpath = QPainterPath(stroke[0])
            for pt in stroke[1:]:
                qpath.lineTo(pt)
            p.drawPath(qpath)
        p.end()
        return img.save(str(path), "PNG")


class SignatureDialog(QDialog):
    """Créer une signature manuscrite (dessin, texte stylisé ou image) et la mémoriser."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ma signature")
        self.setMinimumWidth(600)
        self.result_path: str | None = None
        self.folder = app_settings().signatures_dir()
        lay = QVBoxLayout(self)
        lay.addWidget(label("Choisissez une signature enregistrée ou créez-en une nouvelle.", "muted"))
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        # Signatures enregistrées
        saved = QWidget()
        sl = QVBoxLayout(saved)
        self.saved_list = QListWidget()
        self.saved_list.setViewMode(QListWidget.IconMode)
        self.saved_list.setIconSize(QPixmap(220, 80).size())
        self.saved_list.setResizeMode(QListWidget.Adjust)
        self.saved_list.itemDoubleClicked.connect(lambda *_: self.accept())
        sl.addWidget(self.saved_list)
        sl.addWidget(button("Supprimer la signature sélectionnée", "danger", self._delete_saved))
        self.tabs.addTab(saved, "Enregistrées")

        # Dessin
        draw = QWidget()
        dl = QVBoxLayout(draw)
        self.pad = SignaturePad()
        dl.addWidget(self.pad)
        row = QHBoxLayout()
        row.addWidget(button("Effacer", slot=self.pad.clear))
        self.pad_color = ColorButton("#0B2A6F")
        self.pad_color.changed.connect(lambda: (setattr(self.pad, "pen_color", QColor(self.pad_color.value())), self.pad.update()))
        row.addWidget(QLabel("Encre :"))
        row.addWidget(self.pad_color)
        row.addStretch(1)
        dl.addLayout(row)
        self.tabs.addTab(draw, "✍️ Dessiner")

        # Texte
        typed = QWidget()
        tl = QFormLayout(typed)
        self.typed_name = QLineEdit()
        self.typed_name.setPlaceholderText("Prénom Nom")
        self.typed_name.textChanged.connect(self._preview_typed)
        tl.addRow("Nom", self.typed_name)
        self.typed_font = QComboBox()
        for fam in ("Segoe Script", "Brush Script MT", "Lucida Handwriting", "Comic Sans MS", "URW Chancery L", "Z003", "DejaVu Serif"):
            self.typed_font.addItem(fam)
        self.typed_font.currentIndexChanged.connect(self._preview_typed)
        tl.addRow("Style", self.typed_font)
        self.typed_preview = QLabel()
        self.typed_preview.setMinimumHeight(90)
        self.typed_preview.setAlignment(Qt.AlignCenter)
        self.typed_preview.setStyleSheet("background: white; border-radius: 10px;")
        tl.addRow(self.typed_preview)
        self.tabs.addTab(typed, "🔤 Écrire")

        # Image
        img = QWidget()
        il = QVBoxLayout(img)
        il.addWidget(label("Importez une photo ou un scan de votre signature (fond blanc ou transparent).", "muted", wrap=True))
        self.img_path = QLineEdit()
        row = QHBoxLayout()
        row.addWidget(self.img_path, 1)
        row.addWidget(button("Parcourir…", slot=self._browse_img))
        il.addLayout(row)
        self.remove_bg = QCheckBox("Rendre le fond blanc transparent")
        self.remove_bg.setChecked(True)
        il.addWidget(self.remove_bg)
        il.addStretch(1)
        self.tabs.addTab(img, "🖼️ Importer")

        self.save_check = QCheckBox("Mémoriser cette signature pour la prochaine fois")
        self.save_check.setChecked(True)
        lay.addWidget(self.save_check)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Utiliser cette signature")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._load_saved()
        if self.saved_list.count() == 0:
            self.tabs.setCurrentIndex(1)

    def _load_saved(self):
        self.saved_list.clear()
        for f in sorted(self.folder.glob("*.png"), reverse=True):
            it = QListWidgetItem(QPixmap(str(f)).scaled(220, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation), "")
            it.setData(Qt.UserRole, str(f))
            self.saved_list.addItem(it)
        if self.saved_list.count():
            self.saved_list.setCurrentRow(0)

    def _delete_saved(self):
        it = self.saved_list.currentItem()
        if it:
            Path(it.data(Qt.UserRole)).unlink(missing_ok=True)
            self._load_saved()

    def _typed_image(self) -> QImage | None:
        name = self.typed_name.text().strip()
        if not name:
            return None
        f = QFont(self.typed_font.currentText(), 64)
        f.setItalic(True)
        from PySide6.QtGui import QFontMetrics

        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(name) + 40, fm.height() + 20
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(f)
        p.setPen(QColor("#0B2A6F"))
        p.drawText(img.rect(), Qt.AlignCenter, name)
        p.end()
        return img

    def _preview_typed(self):
        img = self._typed_image()
        self.typed_preview.setPixmap(QPixmap.fromImage(img).scaled(480, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation) if img else QPixmap())

    def _browse_img(self):
        f, _ = QFileDialog.getOpenFileName(self, "Image de signature", app_settings().last_dir(), "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if f:
            self.img_path.setText(f)

    def accept(self):
        tab = self.tabs.currentIndex()
        target = self.folder / f"signature_{int(time.time())}.png"
        ok = False
        if tab == 0:
            it = self.saved_list.currentItem()
            if it:
                self.result_path = it.data(Qt.UserRole)
                return super().accept()
        elif tab == 1:
            ok = self.pad.to_png(target)
        elif tab == 2:
            img = self._typed_image()
            ok = bool(img) and img.save(str(target), "PNG")
        elif tab == 3 and self.img_path.text():
            ok = self._import_image(self.img_path.text(), target)
        if not ok:
            return
        if not self.save_check.isChecked():
            tmp = Path(app_settings().data_dir()) / "signature_temp.png"
            target.replace(tmp)
            target = tmp
        self.result_path = str(target)
        super().accept()

    def _import_image(self, src: str, target: Path) -> bool:
        from PIL import Image

        try:
            img = Image.open(src).convert("RGBA")
        except OSError:
            return False
        if self.remove_bg.isChecked():
            px = img.getdata()
            img.putdata([(r, g, b, 0) if r > 215 and g > 215 and b > 215 else (r, g, b, a) for r, g, b, a in px])
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
        img.save(target)
        return True


class FormDialog(QDialog):
    """Affiche et remplit tous les champs de formulaire d'un document."""

    def __init__(self, doc: fitz.Document, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remplir le formulaire")
        self.setMinimumSize(520, 480)
        self.doc = doc
        lay = QVBoxLayout(self)
        lay.addWidget(label("Saisissez les valeurs puis validez : les champs du PDF seront mis à jour.", "muted"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.form = QFormLayout(inner)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        self.editors: list[tuple[int, str, QWidget, int]] = []
        for page in doc:
            for w in page.widgets():
                name = w.field_name or "(sans nom)"
                t = w.field_type
                if t in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                    ed = QCheckBox(w.field_label or name)
                    ed.setChecked(w.field_value not in (False, "Off", "", None))
                    self.form.addRow(f"p.{page.number + 1} · {name}", ed)
                elif t in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
                    ed = QComboBox()
                    ed.setEditable(t == fitz.PDF_WIDGET_TYPE_COMBOBOX)
                    for c in w.choice_values or []:
                        ed.addItem(c[1] if isinstance(c, (list, tuple)) else str(c))
                    ed.setCurrentText(str(w.field_value or ""))
                    self.form.addRow(f"p.{page.number + 1} · {name}", ed)
                elif t == fitz.PDF_WIDGET_TYPE_TEXT:
                    ed = QLineEdit(str(w.field_value or ""))
                    self.form.addRow(f"p.{page.number + 1} · {name}", ed)
                else:
                    continue
                self.editors.append((page.number, w.xref, ed, t))
        if not self.editors:
            self.form.addRow(label("Ce document ne contient aucun champ de formulaire modifiable.", "muted"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def apply(self) -> int:
        n = 0
        for pno, xref, ed, t in self.editors:
            page = self.doc[pno]
            for w in page.widgets():
                if w.xref != xref:
                    continue
                if t in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                    w.field_value = w.on_state() if ed.isChecked() else "Off"
                elif isinstance(ed, QComboBox):
                    w.field_value = ed.currentText()
                else:
                    w.field_value = ed.text()
                w.update()
                n += 1
        return n


class StepDialog(QDialog):
    """Configure les paramètres d'une étape de flux de travail."""

    def __init__(self, tool_id: str, values: dict | None = None, parent=None):
        super().__init__(parent)
        tool = get_tool(tool_id)
        self.setWindowTitle(f"{tool.icon} {tool.name}")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.addWidget(label(tool.description, "muted", wrap=True))
        self.form = ParamForm(tool.params, values)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form)
        scroll.setMinimumHeight(min(480, 60 + 46 * len(tool.params)))
        lay.addWidget(scroll, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> dict:
        return self.form.values()
