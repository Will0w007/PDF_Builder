"""Gestion des tâches : file d'attente vers le processus de travail."""

from __future__ import annotations

import itertools
import multiprocessing as mp
import queue as pyqueue
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.worker import worker_main


class Job(QObject):
    progress = Signal(float, str)
    finished = Signal(list, list)  # sorties, rapports
    result = Signal(object)
    failed = Signal(str, str)  # message, trace
    password_needed = Signal(str)
    started = Signal()
    cancelled = Signal()

    def __init__(self, job_id: int, task: dict, title: str):
        super().__init__()
        self.id = job_id
        self.task = task
        self.title = title
        self.state = "queued"  # queued, running, done, error, cancelled


class JobManager(QObject):
    """Envoie les tâches une par une à un processus de travail persistant."""

    activity = Signal(str)  # texte de statut global
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ctx = mp.get_context("spawn")
        self._ids = itertools.count(1)
        self._queue: deque[Job] = deque()
        self._current: Job | None = None
        self._jobs: dict[int, Job] = {}
        self._proc = None
        self._task_q = None
        self._result_q = None
        self._start_worker()
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ------------------------------------------------------------------
    def _start_worker(self) -> None:
        self._task_q = self._ctx.Queue()
        self._result_q = self._ctx.Queue()
        self._proc = self._ctx.Process(target=worker_main, args=(self._task_q, self._result_q), daemon=True)
        self._proc.start()

    def _restart_worker(self) -> None:
        try:
            if self._proc and self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(2)
        except Exception:  # noqa: BLE001
            pass
        self._start_worker()

    def shutdown(self) -> None:
        self._timer.stop()
        try:
            self._task_q.put(None)
            self._proc.join(1.5)
            if self._proc.is_alive():
                self._proc.terminate()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    def submit(self, task: dict, title: str = "") -> Job:
        job = Job(next(self._ids), dict(task), title or task.get("tool", "Tâche"))
        job.task["id"] = job.id
        self._jobs[job.id] = job
        self._queue.append(job)
        self._dispatch()
        return job

    def cancel(self, job: Job) -> None:
        if job.state == "queued" and job in self._queue:
            self._queue.remove(job)
        elif job is self._current:
            self._current = None
            self._restart_worker()
        else:
            return
        job.state = "cancelled"
        job.cancelled.emit()
        self._dispatch()

    def is_busy(self) -> bool:
        return self._current is not None or bool(self._queue)

    def pending_count(self) -> int:
        return len(self._queue) + (1 if self._current else 0)

    def _dispatch(self) -> None:
        if self._current is not None or not self._queue:
            if self._current is None:
                self.busy_changed.emit(False)
                self.activity.emit("")
            return
        job = self._queue.popleft()
        self._current = job
        job.state = "running"
        if not self._proc.is_alive():
            self._start_worker()
        self._task_q.put(job.task)
        job.started.emit()
        self.busy_changed.emit(True)
        self.activity.emit(f"⏳ {job.title}")

    def _finish(self, job: Job) -> None:
        if job is self._current:
            self._current = None
        self._jobs.pop(job.id, None)
        self._dispatch()

    def _poll(self) -> None:
        for _ in range(200):
            try:
                msg = self._result_q.get_nowait()
            except pyqueue.Empty:
                break
            except (EOFError, OSError):
                break
            kind = msg[0]
            if kind == "ready":
                continue
            job = self._jobs.get(msg[1])
            if job is None or job.state == "cancelled":
                continue
            if kind == "progress":
                job.progress.emit(msg[2], msg[3])
                if msg[3]:
                    self.activity.emit(f"⏳ {job.title} — {msg[3]}")
            elif kind == "done":
                job.state = "done"
                self._finish(job)
                job.finished.emit(msg[2], msg[3])
            elif kind == "result":
                job.state = "done"
                self._finish(job)
                job.result.emit(msg[2])
            elif kind == "password":
                job.state = "error"
                self._finish(job)
                job.password_needed.emit(msg[2])
            elif kind == "error":
                job.state = "error"
                self._finish(job)
                job.failed.emit(msg[2], msg[3])
        # Processus mort pendant une tâche (fichier corrompu, mémoire…)
        if self._current is not None and self._proc is not None and not self._proc.is_alive():
            job = self._current
            job.state = "error"
            self._start_worker()
            self._finish(job)
            job.failed.emit("Le traitement s'est arrêté de façon inattendue (fichier corrompu ou trop volumineux ?).", "")
