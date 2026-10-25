"""Visionneuse PDF à défilement continu, rendu progressif et outils de saisie.

Les coordonnées de scène sont exprimées en *points PDF du repère visuel* :
chaque page est un élément placé verticalement, le zoom est une simple
transformation de la vue. Les pages sont rendues à la demande (seulement les
pages visibles) à la résolution exacte de l'écran.
"""

from __future__ import annotations

import pymupdf as fitz
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from .theme import color
from .widgets import pixmap_from_page

GAP = 18.0


class PageItem(QGraphicsRectItem):
    def __init__(self, index: int, w: float, h: float):
        super().__init__(0, 0, w, h)
        self.index = index
        self.setBrush(QBrush(QColor("white")))
        self.setPen(QPen(Qt.NoPen))
        self.pix = QGraphicsPixmapItem(self)
        self.pix.setTransformationMode(Qt.SmoothTransformation)
        self.rendered_zoom = 0.0
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.setGraphicsEffect(shadow)


class PdfView(QGraphicsView):
    pageChanged = Signal(int)
    zoomChanged = Signal(float)
    rectSelected = Signal(int, object)  # index, fitz.Rect (repère visuel)
    pointClicked = Signal(int, object)  # index, fitz.Point (repère visuel)
    pathDrawn = Signal(int, list)  # index, [fitz.Point]
    lineDrawn = Signal(int, object, object)
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setAcceptDrops(True)
        self.doc: fitz.Document | None = None
        self.items: list[PageItem] = []
        self.zoom = 1.0
        self.night = False
        self.mode = "pan"  # pan, rect, point, path, line
        self.draw_color = QColor("#4F46E5")
        self._drag_start: QPointF | None = None
        self._drag_page = -1
        self._temp_item = None
        self._path_pts: list[QPointF] = []
        self._search_items: list[QGraphicsRectItem] = []
        self._current_page = 0
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(15)
        self._render_timer.timeout.connect(self._render_visible)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.horizontalScrollBar().valueChanged.connect(lambda *_: self._render_timer.start())
        self.set_mode("pan")
        self._apply_bg()

    def _apply_bg(self):
        self.setBackgroundBrush(QBrush(color("viewer_bg")))

    # ------------------------------------------------------------------ document
    def set_document(self, doc: fitz.Document | None, keep_position: bool = False):
        pos = (self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        cur = self._current_page
        self.doc = doc
        self.clear_search()
        self.scene().clear()
        self.items = []
        self._temp_item = None
        if doc is None:
            return
        y = GAP
        widths = [doc[i].rect.width for i in range(doc.page_count)] or [600]
        max_w = max(widths)
        for i in range(doc.page_count):
            r = doc[i].rect
            item = PageItem(i, r.width, r.height)
            item.setPos((max_w - r.width) / 2 + GAP, y)
            self.scene().addItem(item)
            self.items.append(item)
            y += r.height + GAP
        self.scene().setSceneRect(QRectF(0, 0, max_w + 2 * GAP, y))
        if keep_position:
            self.horizontalScrollBar().setValue(pos[0])
            self.verticalScrollBar().setValue(pos[1])
            self._current_page = min(cur, doc.page_count - 1)
        else:
            self._current_page = 0
            self.verticalScrollBar().setValue(0)
        self._render_timer.start()

    def refresh_page(self, index: int):
        if 0 <= index < len(self.items):
            self.items[index].rendered_zoom = 0
            self._render_timer.start()

    def refresh_all(self):
        for it in self.items:
            it.rendered_zoom = 0
        self._render_timer.start()

    def set_night(self, on: bool):
        self.night = on
        for it in self.items:
            it.setBrush(QBrush(QColor("#111") if on else QColor("white")))
        self.refresh_all()

    def _visible_items(self) -> list[PageItem]:
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        rect.adjust(0, -rect.height() * 0.5, 0, rect.height() * 0.5)
        return [it for it in self.items if it.sceneBoundingRect().intersects(rect)]

    def _render_visible(self):
        if not self.doc:
            return
        dpr = self.devicePixelRatioF()
        visible = self._visible_items()
        budget = 3
        for it in visible:
            if abs(it.rendered_zoom - self.zoom) < 1e-3:
                continue
            page = self.doc[it.index]
            z = min(self.zoom, 6.0)
            it.pix.setPixmap(pixmap_from_page(page, z, dpr, self.night))
            it.pix.setScale(1 / z)
            it.rendered_zoom = self.zoom
            budget -= 1
            if budget == 0:
                self._render_timer.start()
                break
        # Libère la mémoire des pages éloignées.
        keep = {it.index for it in visible}
        for it in self.items:
            if it.rendered_zoom and it.index not in keep and abs(it.index - self._current_page) > 6:
                it.pix.setPixmap(QPixmap())
                it.rendered_zoom = 0

    # ------------------------------------------------------------------ navigation
    def _on_scroll(self, *_):
        self._render_timer.start()
        if not self.items:
            return
        top = self.mapToScene(0, int(self.viewport().height() * 0.3))
        idx = self._current_page
        for it in self.items:
            r = it.sceneBoundingRect()
            if r.top() - GAP <= top.y() <= r.bottom() + GAP / 2:
                idx = it.index
                break
        if idx != self._current_page:
            self._current_page = idx
            self.pageChanged.emit(idx)

    def current_page(self) -> int:
        return self._current_page

    def go_to_page(self, index: int, y_point: float | None = None):
        if not self.items:
            return
        index = max(0, min(index, len(self.items) - 1))
        it = self.items[index]
        target = it.sceneBoundingRect().top() - GAP / 2 + (y_point or 0)
        self.verticalScrollBar().setValue(int(self.mapFromScene(QPointF(0, target)).y() + self.verticalScrollBar().value()))
        self._current_page = index
        self.pageChanged.emit(index)
        self._render_timer.start()

    def set_zoom(self, z: float, anchor_center: bool = True):
        z = max(0.1, min(z, 8.0))
        old_anchor = self.transformationAnchor()
        if anchor_center:
            self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.zoom = z
        self.setTransform(QTransform.fromScale(z, z))
        self.setTransformationAnchor(old_anchor)
        self.zoomChanged.emit(z)
        self._render_timer.start()

    def fit_width(self):
        if not self.items:
            return
        w = self.scene().sceneRect().width()
        self.set_zoom((self.viewport().width() - 8) / w)

    def fit_page(self):
        if not self.items:
            return
        it = self.items[self._current_page]
        r = it.rect()
        z = min((self.viewport().width() - 8) / (r.width() + 2 * GAP), (self.viewport().height() - 8) / (r.height() + 2 * GAP))
        self.set_zoom(z)
        self.go_to_page(self._current_page)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self.zoom * factor, anchor_center=False)
            e.accept()
            return
        super().wheelEvent(e)

    # ------------------------------------------------------------------ outils
    def set_mode(self, mode: str):
        self.mode = mode
        if mode == "pan":
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.CrossCursor if mode in ("rect", "path", "line") else Qt.PointingHandCursor)

    def page_at(self, scene_pt: QPointF) -> tuple[int, fitz.Point] | None:
        for it in self.items:
            if it.sceneBoundingRect().contains(scene_pt):
                local = scene_pt - it.pos()
                return it.index, fitz.Point(local.x(), local.y())
        return None

    def _clamp_to_page(self, index: int, scene_pt: QPointF) -> fitz.Point:
        it = self.items[index]
        local = scene_pt - it.pos()
        r = it.rect()
        return fitz.Point(min(max(local.x(), 0), r.width()), min(max(local.y(), 0), r.height()))

    def mousePressEvent(self, e):
        if self.mode == "pan" or e.button() != Qt.LeftButton or not self.doc:
            return super().mousePressEvent(e)
        sp = self.mapToScene(e.position().toPoint())
        hit = self.page_at(sp)
        if not hit:
            return
        index, pt = hit
        if self.mode == "point":
            self.pointClicked.emit(index, pt)
            return
        self._drag_start = sp
        self._drag_page = index
        pen = QPen(self.draw_color, 1.5 / self.zoom)
        if self.mode == "rect":
            self._temp_item = self.scene().addRect(QRectF(sp, sp), pen, QBrush(QColor(self.draw_color.red(), self.draw_color.green(), self.draw_color.blue(), 40)))
        elif self.mode in ("path", "line"):
            self._path_pts = [sp]
            path = QPainterPath(sp)
            pen.setWidthF(2 / self.zoom)
            self._temp_item = QGraphicsPathItem(path)
            self._temp_item.setPen(pen)
            self.scene().addItem(self._temp_item)

    def mouseMoveEvent(self, e):
        if self._drag_start is None or self._temp_item is None:
            return super().mouseMoveEvent(e)
        sp = self.mapToScene(e.position().toPoint())
        it = self.items[self._drag_page]
        bounds = it.sceneBoundingRect()
        sp = QPointF(min(max(sp.x(), bounds.left()), bounds.right()), min(max(sp.y(), bounds.top()), bounds.bottom()))
        if self.mode == "rect":
            self._temp_item.setRect(QRectF(self._drag_start, sp).normalized())
        elif self.mode == "path":
            self._path_pts.append(sp)
            path = self._temp_item.path()
            path.lineTo(sp)
            self._temp_item.setPath(path)
        elif self.mode == "line":
            path = QPainterPath(self._drag_start)
            path.lineTo(sp)
            self._temp_item.setPath(path)
            self._path_pts = [self._drag_start, sp]

    def mouseReleaseEvent(self, e):
        if self._drag_start is None:
            return super().mouseReleaseEvent(e)
        sp = self.mapToScene(e.position().toPoint())
        index = self._drag_page
        start = self._clamp_to_page(index, self._drag_start)
        end = self._clamp_to_page(index, sp)
        if self._temp_item is not None:
            self.scene().removeItem(self._temp_item)
            self._temp_item = None
        self._drag_start = None
        if self.mode == "rect":
            r = fitz.Rect(start, end).normalize()
            if r.width < 4 and r.height < 4:
                self.pointClicked.emit(index, start)
            else:
                self.rectSelected.emit(index, r)
        elif self.mode == "path":
            pts = [self._clamp_to_page(index, p) for p in self._path_pts]
            if len(pts) > 1:
                self.pathDrawn.emit(index, pts)
        elif self.mode == "line":
            if abs(end.x - start.x) + abs(end.y - start.y) > 4:
                self.lineDrawn.emit(index, start, end)
        self._path_pts = []

    # ------------------------------------------------------------------ recherche
    def show_search(self, hits: list[tuple[int, fitz.Rect]], current: int = -1):
        self.clear_search()
        for k, (pno, r) in enumerate(hits):
            if pno >= len(self.items):
                continue
            it = self.items[pno]
            col = QColor(255, 140, 0, 120) if k == current else QColor(255, 220, 0, 90)
            rect_item = QGraphicsRectItem(QRectF(r.x0, r.y0, r.width, r.height), it)
            rect_item.setBrush(QBrush(col))
            rect_item.setPen(QPen(Qt.NoPen))
            rect_item.setFlag(QGraphicsItem.ItemStacksBehindParent, False)
            self._search_items.append(rect_item)

    def clear_search(self):
        for it in self._search_items:
            if it.scene():
                it.scene().removeItem(it)
        self._search_items = []

    # ------------------------------------------------------------------ glisser-déposer
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.filesDropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        else:
            super().dropEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._render_timer.start()
