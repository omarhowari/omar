"""Page view: renders PDF pages with lazy rendering and handles all mouse tools.

All geometry sent out of this widget is in *unrotated PDF page space* (the space PyMuPDF uses for
annotations, text extraction and search results).
"""
import math

import pymupdf as fitz
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, Signal, QLineF
from PySide6.QtGui import (QImage, QPixmap, QColor, QPen, QBrush, QPainterPath, QPainter, QCursor,
                           QGuiApplication)
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsPixmapItem,
                               QGraphicsLineItem, QGraphicsPathItem, QGraphicsDropShadowEffect, QGraphicsItem)

GAP = 14
BASE = 96 / 72  # 100 % zoom = physical size on a 96-dpi screen

RECT_TOOLS = {"snapshot", "rect", "oval", "textbox", "redact", "whiteout", "addtext", "addimage",
              "stamp", "link", "signature", "field_text", "field_check", "field_radio", "field_combo",
              "field_list", "field_sign", "area_highlight", "digital_sign", "crop_area"}
RECT_TOOLS |= {"zoom_tool", "field_button", "field_date", "field_image", "field_signature", "cloud"}
LINE_TOOLS = {"line", "arrow", "measure", "callout"}
POINT_TOOLS = {"note", "attach", "edittext", "insert_text", "eraser"}
TEXT_TOOLS = {"highlight", "underline", "strike", "squiggly", "replace_text"}
POLY_TOOLS = {"polygon", "polyline", "area_measure", "perimeter"}
TEXT_FLAGS = fitz.TEXT_DEHYPHENATE | fitz.TEXT_MEDIABOX_CLIP | fitz.TEXT_PRESERVE_WHITESPACE
MOVABLE = {"Square", "Circle", "FreeText", "Text", "Stamp", "FileAttachment", "Ink", "Line", "Polygon",
           "PolyLine", "Redact"}


class PageView(QGraphicsView):
    pageChanged = Signal(int)
    zoomChanged = Signal(float)
    toolAction = Signal(str, int, object)       # tool, page, payload
    annotSelected = Signal(int, int)            # page, xref (-1 = none)
    widgetClicked = Signal(int, int)            # page, widget xref
    linkClicked = Signal(object)                # link dict
    textSelectionChanged = Signal(str)
    contextMenu = Signal(int, object, object)   # page, unrot point, global pos
    filesDropped = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#C9D0DA"))
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setLayoutDirection(Qt.LeftToRight)
        self.pdf = None
        self.zoom = 1.0
        self.fit_mode = "width"   # 'width' | 'page' | None
        self.layout_mode = "continuous"
        self.night = False
        self.show_annots = True
        self.tool = "select"
        self.current = 0
        self.page_rects = []      # scene rect per page (None when hidden)
        self.items = {}           # page -> (frame, pixmap item)
        self.rendered = {}        # page -> zoom rendered at
        self.words_cache = {}
        self.overlays = []
        self.search_hits = {}     # page -> [Rect]
        self.search_current = None
        self.sel_words = None     # (page, [rects], text)
        self.sel_annot = None     # (page, xref)
        self._drag = None
        self._poly = None
        self.show_rulers = False
        self.show_grid = False
        self.view_rotation = 0
        self.hand_text = True
        self._loupe = None
        self._render_timer = QTimer(self, singleShot=True, interval=30, timeout=self._render_visible)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda *_: self._render_timer.start())

    # ------------------------------------------------------------------ document
    def set_document(self, pdf):
        self.pdf = pdf
        self.current = 0
        self.relayout()

    @property
    def doc(self):
        return self.pdf.doc

    def scale(self):
        return self.zoom * BASE

    def invalidate(self, page=-1):
        if page < 0:
            self.words_cache.clear()
            self.rendered.clear()
            self.sel_annot = None
            self.relayout()
        else:
            self.words_cache.pop(page, None)
            self.rendered.pop(page, None)
            self._render_timer.start()
            self._draw_overlays()

    def _visible_pages(self):
        n = self.doc.page_count
        if self.layout_mode == "single":
            return [min(self.current, n - 1)]
        if self.layout_mode == "single2":
            a = self.current - (self.current % 2)
            return [p for p in (a, a + 1) if p < n]
        return list(range(n))

    def relayout(self, keep_page=True):
        sc = self.scene()
        sc.clear()
        self.items.clear()
        self.rendered.clear()
        self.overlays = []
        if not self.pdf or self.doc.page_count == 0:
            self.page_rects = []
            return
        n = self.doc.page_count
        self.current = min(self.current, n - 1)
        self._apply_fit()
        s = self.scale()
        sizes = [(self.doc[i].rect.width * s, self.doc[i].rect.height * s) for i in range(n)]
        self.page_rects = [None] * n
        vis = self._visible_pages()
        y = GAP
        if self.layout_mode in ("two", "single2"):
            maxw = max(w for w, h in sizes)
            for row in range(0, n, 2):
                pair = [p for p in (row, row + 1) if p < n and p in vis]
                if not pair:
                    continue
                hrow = max(sizes[p][1] for p in pair)
                for k, p in enumerate(pair):
                    w, h = sizes[p]
                    x = (maxw + GAP / 2 - w) if k == 0 else (maxw + GAP * 1.5)
                    self.page_rects[p] = QRectF(x, y, w, h)
                y += hrow + GAP
            total_w = maxw * 2 + GAP * 2
        else:
            maxw = max(sizes[p][0] for p in vis)
            for p in vis:
                w, h = sizes[p]
                self.page_rects[p] = QRectF((maxw - w) / 2 + GAP, y, w, h)
                y += h + GAP
            total_w = maxw + GAP * 2
        for p, r in enumerate(self.page_rects):
            if r is None:
                continue
            frame = QGraphicsRectItem(r)
            frame.setBrush(QBrush(QColor("#1E1E1E" if self.night else "#FFFFFF")))
            frame.setPen(QPen(Qt.NoPen))
            eff = QGraphicsDropShadowEffect()
            eff.setBlurRadius(14)
            eff.setOffset(0, 2)
            eff.setColor(QColor(15, 23, 42, 90))
            frame.setGraphicsEffect(eff)
            sc.addItem(frame)
            pix = QGraphicsPixmapItem()
            pix.setPos(r.topLeft())
            pix.setTransformationMode(Qt.SmoothTransformation)
            sc.addItem(pix)
            self.items[p] = (frame, pix)
        sc.setSceneRect(0, 0, total_w, y)
        self._render_timer.start()
        self._draw_overlays()
        if keep_page:
            QTimer.singleShot(0, lambda: self.go_to(self.current, emit=False))

    def _apply_fit(self):
        if not self.fit_mode or not self.pdf or self.doc.page_count == 0:
            return
        p = self.doc[min(self.current, self.doc.page_count - 1)]
        sbw = 0 if self.verticalScrollBar().isVisible() else self.style().pixelMetric(
            self.style().PixelMetric.PM_ScrollBarExtent)
        vw = max(200, self.viewport().width() - sbw - GAP * 2 - 4)
        vh = max(200, self.viewport().height() - GAP * 2)
        cols = 2 if self.layout_mode in ("two", "single2") else 1
        zw = (vw - (GAP if cols == 2 else 0)) / (p.rect.width * BASE * cols)
        zh = vh / (p.rect.height * BASE)
        z = zw if self.fit_mode == "width" else min(zw, zh)
        z = max(0.1, min(z, 8.0))
        if abs(z - self.zoom) > 1e-3:
            self.zoom = z
            self.zoomChanged.emit(z)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode and self.pdf:
            old = self.zoom
            self._apply_fit()
            if abs(old - self.zoom) > 1e-3:
                self.relayout()
        self._render_timer.start()

    # ------------------------------------------------------------------ rendering
    def _render_visible(self):
        if not self.pdf:
            return
        vr = self.mapToScene(self.viewport().rect()).boundingRect().adjusted(0, -400, 0, 400)
        s = self.scale()
        dpr = self.devicePixelRatioF()
        keep = set()
        for p, r in enumerate(self.page_rects):
            if r is None or p not in self.items:
                continue
            if not r.intersects(vr):
                continue
            keep.add(p)
            if self.rendered.get(p) == (s, self.night, self.show_annots):
                continue
            page = self.doc[p]
            m = fitz.Matrix(s * dpr, s * dpr)
            try:
                pm = page.get_pixmap(matrix=m, alpha=False, annots=self.show_annots)
            except Exception:
                continue
            if self.night:
                pm.invert_irect(pm.irect)
            img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
            qp = QPixmap.fromImage(img)
            qp.setDevicePixelRatio(dpr)
            self.items[p][1].setPixmap(qp)
            self.rendered[p] = (s, self.night, self.show_annots)
        # free memory of far-away pages
        for p in list(self.rendered):
            if p not in keep and len(self.rendered) > 24:
                self.items[p][1].setPixmap(QPixmap())
                del self.rendered[p]

    # ------------------------------------------------------------------ navigation / zoom
    def _scrolled(self, *_):
        self._render_timer.start()
        if not self.page_rects or self.layout_mode in ("single", "single2"):
            return
        c = self.mapToScene(self.viewport().rect().center() - self.viewport().rect().center() / 2)
        best = self.current
        for p, r in enumerate(self.page_rects):
            if r is not None and r.top() - GAP <= c.y() <= r.bottom() + GAP:
                best = p
                break
        if best != self.current:
            self.current = best
            self.pageChanged.emit(best)

    def go_to(self, page, emit=True, y_offset=None):
        if not self.pdf or self.doc.page_count == 0:
            return
        page = max(0, min(page, self.doc.page_count - 1))
        if emit and page != self.current and not getattr(self, "_nav", False):
            self.hist = getattr(self, "hist", [])[:getattr(self, "hpos", 0) + 1] if getattr(self, "hist", None) else [self.current]
            if not self.hist or self.hist[-1] != self.current:
                self.hist.append(self.current)
            self.hist.append(page)
            self.hpos = len(self.hist) - 1
        need_relayout = self.layout_mode in ("single", "single2") and (self.page_rects[page] is None)
        self.current = page
        if need_relayout:
            self.relayout(keep_page=False)
        r = self.page_rects[page]
        if r is not None:
            y = r.top() - GAP / 2 + (y_offset * self.scale() if y_offset is not None else 0)
            self.verticalScrollBar().setValue(int(self.mapFromScene(QPointF(0, y)).y() + self.verticalScrollBar().value()))
        if emit:
            self.pageChanged.emit(page)
        self._render_timer.start()

    def nav(self, d):
        hist = getattr(self, "hist", [])
        pos = getattr(self, "hpos", len(hist) - 1) + d
        if 0 <= pos < len(hist):
            self.hpos = pos
            self._nav = True
            self.go_to(hist[pos])
            self._nav = False

    def go_to_rect(self, page, rect):
        self.go_to(page)
        r = self.unrot_to_scene_rect(page, fitz.Rect(rect))
        self.centerOn(r.center())

    def set_zoom(self, z, anchor=None):
        z = max(0.1, min(z, 8.0))
        self.fit_mode = None
        if abs(z - self.zoom) < 1e-4:
            return
        page, cur = self.current, None
        if anchor is not None:
            cur = self.scene_to_unrot(self.mapToScene(anchor))
        self.zoom = z
        self.relayout(keep_page=False)
        if cur and cur[0] is not None:
            sp = self.unrot_to_scene(cur[0], cur[1])
            target = self.mapFromScene(sp)
            dx, dy = target.x() - anchor.x(), target.y() - anchor.y()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + int(dx))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + int(dy))
        else:
            self.go_to(page, emit=False)
        self.zoomChanged.emit(z)

    def set_fit(self, mode):
        self.fit_mode = mode
        self._apply_fit()
        self.relayout()
        self.zoomChanged.emit(self.zoom)

    def set_layout(self, mode):
        self.layout_mode = mode
        self.relayout()

    def set_night(self, on):
        self.night = on
        self.relayout()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self.zoom * f, anchor=e.position().toPoint())
            return
        if self.layout_mode in ("single", "single2"):
            sb = self.verticalScrollBar()
            step = 2 if self.layout_mode == "single2" else 1
            if e.angleDelta().y() < 0 and sb.value() >= sb.maximum():
                self.go_to(self.current + step)
                return
            if e.angleDelta().y() > 0 and sb.value() <= sb.minimum() and self.current > 0:
                self.go_to(self.current - step)
                self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
                return
        super().wheelEvent(e)

    # ------------------------------------------------------------------ coordinates
    def page_at(self, sp):
        for p, r in enumerate(self.page_rects):
            if r is not None and r.contains(sp):
                return p
        return None

    def scene_to_unrot(self, sp, page=None):
        p = self.page_at(sp) if page is None else page
        if p is None:
            return None, None
        r = self.page_rects[p]
        s = self.scale()
        vis = fitz.Point((sp.x() - r.left()) / s, (sp.y() - r.top()) / s)
        return p, vis * self.doc[p].derotation_matrix

    def unrot_to_scene(self, page, pt):
        r = self.page_rects[page]
        v = fitz.Point(pt) * self.doc[page].rotation_matrix
        s = self.scale()
        return QPointF(r.left() + v.x * s, r.top() + v.y * s)

    def unrot_to_scene_rect(self, page, rect):
        rr = fitz.Rect(rect) * self.doc[page].rotation_matrix
        r = self.page_rects[page]
        s = self.scale()
        return QRectF(r.left() + rr.x0 * s, r.top() + rr.y0 * s, rr.width * s, rr.height * s)

    def _clamp_to_page(self, page, sp):
        r = self.page_rects[page]
        return QPointF(min(max(sp.x(), r.left()), r.right()), min(max(sp.y(), r.top()), r.bottom()))

    # ------------------------------------------------------------------ overlays
    def _clear_overlays(self):
        for it in self.overlays:
            if it.scene():
                self.scene().removeItem(it)
        self.overlays = []

    def _add_overlay(self, item):
        item.setZValue(10)
        self.scene().addItem(item)
        self.overlays.append(item)

    def _draw_overlays(self):
        self._clear_overlays()
        if not self.pdf:
            return
        for p, rects in self.search_hits.items():
            if p >= len(self.page_rects) or self.page_rects[p] is None:
                continue
            for k, r in enumerate(rects):
                it = QGraphicsRectItem(self.unrot_to_scene_rect(p, r))
                cur = self.search_current == (p, k)
                it.setBrush(QColor(249, 115, 22, 110) if cur else QColor(250, 204, 21, 90))
                it.setPen(QPen(QColor("#EA580C") if cur else Qt.NoPen))
                self._add_overlay(it)
        if self.sel_words and self.page_rects[self.sel_words[0]] is not None:
            p = self.sel_words[0]
            for r in self.sel_words[1]:
                it = QGraphicsRectItem(self.unrot_to_scene_rect(p, r))
                it.setBrush(QColor(37, 99, 235, 70))
                it.setPen(QPen(Qt.NoPen))
                self._add_overlay(it)
        if self.sel_annot:
            p, xref = self.sel_annot
            a = self._annot(p, xref)
            if a is not None and self.page_rects[p] is not None:
                it = QGraphicsRectItem(self.unrot_to_scene_rect(p, a.rect).adjusted(-3, -3, 3, 3))
                pen = QPen(QColor("#2563EB"), 1.5, Qt.DashLine)
                it.setPen(pen)
                self._add_overlay(it)

    def _annot(self, page, xref):
        try:
            from .ops import load_annot
            return load_annot(self.doc, page, xref)
        except Exception:
            return None

    def set_search_hits(self, hits, current=None):
        self.search_hits = hits
        self.search_current = current
        self._draw_overlays()

    def select_annot(self, page, xref):
        self.sel_annot = (page, xref) if xref is not None and xref >= 0 else None
        self._draw_overlays()

    def clear_selection(self):
        self.sel_words = None
        self.sel_annot = None
        self._draw_overlays()

    # ------------------------------------------------------------------ tools
    def set_tool(self, tool):
        self.tool = tool
        self._poly = None
        self._cancel_drag()
        if tool == "hand":
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            if tool == "select":
                self.viewport().setCursor(Qt.ArrowCursor)
            elif tool in ("zoom_tool", "loupe"):
                self.viewport().setCursor(Qt.CrossCursor)
            elif tool in TEXT_TOOLS or tool in ("edittext", "insert_text"):
                self.viewport().setCursor(Qt.IBeamCursor)
            else:
                self.viewport().setCursor(Qt.CrossCursor)

    def _cancel_drag(self):
        if self._drag and self._drag.get("item") is not None and self._drag["item"].scene():
            self.scene().removeItem(self._drag["item"])
        self._drag = None

    def _words(self, page):
        if page not in self.words_cache:
            self.words_cache[page] = self.doc[page].get_text("words", sort=False, flags=TEXT_FLAGS)
        return self.words_cache[page]

    def _word_index_at(self, page, pt, nearest=True):
        words = self._words(page)
        best, bd = None, 1e9
        for i, w in enumerate(words):
            r = fitz.Rect(w[:4])
            if r.contains(pt):
                return i
            if nearest:
                dx = max(r.x0 - pt.x, 0, pt.x - r.x1)
                dy = max(r.y0 - pt.y, 0, pt.y - r.y1)
                d = dx * dx + dy * dy * 4
                if d < bd:
                    bd, best = d, i
        return best if (best is not None and bd < 60 * 60) else None

    def _selection_between(self, page, a, b):
        words = self._words(page)
        if not words:
            return [], ""
        i = self._word_index_at(page, a)
        j = self._word_index_at(page, b)
        if i is None or j is None:
            return [], ""
        if i > j:
            i, j = j, i
        lines = {}
        order = []
        texts = []
        last_key = None
        for w in words[i:j + 1]:
            key = (w[5], w[6])
            if key not in lines:
                lines[key] = fitz.Rect(w[:4])
                order.append(key)
            else:
                lines[key] |= fitz.Rect(w[:4])
            if last_key is not None and key != last_key:
                texts.append("\n")
            elif texts:
                texts.append(" ")
            texts.append(w[4])
            last_key = key
        return [lines[k] for k in order], "".join(texts)

    def selected_text(self):
        return self.sel_words[2] if self.sel_words else ""

    def select_all_text(self):
        p = self.current
        words = self._words(p)
        if not words:
            return
        rects, text = self._selection_between(p, fitz.Point(words[0][:2]), fitz.Point(words[-1][2:4]))
        self.sel_words = (p, rects, text)
        self._draw_overlays()
        self.textSelectionChanged.emit(text)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            sp = self.mapToScene(e.position().toPoint())
            p, pt = self.scene_to_unrot(sp)
            if p is not None:
                self.contextMenu.emit(p, pt, e.globalPosition().toPoint())
            return
        if e.button() == Qt.LeftButton and self.tool == "hand" and self.pdf and self.hand_text:
            sp = self.mapToScene(e.position().toPoint())
            p, pt = self.scene_to_unrot(sp)
            if p is not None and self._words(p) and self._word_index_at(p, pt, nearest=False) is not None:
                self.setDragMode(QGraphicsView.NoDrag)
                self._drag = dict(kind="text", page=p, start=sp, a=pt, item=None, hand=True)
                self.sel_words = None
                return
        if e.button() != Qt.LeftButton or self.tool in ("hand", "loupe") or not self.pdf:
            return super().mousePressEvent(e)
        sp = self.mapToScene(e.position().toPoint())
        p, pt = self.scene_to_unrot(sp)
        if p is None:
            if self.tool == "select":
                self.clear_selection()
                self.annotSelected.emit(-1, -1)
            return
        t = self.tool
        if t == "select":
            # existing selected annotation -> start move
            if self.sel_annot and self.sel_annot[0] == p:
                a = self._annot(p, self.sel_annot[1])
                if a is not None and a.rect.contains(pt) and a.type[1] in MOVABLE:
                    item = QGraphicsRectItem(self.unrot_to_scene_rect(p, a.rect))
                    item.setPen(QPen(QColor("#2563EB"), 1, Qt.DashLine))
                    item.setZValue(20)
                    self.scene().addItem(item)
                    self._drag = dict(kind="move", page=p, start=sp, item=item, xref=a.xref, orig=item.rect())
                    return
            # annotation hit-test (top-most last)
            hit = None
            pg = self.doc[p]
            for a in pg.annots():
                if a.rect.contains(pt) and a.type[1] not in ("Popup", "Link"):
                    hit = a.xref
            if hit is not None:
                self.sel_words = None
                self.sel_annot = (p, hit)
                self._draw_overlays()
                self.annotSelected.emit(p, hit)
                return
            for w in pg.widgets():
                if w.rect.contains(pt):
                    self.widgetClicked.emit(p, w.xref)
                    return
            for l in self.doc[p].get_links():
                if fitz.Rect(l["from"]).contains(pt):
                    self.linkClicked.emit(l)
                    return
            self.sel_annot = None
            self.annotSelected.emit(-1, -1)
            self._drag = dict(kind="text", page=p, start=sp, a=pt, item=None)
            self.sel_words = None
            self._draw_overlays()
            return
        if t in TEXT_TOOLS:
            self._drag = dict(kind="text", page=p, start=sp, a=pt, item=None)
            return
        if t in RECT_TOOLS:
            item = QGraphicsRectItem(QRectF(sp, sp))
            item.setPen(QPen(QColor("#2563EB"), 1.2, Qt.DashLine))
            item.setBrush(QColor(37, 99, 235, 30))
            item.setZValue(20)
            self.scene().addItem(item)
            self._drag = dict(kind="rect", page=p, start=sp, item=item)
            return
        if t in LINE_TOOLS:
            item = QGraphicsLineItem(QLineF(sp, sp))
            item.setPen(QPen(QColor("#DC2626"), 2))
            item.setZValue(20)
            self.scene().addItem(item)
            self._drag = dict(kind="line", page=p, start=sp, item=item)
            return
        if t == "ink":
            path = QPainterPath(sp)
            item = QGraphicsPathItem(path)
            item.setPen(QPen(QColor("#DC2626"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            item.setZValue(20)
            self.scene().addItem(item)
            self._drag = dict(kind="ink", page=p, start=sp, item=item, path=path, pts=[pt])
            return
        if t in POLY_TOOLS:
            if self._poly is None or self._poly["page"] != p:
                path = QPainterPath(sp)
                item = QGraphicsPathItem(path)
                item.setPen(QPen(QColor("#DC2626"), 2))
                item.setZValue(20)
                self.scene().addItem(item)
                self._poly = dict(page=p, pts=[pt], spts=[sp], item=item)
            else:
                self._poly["pts"].append(pt)
                self._poly["spts"].append(self._clamp_to_page(p, sp))
                self._update_poly()
            return
        if t in POINT_TOOLS:
            if t == "eraser":
                pg = self.doc[p]
                hit = None
                for a in pg.annots():
                    if a.type[1] in ("Ink", "Line", "PolyLine", "Polygon", "Square", "Circle") and a.rect.contains(pt):
                        hit = a.xref
                if hit is not None:
                    self.toolAction.emit("delete_annot", p, hit)
                return
            if t == "edittext":
                info = self._line_at(p, pt)
                if info:
                    self.toolAction.emit(t, p, info)
                return
            self.toolAction.emit(t, p, pt)
            return

    def _update_poly(self, extra=None):
        if not self._poly:
            return
        pts = self._poly["spts"] + ([extra] if extra is not None else [])
        path = QPainterPath(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        self._poly["item"].setPath(path)

    def _line_at(self, page, pt):
        d = self.doc[page].get_text("dict")
        for b in d["blocks"]:
            for ln in b.get("lines", []):
                if fitz.Rect(ln["bbox"]).contains(pt):
                    spans = ln["spans"]
                    text = "".join(s["text"] for s in spans)
                    s0 = max(spans, key=lambda s: len(s["text"]))
                    return dict(rect=tuple(ln["bbox"]), text=text, size=s0["size"], font=s0["font"],
                                color="#%06X" % s0["color"], bold=bool(s0["flags"] & 16),
                                italic=bool(s0["flags"] & 2), dir=ln.get("dir", (1, 0)))
        return None

    def _update_loupe(self, e):
        from PySide6.QtWidgets import QLabel
        if self._loupe is None:
            self._loupe = QLabel(self.viewport())
            self._loupe.setFixedSize(260, 170)
            self._loupe.setStyleSheet("border: 2px solid #4A5568; background: white;")
        sp = self.mapToScene(e.position().toPoint())
        p, pt = self.scene_to_unrot(sp)
        if p is None:
            self._loupe.hide()
            return
        z = self.scale() * 3
        w, h = 260 / z, 170 / z
        vp = pt * self.doc[p].rotation_matrix
        clip = fitz.Rect(vp.x - w / 2, vp.y - h / 2, vp.x + w / 2, vp.y + h / 2)
        pm = self.doc[p].get_pixmap(matrix=fitz.Matrix(z, z), clip=clip, alpha=False)
        img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
        self._loupe.setPixmap(QPixmap.fromImage(img))
        pos = e.position().toPoint()
        self._loupe.move(pos.x() + 18, pos.y() + 18)
        self._loupe.show()

    def mouseMoveEvent(self, e):
        if self.tool == "loupe" and self.pdf:
            self._update_loupe(e)
            return
        if self._loupe is not None and self._loupe.isVisible():
            self._loupe.hide()
        sp = self.mapToScene(e.position().toPoint())
        if self._poly is not None:
            self._update_poly(self._clamp_to_page(self._poly["page"], sp))
        if not self._drag:
            if self.tool == "select" and self.pdf:
                p, pt = self.scene_to_unrot(sp)
                cur = Qt.ArrowCursor
                if p is not None:
                    if self._words(p) and self._word_index_at(p, pt, nearest=False) is not None:
                        cur = Qt.IBeamCursor
                    for l in self.doc[p].get_links():
                        if fitz.Rect(l["from"]).contains(pt):
                            cur = Qt.PointingHandCursor
                    if self.sel_annot and self.sel_annot[0] == p:
                        a = self._annot(p, self.sel_annot[1])
                        if a is not None and a.rect.contains(pt):
                            cur = Qt.SizeAllCursor
                self.viewport().setCursor(cur)
            return super().mouseMoveEvent(e)
        d = self._drag
        p = d["page"]
        cp = self._clamp_to_page(p, sp)
        if d["kind"] == "rect":
            d["item"].setRect(QRectF(d["start"], cp).normalized())
        elif d["kind"] == "line":
            end = cp
            if e.modifiers() & Qt.ShiftModifier:
                dx, dy = cp.x() - d["start"].x(), cp.y() - d["start"].y()
                ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
                ln = math.hypot(dx, dy)
                end = QPointF(d["start"].x() + ln * math.cos(ang), d["start"].y() + ln * math.sin(ang))
            d["item"].setLine(QLineF(d["start"], end))
            d["end"] = end
        elif d["kind"] == "ink":
            d["path"].lineTo(cp)
            d["item"].setPath(d["path"])
            d["pts"].append(self.scene_to_unrot(cp, p)[1])
        elif d["kind"] == "text":
            _, b = self.scene_to_unrot(cp, p)
            rects, text = self._selection_between(p, d["a"], b)
            self.sel_words = (p, rects, text) if rects else None
            d["b"] = b
            self._draw_overlays()
        elif d["kind"] == "move":
            delta = sp - d["start"]
            d["item"].setRect(d["orig"].translated(delta))

    def mouseReleaseEvent(self, e):
        if not self._drag or e.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(e)
        d = self._drag
        self._drag = None
        p = d["page"]
        sp = self._clamp_to_page(p, self.mapToScene(e.position().toPoint()))
        if d.get("item") is not None and d["item"].scene():
            self.scene().removeItem(d["item"])
        t = self.tool
        if d.get("hand"):
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            if self.sel_words:
                self.textSelectionChanged.emit(self.sel_words[2])
            return
        if d["kind"] == "rect" and t == "zoom_tool":
            r = QRectF(d["start"], sp).normalized()
            if r.width() < 6 and r.height() < 6:
                f = 1 / 1.25 if e.modifiers() & Qt.ShiftModifier else 1.25
                self.set_zoom(self.zoom * f, anchor=e.position().toPoint())
            else:
                vw, vh = self.viewport().width(), self.viewport().height()
                f = min(vw / r.width(), vh / r.height()) * 0.95
                _, c = self.scene_to_unrot(r.center(), p)
                self.set_zoom(self.zoom * f)
                self.centerOn(self.unrot_to_scene(p, c))
            return
        if d["kind"] == "rect":
            r = QRectF(d["start"], sp).normalized()
            _, a = self.scene_to_unrot(r.topLeft(), p)
            _, b = self.scene_to_unrot(r.bottomRight(), p)
            ur = fitz.Rect(a, b).normalize()
            small = r.width() < 6 and r.height() < 6
            if small and t in ("addtext", "textbox", "stamp", "note", "signature", "addimage",
                               "field_text", "field_check", "field_radio", "field_combo", "field_list"):
                ur = None  # click without drag -> default-size box at that point
                self.toolAction.emit(t, p, ("point", a))
            elif not small:
                self.toolAction.emit(t, p, ur)
        elif d["kind"] == "line":
            end = d.get("end", sp)
            _, a = self.scene_to_unrot(d["start"], p)
            _, b = self.scene_to_unrot(end, p)
            if abs(a.x - b.x) + abs(a.y - b.y) > 3:
                self.toolAction.emit(t, p, (a, b))
        elif d["kind"] == "ink":
            if len(d["pts"]) > 2:
                self.toolAction.emit(t, p, d["pts"])
        elif d["kind"] == "text":
            if self.sel_words:
                if t in TEXT_TOOLS:
                    self.toolAction.emit(t, p, (self.sel_words[1], self.sel_words[2]))
                    self.sel_words = None
                    self._draw_overlays()
                else:
                    self.textSelectionChanged.emit(self.sel_words[2])
            elif t in TEXT_TOOLS and "b" in d:
                r = fitz.Rect(d["a"], d["b"]).normalize()
                if r.width > 4 and r.height > 4:
                    self.toolAction.emit(t, p, ([r], ""))
        elif d["kind"] == "move":
            delta = sp - d["start"]
            if abs(delta.x()) + abs(delta.y()) > 2:
                _, a = self.scene_to_unrot(d["start"], p)
                _, b = self.scene_to_unrot(d["start"] + delta, p)
                self.toolAction.emit("move_annot", p, (d["xref"], b.x - a.x, b.y - a.y))

    def mouseDoubleClickEvent(self, e):
        if self._poly is not None and self.tool in POLY_TOOLS:
            poly = self._poly
            self._poly = None
            if poly["item"].scene():
                self.scene().removeItem(poly["item"])
            pts = poly["pts"]
            # double click adds a duplicate last point
            if len(pts) >= 2 and abs(pts[-1].x - pts[-2].x) + abs(pts[-1].y - pts[-2].y) < 1:
                pts = pts[:-1]
            if len(pts) >= 2:
                self.toolAction.emit(self.tool, poly["page"], pts)
            return
        if self.tool == "select" and self.sel_annot:
            self.toolAction.emit("edit_annot", self.sel_annot[0], self.sel_annot[1])
            return
        if self.tool == "select" and self.pdf:
            # double click selects a word
            sp = self.mapToScene(e.position().toPoint())
            p, pt = self.scene_to_unrot(sp)
            if p is not None:
                i = self._word_index_at(p, pt, nearest=False)
                if i is not None:
                    w = self._words(p)[i]
                    self.sel_words = (p, [fitz.Rect(w[:4])], w[4])
                    self._draw_overlays()
                    self.textSelectionChanged.emit(w[4])
                    return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            if self._poly and self._poly["item"].scene():
                self.scene().removeItem(self._poly["item"])
            self._poly = None
            self._cancel_drag()
            self.clear_selection()
            self.annotSelected.emit(-1, -1)
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel_annot:
            self.toolAction.emit("delete_annot", self.sel_annot[0], self.sel_annot[1])
            return
        if e.matches(QKeySequenceCopy()) and self.sel_words:
            QGuiApplication.clipboard().setText(self.sel_words[2])
            return
        if e.key() in (Qt.Key_PageDown,) and self.layout_mode in ("single", "single2"):
            self.go_to(self.current + (2 if self.layout_mode == "single2" else 1))
            return
        if e.key() in (Qt.Key_PageUp,) and self.layout_mode in ("single", "single2"):
            self.go_to(self.current - (2 if self.layout_mode == "single2" else 1))
            return
        if e.key() == Qt.Key_Home and e.modifiers() & Qt.ControlModifier:
            self.go_to(0)
            return
        if e.key() == Qt.Key_End and e.modifiers() & Qt.ControlModifier:
            self.go_to(self.doc.page_count - 1)
            return
        super().keyPressEvent(e)

    # ------------------------------------------------------------------ rulers / grid / view rotation
    def set_view_rotation(self, deg):
        from PySide6.QtGui import QTransform
        self.view_rotation = deg % 360
        self.setTransform(QTransform().rotate(self.view_rotation))
        self._render_timer.start()

    def drawForeground(self, painter, rect):
        if not self.pdf or not (self.show_grid or self.show_rulers):
            return
        s = self.scale()
        step = 10 * 72 / 25.4 * s   # 10 mm
        if self.show_grid:
            painter.setPen(QPen(QColor(59, 130, 246, 60), 0))
            for r in self.page_rects:
                if r is None or not r.intersects(rect):
                    continue
                x = r.left()
                while x <= r.right():
                    painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                    x += step
                y = r.top()
                while y <= r.bottom():
                    painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                    y += step
        if self.show_rulers and 0 <= self.current < len(self.page_rects) and self.page_rects[self.current] is not None:
            pr = self.page_rects[self.current]
            painter.save()
            painter.setWorldMatrixEnabled(False)
            vp = self.viewport().rect()
            tl = self.mapFromScene(pr.topLeft())
            painter.fillRect(0, 0, vp.width(), 20, QColor("#F3F3F3"))
            painter.fillRect(0, 0, 20, vp.height(), QColor("#F3F3F3"))
            painter.setPen(QPen(QColor("#9CA3AF"), 1))
            painter.drawLine(0, 20, vp.width(), 20)
            painter.drawLine(20, 0, 20, vp.height())
            f = painter.font()
            f.setPixelSize(9)
            painter.setFont(f)
            mm = 72 / 25.4 * s
            k = 0
            while True:
                x = tl.x() + k * mm
                if x > vp.width():
                    break
                if x >= 20:
                    hgt = 10 if k % 10 == 0 else (6 if k % 5 == 0 else 3)
                    painter.drawLine(int(x), 20 - hgt, int(x), 20)
                    if k % 10 == 0:
                        painter.drawText(int(x) + 2, 9, str(k // 10))
                k += 1
            k = 0
            while True:
                y = tl.y() + k * mm
                if y > vp.height():
                    break
                if y >= 20:
                    wdt = 10 if k % 10 == 0 else (6 if k % 5 == 0 else 3)
                    painter.drawLine(20 - wdt, int(y), 20, int(y))
                    if k % 10 == 0:
                        painter.drawText(1, int(y) + 10, str(k // 10))
                k += 1
            painter.restore()

    # ------------------------------------------------------------------ snapshot
    def render_region(self, page, rect, dpi=200):
        pm = self.doc[page].get_pixmap(clip=fitz.Rect(rect), dpi=dpi)
        return QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()

    # ------------------------------------------------------------------ drag & drop
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
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


def QKeySequenceCopy():
    from PySide6.QtGui import QKeySequence
    return QKeySequence.Copy
