"""Thèmes clair et sombre (palette Qt + feuille de style)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#F5F6FA",
    "surface": "#FFFFFF",
    "surface2": "#EEF0F6",
    "border": "#DFE3EC",
    "text": "#1C2030",
    "muted": "#6B7285",
    "accent": "#4F46E5",
    "accent_hover": "#4338CA",
    "accent_soft": "#EBEDFF",
    "accent_text": "#FFFFFF",
    "danger": "#DC2626",
    "success": "#15803D",
    "warning": "#B45309",
    "sidebar": "#191B33",
    "sidebar_text": "#C9CCE6",
    "sidebar_active": "#2E3160",
    "viewer_bg": "#D9DCE5",
    "selection": "#C7CBFF",
}

DARK = {
    "bg": "#11131A",
    "surface": "#1A1D27",
    "surface2": "#232735",
    "border": "#2D3243",
    "text": "#E7E9F2",
    "muted": "#9AA0B4",
    "accent": "#7C83FF",
    "accent_hover": "#959BFF",
    "accent_soft": "#262A4A",
    "accent_text": "#0E1020",
    "danger": "#F87171",
    "success": "#4ADE80",
    "warning": "#FBBF24",
    "sidebar": "#0C0D14",
    "sidebar_text": "#A9AEC8",
    "sidebar_active": "#262A4A",
    "viewer_bg": "#0E1016",
    "selection": "#3B3F7A",
}

CURRENT = dict(LIGHT)

QSS = """
* {{ outline: none; }}
QWidget {{ color: {text}; font-size: 10pt; }}
QMainWindow, QStackedWidget > QWidget#page, QWidget#page {{ background: {bg}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 6px; border-radius: 6px; }}

/* Barre latérale */
QWidget#sidebar {{ background: {sidebar}; }}
QLabel#brand {{ color: white; font-size: 15pt; font-weight: 700; padding: 18px 16px 10px 16px; }}
QLabel#brandSub {{ color: {sidebar_text}; font-size: 8.5pt; padding: 0 16px 14px 16px; }}
QPushButton#navButton {{
    color: {sidebar_text}; background: transparent; border: none; text-align: left;
    padding: 10px 16px; margin: 2px 10px; border-radius: 10px; font-size: 10.5pt;
}}
QPushButton#navButton:hover {{ background: {sidebar_active}; color: white; }}
QPushButton#navButton:checked {{ background: {accent}; color: white; font-weight: 600; }}
QLabel#sidebarHint {{ color: {sidebar_text}; font-size: 8.5pt; padding: 10px 16px; }}

/* Titres */
QLabel#h1 {{ font-size: 20pt; font-weight: 700; }}
QLabel#h2 {{ font-size: 13pt; font-weight: 650; }}
QLabel#h3 {{ font-size: 11pt; font-weight: 600; }}
QLabel#muted, QLabel[muted="true"] {{ color: {muted}; }}
QLabel#bigIcon {{ font-size: 30pt; }}

/* Cartes */
QFrame#card, QWidget#card {{ background: {surface}; border: 1px solid {border}; border-radius: 14px; }}
QFrame#toolCard {{ background: {surface}; border: 1px solid {border}; border-radius: 14px; }}
QFrame#toolCard:hover {{ border: 1.5px solid {accent}; background: {accent_soft}; }}
QLabel#cardIcon {{ font-size: 22pt; background: {accent_soft}; border-radius: 12px; }}
QLabel#cardTitle {{ font-weight: 650; font-size: 10.5pt; }}
QLabel#cardDesc {{ color: {muted}; font-size: 9pt; }}
QFrame#dropZone {{ background: {surface}; border: 2px dashed {border}; border-radius: 16px; }}
QFrame#dropZone[active="true"] {{ border-color: {accent}; background: {accent_soft}; }}
QFrame#suggestion {{ background: {accent_soft}; border: 1px solid {accent}; border-radius: 12px; }}
QFrame#resultPanel {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
QFrame#separator {{ background: {border}; max-height: 1px; min-height: 1px; }}

/* Boutons */
QPushButton {{
    background: {surface}; border: 1px solid {border}; border-radius: 9px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {accent}; color: {accent}; }}
QPushButton:pressed {{ background: {surface2}; }}
QPushButton:disabled {{ color: {muted}; background: {surface2}; border-color: {border}; }}
QPushButton#primary {{ background: {accent}; color: {accent_text}; border: none; font-weight: 650; padding: 9px 22px; }}
QPushButton#primary:hover {{ background: {accent_hover}; color: {accent_text}; }}
QPushButton#primary:disabled {{ background: {border}; color: {muted}; }}
QPushButton#danger {{ color: {danger}; }}
QPushButton#danger:hover {{ border-color: {danger}; }}
QPushButton#link {{ border: none; background: transparent; color: {accent}; padding: 2px 4px; text-align: left; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#chip {{ border-radius: 14px; padding: 5px 12px; background: {surface2}; border: 1px solid {border}; }}
QPushButton#chip:checked {{ background: {accent}; color: {accent_text}; border-color: {accent}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 5px 7px; font-size: 10pt; }}
QToolButton:hover {{ background: {surface2}; border-color: {border}; }}
QToolButton:checked {{ background: {accent_soft}; border-color: {accent}; color: {accent}; }}
QToolButton::menu-indicator {{ width: 0; }}

/* Champs */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {accent}; selection-color: white;
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {accent}; }}
QLineEdit#search {{ padding: 10px 14px; border-radius: 12px; font-size: 11pt; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({arrow_down}); width: 10px; height: 10px; margin-right: 8px; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 18px; border: none; background: transparent; margin: 2px 2px 0 0; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border: none; background: transparent; margin: 0 2px 2px 0; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {surface2}; border-radius: 4px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({arrow_up}); width: 9px; height: 9px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({arrow_down}); width: 9px; height: 9px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; selection-background-color: {accent_soft}; selection-color: {text}; padding: 4px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid {border}; background: {surface}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: none; }}
QCheckBox::indicator:hover {{ border-color: {accent}; }}

/* Listes & arbres */
QListWidget, QTreeWidget, QTableWidget {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; padding: 4px; }}
QListWidget::item, QTreeWidget::item {{ padding: 6px; border-radius: 6px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {accent_soft}; color: {text}; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {surface2}; }}
QHeaderView::section {{ background: {surface2}; border: none; padding: 6px; font-weight: 600; }}

/* Onglets */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; margin-right: 4px; border-bottom: 2px solid transparent; color: {muted}; }}
QTabBar::tab:selected {{ color: {accent}; border-bottom: 2px solid {accent}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {text}; }}

/* Barres de progression */
QProgressBar {{ background: {surface2}; border: none; border-radius: 6px; height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 6px; }}

/* Barres de défilement */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Barre d'outils de l'éditeur */
QFrame#toolbar, QToolBar#toolbar {{ background: {surface}; border: none; border-bottom: 1px solid {border}; padding: 4px 10px; spacing: 3px; }}
QToolBar::separator {{ background: {border}; width: 1px; margin: 6px 6px; }}
QFrame#sidePanel {{ background: {surface}; border-right: 1px solid {border}; }}
QFrame#propPanel {{ background: {surface}; border-left: 1px solid {border}; }}
QGraphicsView {{ border: none; background: {viewer_bg}; }}
QStatusBar {{ background: {surface}; border-top: 1px solid {border}; color: {muted}; }}
QSplitter::handle {{ background: {border}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {accent_soft}; }}
QDialog {{ background: {bg}; }}
QFrame#palette {{ background: {surface}; border: 1px solid {border}; border-radius: 16px; }}
QLabel#badge {{ background: {accent_soft}; color: {accent}; border-radius: 8px; padding: 2px 8px; font-size: 8.5pt; font-weight: 600; }}
QLabel#toast {{ background: {text}; color: {bg}; border-radius: 10px; padding: 10px 16px; }}
"""


def system_prefers_dark() -> bool:
    app = QApplication.instance()
    try:
        from PySide6.QtCore import Qt

        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001
        pal = app.palette()
        return pal.color(QPalette.Window).lightness() < 128


def _arrow_files(hex_color: str) -> dict:
    """Écrit de petites flèches SVG (les flèches natives de Fusion ignorent le thème)."""
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.gettempdir()) / "pdfbuilder_theme"
    folder.mkdir(exist_ok=True)
    paths = {}
    for name, pts in (("up", "1,7 5,2.5 9,7"), ("down", "1,3 5,7.5 9,3")):
        f = folder / f"arrow_{name}_{hex_color.strip('#')}.svg"
        if not f.exists():
            f.write_text(
                f"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 10 10'>"
                f"<polyline points='{pts}' fill='none' stroke='{hex_color}' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/></svg>",
                encoding="utf-8",
            )
        paths[f"arrow_{name}"] = f.as_posix()
    return paths


def apply_theme(mode: str = "system") -> dict:
    app = QApplication.instance()
    dark = mode == "dark" or (mode == "system" and system_prefers_dark())
    tokens = DARK if dark else LIGHT
    CURRENT.clear()
    CURRENT.update(tokens)
    CURRENT["is_dark"] = dark
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(tokens["bg"]))
    pal.setColor(QPalette.WindowText, QColor(tokens["text"]))
    pal.setColor(QPalette.Base, QColor(tokens["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(tokens["surface2"]))
    pal.setColor(QPalette.Text, QColor(tokens["text"]))
    pal.setColor(QPalette.Button, QColor(tokens["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(tokens["text"]))
    pal.setColor(QPalette.Highlight, QColor(tokens["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, QColor(tokens["surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(tokens["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(tokens["muted"]))
    pal.setColor(QPalette.Link, QColor(tokens["accent"]))
    app.setPalette(pal)
    app.setStyleSheet(QSS.format(**tokens, **_arrow_files(tokens["muted"])))
    return tokens


def color(name: str) -> QColor:
    return QColor(CURRENT.get(name, "#000000"))
