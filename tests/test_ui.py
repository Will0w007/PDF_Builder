"""Tests de l'interface (sans affichage : QT_QPA_PLATFORM=offscreen)."""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

import pymupdf as fitz  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pdf_builder.core.registry import load_all  # noqa: E402

from .conftest import make_form_pdf, make_text_pdf  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    load_all()
    from pdf_builder.ui.theme import apply_theme

    apply_theme("light")
    return a


def pump(ms: int = 50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture
def editor(app, tmp_path):
    from pdf_builder.ui.pages.editor import EditorPage

    ed = EditorPage()
    ed.resize(1200, 800)
    ed.show()
    path = make_text_pdf(tmp_path / "doc.pdf", pages=3)
    assert ed.open_file(str(path))
    pump(50)
    return ed


def test_param_forms_for_every_tool(app):
    from pdf_builder.ui.widgets import ParamForm

    for tool in load_all().values():
        form = ParamForm(tool.params)
        values = form.values()
        assert set(values) == {p.key for p in tool.params}, tool.id
        form.set_values(values)
        assert form.values() == values, tool.id


def test_editor_annotations_undo_save(editor, tmp_path, monkeypatch):
    fitz_rect = fitz.Rect(60, 120, 400, 160)
    for tool in ("highlight", "underline", "strike", "rect", "ellipse"):
        editor.current_tool = tool
        editor._on_rect(0, fitz_rect)
    editor.current_tool = "ink"
    editor._on_path(0, [fitz.Point(100, 500), fitz.Point(150, 520), fitz.Point(200, 480)])
    editor._on_line(0, fitz.Point(100, 600), fitz.Point(300, 650))
    assert len(list(editor.doc[0].annots())) == 7
    editor.current_tool = "eraser"
    editor._on_point(0, fitz.Point(130, 140))
    assert len(list(editor.doc[0].annots())) == 6
    editor.undo()
    assert len(list(editor.doc[0].annots())) == 7
    editor.redo()
    assert len(list(editor.doc[0].annots())) == 6

    editor.current_tool = "redact"
    editor._on_rect(0, fitz.Rect(60, 150, 560, 220))
    assert "jean.dupont" not in editor.doc[0].get_text().split("Contexte")[1][:60]

    target = tmp_path / "sortie.pdf"
    monkeypatch.setattr("pdf_builder.ui.pages.editor.QFileDialog.getSaveFileName", lambda *a, **k: (str(target), ""))
    assert editor.save_as()
    with fitz.open(target) as d:
        assert len(list(d[0].annots())) == 6
    assert not editor.modified


def test_editor_text_tools(editor, monkeypatch):
    from pdf_builder.ui import dialogs

    monkeypatch.setattr(dialogs.TextDialog, "exec", lambda self: True)
    monkeypatch.setattr(dialogs.TextDialog, "values", lambda self: {"text": "Bonjour PDF Builder", "font": "helv", "size": 14, "color": "#112233"})
    editor.current_tool = "add_text"
    editor._on_point(1, fitz.Point(100, 700))
    assert "Bonjour PDF Builder" in editor.doc[1].get_text()

    monkeypatch.setattr(dialogs.TextDialog, "values", lambda self: {"text": "Section modifiée", "font": "hebo", "size": 15, "color": "#000000"})
    editor.current_tool = "edit_text"
    span = editor.doc[0].search_for("Section 1.1")[0]
    editor._on_point(0, fitz.Point(span.x0 + 5, span.y0 + 5))
    text = editor.doc[0].get_text()
    assert "Section modifiée" in text and "Section 1.1" not in text


def test_editor_pages_bookmarks_search(editor):
    editor.rotate_page()
    assert editor.doc[0].rotation == 90
    editor.insert_blank()
    assert editor.doc.page_count == 4
    editor.duplicate_page()
    assert editor.doc.page_count == 5
    editor.delete_page()
    assert editor.doc.page_count == 4
    editor.auto_bookmarks()
    assert editor.doc.get_toc()
    assert editor.toc_tree.topLevelItemCount() > 0
    editor.search_edit.setText("IBAN")
    editor.search_next()
    assert editor.search_hits and editor.search_info.text().startswith("1/")


def test_editor_form_dialog(app, tmp_path):
    from pdf_builder.ui.dialogs import FormDialog

    doc = fitz.open(make_form_pdf(tmp_path / "f.pdf"))
    dlg = FormDialog(doc)
    assert len(dlg.editors) == 4
    from PySide6.QtWidgets import QCheckBox

    for _pno, _xref, ed, _t in dlg.editors:
        if isinstance(ed, QCheckBox):
            ed.setChecked(True)
        else:
            ed.setText("Valeur")
    assert dlg.apply() == 4
    values = {w.field_name: w.field_value for w in doc[0].widgets()}
    assert values["nom"] == "Valeur" and values["accord"] not in ("Off", False)


def test_organizer(app, tmp_path):
    from pdf_builder.ui.pages.organizer import OrganizerPage

    org = OrganizerPage()
    a = make_text_pdf(tmp_path / "a.pdf", pages=3)
    b = make_text_pdf(tmp_path / "b.pdf", pages=2)
    org.add_files([str(a), str(b)])
    assert org.grid.count() == 5
    org.grid.item(0).setSelected(True)
    org.rotate(90)
    org.grid.clearSelection()
    org.grid.item(4).setSelected(True)
    org.delete()
    assert org.grid.count() == 4
    org.reverse()
    org.insert_blank()
    org.undo()
    assert org.grid.count() == 4
    out = org.build()
    assert out.page_count == 4
    assert out[-1].rotation == 90  # 1re page pivotée, désormais en dernière position
    org.interleave()
    assert org.grid.count() == 4


def test_home_suggestions(app, tmp_path):
    from pdf_builder.ui.pages.home import suggest

    pdf = make_text_pdf(tmp_path / "x.pdf", pages=2)
    ids = [s[0] for s in suggest([str(pdf)])]
    assert "@editor" in ids and "to_word" in ids
    ids2 = [s[0] for s in suggest([str(pdf), str(pdf)])]
    assert ids2[0] == "merge" and "@compare" in ids2
    assert suggest(["a.png", "b.jpg"])[0][0] == "images_to_pdf"


def test_palette_scoring():
    from pdf_builder.ui.command_palette import score

    assert score("fusion", "🧩 Fusionner") > 0
    assert score("compr", "Compresser") > score("compr", "Comparer deux PDF")
    assert score("pdf word", "PDF → Word") > 0
    assert score("zzz", "Fusionner") == 0


def test_job_manager_runs_in_worker_process(app, tmp_path):
    from pdf_builder.ui.jobs import JobManager

    src = make_text_pdf(tmp_path / "w.pdf", pages=2)
    jm = JobManager()
    try:
        got = {}
        job = jm.submit({"kind": "tool", "tool": "page_numbers", "inputs": [str(src)], "params": {}, "out_dir": str(tmp_path / "o")}, "test")
        job.finished.connect(lambda outs, reps: got.setdefault("outs", outs))
        job.failed.connect(lambda m, t: got.setdefault("err", m))
        t0 = time.time()
        while not got and time.time() - t0 < 60:
            pump(50)
        assert "outs" in got, got
        assert fitz.open(got["outs"][0]).page_count == 2

        # Annulation : la tâche est interrompue et le processus relancé.
        big = [str(src)] * 30
        job2 = jm.submit({"kind": "tool", "tool": "to_images", "inputs": big, "params": {"dpi": 300}, "out_dir": str(tmp_path / "o2")}, "long")
        cancelled = []
        job2.cancelled.connect(lambda: cancelled.append(True))
        pump(300)
        jm.cancel(job2)
        assert cancelled and job2.state == "cancelled"
        got.clear()
        job3 = jm.submit({"kind": "call", "func": "pdf_builder.core.jobs:analyze_job", "kwargs": {"path": str(src)}}, "analyse")
        job3.result.connect(lambda v: got.setdefault("res", v))
        t0 = time.time()
        while not got and time.time() - t0 < 60:
            pump(50)
        assert "Pages : 2" in got["res"]
    finally:
        jm.shutdown()


def test_main_window_navigation(app, tmp_path):
    from pdf_builder.ui.main_window import NAV, MainWindow

    w = MainWindow()
    try:
        for key, _ in NAV:
            w.show_page(key)
            assert w.stack.currentWidget() is w.pages[key]
        w.open_tool("merge", [str(make_text_pdf(tmp_path / "m.pdf", pages=1))])
        assert w.stack.currentWidget() is w.tool_page
        assert w.tool_page.files.files()
        w.set_theme("dark")
        w.set_theme("light")
    finally:
        w.jobs.shutdown()


def _wait(cond, timeout=60):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        pump(50)
    return cond()


def test_compare_search_automation_pages(app, tmp_path):
    from PySide6.QtCore import QPointF

    from pdf_builder.ui.jobs import JobManager
    from pdf_builder.ui.pages.automation import AutomationPage
    from pdf_builder.ui.pages.compare import ComparePage
    from pdf_builder.ui.pages.search import SearchPage

    jm = JobManager()
    try:
        a = make_text_pdf(tmp_path / "v1.pdf", pages=2)
        with fitz.open(a) as d:
            d[1].insert_text((72, 700), "Nouvelle clause importante", fontsize=11)
            d.save(tmp_path / "v2.pdf")
        cmp = ComparePage(jm)
        cmp.set_files([str(a), str(tmp_path / "v2.pdf")])
        cmp.run()
        assert _wait(lambda: cmp.report is not None)
        assert cmp.changes.count() >= 1 and cmp.view.doc.page_count == 3

        search = SearchPage(jm)
        search.folder.setText(str(tmp_path))
        search.query.setText("clause")
        search.run()
        assert _wait(lambda: search.tree.topLevelItemCount() > 0)
        assert "v2.pdf" in search.tree.topLevelItem(0).text(0)

        auto = AutomationPage(jm)
        auto.recipe_list.setCurrentRow(0)  # Préparer pour l'e-mail
        auto.set_files([str(a)])
        auto.out_folder.setText(str(tmp_path / "auto"))
        auto.run_recipe()
        assert _wait(lambda: bool(auto.result.outputs))
        assert auto.result.outputs[0].endswith("v1_traité.pdf")

        # Dossier surveillé
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        auto.watch_in.setText(str(inbox))
        auto.watch_out.setText(str(tmp_path / "sortie"))
        auto.toggle_watch()
        make_text_pdf(inbox / "scan.pdf", pages=1)
        assert _wait(lambda: (tmp_path / "sortie" / "scan.pdf").exists(), 30)
        assert _wait(lambda: (inbox / "originaux" / "scan.pdf").exists(), 10)
        auto.toggle_watch()
    finally:
        jm.shutdown()

    from pdf_builder.ui.dialogs import SignaturePad

    pad = SignaturePad()
    pad.strokes = [[QPointF(10, 10), QPointF(60, 40), QPointF(120, 15)]]
    out = tmp_path / "sig.png"
    assert pad.to_png(out) and out.stat().st_size > 100


def test_edit_text_on_rotated_page(editor, monkeypatch):
    from pdf_builder.ui import dialogs

    editor.rotate_page()
    page = editor.doc[0]
    rect = page.search_for("Section 1.1")[0] * page.rotation_matrix  # repère visuel
    monkeypatch.setattr(dialogs.TextDialog, "exec", lambda self: True)
    monkeypatch.setattr(dialogs.TextDialog, "values", lambda self: {"text": "Titre pivoté", "font": "helv", "size": 15, "color": "#000000"})
    editor.current_tool = "edit_text"
    editor._on_point(0, fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2))
    assert "Titre pivoté" in editor.doc[0].get_text()
    editor.current_tool = "highlight"
    editor._on_rect(0, rect + (-2, -2, 2, 2))
    page = editor.doc[0]
    annot = next(page.annots())
    assert annot.rect.intersects(page.search_for("Titre")[0])


def test_editor_create_form_fields(editor, monkeypatch):
    monkeypatch.setattr("pdf_builder.ui.pages.editor.QInputDialog.getText", lambda *a, **k: ("client", True))
    editor.current_tool = "field_text"
    editor._on_rect(0, fitz.Rect(100, 600, 300, 625))
    monkeypatch.setattr("pdf_builder.ui.pages.editor.QInputDialog.getText", lambda *a, **k: ("accepte", True))
    editor.current_tool = "field_check"
    editor._on_rect(0, fitz.Rect(100, 650, 120, 670))
    page = editor.doc[0]
    names = {w.field_name: w.field_type for w in page.widgets()}
    assert names == {"client": fitz.PDF_WIDGET_TYPE_TEXT, "accepte": fitz.PDF_WIDGET_TYPE_CHECKBOX}
