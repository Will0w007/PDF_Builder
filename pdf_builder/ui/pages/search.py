"""Recherche plein texte dans tous les PDF d'un dossier."""

from __future__ import annotations

import html
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QProgressBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ..widgets import app_settings, button, label, reveal_in_folder


class SearchPage(QWidget):
    open_result = Signal(str, int, str)  # fichier, page (0-based), requête

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.jobs = jobs
        self.job = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        root.addWidget(label("🔎 Rechercher dans vos PDF", "h1"))
        root.addWidget(label("Retrouvez en quelques secondes un mot, un numéro de facture ou un nom dans des centaines de documents.", "muted", wrap=True))

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        row = QHBoxLayout()
        self.folder = QLineEdit(app_settings().last_dir())
        self.folder.setPlaceholderText("Dossier à explorer")
        row.addWidget(label("Dossier :"))
        row.addWidget(self.folder, 1)
        row.addWidget(button("Parcourir…", slot=self._browse))
        cl.addLayout(row)
        row2 = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setObjectName("search")
        self.query.setPlaceholderText("Texte à rechercher… (ex. « facture 2024 », un IBAN, un nom)")
        self.query.returnPressed.connect(self.run)
        row2.addWidget(self.query, 1)
        self.run_btn = button("Rechercher", "primary", self.run)
        row2.addWidget(self.run_btn)
        cl.addLayout(row2)
        row3 = QHBoxLayout()
        self.recursive = QCheckBox("Inclure les sous-dossiers")
        self.recursive.setChecked(True)
        self.case = QCheckBox("Respecter la casse")
        self.regex = QCheckBox("Expression régulière")
        for w in (self.recursive, self.case, self.regex):
            row3.addWidget(w)
        row3.addStretch(1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFixedWidth(200)
        self.progress.hide()
        row3.addWidget(self.progress)
        self.status = label("", "muted")
        row3.addWidget(self.status)
        cl.addLayout(row3)
        root.addWidget(card)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Résultat", "Page"])
        self.tree.setColumnWidth(0, 760)
        self.tree.itemDoubleClicked.connect(self._open)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        root.addWidget(self.tree, 1)
        root.addWidget(label("Double-cliquez sur un résultat pour l'ouvrir à la bonne page, avec le terme surligné.", "muted"))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Dossier à explorer", self.folder.text() or app_settings().last_dir())
        if d:
            self.folder.setText(d)

    def run(self):
        q = self.query.text().strip()
        folder = self.folder.text().strip()
        if not q or not Path(folder).is_dir():
            self.status.setText("Indiquez un dossier valide et un texte à rechercher.")
            return
        if self.job:
            self.jobs.cancel(self.job)
        self.tree.clear()
        task = {
            "kind": "call",
            "func": "pdf_builder.core.jobs:search_job",
            "kwargs": {"folder": folder, "query": q, "regex": self.regex.isChecked(), "case": self.case.isChecked(), "recursive": self.recursive.isChecked()},
        }
        self.job = self.jobs.submit(task, "Recherche")
        self.job.progress.connect(lambda f, m: (self.progress.setValue(int(f * 1000)), self.status.setText(m[:40])))
        self.job.result.connect(self._on_result)
        self.job.failed.connect(lambda m, t: (self.progress.hide(), self.status.setText("❌ " + m)))
        self.progress.show()
        self.status.setText("Recherche…")

    def _on_result(self, results: list):
        self.progress.hide()
        self.job = None
        files: dict[str, QTreeWidgetItem] = {}
        for r in results:
            parent = files.get(r["file"])
            if parent is None:
                parent = QTreeWidgetItem([f"📄 {Path(r['file']).name}   —   {Path(r['file']).parent}", ""])
                parent.setData(0, Qt.UserRole, (r["file"], 0, r["match"]))
                self.tree.addTopLevelItem(parent)
                files[r["file"]] = parent
            child = QTreeWidgetItem(["", str(r["page"])])
            child.setData(0, Qt.UserRole, (r["file"], r["page"] - 1, r["match"]))
            parent.addChild(child)
            snippet = html.escape(r["snippet"])
            pattern = re.escape(html.escape(r["match"]))
            snippet = re.sub(pattern, lambda m: f"<b style='background:#FDE68A;color:#000'>{m.group(0)}</b>", snippet, count=1)
            lab = label(f"…{snippet}…")
            lab.setTextFormat(Qt.RichText)
            self.tree.setItemWidget(child, 0, lab)
        for parent in files.values():
            parent.setText(0, parent.text(0) + f"   ({parent.childCount()})")
        self.tree.expandAll()
        nfiles = len(files)
        self.status.setText(f"{len(results)} occurrence(s) dans {nfiles} fichier(s)" + (" (limite atteinte)" if len(results) >= 2000 else ""))

    def _open(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.UserRole)
        if data:
            self.open_result.emit(data[0], data[1], data[2])

    def _menu(self, pos):
        from PySide6.QtWidgets import QMenu

        item = self.tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.UserRole)
        m = QMenu(self)
        m.addAction("Ouvrir dans l'éditeur", lambda: self._open(item))
        m.addAction("Afficher dans le dossier", lambda: reveal_in_folder(data[0]))
        m.exec(self.tree.viewport().mapToGlobal(pos))
