"""Paramètres de l'application et état des composants optionnels."""

from __future__ import annotations

import importlib.util

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from ... import APP_NAME, __version__
from ...core.external import find_ghostscript, find_soffice, find_tessdata, tesseract_languages
from ...core.registry import REGISTRY
from ...core.tools_optimize import OCR_LANGS
from ..widgets import app_settings, button, label


class SettingsPage(QWidget):
    theme_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        s = app_settings()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("page")
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 20, 28, 28)
        root.setSpacing(14)
        root.addWidget(label("🎛️ Paramètres", "h1"))

        # Apparence & sortie
        card = self._card("Général")
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.theme = QComboBox()
        for v, t in (("system", "Selon le système"), ("light", "Clair"), ("dark", "Sombre")):
            self.theme.addItem(t, v)
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.get("theme"))))
        self.theme.currentIndexChanged.connect(self._theme)
        form.addRow("Thème", self.theme)

        self.out_mode = QComboBox()
        self.out_mode.addItem("À côté du fichier d'origine", "beside")
        self.out_mode.addItem("Toujours dans le dossier ci-dessous", "folder")
        self.out_mode.setCurrentIndex(max(0, self.out_mode.findData(s.get("output_mode"))))
        self.out_mode.currentIndexChanged.connect(lambda: s.set("output_mode", self.out_mode.currentData()))
        form.addRow("Fichiers produits", self.out_mode)
        self.out_folder = self._path_row(form, "Dossier de sortie", "output_folder", folder=True)

        self.after = QComboBox()
        for v, t in (("show", "Afficher le résultat"), ("open_file", "Ouvrir le fichier produit"), ("open_folder", "Ouvrir le dossier")):
            self.after.addItem(t, v)
        self.after.setCurrentIndex(max(0, self.after.findData(s.get("after_run"))))
        self.after.currentIndexChanged.connect(lambda: s.set("after_run", self.after.currentData()))
        form.addRow("Après un traitement", self.after)

        self.ocr_lang = QComboBox()
        for v, t in OCR_LANGS:
            self.ocr_lang.addItem(t, v)
        self.ocr_lang.setCurrentIndex(max(0, self.ocr_lang.findData(s.get("ocr_lang"))))
        self.ocr_lang.currentIndexChanged.connect(lambda: s.set("ocr_lang", self.ocr_lang.currentData()))
        form.addRow("Langue OCR par défaut", self.ocr_lang)
        card.layout().addLayout(form)
        root.addWidget(card)

        # Composants externes
        card = self._card("Composants optionnels")
        form = QFormLayout()
        self._path_row(form, "Dossier tessdata (OCR)", "tessdata", folder=True, on_change=self._refresh_status)
        self._path_row(form, "LibreOffice (soffice)", "soffice", folder=False, on_change=self._refresh_status)
        self._path_row(form, "Ghostscript (PDF/A)", "ghostscript", folder=False, on_change=self._refresh_status)
        card.layout().addLayout(form)
        self.status = label("", None, wrap=True)
        card.layout().addWidget(self.status)
        card.layout().addWidget(button("🔄 Vérifier à nouveau", slot=self._refresh_status))
        root.addWidget(card)

        # À propos
        card = self._card(f"À propos de {APP_NAME}")
        card.layout().addWidget(
            label(
                f"Version {__version__} · {len(REGISTRY)} outils · traitement 100 % local : vos documents ne quittent jamais votre ordinateur.\n\n"
                "Raccourcis : Ctrl+K palette de commandes · Ctrl+O ouvrir · Ctrl+S enregistrer · Ctrl+Z annuler · Ctrl+F rechercher · "
                "Ctrl+1…7 changer de section · Échap revenir à l'outil de navigation.\n\n"
                "Moteurs : PyMuPDF (MuPDF), pikepdf (qpdf), pdf2docx, pyHanko, Tesseract OCR, LibreOffice.",
                "muted",
                wrap=True,
            )
        )
        root.addWidget(card)
        root.addStretch(1)
        self._refresh_status()

    def _card(self, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.addWidget(label(title, "h2"))
        return card

    def _path_row(self, form: QFormLayout, text: str, key: str, folder: bool, on_change=None) -> QLineEdit:
        s = app_settings()
        edit = QLineEdit(s.get(key) or "")
        edit.setPlaceholderText("Détection automatique" if key in ("tessdata", "soffice", "ghostscript") else "")

        def save():
            s.set(key, edit.text().strip())
            if on_change:
                on_change()

        edit.editingFinished.connect(save)

        def browse():
            if folder:
                d = QFileDialog.getExistingDirectory(self, text, edit.text() or s.last_dir())
            else:
                d, _ = QFileDialog.getOpenFileName(self, text, edit.text() or s.last_dir())
            if d:
                edit.setText(d)
                save()

        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(button("…", slot=browse))
        form.addRow(text, row)
        return edit

    def _theme(self):
        v = self.theme.currentData()
        app_settings().set("theme", v)
        self.theme_changed.emit(v)

    def _refresh_status(self):
        s = app_settings()
        tess = find_tessdata(s.get("tessdata") or None)
        langs = tesseract_languages(tess)
        soffice = find_soffice(s.get("soffice") or None)
        gs = find_ghostscript(s.get("ghostscript") or None)
        lines = [
            ("✅" if tess else "⚠️") + " OCR (Tesseract) : " + (f"trouvé — langues : {', '.join(langs[:12])}" if tess else "non trouvé. Installez Tesseract OCR pour rendre les scans cherchables."),
            ("✅" if soffice else "⚠️") + " LibreOffice : " + (f"trouvé ({soffice})" if soffice else "non trouvé. Nécessaire uniquement pour convertir Word/Excel/PowerPoint en PDF."),
            ("✅" if gs else "⚠️") + " Ghostscript : " + (f"trouvé ({gs})" if gs else "non trouvé. Nécessaire uniquement pour la conversion PDF/A."),
        ]
        for mod, name in (("pdf2docx", "Conversion Word"), ("pptx", "Conversion PowerPoint"), ("openpyxl", "Conversion Excel"), ("pyhanko", "Signature numérique"), ("qrcode", "QR codes"), ("pikepdf", "Optimisation Web / réparation")):
            ok = importlib.util.find_spec(mod) is not None
            lines.append(("✅" if ok else "⚠️") + f" {name} : " + ("disponible" if ok else f"module « {mod} » manquant"))
        self.status.setText("\n".join(lines))
