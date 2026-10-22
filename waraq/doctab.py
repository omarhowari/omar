"""One open document: viewer + side panels + properties pane, and all edit handlers."""
import json
import math
import os

import pymupdf as fitz
from PySide6.QtCore import Qt, QSize, Signal, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QDesktopServices, QColor
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QStackedWidget, QToolButton,
                               QButtonGroup, QInputDialog, QMessageBox, QFileDialog, QMenu, QFrame)

from . import ops
from .dialogs import ask, SignatureDialog
from .i18n import tr
from .icons import icon
from .panels import (ThumbnailPanel, BookmarkPanel, CommentsPanel, SearchPanel, AttachmentsPanel,
                     PropertiesPanel)
from .viewer import PageView


def _rgb(h):
    return ops.hex_to_rgb(h) if h else None


def freetext_html(text, fontsize, color, align=None):
    import html
    rtl = ops.is_rtl(text)
    al = align or ("right" if rtl else "left")
    body = "<br/>".join(html.escape(l) for l in text.split("\n"))
    d = ' dir="rtl"' if rtl else ""
    style = f"font-size:{fontsize}pt;color:{color};font-family:sans-serif;text-align:{al}"
    return f"<p{d}>{body}</p>", style


class DocTab(QWidget):
    status = Signal(str)
    stateChanged = Signal()

    def __init__(self, pdf, style, main):
        super().__init__()
        self.pdf = pdf
        self.style = style
        self.main = main
        self.stamp_cfg = dict(label="Approved", dynamic=True, image=None)
        self.signature_path = None
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ---- left rail + panels
        self.rail = QFrame()
        self.rail.setObjectName("rail")
        rv = QVBoxLayout(self.rail)
        rv.setContentsMargins(4, 8, 4, 8)
        rv.setSpacing(4)
        self.stack = QStackedWidget()
        self.stack.setObjectName("sidepanel")
        self.thumbs = ThumbnailPanel()
        self.thumbs.setLayoutDirection(Qt.LeftToRight)
        self.books = BookmarkPanel()
        self.comments = CommentsPanel()
        self.search = SearchPanel()
        self.attach = AttachmentsPanel()
        self.rail_group = QButtonGroup(self)
        for k, (w, ic, tip) in enumerate(((self.thumbs, "thumbs", tr("Thumbnails")),
                                          (self.books, "bookmark", tr("Bookmarks")),
                                          (self.comments, "comments", tr("Comments")),
                                          (self.search, "search", tr("Search")),
                                          (self.attach, "attach", tr("Attachments")))):
            self.stack.addWidget(w)
            b = QToolButton()
            b.setIcon(icon(ic))
            b.setProperty("ic", ic)
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setFixedSize(38, 38)
            b.clicked.connect(lambda _=False, i=k: self.show_panel(i))
            self.rail_group.addButton(b, k)
            rv.addWidget(b)
        rv.addStretch()
        self.rail_group.button(0).setChecked(True)

        self.view = PageView()
        from .icons import THEME_COLOR
        if THEME_COLOR != "#1F2937":
            self.view.setBackgroundBrush(QColor("#2B2F36"))
        self.props = PropertiesPanel(style)
        self.props.setObjectName("props")

        self.split = QSplitter(Qt.Horizontal)
        self.split.addWidget(self.stack)
        self.split.addWidget(self.view)
        self.split.addWidget(self.props)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([260, 900, 260])
        self.split.setCollapsible(1, False)
        h.addWidget(self.rail)
        h.addWidget(self.split)

        # ---- wiring
        v = self.view
        v.toolAction.connect(self.on_tool)
        v.annotSelected.connect(self.on_annot_selected)
        v.widgetClicked.connect(self.fill_widget)
        v.linkClicked.connect(self.follow_link)
        v.pageChanged.connect(self._page_changed)
        v.contextMenu.connect(self.page_menu)
        v.textSelectionChanged.connect(lambda t: self.status.emit(f"{len(t)} chars selected — Ctrl+C to copy"))
        v.filesDropped.connect(self.main.open_files)
        self.thumbs.pageClicked.connect(lambda p: v.go_to(p))
        self.thumbs.reorderRequested.connect(self.reorder)
        self.thumbs.pageAction.connect(self.page_action)
        self.books.goTo.connect(lambda p, y: v.go_to(p))
        self.books.tocChanged.connect(self.set_toc)
        self.books.current_page = lambda: self.view.current
        self.comments.goToAnnot.connect(self.goto_annot)
        self.comments.action.connect(lambda a: self.main.cmd({"summarize": "summarize",
                                                               "delete_all": "delete_comments"}[a]))
        self.search.hitsChanged.connect(lambda hits, cur: v.set_search_hits(hits, cur))
        self.search.goToHit.connect(self._goto_hit)
        self.props.applyRequested.connect(self.apply_props)
        self.props.deleteRequested.connect(self.delete_selected)
        pdf.changed.connect(self.on_doc_changed)
        pdf.modifiedChanged.connect(lambda *_: self.stateChanged.emit())

        v.set_document(pdf)
        self.thumbs.set_document(pdf.doc)
        self.books.set_document(pdf.doc)
        self.comments.set_document(pdf.doc)
        self.search.set_document(pdf.doc)
        self.attach.set_document(pdf)

    # ------------------------------------------------------------------ helpers
    @property
    def doc(self):
        return self.pdf.doc

    @property
    def page(self):
        return self.view.current

    def show_panel(self, i):
        if self.stack.isVisible() and self.stack.currentIndex() == i:
            self.stack.setVisible(False)
            self.rail_group.setExclusive(False)
            self.rail_group.button(i).setChecked(False)
            self.rail_group.setExclusive(True)
            return
        self.stack.setVisible(True)
        self.stack.setCurrentIndex(i)
        self.rail_group.button(i).setChecked(True)
        if i == 3:
            self.search.focus(self.view.selected_text())

    def _page_changed(self, p):
        self.thumbs.set_current(p)
        self.stateChanged.emit()

    def _goto_hit(self, page, kr):
        k, r = kr
        self.view.set_search_hits(self.view.search_hits, (page, k))
        self.view.go_to_rect(page, r)

    def on_doc_changed(self, page):
        if page == -2:  # attachments/metadata only
            self.stateChanged.emit()
            return
        if page < 0:
            self.view.invalidate(-1)
            self.thumbs.set_document(self.doc)
            self.books.set_document(self.doc)
            self.search.set_document(self.doc)
            self.attach.set_document(self.pdf)
            self.view.set_search_hits({})
        else:
            self.view.invalidate(page)
            self.thumbs.refresh_page(page)
        self.comments.set_document(self.doc)
        self.stateChanged.emit()

    def edit(self, page=-1):
        """Context manager-ish: create undo checkpoint."""
        self.pdf.checkpoint()

    def done(self, page=-1, msg=""):
        self.pdf.touched(page)
        if msg:
            self.status.emit(msg)

    def pages_from_spec(self, spec):
        return ops.parse_ranges(spec, self.doc.page_count)

    # ------------------------------------------------------------------ annotation style
    def _finish_annot(self, a, content=None, use_fill=True, width=True):
        st = self.style
        try:
            if use_fill and st["fill"]:
                a.set_colors(stroke=_rgb(st["color"]), fill=_rgb(st["fill"]))
            else:
                a.set_colors(stroke=_rgb(st["color"]))
        except Exception:
            pass
        if width:
            try:
                a.set_border(width=st["width"])
            except Exception:
                pass
        a.set_opacity(st["opacity"])
        a.set_info(title=st["author"], content=content if content is not None else a.info.get("content", ""))
        a.update()
        return a

    # ------------------------------------------------------------------ tool actions
    def on_tool(self, tool, p, payload):
        try:
            self._on_tool(tool, p, payload)
        except Exception as e:
            QMessageBox.warning(self, tr("Error"), str(e))
        keep = {"select", "hand", "move_annot", "delete_annot", "edit_annot", "snapshot", "zoom_tool", "loupe", "eraser",
                "highlight", "underline", "strike", "squiggly", "ink"}
        if tool not in keep and not getattr(self.main, "exclusive", True):
            self.main.set_tool("hand")

    def _default_rect(self, page, pt, w=200, h=60):
        r = fitz.Rect(pt.x, pt.y, pt.x + w, pt.y + h)
        pr = page.mediabox
        if r.x1 > pr.x1:
            r.x0, r.x1 = pr.x1 - w, pr.x1
        if r.y1 > pr.y1:
            r.y0, r.y1 = pr.y1 - h, pr.y1
        return r

    def _on_tool(self, tool, p, payload):
        page = self.doc[p]
        st = self.style
        if isinstance(payload, tuple) and len(payload) == 2 and payload[0] == "point":
            pt = payload[1]
            sizes = {"stamp": (180, 70), "signature": (160, 60), "addimage": (200, 150), "textbox": (200, 60),
                     "addtext": (260, 40), "field_text": (180, 22), "field_check": (16, 16), "field_radio": (16, 16),
                     "field_combo": (160, 22), "field_list": (160, 70)}
            w, h = sizes.get(tool, (200, 60))
            payload = self._default_rect(page, pt, w, h)

        if tool in ("highlight", "underline", "strike", "squiggly"):
            rects, text = payload
            fn = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
                  "strike": page.add_strikeout_annot, "squiggly": page.add_squiggly_annot}[tool]
            self.edit()
            a = fn(quads=[r.quad for r in rects]) if len(rects) > 1 else fn(rects[0])
            a.set_colors(stroke=_rgb(st["color"]))
            a.set_opacity(st["opacity"])
            a.set_info(title=st["author"], content="")
            a.update()
            self.done(p)
            if text:
                self.status.emit(f"{tool}: “{text[:60]}”")
        elif tool == "area_highlight":
            self.edit()
            a = page.add_highlight_annot(payload)
            a.set_colors(stroke=_rgb(st["color"]))
            a.set_opacity(st["opacity"])
            a.set_info(title=st["author"])
            a.update()
            self.done(p)
        elif tool == "note":
            text, ok = QInputDialog.getMultiLineText(self, tr("Sticky note"), tr("Note"))
            if not ok:
                return
            self.edit()
            a = page.add_text_annot(payload, text, icon="Comment")
            a.set_colors(stroke=_rgb(st["color"]))
            a.set_info(title=st["author"], content=text)
            a.update()
            self.done(p)
        elif tool in ("textbox", "callout"):
            text, ok = QInputDialog.getMultiLineText(self, tr("Text box"), tr("Text"))
            if not ok or not text:
                return
            self.edit()
            if tool == "callout":
                a_pt, b_pt = payload
                lines = text.count("\n") + 1
                w = min(240, max(80, max(len(l) for l in text.split("\n")) * st["fontsize"] * 0.6 + 16))
                h = lines * st["fontsize"] * 1.5 + 12
                rect = fitz.Rect(b_pt.x, b_pt.y - h / 2, b_pt.x + w, b_pt.y + h / 2)
                if b_pt.x < a_pt.x:
                    rect = fitz.Rect(b_pt.x - w, b_pt.y - h / 2, b_pt.x, b_pt.y + h / 2)
                knee = fitz.Point((a_pt.x + (rect.x0 if b_pt.x >= a_pt.x else rect.x1)) / 2, b_pt.y)
                end = fitz.Point(rect.x0 if b_pt.x >= a_pt.x else rect.x1, b_pt.y)
                callout = (a_pt, knee, end)
            else:
                rect, callout = payload, None
            html, css = freetext_html(text, st["fontsize"], st["color"])
            a = page.add_freetext_annot(rect, html, fontsize=st["fontsize"], richtext=True, style=css,
                                        fill_color=_rgb(st["fill"]) if st["fill"] else None,
                                        border_color=_rgb(st["color"]) if (st["width"] or callout) else None,
                                        border_width=max(st["width"], 1 if callout else 0),
                                        callout=callout, line_end=fitz.PDF_ANNOT_LE_OPEN_ARROW,
                                        opacity=st["opacity"], rotate=page.rotation)
            a.set_info(title=st["author"], content=text)
            a.update()
            self.done(p)
        elif tool in ("rect", "oval", "redact_mark"):
            self.edit()
            a = page.add_rect_annot(payload) if tool == "rect" else page.add_circle_annot(payload)
            self._finish_annot(a)
            self.done(p)
        elif tool in ("line", "arrow", "measure"):
            a_pt, b_pt = payload
            self.edit()
            a = page.add_line_annot(a_pt, b_pt)
            content = None
            if tool == "arrow":
                a.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
            if tool == "measure":
                a.set_line_ends(fitz.PDF_ANNOT_LE_BUTT, fitz.PDF_ANNOT_LE_BUTT)
                mm = math.hypot(b_pt.x - a_pt.x, b_pt.y - a_pt.y) / ops.MM
                content = f"{mm / 10:.2f} cm"
            self._finish_annot(a, content=content, use_fill=True)
            if tool == "measure":
                mid = fitz.Point((a_pt.x + b_pt.x) / 2, (a_pt.y + b_pt.y) / 2)
                lab = page.add_freetext_annot(fitz.Rect(mid.x - 32, mid.y - 18, mid.x + 32, mid.y - 4), content,
                                              fontsize=8, text_color=_rgb(st["color"]), rotate=page.rotation,
                                              fill_color=(1, 1, 1))
                lab.set_info(title=st["author"], content=content)
                lab.update()
                self.status.emit(f"{tr('Distance')}: {content}")
            self.done(p)
        elif tool in ("polygon", "polyline", "area_measure"):
            pts = payload
            self.edit()
            if tool == "polyline":
                a = page.add_polyline_annot(pts)
                self._finish_annot(a)
            else:
                a = page.add_polygon_annot(pts)
                content = None
                if tool == "area_measure":
                    area = 0
                    for i in range(len(pts)):
                        x1, y1 = pts[i].x, pts[i].y
                        x2, y2 = pts[(i + 1) % len(pts)].x, pts[(i + 1) % len(pts)].y
                        area += x1 * y2 - x2 * y1
                    cm2 = abs(area) / 2 / (ops.MM * 10) ** 2
                    content = f"{cm2:.2f} cm²"
                    self.status.emit(f"{tr('Area')}: {content}")
                self._finish_annot(a, content=content)
            self.done(p)
        elif tool == "ink":
            self.edit()
            a = page.add_ink_annot([[(q.x, q.y) for q in payload]])
            self._finish_annot(a, use_fill=False)
            self.done(p)
        elif tool == "stamp":
            self.edit()
            ops.add_stamp(page, payload, self.stamp_cfg["label"], st["author"], self.stamp_cfg["dynamic"],
                          image_path=self.stamp_cfg.get("image"))
            self.done(p)
        elif tool == "signature":
            if not self.signature_path or not os.path.exists(self.signature_path):
                d = SignatureDialog(self)
                if not d.exec():
                    return
                self.signature_path = d.result_path
            self.edit()
            pix = fitz.Pixmap(self.signature_path)
            r = fitz.Rect(payload)
            ar = pix.width / pix.height
            r = fitz.Rect(r.x0, r.y0, r.x0 + r.height * ar, r.y1) if r.width / r.height > ar else \
                fitz.Rect(r.x0, r.y0, r.x1, r.y0 + r.width / ar)
            if page.rotation:
                pix = ops.rotate_pixmap(pix, (360 - page.rotation) % 360)
            a = page.add_stamp_annot(r, stamp=pix)
            a.set_info(title=st["author"], subject="Signature", content="Signature")
            a.update()
            self.done(p, "Signature placed — use Comment › Flatten to make it permanent.")
        elif tool == "addimage":
            fn, _ = QFileDialog.getOpenFileName(self, tr("Add image"), "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)")
            if not fn:
                return
            self.edit()
            page.insert_image(payload, filename=fn, keep_proportion=True, rotate=page.rotation)
            self.done(p)
        elif tool == "addtext":
            v = ask(self, tr("Add text"), [
                ("text", tr("Text"), "multiline", ""),
                ("size", tr("Font size"), "int", st["fontsize"], (4, 200)),
                ("color", tr("Color"), "color", "#111827"),
                ("font", "Font", "choice", "sans-serif", ["sans-serif", "serif", "monospace"]),
                ("bold", "Bold", "bool", False), ("italic", "Italic", "bool", False),
                ("align", "Align", "choice", "left", ["left", "center", "right", "justify"])])
            if not v or not v["text"].strip():
                return
            rect = fitz.Rect(payload)
            lines = v["text"].count("\n") + 1
            if rect.height < lines * v["size"] * 1.4:
                rect.y1 = rect.y0 + lines * v["size"] * 1.45 + 4
            self.edit()
            res = ops.insert_text_box(page, rect, v["text"], v["size"], v["color"], v["align"], bold=v["bold"],
                                      italic=v["italic"], rotate=page.rotation, font_family=v["font"])
            self.done(p)
            if res and res[0] < 0:
                self.status.emit("Text did not fit — it was shrunk; draw a larger box for bigger text.")
        elif tool == "edittext":
            info = payload
            v = ask(self, tr("Edit text"), [
                ("text", tr("Text"), "multiline", info["text"]),
                ("size", tr("Font size"), "float", round(info["size"], 1), (3, 200)),
                ("color", tr("Color"), "color", info["color"]),
                ("bold", "Bold", "bool", info["bold"])],
                help_text=f"Original font: {info['font']}. The line is removed and re-typed with a standard font.")
            if not v:
                return
            self.edit()
            r = fitz.Rect(info["rect"])
            hgt = r.height
            page.add_redact_annot(fitz.Rect(r.x0, r.y0 + hgt * 0.22, r.x1, r.y1 - hgt * 0.22), fill=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
            if v["text"].strip():
                tr_ = fitz.Rect(r.x0, r.y0 - 1, max(r.x1, r.x0 + len(v["text"]) * v["size"] * 0.62) + 4, r.y1 + v["size"] * 0.5)
                ops.insert_text_box(page, tr_, v["text"], v["size"], v["color"], "left", bold=v["bold"],
                                    rotate=page.rotation)
            self.done(p)
        elif tool == "whiteout":
            self.edit()
            page.draw_rect(payload, color=None, fill=(1, 1, 1), overlay=True)
            self.done(p)
        elif tool == "redact":
            self.edit()
            a = page.add_redact_annot(payload, fill=(0, 0, 0))
            a.set_info(title=st["author"])
            a.update()
            self.done(p, "Marked for redaction — Protect › Apply redactions to remove the content.")
        elif tool == "snapshot":
            img = self.view.render_region(p, payload)
            QGuiApplication.clipboard().setImage(img)
            self.status.emit("Snapshot copied to clipboard.")
        elif tool == "link":
            v = ask(self, tr("Link"), [("kind", "Link to", "choice", "url", [("url", "Web address"), ("page", "Page")]),
                                       ("url", "URL", "text", "https://"),
                                       ("page", tr("Page"), "int", 1, (1, self.doc.page_count))])
            if not v:
                return
            self.edit()
            if v["kind"] == "url":
                page.insert_link({"kind": fitz.LINK_URI, "from": payload, "uri": v["url"]})
            else:
                page.insert_link({"kind": fitz.LINK_GOTO, "from": payload, "page": v["page"] - 1, "to": fitz.Point(0, 0)})
            a = page.add_rect_annot(payload)
            a.set_colors(stroke=(0.15, 0.39, 0.92))
            a.set_border(width=0.5, dashes=[2, 2])
            a.set_info(content="Link", title=st["author"])
            a.update()
            self.done(p)
        elif tool == "attach":
            fn, _ = QFileDialog.getOpenFileName(self, tr("Attach file"))
            if not fn:
                return
            self.edit()
            with open(fn, "rb") as f:
                a = page.add_file_annot(payload, f.read(), os.path.basename(fn), icon="Paperclip")
            a.set_info(title=st["author"], content=os.path.basename(fn))
            a.update()
            self.done(p)
        elif tool == "insert_text":
            text, ok = QInputDialog.getMultiLineText(self, tr("Insert text"), tr("Text to insert"))
            if not ok:
                return
            self.edit()
            a = page.add_caret_annot(payload)
            a.set_colors(stroke=(0.15, 0.39, 0.92))
            a.set_info(title=st["author"], content=text, subject="Insert text")
            a.update()
            self.done(p)
        elif tool == "replace_text":
            rects, old = payload
            new, ok = QInputDialog.getMultiLineText(self, tr("Replace text"), f"“{old[:80]}” →", "")
            if not ok:
                return
            self.edit()
            fn = page.add_strikeout_annot
            a = fn(quads=[r.quad for r in rects]) if len(rects) > 1 else fn(rects[0])
            a.set_colors(stroke=(0.86, 0.15, 0.15))
            a.set_info(title=st["author"], content=new, subject="Replace text")
            a.update()
            c = page.add_caret_annot(fitz.Point(rects[-1].x1, rects[-1].y1))
            c.set_colors(stroke=(0.15, 0.39, 0.92))
            c.set_info(title=st["author"], content=new, subject="Replace text")
            c.update()
            self.done(p)
        elif tool == "perimeter":
            pts = payload
            self.edit()
            a = page.add_polyline_annot(pts)
            length = sum(math.hypot(pts[k + 1].x - pts[k].x, pts[k + 1].y - pts[k].y) for k in range(len(pts) - 1))
            content = f"{length / ops.MM / 10:.2f} cm"
            self._finish_annot(a, content=content)
            self.status.emit(f"{tr('Perimeter')}: {content}")
            self.done(p)
        elif tool == "cloud":
            self.edit()
            a = page.add_rect_annot(payload)
            a.set_border(width=max(1, st["width"]), clouds=2)
            a.set_colors(stroke=_rgb(st["color"]), fill=_rgb(st["fill"]) if st["fill"] else None)
            a.set_opacity(st["opacity"])
            a.set_info(title=st["author"])
            a.update()
            self.done(p)
        elif tool.startswith("field_"):
            self.add_field(page, tool, payload)
            self.done(p)
        elif tool == "digital_sign":
            self.main.digital_sign(p, payload)
        elif tool == "crop_area":
            self.edit()
            pages = list(range(self.doc.page_count)) if QMessageBox.question(
                self, tr("Crop"), "Apply this crop to all pages?") == QMessageBox.Yes else [p]
            for i in pages:
                pg = self.doc[i]
                pg.set_cropbox(fitz.Rect(payload) & pg.mediabox)
            self.done(-1)
        elif tool == "move_annot":
            xref, dx, dy = payload
            self.move_annot(p, xref, dx, dy)
        elif tool == "delete_annot":
            self.view.sel_annot = (p, payload)
            self.delete_selected()
        elif tool == "edit_annot":
            self.edit_annot(p, payload)

    # ------------------------------------------------------------------ annotation editing
    def on_annot_selected(self, p, xref):
        if p < 0:
            self.props.show_defaults()
            self.main.annot_selected(None)
            return
        a = ops.load_annot(self.doc, p, xref)
        if a is not None:
            self.props.show_annot(a)
            self.props.fontsize.setValue(int(self.style["fontsize"]))
            self.main.annot_selected(a)

    def apply_props(self, v):
        if not self.view.sel_annot:
            return
        p, xref = self.view.sel_annot
        page = self.doc[p]
        a = page.load_annot(xref)
        if a is None:
            return
        self.edit()
        t = a.type[1]
        if t == "FreeText":
            html, css = freetext_html(v["content"] or "", v["fontsize"], v["color"] or "#000000")
            rect, rot = a.rect, page.rotation
            info = a.info
            page.delete_annot(a)
            a = page.add_freetext_annot(rect, html, fontsize=v["fontsize"], richtext=True, style=css,
                                        fill_color=_rgb(v["fill"]) if v["fill"] else None,
                                        border_color=_rgb(v["color"]) if v["width"] else None,
                                        border_width=v["width"], opacity=v["opacity"], rotate=rot)
            a.set_info(title=v["author"], content=v["content"])
            a.update()
            self.view.sel_annot = (p, a.xref)
        else:
            try:
                if t in ("Square", "Circle", "Polygon", "Line", "PolyLine") and v["fill"]:
                    a.set_colors(stroke=_rgb(v["color"]), fill=_rgb(v["fill"]))
                elif t in ("Square", "Circle", "Polygon"):
                    a.set_colors(stroke=_rgb(v["color"]), fill=[])
                elif t not in ("Stamp", "FileAttachment"):
                    a.set_colors(stroke=_rgb(v["color"]))
            except Exception:
                pass
            if t in ("Square", "Circle", "Line", "PolyLine", "Polygon", "Ink"):
                a.set_border(width=v["width"])
            a.set_opacity(v["opacity"])
            a.set_info(title=v["author"], content=v["content"])
            if t != "Stamp":
                a.update()
        self.done(p, "Comment updated.")
        self.view._draw_overlays()

    def delete_selected(self):
        if not self.view.sel_annot:
            return
        p, xref = self.view.sel_annot
        a = ops.load_annot(self.doc, p, xref)
        if a is None:
            return
        self.edit()
        a._page_ref.delete_annot(a)
        self.view.sel_annot = None
        self.props.show_defaults()
        self.done(p, "Comment deleted.")

    def edit_annot(self, p, xref):
        a = ops.load_annot(self.doc, p, xref)
        if a is None:
            return
        if a.type[1] in ("FreeText", "Text", "Square", "Circle", "Highlight", "Underline", "StrikeOut", "Squiggly",
                         "Line", "Polygon", "PolyLine", "Ink"):
            text, ok = QInputDialog.getMultiLineText(self, a.type[1], tr("Text") if a.type[1] == "FreeText" else tr("Note"),
                                                     a.info.get("content", ""))
            if ok:
                v = dict(color=self.props.stroke.color(), fill=self.props.fill.color(),
                         opacity=self.props.opacity.value() / 100, width=self.props.width.value(),
                         fontsize=self.props.fontsize.value(), author=self.props.author.text(), content=text)
                self.view.sel_annot = (p, xref)
                self.apply_props(v)
        elif a.type[1] == "FileAttachment":
            info = a.file_info
            fn, _ = QFileDialog.getSaveFileName(self, tr("Save"), info.get("filename", "attachment"))
            if fn:
                with open(fn, "wb") as f:
                    f.write(a.get_file())

    def move_annot(self, p, xref, dx, dy):
        page = self.doc[p]
        a = page.load_annot(xref)
        if a is None:
            return
        t = a.type[1]
        self.edit()
        if t in ("Ink", "Line", "Polygon", "PolyLine"):
            # recreate with shifted vertices, keeping look
            cols = a.colors
            border = a.border
            op = a.opacity
            info = a.info
            le = a.line_ends
            verts = a.vertices
            page.delete_annot(a)
            if t == "Ink":
                strokes = verts if verts and isinstance(verts[0], list) else [verts]
                na = page.add_ink_annot([[(x + dx, y + dy) for x, y in s] for s in strokes])
            else:
                pts = [fitz.Point(x + dx, y + dy) for x, y in verts]
                if t == "Line":
                    na = page.add_line_annot(pts[0], pts[1])
                    if le:
                        na.set_line_ends(*le)
                elif t == "Polygon":
                    na = page.add_polygon_annot(pts)
                else:
                    na = page.add_polyline_annot(pts)
            try:
                na.set_colors(stroke=cols.get("stroke"), fill=cols.get("fill") or None)
            except Exception:
                na.set_colors(stroke=cols.get("stroke"))
            na.set_border(width=border.get("width", 1))
            na.set_opacity(op if op >= 0 else 1)
            na.set_info(info)
            na.update()
            self.view.sel_annot = (p, na.xref)
        elif t == "Stamp":
            # stamps have custom appearance; move via xref Rect key to keep the image
            r = a.rect + (dx, dy, dx, dy)
            self.doc.xref_set_key(xref, "Rect", f"[{r.x0} {page.mediabox.y1 - r.y1} {r.x1} {page.mediabox.y1 - r.y0}]")
        else:
            r = a.rect + (dx, dy, dx, dy)
            a.set_rect(r)
            if t != "FileAttachment":
                a.update()
        self.done(p)
        self.view._draw_overlays()

    def goto_annot(self, p, xref):
        a = ops.load_annot(self.doc, p, xref)
        if a is None:
            return
        self.view.go_to_rect(p, a.rect)
        self.main.set_tool("select")
        self.view.select_annot(p, xref)
        self.on_annot_selected(p, xref)

    # ------------------------------------------------------------------ forms
    def add_field(self, page, tool, rect):
        kinds = {"field_text": fitz.PDF_WIDGET_TYPE_TEXT, "field_check": fitz.PDF_WIDGET_TYPE_CHECKBOX,
                 "field_radio": fitz.PDF_WIDGET_TYPE_RADIOBUTTON, "field_combo": fitz.PDF_WIDGET_TYPE_COMBOBOX,
                 "field_list": fitz.PDF_WIDGET_TYPE_LISTBOX, "field_button": fitz.PDF_WIDGET_TYPE_BUTTON,
                 "field_date": fitz.PDF_WIDGET_TYPE_TEXT, "field_image": fitz.PDF_WIDGET_TYPE_BUTTON,
                 "field_signature": fitz.PDF_WIDGET_TYPE_SIGNATURE}
        n = sum(1 for p in self.doc for _ in p.widgets()) + 1
        fields = [("name", "Field name", "text", f"{tool[6:]}_{n}")]
        if tool == "field_signature":
            fields = [("name", "Field name", "text", f"Signature_{n}")]
        if tool in ("field_combo", "field_list"):
            fields.append(("options", "Options (one per line)", "multiline", "Option 1\nOption 2\nOption 3"))
        if tool == "field_text":
            fields += [("value", "Default value", "text", ""), ("multiline", "Multi-line", "bool", False),
                       ("size", tr("Font size"), "int", 10, (0, 72))]
        if tool == "field_radio":
            fields.append(("group", "Group name", "text", "group1"))
        if tool in ("field_button", "field_image"):
            fields.append(("caption", "Caption", "text", "Button" if tool == "field_button" else "Image"))
        v = ask(self, "Form field", fields)
        if not v:
            return
        self.edit()
        w = fitz.Widget()
        w.field_type = kinds[tool]
        w.field_name = v.get("group") or v["name"]
        w.rect = fitz.Rect(rect)
        w.border_color = (0.4, 0.45, 0.55)
        w.border_width = 0.8
        w.fill_color = (0.94, 0.96, 1.0)
        if tool == "field_text":
            w.field_value = v["value"]
            w.text_fontsize = v["size"]
            if v["multiline"]:
                w.field_flags |= fitz.PDF_TX_FIELD_IS_MULTILINE
        elif tool in ("field_combo", "field_list"):
            opts = [o for o in v["options"].split("\n") if o.strip()]
            w.choice_values = opts
            w.field_value = opts[0] if opts else ""
        elif tool == "field_date":
            import datetime
            w.field_value = datetime.date.today().strftime("%Y-%m-%d")
            w.text_fontsize = 10
            w.script_format = 'AFDate_FormatEx("yyyy-mm-dd");'
            w.script_keystroke = 'AFDate_KeystrokeEx("yyyy-mm-dd");'
        elif tool in ("field_button", "field_image"):
            w.button_caption = v["caption"]
            w.fill_color = (0.88, 0.9, 0.93)
        elif tool in ("field_check", "field_radio"):
            w.field_value = True   # creates the proper "on" appearance state …
        page.add_widget(w)
        if tool in ("field_check", "field_radio"):
            w.field_value = False  # … then start unchecked
            w.update()

    def fill_widget(self, p, xref):
        page = self.doc[p]
        w = next((x for x in page.widgets() if x.xref == xref), None)
        if w is None:
            return
        t = w.field_type
        val = None
        if t == fitz.PDF_WIDGET_TYPE_TEXT:
            if w.field_flags & fitz.PDF_TX_FIELD_IS_MULTILINE:
                val, ok = QInputDialog.getMultiLineText(self, w.field_name, w.field_label or w.field_name, w.field_value or "")
            else:
                val, ok = QInputDialog.getText(self, w.field_name, w.field_label or w.field_name, text=w.field_value or "")
            if not ok:
                return
        elif t in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
            is_on = bool(w.field_value) and w.field_value not in ("Off", False)
            val = not is_on
        elif t in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
            opts = [o if isinstance(o, str) else o[1] for o in (w.choice_values or [])]
            cur = opts.index(w.field_value) if w.field_value in opts else 0
            val, ok = QInputDialog.getItem(self, w.field_name, w.field_name, opts, cur, t == fitz.PDF_WIDGET_TYPE_COMBOBOX)
            if not ok:
                return
        elif t == fitz.PDF_WIDGET_TYPE_SIGNATURE:
            self.main.set_tool("digital_sign")
            self.on_tool("digital_sign", p, w.rect)
            return
        else:
            return
        self.edit()
        w.field_value = val
        w.update()
        self.done(p)

    def form_data(self):
        data = {}
        for p in self.doc:
            for w in p.widgets():
                data[w.field_name] = w.field_value
        return data

    def set_form_data(self, data):
        self.edit()
        n = 0
        for p in self.doc:
            for w in p.widgets():
                if w.field_name in data:
                    w.field_value = data[w.field_name]
                    w.update()
                    n += 1
        self.done(-1, f"{n} fields filled.")

    def reset_form(self):
        self.edit()
        for p in self.doc:
            for w in p.widgets():
                w.reset()
        self.done(-1)

    # ------------------------------------------------------------------ links / pages
    def follow_link(self, l):
        if l.get("kind") == fitz.LINK_URI and l.get("uri"):
            if QMessageBox.question(self, tr("Link"), f"Open {l['uri']} ?") == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(l["uri"]))
        elif l.get("page", -1) >= 0:
            self.view.go_to(l["page"])

    def set_toc(self, toc):
        self.edit()
        try:
            self.doc.set_toc(toc)
        except Exception as e:
            QMessageBox.warning(self, tr("Bookmarks"), str(e))
        self.done(-2)

    def reorder(self, order):
        self.edit()
        self.doc.select(order)
        self.done(-1, "Pages reordered.")

    def page_action(self, key, pages):
        m = self.main
        if key == "rotate_right":
            m.rotate_pages(90, pages)
        elif key == "rotate_left":
            m.rotate_pages(-90, pages)
        elif key == "delete":
            m.delete_pages(pages)
        elif key == "extract":
            m.extract_pages(pages)
        elif key == "duplicate":
            self.edit()
            ops.duplicate_pages(self.doc, pages)
            self.done(-1)
        elif key == "insert_blank_before":
            self.edit()
            ops.insert_blank(self.doc, pages[0])
            self.done(-1)
        elif key == "insert_blank_after":
            self.edit()
            ops.insert_blank(self.doc, pages[-1] + 1)
            self.done(-1)
        elif key == "insert_file":
            m.insert_file(pages[-1] + 1)
        elif key == "to_images":
            m.to_images(pages)
        elif key == "print":
            m.print_doc(pages)

    def page_menu(self, p, pt, gpos):
        menu = QMenu(self)
        if self.view.selected_text():
            menu.addAction(icon("extracttext"), tr("Copy"), lambda: QGuiApplication.clipboard().setText(self.view.selected_text()))
        menu.addAction(tr("Select all"), self.view.select_all_text)
        menu.addSeparator()
        menu.addAction(icon("note"), tr("Sticky note"), lambda: self.on_tool("note", p, pt))
        menu.addAction(icon("bookmark"), tr("Add bookmark"), lambda: (self.view.go_to(p, emit=False), self.books.add()))
        menu.addSeparator()
        menu.addAction(icon("rotate"), tr("Rotate right"), lambda: self.main.rotate_pages(90, [p]))
        menu.addAction(icon("extract"), tr("Extract"), lambda: self.main.extract_pages([p]))
        menu.addAction(icon("delete"), tr("Delete") + f" ({tr('Page')} {p + 1})", lambda: self.main.delete_pages([p]))
        menu.addSeparator()
        menu.addAction(icon("info"), tr("Document properties"), lambda: self.main.cmd("properties"))
        menu.exec(gpos)
