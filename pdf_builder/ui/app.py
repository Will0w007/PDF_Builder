"""Création de l'application Qt."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import APP_ID, APP_NAME, __version__


def run(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setApplicationVersion(__version__)
    if sys.platform.startswith("win"):
        try:  # icône correcte dans la barre des tâches Windows
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.{__version__}")
        except Exception:  # noqa: BLE001
            pass

    from ..core.registry import load_all
    from .main_window import MainWindow
    from .theme import apply_theme
    from .widgets import app_settings, emoji_icon

    load_all()
    apply_theme(app_settings().get("theme"))
    icon_path = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
    app.setWindowIcon(QIcon(str(icon_path)) if icon_path.exists() else emoji_icon("📘", 128))
    win = MainWindow()
    win.show()
    win.open_files_from_cli(argv[1:])
    return app.exec()
