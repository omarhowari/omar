"""Side panels: thumbnails, bookmarks, comments, search, attachments and the properties pane."""
import os

import pymupdf as fitz
from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap, QColor, QAction
from PySide6.QtWidgets import (QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QWidget, QVBoxLayout,
                               QHBoxLayout, QLineEdit, QPushButton, QCheckBox, QLabel, QToolButton, QMenu,
                               QAbstractItemView, QFormLayout, QSlider, QSpinBox, QDoubleSpinBox, QPlainTextEdit,
                               QColorDialog, QComboBox, QInputDialog, QFileDialog, QMessageBox, QFrame)

from .i18n import tr
from .icons import icon
from . import ops


def _small_btn(name, tip, slot):
    b = QToolButton()
    b.setIcon(icon(name))
    b.setIconSize(QSize(18, 18))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.clicked.connect(slot)
    return b


def _header(title):
    l = QLabel(title)
    l.setObjectName("panelTitle")
    return l


# ============================================================== thumbnails
class ThumbnailPanel(QListWidget):
    pageClicked = Signal(int)
    reorderRequested = Signal(object)
    pageAction = Signal(str, list)

    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.IconMode)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Snap)
        self.setIconSize(QSize(110, 150))
        self.setGridSize(QSize(132, 186))
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setUniformItemSizes(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(lambda it: self.pageClicked.emit(self.row(it)))
        self.model().rowsMoved.connect(self._moved)
        self.doc = None
        self._todo = []
        self._timer = QTimer(self, interval=0, timeout=self._render_some)
        self._silent = False

    def set_document(self, doc):
        self.doc = doc
        self.rebuild()

    def rebuild(self):
        self._silent = True
        self.clear()
        if not self.doc:
            return
        ph = QPixmap(110, 150)
        ph.fill(QColor("#FFFFFF"))
        for i in range(self.doc.page_count):
            it = QListWidgetItem(QIcon(ph), str(i + 1))
            it.setData(Qt.UserRole, i)
            it.setTextAlignment(Qt.AlignHCenter)
            self.addItem(it)
        self._todo = list(range(self.doc.page_count))
        self._timer.start()
        self._silent = False

    def refresh_page(self, i):
        if 0 <= i < self.count():
            self._todo.insert(0, i)
            self._timer.start()

    def _render_some(self):
        for _ in range(3):
            if not self._todo or not self.doc:
                self._timer.stop()
                return
            i = self._todo.pop(0)
            if i >= self.doc.page_count or i >= self.count():
                continue
            p = self.doc[i]
            z = min(110 / p.rect.width, 150 / p.rect.height)
            pm = p.get_pixmap(matrix=fitz.Matrix(z * 1.5, z * 1.5), alpha=False)
            img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
            qp = QPixmap.fromImage(img)
            ic = QIcon(qp)
            ic.addPixmap(qp, QIcon.Selected)
            self.item(i).setIcon(ic)

    def set_current(self, i):
        if 0 <= i < self.count():
            self.blockSignals(True)
            self.setCurrentRow(i)
            self.scrollToItem(self.item(i))
            self.blockSignals(False)

    def selected_pages(self):
        rows = sorted(self.row(it) for it in self.selectedItems())
        return rows or ([self.currentRow()] if self.currentRow() >= 0 else [])

    def _moved(self, *args):
        if self._silent:
            return
        order = [self.item(r).data(Qt.UserRole) for r in range(self.count())]
        if order != list(range(len(order))):
            QTimer.singleShot(0, lambda: self.reorderRequested.emit(order))

    def _menu(self, pos):
        if not self.doc:
            return
        pages = self.selected_pages()
        m = QMenu(self)
        for key, label, ic in (("rotate_right", tr("Rotate right"), "rotate"),
                               ("rotate_left", tr("Rotate left"), "rotateleft"),
                               (None, None, None),
                               ("insert_blank_before", tr("Blank page") + " ↑", "blank"),
                               ("insert_blank_after", tr("Blank page") + " ↓", "blank"),
                               ("insert_file", tr("Insert pages from file"), "insert"),
                               ("duplicate", tr("Duplicate"), "insert"),
                               (None, None, None),
                               ("extract", tr("Extract"), "extract"),
                               ("to_images", tr("To images"), "toimages"),
                               ("print", tr("Print"), "print"),
                               (None, None, None),
                               ("delete", tr("Delete"), "delete")):
            if key is None:
                m.addSeparator()
                continue
            a = m.addAction(icon(ic), label)
            a.triggered.connect(lambda _=False, k=key: self.pageAction.emit(k, pages))
        m.exec(self.viewport().mapToGlobal(pos))


# ============================================================== bookmarks
class BookmarkPanel(QWidget):
    goTo = Signal(int, float)
    tocChanged = Signal(object)

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        bar.addWidget(_header(tr("Bookmarks")))
        bar.addStretch()
        bar.addWidget(_small_btn("bookmark", tr("Add bookmark"), self.add))
        bar.addWidget(_small_btn("text", tr("Rename"), self.rename))
        bar.addWidget(_small_btn("delete", tr("Delete"), self.delete))
        v.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.model().rowsMoved.connect(lambda *a: QTimer.singleShot(0, self._emit))
        self.tree.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.tree.itemChanged.connect(lambda *a: self._emit())
        v.addWidget(self.tree)
        self.doc = None
        self.current_page = lambda: 0
        self._silent = False

    def set_document(self, doc):
        self.doc = doc
        self.rebuild()

    def rebuild(self):
        self._silent = True
        self.tree.clear()
        if not self.doc:
            self._silent = False
            return
        stack = [(0, self.tree.invisibleRootItem())]
        for entry in self.doc.get_toc(simple=False):
            lvl, title, page = entry[:3]
            dest = entry[3] if len(entry) > 3 else {}
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            parent = stack[-1][1] if stack else self.tree.invisibleRootItem()
            it = QTreeWidgetItem(parent, [title])
            y = 0.0
            if isinstance(dest, dict) and dest.get("to") is not None:
                try:
                    y = float(dest["to"].y)
                except Exception:
                    y = 0.0
            it.setData(0, Qt.UserRole, (page, y))
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            stack.append((lvl, it))
        self.tree.expandToDepth(0)
        self._silent = False

    def _clicked(self, it):
        page, y = it.data(0, Qt.UserRole) or (1, 0)
        if page and page > 0:
            self.goTo.emit(page - 1, y)

    def _collect(self):
        toc = []

        def walk(item, lvl):
            for k in range(item.childCount()):
                c = item.child(k)
                page, _ = c.data(0, Qt.UserRole) or (1, 0)
                toc.append([lvl, c.text(0), page])
                walk(c, lvl + 1)
        walk(self.tree.invisibleRootItem(), 1)
        return toc

    def _emit(self):
        if not self._silent:
            self.tocChanged.emit(self._collect())

    def add(self):
        if not self.doc:
            return
        title, ok = QInputDialog.getText(self, tr("Add bookmark"), tr("Title"),
                                         text=f"{tr('Page')} {self.current_page() + 1}")
        if not ok or not title:
            return
        self._silent = True
        it = QTreeWidgetItem([title])
        it.setData(0, Qt.UserRole, (self.current_page() + 1, 0))
        it.setFlags(it.flags() | Qt.ItemIsEditable)
        sel = self.tree.currentItem()
        if sel and sel.parent():
            sel.parent().addChild(it)
        else:
            self.tree.addTopLevelItem(it)
        self._silent = False
        self._emit()

    def rename(self):
        it = self.tree.currentItem()
        if it:
            self.tree.editItem(it)

    def delete(self):
        it = self.tree.currentItem()
        if not it:
            return
        (it.parent() or self.tree.invisibleRootItem()).removeChild(it)
        self._emit()


# ============================================================== comments
class CommentsPanel(QWidget):
    goToAnnot = Signal(int, int)
    action = Signal(str)

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        bar.addWidget(_header(tr("Comments")))
        bar.addStretch()
        bar.addWidget(_small_btn("extracttext", tr("Summarize"), lambda: self.action.emit("summarize")))
        bar.addWidget(_small_btn("delete", tr("Delete all"), lambda: self.action.emit("delete_all")))
        v.addLayout(bar)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Search") + "…")
        self.filter.textChanged.connect(self.rebuild)
        f = QHBoxLayout()
        f.setContentsMargins(6, 0, 6, 0)
        f.addWidget(self.filter)
        v.addLayout(f)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setWordWrap(True)
        self.tree.itemClicked.connect(self._clicked)
        v.addWidget(self.tree)
        self.doc = None

    def set_document(self, doc):
        self.doc = doc
        self.rebuild()

    def rebuild(self, *_):
        self.tree.clear()
        if not self.doc:
            return
        q = self.filter.text().lower()
        pages = {}
        for c in ops.list_comments(self.doc):
            if c["type"] in ("Popup", "Link", "Widget"):
                continue
            label = f"{tr(c['type']) if c['type'] in ('Highlight',) else c['type']} · {c['author']}"
            body = c["content"] or ""
            if q and q not in (label + body).lower():
                continue
            if c["page"] not in pages:
                pages[c["page"]] = QTreeWidgetItem(self.tree, [f"{tr('Page')} {c['page'] + 1}"])
                pages[c["page"]].setFirstColumnSpanned(True)
            it = QTreeWidgetItem(pages[c["page"]], [label + ("\n" + body if body else "")])
            pm = QPixmap(10, 10)
            pm.fill(QColor(c["color"]))
            it.setIcon(0, QIcon(pm))
            it.setData(0, Qt.UserRole, (c["page"], c["xref"]))
        self.tree.expandAll()

    def _clicked(self, it):
        d = it.data(0, Qt.UserRole)
        if d:
            self.goToAnnot.emit(*d)


# ============================================================== search
class SearchPanel(QWidget):
    hitsChanged = Signal(object, object)
    goToHit = Signal(int, object)

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 6)
        v.addWidget(_header(tr("Find in document")))
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Search") + "…")
        self.edit.returnPressed.connect(self.run)
        row.addWidget(self.edit)
        row.addWidget(_small_btn("search", tr("Find"), self.run))
        v.addLayout(row)
        opts = QHBoxLayout()
        self.case = QCheckBox(tr("Match case"))
        self.whole = QCheckBox(tr("Whole words"))
        opts.addWidget(self.case)
        opts.addWidget(self.whole)
        v.addLayout(opts)
        nav = QHBoxLayout()
        self.count = QLabel("")
        nav.addWidget(self.count)
        nav.addStretch()
        nav.addWidget(_small_btn("prev", tr("Previous page"), lambda: self.step(-1)))
        nav.addWidget(_small_btn("next", tr("Next page"), lambda: self.step(1)))
        v.addLayout(nav)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemClicked.connect(self._clicked)
        v.addWidget(self.list)
        self.doc = None
        self.flat = []
        self.pos = -1

    def set_document(self, doc):
        self.doc = doc
        self.list.clear()
        self.flat = []
        self.count.setText("")

    def focus(self, text=""):
        if text:
            self.edit.setText(text)
        self.edit.setFocus()
        self.edit.selectAll()

    def run(self):
        self.list.clear()
        self.flat = []
        self.pos = -1
        q = self.edit.text().strip()
        if not self.doc or not q:
            self.hitsChanged.emit({}, None)
            self.count.setText("")
            return
        hits = {}
        import re
        for i in range(self.doc.page_count):
            page = self.doc[i]
            rects = page.search_for(q, flags=fitz.TEXT_DEHYPHENATE | fitz.TEXT_MEDIABOX_CLIP)
            if rects and (self.case.isChecked() or self.whole.isChecked()):
                keep = []
                for r in rects:
                    t = page.get_textbox(r + (-1, -1, 1, 1)).strip()
                    w = page.get_textbox(r + (-6, -1, 6, 1))
                    ok = True
                    if self.case.isChecked() and q not in t:
                        ok = False
                    if self.whole.isChecked() and re.search(r"\w" + re.escape(q) + r"|" + re.escape(q) + r"\w",
                                                            w, 0 if self.case.isChecked() else re.I):
                        ok = False
                    if ok:
                        keep.append(r)
                rects = keep
            if rects:
                hits[i] = rects
                for k, r in enumerate(rects):
                    ctx = page.get_textbox(fitz.Rect(r.x0 - 140, r.y0 + 1, r.x1 + 140, r.y1 - 1)).strip()
                    ctx = " ".join(ctx.split())[:120]
                    it = QListWidgetItem(f"{tr('Page')} {i + 1}: {ctx}")
                    it.setData(Qt.UserRole, len(self.flat))
                    self.list.addItem(it)
                    self.flat.append((i, k, r))
        self.count.setText(f"{len(self.flat)} {tr('results')}")
        self.hitsChanged.emit(hits, None)
        if self.flat:
            self.step(1)

    def step(self, d):
        if not self.flat:
            return
        self.pos = (self.pos + d) % len(self.flat)
        self.list.setCurrentRow(self.pos)
        i, k, r = self.flat[self.pos]
        self.goToHit.emit(i, (k, r))

    def _clicked(self, it):
        self.pos = it.data(Qt.UserRole) - 1
        self.step(1)


# ============================================================== attachments
class AttachmentsPanel(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        bar.addWidget(_header(tr("Attachments")))
        bar.addStretch()
        bar.addWidget(_small_btn("attach", tr("Attach file"), self.add))
        bar.addWidget(_small_btn("save", tr("Save"), self.save))
        bar.addWidget(_small_btn("delete", tr("Delete"), self.delete))
        v.addLayout(bar)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.save())
        v.addWidget(self.list)
        self.pdf = None

    def set_document(self, pdf):
        self.pdf = pdf
        self.rebuild()

    def rebuild(self):
        self.list.clear()
        if not self.pdf:
            return
        d = self.pdf.doc
        for name in d.embfile_names():
            info = d.embfile_info(name)
            it = QListWidgetItem(icon("attach"), f"{name}  ({info.get('size', 0) / 1024:,.1f} KB)")
            it.setData(Qt.UserRole, name)
            self.list.addItem(it)

    def add(self):
        if not self.pdf:
            return
        files, _ = QFileDialog.getOpenFileNames(self, tr("Attach file"))
        if not files:
            return
        self.pdf.checkpoint()
        for f in files:
            name = os.path.basename(f)
            if name in self.pdf.doc.embfile_names():
                self.pdf.doc.embfile_del(name)
            ops.add_attachment(self.pdf.doc, f)
        self.pdf.touched(-2)
        self.rebuild()

    def save(self):
        it = self.list.currentItem()
        if not it or not self.pdf:
            return
        name = it.data(Qt.UserRole)
        fn, _ = QFileDialog.getSaveFileName(self, tr("Save"), name)
        if fn:
            with open(fn, "wb") as f:
                f.write(self.pdf.doc.embfile_get(name))

    def delete(self):
        it = self.list.currentItem()
        if not it or not self.pdf:
            return
        self.pdf.checkpoint()
        self.pdf.doc.embfile_del(it.data(Qt.UserRole))
        self.pdf.touched(-2)
        self.rebuild()


# ============================================================== properties pane
class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color="#DC2626", allow_none=False):
        super().__init__()
        self.allow_none = allow_none
        self.setFixedSize(46, 26)
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, c):
        self._c = c
        if c:
            self.setStyleSheet(f"QPushButton{{background:{c};border:1px solid #94A3B8;border-radius:4px}}")
            self.setText("")
        else:
            self.setStyleSheet("QPushButton{background:#FFFFFF;border:1px dashed #94A3B8;border-radius:4px;color:#64748B}")
            self.setText("—")

    def color(self):
        return self._c

    def _pick(self):
        menu = QMenu(self)
        for c in ("#FDE047", "#86EFAC", "#93C5FD", "#F9A8D4", "#FDBA74", "#DC2626", "#2563EB",
                  "#16A34A", "#111827", "#FFFFFF"):
            pm = QPixmap(14, 14)
            pm.fill(QColor(c))
            a = menu.addAction(QIcon(pm), c)
            a.triggered.connect(lambda _=False, cc=c: (self.set_color(cc), self.colorChanged.emit(cc)))
        if self.allow_none:
            a = menu.addAction(tr("None") if tr("None") != "None" else "None")
            a.triggered.connect(lambda: (self.set_color(""), self.colorChanged.emit("")))
        menu.addSeparator()
        more = menu.addAction("…")

        def custom():
            c = QColorDialog.getColor(QColor(self._c or "#000000"), self)
            if c.isValid():
                self.set_color(c.name().upper())
                self.colorChanged.emit(self._c)
        more.triggered.connect(custom)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))


class PropertiesPanel(QWidget):
    """Edits the selected annotation, or the default style for new annotations."""
    applyRequested = Signal(object)
    deleteRequested = Signal()

    def __init__(self, style):
        super().__init__()
        self.style = style  # shared dict with defaults for new annotations
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        v.addWidget(self.title)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.stroke = ColorButton(style["color"])
        self.fill = ColorButton(style["fill"], allow_none=True)
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(int(style["opacity"] * 100))
        self.op_label = QLabel(f"{self.opacity.value()}%")
        self.opacity.valueChanged.connect(lambda v: self.op_label.setText(f"{v}%"))
        op = QHBoxLayout()
        op.addWidget(self.opacity)
        op.addWidget(self.op_label)
        self.width = QDoubleSpinBox()
        self.width.setRange(0, 20)
        self.width.setSingleStep(0.5)
        self.width.setValue(style["width"])
        self.fontsize = QSpinBox()
        self.fontsize.setRange(4, 120)
        self.fontsize.setValue(style["fontsize"])
        self.author = QLineEdit(style["author"])
        self.content = QPlainTextEdit()
        self.content.setFixedHeight(90)
        form.addRow(tr("Color"), self.stroke)
        form.addRow(tr("Fill"), self.fill)
        form.addRow(tr("Opacity"), op)
        form.addRow(tr("Width"), self.width)
        form.addRow(tr("Font size"), self.fontsize)
        form.addRow(tr("Author"), self.author)
        v.addLayout(form)
        self.content_label = QLabel(tr("Note"))
        v.addWidget(self.content_label)
        v.addWidget(self.content)
        row = QHBoxLayout()
        self.apply_btn = QPushButton(tr("Apply"))
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._apply)
        self.del_btn = QPushButton(tr("Delete"))
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self.deleteRequested.emit)
        row.addWidget(self.apply_btn)
        row.addWidget(self.del_btn)
        v.addLayout(row)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("muted")
        v.addWidget(self.info)
        v.addStretch()
        for w in (self.stroke, self.fill):
            w.colorChanged.connect(self._live_default)
        self.opacity.valueChanged.connect(self._live_default)
        self.width.valueChanged.connect(self._live_default)
        self.fontsize.valueChanged.connect(self._live_default)
        self.author.textChanged.connect(self._live_default)
        self.annot = None
        self.show_defaults()

    def _live_default(self, *_):
        if self.annot is None:
            self.style.update(color=self.stroke.color() or "#DC2626", fill=self.fill.color(),
                              opacity=self.opacity.value() / 100, width=self.width.value(),
                              fontsize=self.fontsize.value(), author=self.author.text())

    def show_defaults(self, tool_name=""):
        self.annot = None
        self.title.setText((tool_name + " — " if tool_name else "") + tr("Properties"))
        for w in (self.stroke, self.fill, self.opacity, self.width, self.fontsize, self.author):
            w.blockSignals(True)
        self.stroke.set_color(self.style["color"])
        self.fill.set_color(self.style["fill"])
        self.opacity.setValue(int(self.style["opacity"] * 100))
        self.width.setValue(self.style["width"])
        self.fontsize.setValue(self.style["fontsize"])
        self.author.setText(self.style["author"])
        for w in (self.stroke, self.fill, self.opacity, self.width, self.fontsize, self.author):
            w.blockSignals(False)
        self.content.setPlainText("")
        self.content.setEnabled(False)
        self.content_label.setEnabled(False)
        self.apply_btn.setVisible(False)
        self.del_btn.setVisible(False)
        self.info.setText("Style used for new comments and drawings.")

    def show_annot(self, annot):
        self.annot = annot
        t = annot.type[1]
        self.title.setText(f"{t} — {tr('Properties')}")
        cols = annot.colors or {}
        self.stroke.set_color(ops.rgb_to_hex(cols.get("stroke")) if cols.get("stroke") else "#000000")
        self.fill.set_color(ops.rgb_to_hex(cols.get("fill")) if cols.get("fill") else "")
        self.opacity.setValue(int((annot.opacity if annot.opacity >= 0 else 1) * 100))
        self.width.setValue((annot.border or {}).get("width", 1) or 0)
        info = annot.info
        self.author.blockSignals(True)
        self.author.setText(info.get("title", ""))
        self.author.blockSignals(False)
        self.content.setEnabled(True)
        self.content_label.setEnabled(True)
        self.content.setPlainText(info.get("content", ""))
        self.apply_btn.setVisible(True)
        self.del_btn.setVisible(True)
        page = annot.parent.number + 1
        self.info.setText(f"{tr('Page')} {page} · {ops._pdf_date(info.get('modDate') or info.get('creationDate'))}")

    def _apply(self):
        self.applyRequested.emit(dict(color=self.stroke.color(), fill=self.fill.color(),
                                      opacity=self.opacity.value() / 100, width=self.width.value(),
                                      fontsize=self.fontsize.value(), author=self.author.text(),
                                      content=self.content.toPlainText()))
