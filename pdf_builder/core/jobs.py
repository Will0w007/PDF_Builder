"""Fonctions appelables par le processus de travail (tâches de type « call »)."""

from __future__ import annotations

from pathlib import Path


def compare_job(ctx, path_a: str, path_b: str, out_path: str) -> dict:
    from .tools_extract import build_compare_report, compare_documents
    from .utils import make_upright

    a = make_upright(ctx.open(path_a))
    b = make_upright(ctx.open(path_b))
    res = compare_documents(a, b, ctx.progress)
    ctx.progress(0.8, "Création du rapport…")
    report = build_compare_report(a, b, res, Path(path_a).name, Path(path_b).name)
    report.save(out_path, garbage=3, deflate=True)
    report.close()
    a.close()
    b.close()
    return {
        "report": out_path,
        "similarity": res["similarity"],
        "changes": res["changes"],
        "visual": [v + 1 for v in res["visual"]],
        "pages": res["pages"],
    }


def search_job(ctx, folder: str, query: str, regex: bool = False, case: bool = False, recursive: bool = True) -> list[dict]:
    from .tools_extract import search_folder

    return search_folder(folder, query, regex=regex, case=case, recursive=recursive, progress=ctx.progress)


def analyze_job(ctx, path: str) -> str:
    from .tools_extract import analyze, format_report

    doc = ctx.open(path)
    try:
        return format_report(analyze(doc, Path(path)), Path(path).name)
    finally:
        doc.close()
