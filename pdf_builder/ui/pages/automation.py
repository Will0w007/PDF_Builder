"""Automatisation : recettes (enchaînements d'outils) et dossier surveillé."""

from __future__ import annotations

import copy
import json
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.recipes import BUILTIN_RECIPES, load_user_recipes, save_user_recipes
from ...core.registry import REGISTRY
from ..dialogs import StepDialog
from ..widgets import FileList, ResultPanel, app_settings, button, label


def _describe_step(step: dict) -> str:
    t = REGISTRY.get(step["tool"])
    if not t:
        return f"⚠️ outil inconnu : {step['tool']}"
    details = []
    for p in t.params:
        if p.key in step.get("params", {}) and step["params"][p.key] not in ("", None, p.default) and p.kind != "password":
            v = step["params"][p.key]
            if p.kind == "choice":
                v = dict(p.choices or []).get(v, v)
            elif p.kind == "bool":
                v = "oui" if v else "non"
            details.append(f"{p.label} : {v}")
    return f"{t.icon}  {t.name}" + (f"   —   {', '.join(details[:3])}" if details else "")


class AutomationPage(QWidget):
    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.jobs = jobs
        self.recipes: list[dict] = []
        self.job = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(10)
        root.addWidget(label("⚙️ Automatiser", "h1"))
        root.addWidget(label("Enchaînez plusieurs outils en une seule « recette », appliquez-la à des centaines de fichiers, ou laissez PDF Builder traiter automatiquement tout ce qui arrive dans un dossier.", "muted", wrap=True))
        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        tabs.addTab(self._build_recipes(), "🧪 Recettes")
        tabs.addTab(self._build_watch(), "👀 Dossier surveillé")
        self._load_recipes()

    # ================================================================ recettes
    def _build_recipes(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(14)

        left = QFrame()
        left.setObjectName("card")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 12, 14, 12)
        ll.addWidget(label("Mes recettes", "h3"))
        self.recipe_list = QListWidget()
        self.recipe_list.currentRowChanged.connect(self._show_recipe)
        ll.addWidget(self.recipe_list, 1)
        row = QHBoxLayout()
        row.addWidget(button("＋ Nouvelle", slot=self.new_recipe))
        row.addWidget(button("⧉", slot=self.duplicate_recipe, tip="Dupliquer"))
        row.addWidget(button("✎", slot=self.rename_recipe, tip="Renommer"))
        row.addWidget(button("🗑", "danger", self.delete_recipe, tip="Supprimer"))
        ll.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(button("Importer…", slot=self.import_recipes))
        row2.addWidget(button("Exporter…", slot=self.export_recipe))
        ll.addLayout(row2)
        left.setMaximumWidth(330)
        lay.addWidget(left)

        mid = QFrame()
        mid.setObjectName("card")
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(14, 12, 14, 12)
        self.recipe_title = label("", "h3")
        ml.addWidget(self.recipe_title)
        self.recipe_desc = label("", "muted", wrap=True)
        ml.addWidget(self.recipe_desc)
        ml.addWidget(label("Étapes (exécutées dans l'ordre) :"))
        self.steps = QListWidget()
        self.steps.setWordWrap(True)
        self.steps.itemDoubleClicked.connect(lambda *_: self.edit_step())
        ml.addWidget(self.steps, 1)
        row = QHBoxLayout()
        self.add_combo = QComboBox()
        for t in sorted((t for t in REGISTRY.values() if t.chainable), key=lambda t: t.name):
            self.add_combo.addItem(f"{t.icon} {t.name}", t.id)
        row.addWidget(self.add_combo, 1)
        row.addWidget(button("＋ Ajouter l'étape", slot=self.add_step))
        ml.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("⚙ Régler", slot=self.edit_step))
        row.addWidget(button("▲", slot=lambda: self.move_step(-1)))
        row.addWidget(button("▼", slot=lambda: self.move_step(1)))
        row.addStretch(1)
        row.addWidget(button("Retirer", "danger", self.remove_step))
        ml.addLayout(row)
        lay.addWidget(mid, 1)

        right = QFrame()
        right.setObjectName("card")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(14, 12, 14, 12)
        self.run_files = FileList({".pdf"})
        self.run_files.title.setText("Fichiers à traiter")
        rl.addWidget(self.run_files, 1)
        row = QHBoxLayout()
        row.addWidget(label("Suffixe :"))
        self.suffix = QLineEdit("_traité")
        self.suffix.setFixedWidth(110)
        row.addWidget(self.suffix)
        row.addStretch(1)
        rl.addLayout(row)
        row = QHBoxLayout()
        self.out_folder = QLineEdit()
        self.out_folder.setPlaceholderText("À côté des originaux")
        row.addWidget(self.out_folder, 1)
        row.addWidget(button("…", slot=lambda: self._pick_folder(self.out_folder)))
        rl.addLayout(row)
        self.run_progress = QProgressBar()
        self.run_progress.setRange(0, 1000)
        self.run_progress.hide()
        rl.addWidget(self.run_progress)
        self.run_btn = button("Exécuter la recette  ▶", "primary", self.run_recipe)
        rl.addWidget(self.run_btn)
        self.result = ResultPanel()
        rl.addWidget(self.result)
        lay.addWidget(right, 1)
        return w

    def _load_recipes(self):
        self.recipes = copy.deepcopy(BUILTIN_RECIPES) + load_user_recipes(app_settings().recipes_file())
        self._refresh_list()

    def _save(self):
        save_user_recipes(app_settings().recipes_file(), self.recipes)
        self._refresh_watch_recipes()

    def _refresh_list(self, select: int = 0):
        self.recipe_list.blockSignals(True)
        self.recipe_list.clear()
        for r in self.recipes:
            it = QListWidgetItem(r["name"] + ("" if not r.get("builtin") else "   ·  modèle"))
            self.recipe_list.addItem(it)
        self.recipe_list.blockSignals(False)
        if self.recipes:
            self.recipe_list.setCurrentRow(min(select, len(self.recipes) - 1))
        self._refresh_watch_recipes()

    def current(self) -> dict | None:
        i = self.recipe_list.currentRow()
        return self.recipes[i] if 0 <= i < len(self.recipes) else None

    def _show_recipe(self, *_):
        r = self.current()
        self.steps.clear()
        if not r:
            self.recipe_title.setText("")
            return
        self.recipe_title.setText(r["name"])
        self.recipe_desc.setText((r.get("description") or "") + ("\nModèle intégré : dupliquez-le pour le personnaliser." if r.get("builtin") else ""))
        for i, s in enumerate(r["steps"], 1):
            self.steps.addItem(f"{i}.  {_describe_step(s)}")

    def _editable(self) -> dict | None:
        r = self.current()
        if r and r.get("builtin"):
            QMessageBox.information(self, "Recette modèle", "Les recettes modèles ne sont pas modifiables : dupliquez-la pour créer votre version.")
            return None
        return r

    def new_recipe(self):
        name, ok = QInputDialog.getText(self, "Nouvelle recette", "Nom de la recette :")
        if ok and name.strip():
            self.recipes.append({"name": name.strip(), "description": "", "steps": []})
            self._save()
            self._refresh_list(len(self.recipes) - 1)

    def duplicate_recipe(self):
        r = self.current()
        if r:
            c = copy.deepcopy(r)
            c.pop("builtin", None)
            c["name"] = r["name"] + " (copie)"
            self.recipes.append(c)
            self._save()
            self._refresh_list(len(self.recipes) - 1)

    def rename_recipe(self):
        r = self._editable()
        if r:
            name, ok = QInputDialog.getText(self, "Renommer", "Nom :", text=r["name"])
            if ok and name.strip():
                r["name"] = name.strip()
                self._save()
                self._refresh_list(self.recipe_list.currentRow())

    def delete_recipe(self):
        r = self._editable()
        if r and QMessageBox.question(self, "Supprimer", f"Supprimer la recette « {r['name']} » ?") == QMessageBox.Yes:
            self.recipes.remove(r)
            self._save()
            self._refresh_list()

    def add_step(self):
        r = self._editable()
        if not r:
            return
        tid = self.add_combo.currentData()
        dlg = StepDialog(tid, None, self)
        if dlg.exec():
            r["steps"].append({"tool": tid, "params": dlg.values()})
            self._save()
            self._show_recipe()

    def edit_step(self):
        r = self._editable()
        i = self.steps.currentRow()
        if not r or i < 0:
            return
        step = r["steps"][i]
        dlg = StepDialog(step["tool"], step.get("params"), self)
        if dlg.exec():
            step["params"] = dlg.values()
            self._save()
            self._show_recipe()
            self.steps.setCurrentRow(i)

    def move_step(self, d: int):
        r = self._editable()
        i = self.steps.currentRow()
        if not r or i < 0 or not 0 <= i + d < len(r["steps"]):
            return
        r["steps"][i], r["steps"][i + d] = r["steps"][i + d], r["steps"][i]
        self._save()
        self._show_recipe()
        self.steps.setCurrentRow(i + d)

    def remove_step(self):
        r = self._editable()
        i = self.steps.currentRow()
        if r and i >= 0:
            del r["steps"][i]
            self._save()
            self._show_recipe()

    def import_recipes(self):
        f, _ = QFileDialog.getOpenFileName(self, "Importer des recettes", app_settings().last_dir(), "Recettes (*.json)")
        if f:
            try:
                data = json.loads(Path(f).read_text(encoding="utf-8"))
                data = data if isinstance(data, list) else [data]
                added = [d for d in data if isinstance(d, dict) and d.get("steps") is not None and all(s.get("tool") in REGISTRY for s in d["steps"])]
                for d in added:
                    d.pop("builtin", None)
                self.recipes.extend(added)
                self._save()
                self._refresh_list(len(self.recipes) - 1)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Import", f"Fichier invalide : {exc}")

    def export_recipe(self):
        r = self.current()
        if not r:
            return
        f, _ = QFileDialog.getSaveFileName(self, "Exporter la recette", str(Path(app_settings().last_dir()) / "recette.json"), "Recettes (*.json)")
        if f:
            clean = {k: v for k, v in r.items() if k != "builtin"}
            Path(f).write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")

    def _pick_folder(self, edit: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "Choisir un dossier", edit.text() or app_settings().last_dir())
        if d:
            edit.setText(d)

    def run_recipe(self):
        r = self.current()
        files = self.run_files.files()
        if not r or not r["steps"]:
            QMessageBox.information(self, "Recette", "Cette recette ne contient aucune étape.")
            return
        if not files:
            QMessageBox.information(self, "Recette", "Ajoutez des fichiers à traiter.")
            return
        task = {
            "kind": "workflow",
            "steps": r["steps"],
            "inputs": files,
            "out_dir": self.out_folder.text().strip() or None,
            "suffix": self.suffix.text(),
            "settings": app_settings().worker_settings(),
        }
        self.result.hide()
        self.job = self.jobs.submit(task, r["name"])
        self.job.progress.connect(lambda f, m: self.run_progress.setValue(int(f * 1000)))
        self.job.finished.connect(lambda o, rep: (self.run_progress.hide(), self.run_btn.setEnabled(True), self.result.show_success(o, rep)))
        self.job.failed.connect(lambda m, t: (self.run_progress.hide(), self.run_btn.setEnabled(True), self.result.show_error(m)))
        self.job.password_needed.connect(lambda p: (self.run_progress.hide(), self.run_btn.setEnabled(True), self.result.show_error(f"« {Path(p).name} » est protégé par mot de passe : déverrouillez-le d'abord.")))
        self.run_progress.show()
        self.run_btn.setEnabled(False)

    # ================================================================ dossier surveillé
    def _build_watch(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.addWidget(label("Chaque PDF déposé dans le dossier d'entrée est automatiquement traité par la recette choisie, puis enregistré dans le dossier de sortie. Idéal pour un scanner réseau ou un dossier partagé.", "muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(label("Dossier d'entrée :"))
        self.watch_in = QLineEdit()
        row.addWidget(self.watch_in, 1)
        row.addWidget(button("…", slot=lambda: self._pick_folder(self.watch_in)))
        cl.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(label("Dossier de sortie :"))
        self.watch_out = QLineEdit()
        row.addWidget(self.watch_out, 1)
        row.addWidget(button("…", slot=lambda: self._pick_folder(self.watch_out)))
        cl.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(label("Recette :"))
        self.watch_recipe = QComboBox()
        row.addWidget(self.watch_recipe, 1)
        cl.addLayout(row)
        self.watch_move = QCheckBox("Déplacer les originaux dans un sous-dossier « originaux » après traitement")
        self.watch_move.setChecked(True)
        cl.addWidget(self.watch_move)
        self.watch_existing = QCheckBox("Traiter aussi les fichiers déjà présents au démarrage")
        cl.addWidget(self.watch_existing)
        row = QHBoxLayout()
        self.watch_btn = button("▶ Démarrer la surveillance", "primary", self.toggle_watch)
        row.addWidget(self.watch_btn)
        self.watch_state = label("⏸ Inactif", "muted")
        row.addWidget(self.watch_state)
        row.addStretch(1)
        cl.addLayout(row)
        lay.addWidget(card)
        lay.addWidget(label("Journal", "h3"))
        self.watch_log = QListWidget()
        lay.addWidget(self.watch_log, 1)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda *_: self._scan())
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(4000)
        self.watch_timer.timeout.connect(self._scan)
        self.watch_seen: dict[str, tuple[int, float]] = {}
        self.watch_done: set[str] = set()
        self.watching = False
        return w

    def _refresh_watch_recipes(self):
        if not hasattr(self, "watch_recipe"):
            return
        cur = self.watch_recipe.currentText()
        self.watch_recipe.clear()
        for r in self.recipes:
            if r["steps"]:
                self.watch_recipe.addItem(r["name"])
        i = self.watch_recipe.findText(cur)
        if i >= 0:
            self.watch_recipe.setCurrentIndex(i)

    def _log(self, text: str):
        self.watch_log.insertItem(0, f"{time.strftime('%H:%M:%S')}  {text}")

    def toggle_watch(self):
        if self.watching:
            self.watching = False
            self.watch_timer.stop()
            if self.watcher.directories():
                self.watcher.removePaths(self.watcher.directories())
            self.watch_btn.setText("▶ Démarrer la surveillance")
            self.watch_state.setText("⏸ Inactif")
            self._log("Surveillance arrêtée")
            return
        src, dst = Path(self.watch_in.text().strip()), self.watch_out.text().strip()
        if not src.is_dir():
            QMessageBox.warning(self, "Dossier surveillé", "Choisissez un dossier d'entrée valide.")
            return
        if not dst:
            dst = str(src / "traités")
            self.watch_out.setText(dst)
        Path(dst).mkdir(parents=True, exist_ok=True)
        self.watch_done = set()
        if not self.watch_existing.isChecked():
            self.watch_done = {str(p) for p in src.glob("*.pdf")}
        self.watcher.addPath(str(src))
        self.watch_timer.start()
        self.watching = True
        self.watch_btn.setText("⏹ Arrêter")
        self.watch_state.setText(f"🟢 Surveillance de « {src.name} »")
        self._log(f"Surveillance démarrée : {src}  →  {dst}")
        self._scan()

    def _scan(self):
        if not self.watching:
            return
        src = Path(self.watch_in.text().strip())
        now = time.time()
        for p in src.glob("*.pdf"):
            key = str(p)
            if key in self.watch_done:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            prev = self.watch_seen.get(key)
            # Attendre que le fichier soit complètement copié (taille stable).
            if prev is None or prev[0] != size:
                self.watch_seen[key] = (size, now)
                QTimer.singleShot(1600, self._scan)
                continue
            if now - prev[1] < 1.5:
                continue
            self.watch_done.add(key)
            self._process(p)

    def _process(self, p: Path):
        name = self.watch_recipe.currentText()
        recipe = next((r for r in self.recipes if r["name"] == name), None)
        if not recipe:
            self._log("⚠️ Aucune recette sélectionnée")
            return
        task = {
            "kind": "workflow",
            "steps": recipe["steps"],
            "inputs": [str(p)],
            "out_dir": self.watch_out.text().strip(),
            "suffix": "",
            "settings": app_settings().worker_settings(),
        }
        self._log(f"⏳ {p.name} : traitement avec « {name} »")
        job = self.jobs.submit(task, f"Dossier surveillé : {p.name}")

        def done(outputs, reports, p=p):
            self._log(f"✅ {p.name} → {', '.join(Path(o).name for o in outputs)}")
            if self.watch_move.isChecked() and p.exists():
                dest = p.parent / "originaux"
                dest.mkdir(exist_ok=True)
                try:
                    shutil.move(str(p), str(dest / p.name))
                except OSError as exc:
                    self._log(f"⚠️ Impossible de déplacer {p.name} : {exc}")

        job.finished.connect(done)
        job.failed.connect(lambda m, t, p=p: self._log(f"❌ {p.name} : {m}"))
        job.password_needed.connect(lambda path, p=p: self._log(f"🔒 {p.name} : protégé par mot de passe, ignoré"))

    def set_files(self, files: list[str]):
        self.run_files.add_files(files)
