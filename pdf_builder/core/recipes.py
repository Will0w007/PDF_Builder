"""Recettes (flux de travail) prêtes à l'emploi et persistance des recettes utilisateur."""

from __future__ import annotations

import json
from pathlib import Path

BUILTIN_RECIPES = [
    {
        "name": "📧 Préparer pour l'e-mail",
        "description": "Compression forte et suppression des métadonnées.",
        "builtin": True,
        "steps": [
            {"tool": "compress", "params": {"level": "strong", "strip": True}},
        ],
    },
    {
        "name": "🗄️ Archivage numérique",
        "description": "OCR des scans, signets automatiques, compression recommandée.",
        "builtin": True,
        "steps": [
            {"tool": "ocr", "params": {"lang": "fra", "mode": "auto"}},
            {"tool": "compress", "params": {"level": "medium"}},
        ],
    },
    {
        "name": "📠 Nettoyer un scan",
        "description": "Supprime les pages blanches, rogne les marges et rend le texte cherchable.",
        "builtin": True,
        "steps": [
            {"tool": "remove_blank", "params": {}},
            {"tool": "ocr", "params": {"lang": "fra", "mode": "auto"}},
            {"tool": "compress", "params": {"level": "medium"}},
        ],
    },
    {
        "name": "🔒 Diffusion confidentielle",
        "description": "Filigrane CONFIDENTIEL, assainissement et protection anti-copie.",
        "builtin": True,
        "steps": [
            {"tool": "watermark", "params": {"text": "CONFIDENTIEL", "opacity": 18}},
            {"tool": "sanitize", "params": {}},
            {"tool": "protect", "params": {"allow_copy": False, "allow_modify": False}},
        ],
    },
    {
        "name": "📚 Prêt à imprimer",
        "description": "Format A4 uniforme, numéros de page et page blanche finale si nombre impair.",
        "builtin": True,
        "steps": [
            {"tool": "resize", "params": {"paper": "A4"}},
            {"tool": "page_numbers", "params": {"format": "{n} / {total}"}},
            {"tool": "insert_blank", "params": {"where": "even"}},
        ],
    },
]


def load_user_recipes(path: Path) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return [r for r in data if isinstance(r, dict) and r.get("steps") is not None]
    except (OSError, ValueError):
        return []


def save_user_recipes(path: Path, recipes: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = [{k: v for k, v in r.items() if k != "builtin"} for r in recipes if not r.get("builtin")]
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
