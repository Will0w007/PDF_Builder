"""Page générique d'exécution d'un outil (fichiers + paramètres + résultats)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.registry import Tool, get_tool
from ..widgets import FileList, ParamForm, ResultPanel, app_settings, button, label, open_path, reveal_in_folder

# Mémorise les derniers réglages de chaque outil pendant la session.
_LAST_VALUES: dict[str, dict] = {}


class ToolPage(QWidget):
    back_requested = Signal()
    open_in_editor = Signal(str)
    chain_requested = Signal(list)

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.jobs = jobs
        self.tool: Tool | None = None
        self.job = None
        self.passwords: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)

        # En-tête
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(button("← Tous les outils", slot=self.back_requested.emit))
        self.icon = label("", "bigIcon")
        head.addWidget(self.icon)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = label("", "h1")
        self.desc = label("", "muted", wrap=True)
        titles.addWidget(self.title)
        titles.addWidget(self.desc)
        head.addLayout(titles, 1)
        root.addLayout(head)

        # Corps : fichiers | paramètres
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(14)
        split.setStyleSheet("QSplitter::handle { background: transparent; }")

        self.files_card = QFrame()
        self.files_card.setObjectName("card")
        fl = QVBoxLayout(self.files_card)
        fl.setContentsMargins(16, 14, 16, 14)
        self.files = FileList()
        fl.addWidget(self.files)
        split.addWidget(self.files_card)

        params_card = QFrame()
        params_card.setObjectName("card")
        pl = QVBoxLayout(params_card)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.addWidget(label("Réglages", "h3"))
        self.params_scroll = QScrollArea()
        self.params_scroll.setWidgetResizable(True)
        self.params_scroll.setFrameShape(QFrame.NoFrame)
        pl.addWidget(self.params_scroll, 1)
        self.no_params = label("Aucun réglage nécessaire : ajoutez vos fichiers et lancez !", "muted", wrap=True)
        pl.addWidget(self.no_params)
        split.addWidget(params_card)
        split.setSizes([420, 520])
        root.addWidget(split, 1)

        # Destination + exécution
        bar = QFrame()
        bar.setObjectName("card")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(10)
        bl.addWidget(label("Enregistrer :"))
        self.dest_mode = QComboBox()
        self.dest_mode.addItem("À côté du fichier d'origine", "beside")
        self.dest_mode.addItem("Dans un dossier…", "folder")
        self.dest_mode.currentIndexChanged.connect(self._dest_changed)
        bl.addWidget(self.dest_mode)
        self.dest_folder = QLineEdit()
        self.dest_folder.setPlaceholderText("Choisissez un dossier")
        bl.addWidget(self.dest_folder, 1)
        self.dest_browse = button("…", slot=self._browse_dest)
        bl.addWidget(self.dest_browse)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFixedWidth(180)
        self.progress.hide()
        bl.addWidget(self.progress)
        self.status = label("", "muted")
        bl.addWidget(self.status)
        self.cancel_btn = button("Annuler", "danger", self.cancel)
        self.cancel_btn.hide()
        bl.addWidget(self.cancel_btn)
        self.run_btn = button("Lancer  ▶", "primary", self.run)
        self.run_btn.setMinimumWidth(150)
        bl.addWidget(self.run_btn)
        root.addWidget(bar)

        self.result = ResultPanel()
        self.result.open_in_editor.connect(self.open_in_editor)
        self.result.use_as_input.connect(self.chain_requested)
        root.addWidget(self.result)
        self.form: ParamForm | None = None
        self._init_dest()

    # ------------------------------------------------------------------
    def _init_dest(self):
        s = app_settings()
        if s.get("output_mode") == "folder":
            self.dest_mode.setCurrentIndex(1)
            self.dest_folder.setText(s.get("output_folder") or "")
        self._dest_changed()

    def _dest_changed(self):
        folder = self.dest_mode.currentData() == "folder"
        self.dest_folder.setVisible(folder)
        self.dest_browse.setVisible(folder)

    def _browse_dest(self):
        d = QFileDialog.getExistingDirectory(self, "Dossier de destination", self.dest_folder.text() or app_settings().last_dir())
        if d:
            self.dest_folder.setText(d)

    def set_tool(self, tool_id: str, files: list[str] | None = None):
        if self.tool and self.form:
            _LAST_VALUES[self.tool.id] = self.form.values()
        tool = get_tool(tool_id)
        same = self.tool is not None and self.tool.id == tool.id
        self.tool = tool
        self.icon.setText(tool.icon)
        self.title.setText(tool.name)
        self.desc.setText(tool.description)
        self.files.set_exts(tool.extensions() or None)
        self.files.max_files = tool.max_inputs
        accepts_files = tool.accepts != "none"
        self.files_card.setVisible(accepts_files)
        if tool.mode == "all" and tool.min_inputs >= 2:
            self.files.title.setText(f"Fichiers (au moins {tool.min_inputs}, dans l'ordre)")
        elif tool.mode == "all":
            self.files.title.setText("Fichiers (dans l'ordre)")
        else:
            self.files.title.setText("Fichiers à traiter (traitement par lot possible)")
        if not same:
            self.files.clear()
            self.result.hide()
        if files:
            self.files.add_files(files)
        self.form = ParamForm(tool.params, _LAST_VALUES.get(tool.id))
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.addWidget(self.form)
        lay.addStretch(1)
        self.params_scroll.setWidget(holder)
        self.no_params.setVisible(not tool.params)
        self.params_scroll.setVisible(bool(tool.params))
        self._set_running(False)

    # ------------------------------------------------------------------
    def run(self):
        if not self.tool:
            return
        files = self.files.files()
        t = self.tool
        if t.accepts != "none" and len(files) < max(1, t.min_inputs):
            QMessageBox.information(self, t.name, f"Ajoutez au moins {max(1, t.min_inputs)} fichier(s) à traiter.")
            return
        out_dir = None
        if self.dest_mode.currentData() == "folder":
            out_dir = self.dest_folder.text().strip()
            if not out_dir:
                self._browse_dest()
                out_dir = self.dest_folder.text().strip()
                if not out_dir:
                    return
        params = self.form.values() if self.form else {}
        task = {
            "kind": "tool",
            "tool": t.id,
            "inputs": files,
            "params": params,
            "out_dir": out_dir,
            "passwords": self.passwords,
            "settings": app_settings().worker_settings(),
        }
        self.result.hide()
        self.job = self.jobs.submit(task, t.name)
        self.job.progress.connect(self._on_progress)
        self.job.finished.connect(self._on_done)
        self.job.failed.connect(self._on_failed)
        self.job.password_needed.connect(self._on_password)
        self.job.cancelled.connect(lambda: self._set_running(False, "Annulé"))
        self._set_running(True, "En attente…")

    def cancel(self):
        if self.job:
            self.jobs.cancel(self.job)

    def _set_running(self, running: bool, status: str = ""):
        self.run_btn.setEnabled(not running)
        self.cancel_btn.setVisible(running)
        self.progress.setVisible(running)
        self.progress.setValue(0)
        self.status.setText(status)

    def _on_progress(self, f: float, msg: str):
        self.progress.setValue(int(f * 1000))
        self.status.setText(msg[:60])

    def _on_done(self, outputs: list, reports: list):
        self._set_running(False)
        self.result.show_success(outputs, reports)
        after = app_settings().get("after_run")
        if outputs:
            if after == "open_file" and len(outputs) == 1:
                open_path(outputs[0])
            elif after == "open_folder":
                reveal_in_folder(outputs[0])

    def _on_failed(self, message: str, trace: str):
        self._set_running(False)
        self.result.show_error(message + (f"\n\nDétails techniques :\n{trace[-1500:]}" if trace else ""))

    def _on_password(self, path: str):
        self._set_running(False)
        pw, ok = QInputDialog.getText(self, "Mot de passe requis", f"« {Path(path).name} » est protégé.\nSaisissez son mot de passe :", QLineEdit.Password)
        if ok and pw:
            self.passwords[path] = pw
            self.run()
