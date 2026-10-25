"""Comparaison visuelle de deux versions d'un document."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QProgressBar, QSplitter, QVBoxLayout, QWidget

from ..viewer import PdfView
from ..widgets import DropZone, app_settings, button, label


class FileSlot(QFrame):
    changed = Signal()

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        self.path: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.addWidget(label(title, "h3"))
        self.drop = DropZone("Déposez un PDF", "ou cliquez pour choisir", {".pdf"}, multiple=False)
        self.drop.setMinimumHeight(110)
        self.drop.files_dropped.connect(lambda f: self.set_path(f[0]))
        lay.addWidget(self.drop)
        self.name = label("", "muted", wrap=True)
        lay.addWidget(self.name)

    def set_path(self, p: str):
        self.path = p
        self.name.setText(f"📄 {Path(p).name}")
        self.changed.emit()


class ComparePage(QWidget):
    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.jobs = jobs
        self.job = None
        self.report: str | None = None
        self._tmp = Path(tempfile.mkdtemp(prefix="pdfb_cmp_"))
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        root.addWidget(label("🆚 Comparer deux versions", "h1"))
        root.addWidget(label("Repérez instantanément ce qui a changé entre deux documents : texte supprimé en rouge, ajouté en vert, pages visuellement différentes signalées.", "muted", wrap=True))
        row = QHBoxLayout()
        self.a = FileSlot("Version A (originale)")
        self.b = FileSlot("Version B (modifiée)")
        self.a.changed.connect(self._update)
        self.b.changed.connect(self._update)
        row.addWidget(self.a)
        row.addWidget(self.b)
        side = QVBoxLayout()
        side.addStretch(1)
        self.run_btn = button("Comparer  ▶", "primary", self.run)
        side.addWidget(self.run_btn)
        side.addWidget(button("⇆ Inverser", slot=self.swap))
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.hide()
        side.addWidget(self.progress)
        side.addStretch(1)
        row.addLayout(side)
        root.addLayout(row)

        self.results = QSplitter(Qt.Horizontal)
        left = QFrame()
        left.setObjectName("card")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        self.summary = label("", "h3", wrap=True)
        ll.addWidget(self.summary)
        self.changes = QListWidget()
        self.changes.itemClicked.connect(self._goto_change)
        ll.addWidget(self.changes, 1)
        self.save_btn = button("💾 Enregistrer le rapport PDF", slot=self.save_report)
        ll.addWidget(self.save_btn)
        self.results.addWidget(left)
        self.view = PdfView()
        self.results.addWidget(self.view)
        self.results.setSizes([340, 800])
        self.results.hide()
        root.addWidget(self.results, 1)
        self._update()

    def _update(self):
        self.run_btn.setEnabled(bool(self.a.path and self.b.path))

    def swap(self):
        pa, pb = self.a.path, self.b.path
        if pb:
            self.a.set_path(pb)
        if pa:
            self.b.set_path(pa)

    def set_files(self, files: list[str]):
        if files:
            self.a.set_path(files[0])
        if len(files) > 1:
            self.b.set_path(files[1])

    def run(self):
        out = str(self._tmp / f"comparaison_{Path(self.a.path).stem}_{Path(self.b.path).stem}.pdf")
        task = {"kind": "call", "func": "pdf_builder.core.jobs:compare_job", "kwargs": {"path_a": self.a.path, "path_b": self.b.path, "out_path": out}}
        self.job = self.jobs.submit(task, "Comparaison")
        self.job.progress.connect(lambda f, m: self.progress.setValue(int(f * 1000)))
        self.job.result.connect(self._on_result)
        self.job.failed.connect(self._on_failed)
        self.job.password_needed.connect(lambda p: self._on_failed(f"« {Path(p).name} » est protégé : retirez d'abord son mot de passe.", ""))
        self.progress.show()
        self.run_btn.setEnabled(False)

    def _on_failed(self, msg: str, trace: str):
        from PySide6.QtWidgets import QMessageBox

        self.progress.hide()
        self._update()
        QMessageBox.warning(self, "Comparaison", msg)

    def _on_result(self, res: dict):
        self.progress.hide()
        self._update()
        self.report = res["report"]
        n = len(res["changes"])
        self.summary.setText(
            f"Similarité : {res['similarity'] * 100:.1f} %\n{n} différence(s) de texte"
            + (f"\nPages visuellement différentes : {', '.join(map(str, res['visual'][:15]))}" if res["visual"] else "")
        )
        self.changes.clear()
        icons = {"ajouté": "🟢", "supprimé": "🔴", "modifié": "🟠"}
        for ch in res["changes"]:
            txt = f"{icons.get(ch['type'], '•')} p.{ch['page_b'] or ch['page_a']}  "
            if ch["old"] and ch["new"]:
                txt += f"« {ch['old'][:50]} » → « {ch['new'][:50]} »"
            else:
                txt += f"« {(ch['old'] or ch['new'])[:90]} »"
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, (ch["page_a"] or ch["page_b"] or 1))
            it.setToolTip(f"Avant : {ch['old']}\nAprès : {ch['new']}")
            self.changes.addItem(it)
        if not n:
            self.changes.addItem("✅ Aucune différence de texte détectée.")
        doc = fitz.open(self.report)
        self.view.set_document(doc)
        self.results.show()
        self.view.fit_width()

    def _goto_change(self, it: QListWidgetItem):
        page = it.data(Qt.UserRole)
        if page:
            self.view.go_to_page(page)  # +1 page de synthèse, -1 indice

    def save_report(self):
        if not self.report:
            return
        start = str(Path(self.a.path).with_name(Path(self.report).name)) if self.a.path else app_settings().last_dir()
        f, _ = QFileDialog.getSaveFileName(self, "Enregistrer le rapport", start, "Documents PDF (*.pdf)")
        if f:
            shutil.copyfile(self.report, f)
