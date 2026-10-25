"""Processus de travail : exécute les tâches lourdes hors de l'interface.

L'interface envoie des dictionnaires sur ``task_q`` et lit les événements sur
``result_q`` :

* ``("progress", job_id, fraction, message)``
* ``("done", job_id, [chemins], [rapports])``
* ``("result", job_id, valeur)`` – pour les appels de fonctions (« call »)
* ``("password", job_id, chemin)``
* ``("error", job_id, message, trace)``

Exécuter PyMuPDF dans un processus séparé garantit une interface fluide, une
annulation immédiate (le processus est simplement relancé) et protège
l'application d'un éventuel plantage sur un fichier corrompu.
"""

from __future__ import annotations

import importlib
import time
import traceback


def _resolve(dotted: str):
    module, _, name = dotted.partition(":")
    if not module.startswith("pdf_builder."):
        raise ValueError("Fonction non autorisée")
    return getattr(importlib.import_module(module), name)


def worker_main(task_q, result_q) -> None:  # pragma: no cover - exécuté dans un sous-processus
    from .registry import Context, PasswordRequired, ToolError, execute, execute_workflow, load_all

    load_all()
    result_q.put(("ready", 0))
    while True:
        task = task_q.get()
        if task is None:
            break
        jid = task["id"]
        last = [0.0, -1.0]

        def progress(fraction: float, message: str, jid=jid, last=last) -> None:
            now = time.monotonic()
            if now - last[0] > 0.08 or fraction >= 1 or abs(fraction - last[1]) > 0.05:
                last[0], last[1] = now, fraction
                result_q.put(("progress", jid, float(fraction), str(message)))

        ctx = Context(
            out_dir=task.get("out_dir"),
            passwords=task.get("passwords"),
            progress=progress,
            settings=task.get("settings"),
        )
        try:
            kind = task.get("kind", "tool")
            if kind == "tool":
                outputs = execute(task["tool"], task["inputs"], task.get("params"), ctx)
                result_q.put(("done", jid, [str(o) for o in outputs], ctx.reports))
            elif kind == "workflow":
                outputs = execute_workflow(task["steps"], task["inputs"], ctx, task.get("suffix", "_traité"))
                result_q.put(("done", jid, [str(o) for o in outputs], ctx.reports))
            elif kind == "call":
                func = _resolve(task["func"])
                value = func(ctx=ctx, **task.get("kwargs", {}))
                result_q.put(("result", jid, value))
            else:
                raise ToolError(f"Type de tâche inconnu : {kind}")
        except PasswordRequired as exc:
            result_q.put(("password", jid, exc.path))
        except ToolError as exc:
            result_q.put(("error", jid, str(exc), ""))
        except Exception as exc:  # noqa: BLE001
            result_q.put(("error", jid, f"Erreur inattendue : {exc}", traceback.format_exc()))


def run_inline(task: dict, progress=None):
    """Exécute une tâche dans le processus courant (tests, ligne de commande)."""
    from .registry import Context, execute, execute_workflow, load_all

    load_all()
    ctx = Context(out_dir=task.get("out_dir"), passwords=task.get("passwords"), progress=progress, settings=task.get("settings"))
    kind = task.get("kind", "tool")
    if kind == "tool":
        return execute(task["tool"], task["inputs"], task.get("params"), ctx), ctx.reports
    if kind == "workflow":
        return execute_workflow(task["steps"], task["inputs"], ctx, task.get("suffix", "_traité")), ctx.reports
    return _resolve(task["func"])(ctx=ctx, **task.get("kwargs", {})), ctx.reports
