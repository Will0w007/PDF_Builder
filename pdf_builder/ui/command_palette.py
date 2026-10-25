"""Palette de commandes (Ctrl+K) : accès instantané à tout outil ou action."""

from __future__ import annotations

import unicodedata

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from .widgets import label


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def score(query: str, text: str) -> float:
    """Score flou : mots présents > sous-séquence > rien."""
    q, t = _norm(query).strip(), _norm(text)
    if not q:
        return 1.0
    if t.startswith(q):
        return 100.0
    words = q.split()
    if all(w in t for w in words):
        return 50.0 - t.find(words[0]) * 0.1
    i = 0
    for c in t:
        if i < len(q) and c == q[i]:
            i += 1
    return 10.0 * i / len(q) if i == len(q) else 0.0


class CommandPalette(QDialog):
    def __init__(self, commands: list[tuple[str, str, str, object]], parent=None):
        """``commands`` : liste de (titre, détail, mots-clés, callable)."""
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Popup)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.commands = commands
        self.resize(640, 460)
        outer = QVBoxLayout(self)
        frame = QFrame()
        frame.setObjectName("palette")
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 14, 14, 10)
        self.edit = QLineEdit()
        self.edit.setObjectName("search")
        self.edit.setPlaceholderText("Tapez une commande : fusionner, compresser, signer, thème sombre…")
        self.edit.textChanged.connect(self._filter)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit)
        self.list = QListWidget()
        self.list.itemActivated.connect(self._run)
        self.list.itemClicked.connect(self._run)
        lay.addWidget(self.list, 1)
        lay.addWidget(label("↑↓ naviguer · Entrée exécuter · Échap fermer", "muted"))
        self._filter("")

    def _filter(self, text: str):
        self.list.clear()
        ranked = []
        for i, (title, detail, kw, _fn) in enumerate(self.commands):
            s = max(score(text, title) * 1.5, score(text, f"{title} {detail} {kw}"))
            if s > 0:
                ranked.append((-s, i))
        for _s, i in sorted(ranked)[:60]:
            title, detail, _kw, fn = self.commands[i]
            it = QListWidgetItem(f"{title}" + (f"     —  {detail}" if detail else ""))
            it.setData(Qt.UserRole, i)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent

        if obj is self.edit and e.type() == QEvent.KeyPress:
            if e.key() in (Qt.Key_Down, Qt.Key_Up):
                row = self.list.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(row, self.list.count() - 1)))
                return True
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                if self.list.currentItem():
                    self._run(self.list.currentItem())
                return True
        return super().eventFilter(obj, e)

    def _run(self, item):
        i = item.data(Qt.UserRole)
        self.accept()
        self.commands[i][3]()

    def showEvent(self, e):
        super().showEvent(e)
        p = self.parentWidget()
        if p:
            g = p.geometry()
            self.move(g.x() + (g.width() - self.width()) // 2, g.y() + 90)
        self.edit.setFocus()
