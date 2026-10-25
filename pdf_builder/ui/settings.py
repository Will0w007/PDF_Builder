"""Préférences persistantes de l'application."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

from .. import APP_ID

DEFAULTS = {
    "theme": "system",
    "output_mode": "beside",  # beside | folder
    "output_folder": "",
    "after_run": "show",  # show | open_file | open_folder
    "tessdata": "",
    "soffice": "",
    "ghostscript": "",
    "ocr_lang": "fra",
    "recent": [],
    "last_dir": "",
    "show_tips": True,
}


class Settings:
    def __init__(self):
        self._q = QSettings(APP_ID, APP_ID)

    def get(self, key: str):
        default = DEFAULTS.get(key)
        value = self._q.value(key, default)
        if isinstance(default, bool):
            return value in (True, "true", "1", 1)
        if isinstance(default, list):
            if value is None or value == "":
                return []
            return list(value) if isinstance(value, (list, tuple)) else [value]
        return value

    def set(self, key: str, value) -> None:
        self._q.setValue(key, value)

    # -- dossiers ---------------------------------------------------------
    @staticmethod
    def data_dir() -> Path:
        base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or str(Path.home() / ".pdfbuilder")
        p = Path(base)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def recipes_file(self) -> Path:
        return self.data_dir() / "recipes.json"

    def signatures_dir(self) -> Path:
        p = self.data_dir() / "signatures"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def output_dir(self) -> str | None:
        if self.get("output_mode") == "folder" and self.get("output_folder"):
            return self.get("output_folder")
        return None

    def worker_settings(self) -> dict:
        return {k: self.get(k) or None for k in ("tessdata", "soffice", "ghostscript")}

    # -- fichiers récents -------------------------------------------------
    def add_recent(self, path: str) -> None:
        rec = [p for p in self.get("recent") if p != path]
        rec.insert(0, path)
        self.set("recent", rec[:15])

    def recent(self) -> list[str]:
        return [p for p in self.get("recent") if Path(p).exists()]

    def last_dir(self) -> str:
        d = self.get("last_dir")
        return d if d and Path(d).is_dir() else str(Path.home())

    def remember_dir(self, path: str) -> None:
        p = Path(path)
        self.set("last_dir", str(p if p.is_dir() else p.parent))
