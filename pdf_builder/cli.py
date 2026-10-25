"""Ligne de commande : tous les outils de PDF Builder sont scriptables.

Exemples ::

    python -m pdf_builder.cli liste
    python -m pdf_builder.cli aide compress
    python -m pdf_builder.cli compress rapport.pdf -p level=strong -o sortie/
    python -m pdf_builder.cli merge a.pdf b.pdf c.png -p name=dossier toc_page=true
    python -m pdf_builder.cli recette "📧 Préparer pour l'e-mail" *.pdf
"""

from __future__ import annotations

import argparse
import glob
import sys

from .core.recipes import BUILTIN_RECIPES
from .core.registry import CATEGORIES, Context, ToolError, execute, execute_workflow, get_tool, load_all


def _convert(value: str, kind: str):
    if kind == "bool":
        return value.strip().lower() in ("1", "true", "vrai", "oui", "yes", "on")
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value.replace(",", "."))
    if kind == "files":
        return [v for v in value.split(";") if v]
    return value


def _progress(fraction: float, message: str) -> None:
    bar = "█" * int(fraction * 30)
    sys.stderr.write(f"\r[{bar:<30}] {fraction * 100:5.1f} %  {message[:40]:<40}")
    sys.stderr.flush()


def main(argv: list[str] | None = None) -> int:
    reg = load_all()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "liste", "list"):
        print("PDF Builder – outils disponibles :\n")
        for cat, name, icon in CATEGORIES:
            print(f"{icon} {name}")
            for t in reg.values():
                if t.category == cat:
                    print(f"   {t.id:<20} {t.name}")
        print("\nUsage : python -m pdf_builder.cli <outil> fichiers… [-p clé=valeur …] [-o dossier] [--password mdp]")
        print("        python -m pdf_builder.cli aide <outil>")
        print("        python -m pdf_builder.cli recette <nom> fichiers…")
        return 0
    if argv[0] in ("aide", "help"):
        t = get_tool(argv[1])
        print(f"{t.icon} {t.name} ({t.id})\n{t.description}\n\nParamètres :")
        for p in t.params:
            extra = f" choix : {', '.join(v for v, _ in p.choices)}" if p.choices else ""
            print(f"  {p.key:<16} {p.label} [{p.kind}, défaut : {p.default!r}]{extra}")
        return 0

    parser = argparse.ArgumentParser(prog="pdf_builder.cli")
    parser.add_argument("command")
    parser.add_argument("inputs", nargs="*")
    parser.add_argument("-p", "--param", nargs="*", default=[], help="clé=valeur")
    parser.add_argument("-o", "--out", default=None, help="dossier de sortie")
    parser.add_argument("--password", default=None, help="mot de passe des fichiers protégés")
    args = parser.parse_args(argv)

    files: list[str] = []
    for pattern in args.inputs:
        files.extend(sorted(glob.glob(pattern)) or [pattern])
    ctx = Context(out_dir=args.out, passwords={"*": args.password} if args.password else None, progress=_progress)
    try:
        if args.command in ("recette", "recipe"):
            name, files = files[0], files[1:]
            recipe = next((r for r in BUILTIN_RECIPES if name.lower() in r["name"].lower()), None)
            if not recipe:
                raise ToolError(f"Recette inconnue : {name}")
            outputs = execute_workflow(recipe["steps"], files, ctx)
        else:
            tool = get_tool(args.command)
            kinds = {p.key: p.kind for p in tool.params}
            params = {}
            for item in args.param:
                key, _, value = item.partition("=")
                if key not in kinds:
                    raise ToolError(f"Paramètre inconnu pour {tool.id} : {key}")
                params[key] = _convert(value, kinds[key])
            outputs = execute(tool.id, files, params, ctx)
    except ToolError as exc:
        sys.stderr.write(f"\n❌ {exc}\n")
        return 1
    sys.stderr.write("\n")
    for r in ctx.reports:
        print(r)
    for o in outputs:
        print(f"✅ {o}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
