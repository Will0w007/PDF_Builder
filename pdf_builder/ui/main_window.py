"""Fenêtre principale : navigation latérale et pages."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from .. import APP_NAME
from ..core.registry import REGISTRY
from .command_palette import CommandPalette
from .jobs import JobManager
from .pages.automation import AutomationPage
from .pages.compare import ComparePage
from .pages.editor import EditorPage
from .pages.home import HomePage
from .pages.organizer import OrganizerPage
from .pages.search import SearchPage
from .pages.settings_page import SettingsPage
from .pages.tool_page import ToolPage
from .theme import apply_theme
from .widgets import Toast, app_settings, label

NAV = [
    ("home", "🏠  Accueil"),
    ("editor", "✏️  Éditeur"),
    ("organizer", "🗂️  Organiser"),
    ("compare", "🆚  Comparer"),
    ("search", "🔎  Rechercher"),
    ("automation", "⚙️  Automatiser"),
    ("settings", "🎛️  Paramètres"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)
        self.setMinimumSize(1040, 680)
        self.setAcceptDrops(True)
        self.jobs = JobManager(self)

        central = QWidget()
        self.setCentralWidget(central)
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Barre latérale
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(212)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 6, 0, 10)
        sl.setSpacing(0)
        sl.addWidget(label("📘 PDF Builder", "brand"))
        sl.addWidget(label("La suite PDF complète", "brandSub"))
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for i, (key, text) in enumerate(NAV):
            b = QPushButton(text)
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"Ctrl+{i + 1}")
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            sl.addWidget(b)
        sl.addStretch(1)
        palette_btn = QPushButton("⌘  Palette  (Ctrl+K)")
        palette_btn.setObjectName("navButton")
        palette_btn.clicked.connect(self.open_palette)
        sl.addWidget(palette_btn)
        self.activity = QLabel("")
        self.activity.setObjectName("sidebarHint")
        self.activity.setWordWrap(True)
        sl.addWidget(self.activity)
        lay.addWidget(side)

        # Pages
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.home = HomePage()
        self.tool_page = ToolPage(self.jobs)
        self.editor = EditorPage()
        self.organizer = OrganizerPage()
        self.compare = ComparePage(self.jobs)
        self.search = SearchPage(self.jobs)
        self.automation = AutomationPage(self.jobs)
        self.settings = SettingsPage()
        self.pages = {
            "home": self.home,
            "tool": self.tool_page,
            "editor": self.editor,
            "organizer": self.organizer,
            "compare": self.compare,
            "search": self.search,
            "automation": self.automation,
            "settings": self.settings,
        }
        for w in self.pages.values():
            self.stack.addWidget(w)

        # Connexions
        self.home.tool_requested.connect(self.open_tool)
        self.home.action_requested.connect(self.run_action)
        self.tool_page.back_requested.connect(lambda: self.show_page("home"))
        self.tool_page.open_in_editor.connect(self.open_in_editor)
        self.tool_page.chain_requested.connect(self.chain_files)
        self.editor.status_message.connect(self.toast)
        self.editor.run_tool.connect(self.open_tool)
        self.editor.document_opened.connect(lambda *_: self.home.refresh_recent())
        self.organizer.status_message.connect(self.toast)
        self.organizer.open_in_editor.connect(self.open_in_editor)
        self.search.open_result.connect(lambda f, p, q: self.open_in_editor(f, p, q))
        self.settings.theme_changed.connect(self.set_theme)
        self.jobs.activity.connect(lambda t: self.activity.setText(t[:120]))

        self.toast_widget = Toast(self)
        for i, (key, _t) in enumerate(NAV):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda k=key: self.show_page(k))
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_palette)
        QShortcut(QKeySequence.Open, self, activated=lambda: (self.show_page("editor"), self.editor.browse()))
        self.show_page("home")

    # ------------------------------------------------------------------
    def show_page(self, key: str):
        self.stack.setCurrentWidget(self.pages[key])
        btn = self.nav_buttons.get(key if key != "tool" else "home")
        if btn:
            btn.setChecked(True)
        if key == "editor" and self.editor.doc is not None:
            name = self.editor.path.name if self.editor.path else "Document"
            self.setWindowTitle(f"{name} — {APP_NAME}")
        else:
            self.setWindowTitle(APP_NAME)

    def open_tool(self, tool_id: str, files: list[str] | None = None):
        if tool_id.startswith("@"):
            return self.run_action(tool_id, files or [])
        self.tool_page.set_tool(tool_id, files or [])
        self.show_page("tool")

    def run_action(self, action: str, files: list[str]):
        if action == "@editor":
            pdf = next((f for f in files if f.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".xps", ".epub"))), None)
            self.show_page("editor")
            if pdf:
                self.editor.open_file(pdf)
        elif action == "@organizer":
            self.show_page("organizer")
            if files:
                self.organizer.add_files(files)
        elif action == "@compare":
            self.show_page("compare")
            self.compare.set_files(files)

    def open_in_editor(self, path: str, page: int = 0, search: str | None = None):
        self.show_page("editor")
        self.editor.open_file(path, page, search)

    def chain_files(self, files: list[str]):
        pdfs = [f for f in files if f.lower().endswith(".pdf")]
        self.show_page("home")
        self.home.show_suggestions(pdfs)
        self.toast("Choisissez l'outil à appliquer aux fichiers produits")

    def set_theme(self, mode: str):
        apply_theme(mode)
        self.editor.view._apply_bg()
        self.compare.view._apply_bg()

    def toast(self, text: str):
        if text:
            self.toast_widget.show_message(text)

    def open_palette(self):
        cmds = []
        for key, text in NAV:
            cmds.append((f"Aller à : {text.strip()}", "", key, lambda k=key: self.show_page(k)))
        for t in REGISTRY.values():
            cmds.append((f"{t.icon} {t.name}", t.description[:70], t.keywords, lambda tid=t.id: self.open_tool(tid)))
        cmds += [
            ("📂 Ouvrir un PDF dans l'éditeur", "Ctrl+O", "ouvrir fichier", lambda: (self.show_page("editor"), self.editor.browse())),
            ("🌙 Thème sombre", "", "dark nuit theme", lambda: self._theme_cmd("dark")),
            ("☀️ Thème clair", "", "light jour theme", lambda: self._theme_cmd("light")),
        ]
        for f in app_settings().recent()[:8]:
            cmds.append((f"🕘 {Path(f).name}", f, "récent recent", lambda f=f: self.open_in_editor(f)))
        CommandPalette(cmds, self).exec()

    def _theme_cmd(self, mode: str):
        app_settings().set("theme", mode)
        idx = self.settings.theme.findData(mode)
        self.settings.theme.blockSignals(True)
        self.settings.theme.setCurrentIndex(idx)
        self.settings.theme.blockSignals(False)
        self.set_theme(mode)

    # ------------------------------------------------------------------ glisser-déposer global
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not files:
            return
        current = self.stack.currentWidget()
        if current is self.editor:
            self.editor.open_file(files[0])
        elif current is self.organizer:
            self.organizer.add_files(files)
        elif current is self.tool_page:
            self.tool_page.files.add_files(files)
        elif current is self.compare:
            self.compare.set_files(files)
        elif current is self.automation:
            self.automation.set_files(files)
        else:
            self.show_page("home")
            self.home.show_suggestions(files)

    def open_files_from_cli(self, files: list[str]):
        files = [f for f in files if Path(f).exists()]
        if not files:
            return
        if len(files) == 1 and files[0].lower().endswith(".pdf"):
            QTimer.singleShot(50, lambda: self.open_in_editor(files[0]))
        else:
            self.home.show_suggestions(files)

    def closeEvent(self, e):
        if not self.editor.confirm_discard():
            e.ignore()
            return
        if self.jobs.is_busy():
            from PySide6.QtWidgets import QMessageBox

            if QMessageBox.question(self, "Traitement en cours", "Un traitement est en cours. Quitter quand même ?") != QMessageBox.Yes:
                e.ignore()
                return
        self.jobs.shutdown()
        super().closeEvent(e)
