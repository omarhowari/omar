"""Main window: ribbon, document tabs, start screen, status bar and all commands."""
import datetime as _dt
import json
import os
import sys
import tempfile

import pymupdf as fitz
from PySide6.QtCore import Qt, QSize, QSettings, QTimer, QUrl, QRectF
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QImage, QPainter, QDesktopServices, QIcon, QShortcut
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QToolButton, QLabel,
                               QFrame, QStackedWidget, QFileDialog, QMessageBox, QInputDialog, QMenu, QSpinBox,
                               QComboBox, QStatusBar, QProgressDialog, QApplication, QSizePolicy, QPushButton,
                               QGridLayout, QTreeWidget, QTreeWidgetItem, QHeaderView, QDialog, QScrollArea)

from . import ops, convert, i18n
from .dialogs import (ask, PAGES_HELP, MergeDialog, SignatureDialog, DocPropertiesDialog, ReportDialog,
                      app_data_dir)
from .document import PdfDocument
from .doctab import DocTab
from .i18n import tr
from .icons import icon

APP = "Waraq PDF"
OPEN_FILTER = ("All supported (*.pdf *.xps *.oxps *.epub *.cbz *.fb2 *.svg *.png *.jpg *.jpeg *.tif *.tiff *.bmp "
               "*.gif *.webp *.txt *.md *.html *.htm *.doc *.docx *.odt *.rtf *.xls *.xlsx *.ods *.csv *.ppt *.pptx "
               "*.odp);;PDF (*.pdf);;All files (*)")

TOOLS = {"zoom_tool", "loupe", "eraser", "insert_text", "replace_text", "perimeter", "cloud", "field_button", "field_date",
         "field_image", "field_signature", "hand", "select", "snapshot", "addtext", "addimage", "edittext", "whiteout", "highlight", "underline",
         "strike", "squiggly", "area_highlight", "note", "textbox", "callout", "stamp", "rect", "oval", "line",
         "arrow", "polygon", "polyline", "ink", "link", "attach", "measure", "area_measure", "field_text",
         "field_check", "field_radio", "field_combo", "field_list", "redact", "signature", "digital_sign",
         "crop_area"}

TOOL_COLORS = {"highlight": "#FDE047", "area_highlight": "#FDE047", "underline": "#2563EB", "strike": "#DC2626",
               "squiggly": "#16A34A"}


CHECKABLE = TOOLS | {"layout_single", "layout_continuous", "layout_two", "layout_single2", "dark", "night",
                     "hide_comments", "fullscreen", "toggle_props", "rulers", "grid", "highlight_fields", "exclusive",
                     "smooth_scroll", "hand_text", "doc_tabs"}


class StartPage(QScrollArea):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        w = QWidget()
        w.setObjectName("start")
        self.setWidget(w)
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 32, 40, 32)
        v.setSpacing(22)
        hour = _dt.datetime.now().hour
        greet = "Good morning" if hour < 12 else ("Good afternoon" if hour < 18 else "Good evening")
        if i18n.LANG == "ar":
            greet = "صباح الخير" if hour < 12 else "مساء الخير"
        name = main.style["author"]
        t = QLabel(f"{greet}{', ' + name if name else ''}")
        t.setObjectName("h1")
        v.addWidget(t)
        sub = QLabel("Open a PDF, or pick a tool to start." if i18n.LANG != "ar" else "افتح ملف PDF أو اختر أداة للبدء.")
        sub.setObjectName("muted")
        v.addWidget(sub)

        drop = QFrame()
        drop.setObjectName("drop")
        dh = QHBoxLayout(drop)
        dh.setContentsMargins(24, 22, 24, 22)
        ic = QLabel()
        ic.setPixmap(icon("open", "#1D4ED8").pixmap(36, 36))
        dh.addWidget(ic)
        tx = QVBoxLayout()
        a = QLabel(tr("Drop PDF files here"))
        a.setObjectName("h2")
        b = QLabel("PDF, images, Word/Excel/PowerPoint, text and Markdown — several files open as tabs.")
        b.setObjectName("muted")
        tx.addWidget(a)
        tx.addWidget(b)
        dh.addLayout(tx, 1)
        ob = QPushButton(tr("Open file…"))
        ob.setObjectName("primary")
        ob.setMinimumHeight(40)
        ob.clicked.connect(lambda: main.cmd("open"))
        dh.addWidget(ob)
        v.addWidget(drop)

        h = QLabel(tr("Quick tools"))
        h.setObjectName("h2")
        v.addWidget(h)
        grid = QGridLayout()
        grid.setSpacing(10)
        tools = [("merge", tr("Merge"), "merge"), ("split", tr("Split"), "split"), ("compress", tr("Compress"), "compress"),
                 ("to_images", tr("To images"), "toimages"), ("images_to_pdf", tr("Images to PDF"), "imagestopdf"),
                 ("to_word", tr("To Word"), "extracttext"), ("ocr", tr("OCR"), "snapshot"),
                 ("password", tr("Password"), "lock"), ("watermark", tr("Watermark"), "watermark"),
                 ("files_to_pdf", tr("Files to PDF"), "insert"), ("scan", tr("Scan"), "snapshot"),
                 ("batch", tr("Batch tools"), "compress")]
        for k, (cmd, label, ic) in enumerate(tools):
            b = QToolButton()
            b.setObjectName("tool")
            b.setText(label)
            b.setIcon(icon(ic, "#1D4ED8"))
            b.setIconSize(QSize(26, 26))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setMinimumSize(130, 84)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, c=cmd: main.quick_tool(c))
            grid.addWidget(b, k // 6, k % 6)
        v.addLayout(grid)

        h2 = QLabel(tr("Recent files"))
        h2.setObjectName("h2")
        v.addWidget(h2)
        self.recent = QTreeWidget()
        self.recent.setHeaderLabels(["Name", "Folder", "Opened"])
        self.recent.setRootIsDecorated(False)
        self.recent.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.recent.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.recent.setMinimumHeight(220)
        self.recent.itemActivated.connect(lambda it, _c: main.open_files([it.data(0, Qt.UserRole)]))
        self.recent.itemClicked.connect(lambda it, _c: main.open_files([it.data(0, Qt.UserRole)]))
        v.addWidget(self.recent)
        v.addStretch()
        self.refresh()

    def refresh(self):
        self.recent.clear()
        for e in self.main.recent_files():
            p = e["path"]
            if not os.path.exists(p):
                continue
            it = QTreeWidgetItem([os.path.basename(p), os.path.dirname(p), e.get("when", "")])
            it.setIcon(0, icon("blank", "#DC2626"))
            it.setData(0, Qt.UserRole, p)
            self.recent.addTopLevelItem(it)


from .commands2 import Commands2Mixin


class MainWindow(Commands2Mixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Waraq", "WaraqPDF")
        self.style = dict(color="#DC2626", fill="", opacity=1.0, width=1.5, fontsize=12,
                          author=self.settings.value("author", os.environ.get("USERNAME") or os.environ.get("USER") or ""))
        self.tool_colors = dict(TOOL_COLORS)
        self.current_tool = "select"
        self.dark = self.settings.value("dark", False, type=bool)
        self.setWindowTitle(APP)
        self.setWindowIcon(app_icon())
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self.actions = {}

        self.zoom_boxes = []
        self.page_boxes = []
        self.sig_lists = []
        self.context_title = ""
        self.exclusive = self.settings.value("exclusive", False, type=bool)
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.layout_group = QActionGroup(self)
        self.frameless = not self.settings.value("native_titlebar", False, type=bool)
        central = QWidget()
        central.setObjectName("central")
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        from .ribbon import build_ribbon, TitleBar, install_edge_resize
        self.titlebar = None
        if self.frameless:
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            self.titlebar = TitleBar(self)
            cv.addWidget(self.titlebar)
            install_edge_resize(self)
        self.ribbon = build_ribbon(self)
        cv.addWidget(self.ribbon)
        self.stack = QStackedWidget()
        self.start = StartPage(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("doctabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.setLayoutDirection(Qt.LeftToRight)
        self.tabs.tabBar().setLayoutDirection(Qt.LeftToRight)
        plus = QToolButton()
        plus.setObjectName("plustab")
        plus.setText("+")
        plus.setToolTip(tr("Open"))
        plus.clicked.connect(lambda: self.cmd("open"))
        self.tabs.setCornerWidget(plus, Qt.TopRightCorner)
        home = QToolButton()
        home.setObjectName("plustab")
        home.setIcon(icon("home", "#FFFFFF"))
        home.setToolTip(tr("Start screen"))
        home.clicked.connect(lambda: self.stack.setCurrentWidget(self.start))
        self.tabs.setCornerWidget(home, Qt.TopLeftCorner)
        self.stack.addWidget(self.start)
        self.stack.addWidget(self.tabs)
        cv.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self._build_status()
        self._shortcuts()
        self.set_tool("select")
        self.actions["layout_continuous"].setChecked(True)
        for k, on in (("exclusive", self.exclusive), ("smooth_scroll", True), ("hand_text", True), ("doc_tabs", True)):
            if k in self.actions:
                self.actions[k].setChecked(on)
        if self.titlebar:
            self.titlebar.setup_completer([a.text() for a in self.actions.values()])
        self.actions["toggle_props"].setChecked(self.settings.value("props_pane", False, type=bool))
        if self.dark:
            self.actions["dark"].setChecked(True)
        self._update_state()

    # ================================================================== UI construction
    def _action(self, cmd, label, ic):
        if cmd in self.actions:
            return self.actions[cmd]
        from .icons import cicon
        a = QAction(cicon(ic), label, self)
        a.setData(ic)
        a.setToolTip(label)
        if cmd in CHECKABLE:
            a.setCheckable(True)
            if cmd in TOOLS:
                self.tool_group.addAction(a)
            if cmd.startswith("layout_"):
                self.layout_group.addAction(a)
        a.triggered.connect(lambda checked=False, c=cmd: self.cmd(c, checked))
        self.actions[cmd] = a
        return a

    def _stamp_menu(self):
        m = QMenu(self)
        for s in ops.STAMPS:
            m.addAction(s, lambda s=s: self._set_stamp(label=s, image=None))
        m.addSeparator()
        dyn = m.addAction("Dynamic (name + date)")
        dyn.setCheckable(True)
        dyn.setChecked(True)
        dyn.toggled.connect(lambda on: self._set_stamp(dynamic=on))
        m.addAction("Custom text…", self._custom_stamp)
        m.addAction("From image…", self._image_stamp)
        return m

    def _set_stamp(self, **kw):
        self.stamp_cfg = getattr(self, "stamp_cfg", dict(label="Approved", dynamic=True, image=None))
        self.stamp_cfg.update(kw)
        for t in self.doc_tabs():
            t.stamp_cfg = dict(self.stamp_cfg)
        self.set_tool("stamp")
        self.statusBar().showMessage(f"{tr('Stamp')}: {self.stamp_cfg.get('label')} — click or drag on the page", 5000)

    def _custom_stamp(self):
        t, ok = QInputDialog.getText(self, tr("Stamp"), tr("Text"))
        if ok and t:
            self._set_stamp(label=t, image=None)

    def _image_stamp(self):
        fn, _ = QFileDialog.getOpenFileName(self, tr("Stamp"), "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if fn:
            self._set_stamp(image=fn, label=os.path.basename(fn))

    def _fill_file_menu(self):
        m = self.file_menu
        m.clear()
        m.addAction(icon("open"), tr("Open") + "\tCtrl+O", lambda: self.cmd("open"))
        rec = m.addMenu(tr("Recent files"))
        for e in self.recent_files()[:15]:
            rec.addAction(e["path"], lambda p=e["path"]: self.open_files([p]))
        m.addAction(icon("save"), tr("Save") + "\tCtrl+S", lambda: self.cmd("save"))
        m.addAction(icon("saveas"), tr("Save As") + "\tCtrl+Shift+S", lambda: self.cmd("saveas"))
        m.addAction(icon("print"), tr("Print") + "\tCtrl+P", lambda: self.cmd("print"))
        m.addSeparator()
        m.addAction(icon("merge"), tr("Files to PDF"), lambda: self.cmd("files_to_pdf"))
        m.addAction(icon("snapshot"), tr("Scan"), lambda: self.cmd("scan"))
        m.addSeparator()
        m.addAction(icon("info"), tr("Document properties") + "\tCtrl+D", lambda: self.cmd("properties"))
        m.addAction(icon("compress"), tr("Batch tools"), lambda: self.cmd("batch"))
        m.addAction(icon("info"), tr("Settings"), lambda: self.cmd("settings"))
        m.addSeparator()
        m.addAction(icon("close"), tr("Close") + "\tCtrl+W", lambda: self.close_tab(self.tabs.currentIndex()))
        m.addAction("Exit", self.close)

    def _build_status(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        nav = QWidget()
        h = QHBoxLayout(nav)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        for cmd, ic in (("first", "first"), ("prev", "prev")):
            b = QToolButton()
            b.setIcon(icon(ic))
            b.setProperty("ic", ic)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, c=cmd: self.cmd(c))
            h.addWidget(b)
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.page_spin.setFixedWidth(64)
        self.page_spin.setAlignment(Qt.AlignCenter)
        self.page_spin.editingFinished.connect(lambda: self.tab() and self.tab().view.go_to(self.page_spin.value() - 1))
        h.addWidget(self.page_spin)
        self.page_total = QLabel("/ 0")
        h.addWidget(self.page_total)
        for cmd, ic in (("next", "next"), ("last", "last")):
            b = QToolButton()
            b.setIcon(icon(ic))
            b.setProperty("ic", ic)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, c=cmd: self.cmd(c))
            h.addWidget(b)
        sb.addPermanentWidget(nav)
        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        sb.addPermanentWidget(self.size_label)
        zb = QToolButton()
        zb.setIcon(icon("zoomout"))
        zb.setAutoRaise(True)
        zb.clicked.connect(lambda: self.cmd("zoomout"))
        sb.addPermanentWidget(zb)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.addItems(["25%", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%",
                                  tr("Fit width"), tr("Fit page")])
        self.zoom_combo.setFixedWidth(100)
        self.zoom_combo.activated.connect(self._zoom_combo)
        self.zoom_combo.lineEdit().returnPressed.connect(self._zoom_combo)
        sb.addPermanentWidget(self.zoom_combo)
        zi = QToolButton()
        zi.setIcon(icon("zoomin"))
        zi.setAutoRaise(True)
        zi.clicked.connect(lambda: self.cmd("zoomin"))
        sb.addPermanentWidget(zi)

    def _zoom_combo(self, *_):
        self._zoom_from(self.zoom_combo)

    def _zoom_from(self, combo):
        t = self.tab()
        if not t:
            return
        txt = combo.currentText()
        if txt == tr("Fit width"):
            t.view.set_fit("width")
        elif txt == tr("Fit page"):
            t.view.set_fit("page")
        else:
            try:
                t.view.set_zoom(float(txt.strip().rstrip("%")) / 100)
            except ValueError:
                pass

    def _shortcuts(self):
        for seq, cmd in ((QKeySequence.Open, "open"), (QKeySequence.Save, "save"), ("Ctrl+Shift+S", "saveas"),
                         (QKeySequence.Print, "print"), (QKeySequence.Undo, "undo"), ("Ctrl+Y", "redo"),
                         ("Ctrl+Shift+Z", "redo"), (QKeySequence.Find, "find"), ("Ctrl+W", "close"),
                         ("Ctrl+D", "properties"), ("Ctrl++", "zoomin"), ("Ctrl+=", "zoomin"), ("Ctrl+-", "zoomout"),
                         ("Ctrl+0", "fitpage"), ("Ctrl+1", "actual"), ("Ctrl+2", "fitwidth"), ("F11", "fullscreen"), ("Alt+Left", "back"), ("Alt+Right", "forward"),
                         ("H", "hand"), ("V", "select"), ("Ctrl+Shift+H", "highlight"), ("F3", "find_next"),
                         ("Ctrl+Tab", "next_tab"), ("Ctrl+Shift+R", "rotate_right"), ("Ctrl+Shift+L", "rotate_left"),
                         ("Ctrl+Shift+D", "delete_pages"), ("Ctrl+Shift+I", "insert_file"), ("Ctrl+T", "addtext")):
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(lambda c=cmd: self.cmd(c))

    # ================================================================== tabs & documents
    def tab(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocTab) else None

    def doc_tabs(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def recent_files(self):
        try:
            return json.loads(self.settings.value("recent", "[]"))
        except Exception:
            return []

    def _add_recent(self, path):
        rec = [e for e in self.recent_files() if e["path"] != path]
        rec.insert(0, dict(path=path, when=_dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
        self.settings.setValue("recent", json.dumps(rec[:30]))
        self.start.refresh()

    def open_files(self, paths):
        for path in paths:
            if not path:
                continue
            path = os.path.abspath(path)
            for i, t in enumerate(self.doc_tabs()):
                if t.pdf.path and os.path.normcase(t.pdf.path) == os.path.normcase(path):
                    self.tabs.setCurrentIndex(i)
                    self.stack.setCurrentWidget(self.tabs)
                    break
            else:
                try:
                    pdf = self._load(path)
                except Exception as e:
                    QMessageBox.warning(self, tr("Error"), f"{os.path.basename(path)}\n\n{e}")
                    continue
                if pdf:
                    self.add_tab(pdf)
                    if pdf.path:
                        self._add_recent(path)

    def _load(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            try:
                return PdfDocument(path)
            except PermissionError:
                for _ in range(3):
                    pw, ok = QInputDialog.getText(self, tr("Password"), f"{os.path.basename(path)}:",
                                                  echo=QInputDialog.Password if hasattr(QInputDialog, "Password") else 2)
                    if not ok:
                        return None
                    try:
                        return PdfDocument(path, password=pw)
                    except PermissionError:
                        continue
                return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            doc = ops.open_any(path)
        finally:
            QApplication.restoreOverrideCursor()
        pdf = PdfDocument(doc=doc)
        pdf.suggested = os.path.splitext(path)[0] + ".pdf"
        pdf.set_modified(True)
        return pdf

    def add_tab(self, pdf, title=None):
        t = DocTab(pdf, self.style, self)
        t.stamp_cfg = dict(getattr(self, "stamp_cfg", t.stamp_cfg))
        t.status.connect(lambda m: self.statusBar().showMessage(m, 6000))
        t.stateChanged.connect(self._update_state)
        t.view.zoomChanged.connect(lambda z: self._update_state())
        t.view.set_tool(self.current_tool)
        t.view.night = self.actions["night"].isChecked()
        t.view.show_annots = not self.actions["hide_comments"].isChecked()
        t.props.setVisible(self.actions["toggle_props"].isChecked())
        lay = "single" if self.actions["layout_single"].isChecked() else (
            "two" if self.actions["layout_two"].isChecked() else "continuous")
        t.view.layout_mode = lay
        i = self.tabs.addTab(t, icon("blank", "#DC2626"), title or pdf.title)
        self.tabs.setCurrentIndex(i)
        self.stack.setCurrentWidget(self.tabs)
        QTimer.singleShot(50, lambda: t.view.set_fit("width"))
        self._update_state()
        return t

    def close_tab(self, i):
        if i < 0:
            return
        t = self.tabs.widget(i)
        if t.pdf.is_modified():
            r = QMessageBox.question(self, tr("Unsaved changes"), f"{tr('Save changes to')} {t.pdf.title}?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save and not self.save(t):
                return False
        self.tabs.removeTab(i)
        t.pdf.close()
        t.deleteLater()
        if self.tabs.count() == 0:
            self.stack.setCurrentWidget(self.start)
        self._update_state()
        return True

    def closeEvent(self, e):
        while self.tabs.count():
            if self.close_tab(0) is False:
                e.ignore()
                return
        self.settings.setValue("author", self.style["author"])
        e.accept()

    def _tab_changed(self, *_):
        self.refresh_signatures()
        t = self.tab()
        if t:
            t.view.set_tool(self.current_tool)
        self._update_state()

    def _update_state(self):
        t = self.tab()
        has = t is not None
        for i, tt in enumerate(self.doc_tabs()):
            self.tabs.setTabText(i, ("● " if tt.pdf.is_modified() else "") + tt.pdf.title)
        if has:
            n = t.doc.page_count
            self.page_spin.setMaximum(max(1, n))
            self.page_spin.setValue(t.view.current + 1)
            self.page_total.setText(f"/ {n}")
            for pb in self.page_boxes:
                if not pb.hasFocus():
                    pb.setText(f"{t.view.current + 1} / {n}")
            for zb in [self.zoom_combo] + self.zoom_boxes:
                zb.setEditText(f"{t.view.zoom * 100:.2f}%".replace(".00%", "%"))
            if n:
                r = t.doc[t.view.current].rect
                self.size_label.setText(f"{r.width / ops.MM:.0f} × {r.height / ops.MM:.0f} mm")
            self.setWindowTitle(f"{t.pdf.title}{' *' if t.pdf.is_modified() else ''} - {APP}")
        else:
            self.page_total.setText("/ 0")
            self.size_label.setText("")
            self.setWindowTitle(APP)

    def setWindowTitle(self, t):
        super().setWindowTitle(t)
        if getattr(self, "titlebar", None):
            self.titlebar.set_title(t)

    def changeEvent(self, e):
        super().changeEvent(e)
        if getattr(self, "titlebar", None) and e.type() == e.Type.WindowStateChange:
            self.titlebar.btns[1].setText("❐" if self.isMaximized() else "☐")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.open_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ================================================================== tools
    def set_tool(self, tool):
        if self.current_tool in TOOL_COLORS or self.current_tool in self.tool_colors:
            self.tool_colors[self.current_tool] = self.style["color"]
        elif self.current_tool not in ("select", "hand"):
            self.tool_colors["_shape"] = self.style["color"]
        self.current_tool = tool
        if tool in self.tool_colors:
            self.style["color"] = self.tool_colors[tool]
            if tool in ("highlight", "area_highlight"):
                self.style["opacity"] = min(self.style["opacity"], 1.0)
        elif tool not in ("select", "hand"):
            self.style["color"] = self.tool_colors.get("_shape", "#DC2626")
        if tool in self.actions:
            self.actions[tool].setChecked(True)
        self._show_format(tool not in ("select", "hand", "snapshot"), self.actions[tool].text() if tool in self.actions else "")
        if tool not in ("select", "hand", "snapshot"):
            st = self.style
            self.ribbon.format_page.load(st["color"], st["fill"], st["width"], st["opacity"], st["fontsize"])
        for t in self.doc_tabs():
            t.view.set_tool(tool)
            if not t.view.sel_annot:
                label = self.actions[tool].text() if tool in self.actions else ""
                t.props.show_defaults(label if tool not in ("select", "hand") else "")

    # ================================================================== contextual format tab
    def _show_format(self, on, title=""):
        rib = self.ribbon
        rib.ctx_stack.setCurrentIndex(1 if on else 0)
        if not title:
            a = self.actions.get(self.current_tool)
            title = a.text() if a else ""
        self.context_title = title
        rib.setTabToolTip(rib.bar.contextual, title)
        if self.titlebar:
            self.titlebar.update()

    def annot_selected(self, annot):
        """Called by DocTab when an annotation gets selected (None = cleared)."""
        if annot is None:
            self._show_format(self.current_tool not in ("select", "hand", "snapshot"))
            return
        cols = annot.colors or {}
        self.ribbon.format_page.load(ops.rgb_to_hex(cols.get("stroke")) if cols.get("stroke") else "#000000",
                                     ops.rgb_to_hex(cols.get("fill")) if cols.get("fill") else "",
                                     (annot.border or {}).get("width", 1) or 0,
                                     annot.opacity if annot.opacity >= 0 else 1, self.style["fontsize"])
        self._show_format(True, annot.type[1])

    def format_changed(self, v):
        t = self.tab()
        if t and t.view.sel_annot:
            p, xref = t.view.sel_annot
            a = ops.load_annot(t.doc, p, xref)
            if a is None:
                return
            vals = dict(v, author=a.info.get("title", ""), content=a.info.get("content", ""))
            t.apply_props(vals)
        else:
            self.style.update(color=v["color"], fill=v["fill"], width=v["width"], opacity=v["opacity"],
                              fontsize=v["fontsize"])
            for tt in self.doc_tabs():
                if not tt.view.sel_annot:
                    tt.props.show_defaults()

    def do_delete_selected(self):
        t = self._need()
        t and t.delete_selected()

    # ================================================================== menus for ribbon buttons
    def _recent_menu(self):
        m = QMenu(self)

        def fill():
            m.clear()
            for e in self.recent_files()[:15]:
                m.addAction(icon("blank", "#DC2626"), e["path"], lambda p=e["path"]: self.open_files([p]))
        m.aboutToShow.connect(fill)
        return m

    def _clipboard_menu(self):
        m = QMenu(self)
        m.addAction(icon("extracttext"), tr("Copy text"), lambda: self.cmd("clipboard"))
        m.addAction(icon("image"), tr("Copy page as image"), lambda: self.cmd("copy_page_image"))
        m.addAction(icon("insert"), tr("Paste image as stamp"), lambda: self.cmd("paste_image"))
        m.addAction(icon("blank"), tr("New document from clipboard"), lambda: self.cmd("new_from_clipboard"))
        return m

    def _search_menu(self):
        m = QMenu(self)
        m.addAction(icon("search"), tr("Find") + "\tCtrl+F", lambda: self.cmd("find"))
        m.addAction(icon("search"), tr("Find next") + "\tF3", lambda: self.cmd("find_next"))
        m.addAction(icon("redact"), tr("Search & redact"), lambda: self.cmd("search_redact"))
        return m

    def _weblinks_menu(self):
        m = QMenu(self)
        m.addAction(icon("web"), tr("Create links from URLs"), lambda: self.cmd("web_links"))
        m.addAction(icon("delete"), tr("Remove all links"), lambda: self.cmd("remove_links"))
        return m

    def _signature_menu(self):
        m = QMenu(self)
        m.addAction(tr("New signature…"), self.new_signature)
        return m

    # ================================================================== extra commands (PDF-XChange-like tabs)
    def do_select_objects(self):
        self.set_tool("select")

    def do_select_comments(self):
        self.set_tool("select")
        t = self.tab()
        if t:
            t.show_panel(2)

    def do_clipboard(self):
        t = self._need()
        if t:
            txt = t.view.selected_text()
            if txt:
                QApplication.clipboard().setText(txt)
                self.statusBar().showMessage(tr("Copied"), 2000)
            else:
                self.statusBar().showMessage(tr("Select text first (Select text tool)"), 4000)

    def do_copy_page_image(self):
        t = self._need()
        if t:
            pm = t.doc[t.view.current].get_pixmap(dpi=150, alpha=False)
            QApplication.clipboard().setImage(QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy())
            self.statusBar().showMessage(tr("Copied"), 2000)

    def do_paste_image(self):
        t = self._need()
        img = QApplication.clipboard().image()
        if not t or img.isNull():
            self.statusBar().showMessage(tr("No image in clipboard"), 3000)
            return
        tmp = os.path.join(tempfile.mkdtemp(), "clip.png")
        img.save(tmp)
        page = t.doc[t.view.current]
        r = page.rect
        w = min(r.width * 0.5, img.width() * 0.75)
        h = w * img.height() / max(img.width(), 1)
        rect = fitz.Rect(r.x0 + (r.width - w) / 2, r.y0 + (r.height - h) / 2, r.x0 + (r.width + w) / 2, r.y0 + (r.height + h) / 2)
        t.pdf.checkpoint()
        ops.add_stamp(page, rect * page.derotation_matrix, "Image", self.style["author"], image_path=tmp)
        t.done(t.view.current)

    def do_new_from_clipboard(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            self.statusBar().showMessage(tr("No image in clipboard"), 3000)
            return
        tmp = os.path.join(tempfile.mkdtemp(), "clip.png")
        img.save(tmp)
        pdf = PdfDocument(doc=ops.images_to_pdf([tmp]))
        pdf.suggested = "Clipboard.pdf"
        pdf.set_modified(True)
        self.add_tab(pdf)

    def _panel(self, i):
        t = self._need()
        if t:
            t.show_panel(i)

    def do_panel_thumbs(self):
        self._panel(0)

    def do_panel_bookmarks(self):
        self._panel(1)

    def do_panel_comments(self):
        self._panel(2)

    def do_panel_search(self):
        self._panel(3)

    def do_panel_attach(self):
        self._panel(4)

    def do_back(self):
        t = self._need()
        t and t.view.nav(-1)

    def do_forward(self):
        t = self._need()
        t and t.view.nav(1)

    def do_add_bookmark(self):
        t = self._need()
        if t:
            if not (t.stack.isVisible() and t.stack.currentIndex() == 1):
                t.show_panel(1)
            t.books.add()

    def do_delete_bookmarks(self):
        t = self._need()
        if t and t.doc.get_toc() and QMessageBox.question(self, tr("Bookmarks"), tr("Delete all bookmarks?")) == QMessageBox.Yes:
            t.pdf.checkpoint()
            t.doc.set_toc([])
            t.done(-1)

    def do_split_bookmarks(self):
        t = self._need()
        if not t:
            return
        folder = QFileDialog.getExistingDirectory(self, tr("Output folder"), os.path.dirname(t.pdf.path or ""))
        if not folder:
            return
        parts, idx = ops.split_doc(t.doc, "bookmarks")
        toc = {e[2] - 1: e[1] for e in t.doc.get_toc() if e[0] == 1}
        base = os.path.splitext(t.pdf.title)[0]
        for k, (p, pages) in enumerate(zip(parts, idx)):
            name = "".join(c for c in toc.get(pages[0], "") if c not in '\\/:*?"<>|')[:40]
            p.save(os.path.join(folder, f"{base}_{k + 1:03d}{'_' + name if name else ''}.pdf"), garbage=3, deflate=True)
        QMessageBox.information(self, tr("Split"), f"{len(parts)} ✓")

    def do_web_links(self):
        t = self._need()
        if not t:
            return
        import re
        rx = re.compile(r"(https?://[^\s<>\"]+|www\.[^\s<>\"]+)")
        t.pdf.checkpoint()
        n = 0
        for page in t.doc:
            existing = [fitz.Rect(l["from"]) for l in page.get_links()]
            for url in set(m.group(0).rstrip(".,);") for m in rx.finditer(page.get_text())):
                for r in page.search_for(url):
                    if any(r.intersects(e) for e in existing):
                        continue
                    page.insert_link({"kind": fitz.LINK_URI, "from": r,
                                      "uri": url if url.startswith("http") else "http://" + url})
                    n += 1
        t.done(-1, f"{n} " + tr("links created"))

    def do_remove_links(self):
        t = self._need()
        if not t:
            return
        t.pdf.checkpoint()
        n = 0
        for page in t.doc:
            for l in page.get_links():
                page.delete_link(l)
                n += 1
        t.done(-1, f"{n} " + tr("links removed"))

    def do_email(self):
        t = self._need()
        if not t:
            return
        if t.pdf.is_modified() or not t.pdf.path:
            if not self.save(t):
                return
        path = os.path.abspath(t.pdf.path)
        sent = False
        if sys.platform.startswith("win"):
            try:
                import win32com.client
                ol = win32com.client.Dispatch("Outlook.Application")
                mail = ol.CreateItem(0)
                mail.Subject = os.path.basename(path)
                mail.Attachments.Add(path)
                mail.Display()
                sent = True
            except Exception:
                sent = False
        if not sent:
            QApplication.clipboard().setText(path)
            QDesktopServices.openUrl(QUrl(f"mailto:?subject={os.path.basename(path)}"))
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
            self.statusBar().showMessage(tr("File path copied — attach it to the email"), 8000)

    def do_open_folder(self):
        t = self._need()
        if t and t.pdf.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(t.pdf.path)))

    def do_copy_path(self):
        t = self._need()
        if t and t.pdf.path:
            QApplication.clipboard().setText(t.pdf.path)
            self.statusBar().showMessage(tr("Copied"), 2000)

    def do_word_count(self):
        t = self._need()
        if not t:
            return
        txt = ops.to_text(t.doc)
        words = len(txt.split())
        chars = len(txt.replace("\n", "").replace("\f", ""))
        QMessageBox.information(self, tr("Word count"), f"{tr('Pages')}: {t.doc.page_count}\n{tr('Words')}: {words:,}\n"
                                                        f"{tr('Characters')}: {chars:,}")

    def do_compare(self):
        t = self._need()
        if not t:
            return
        fn, _ = QFileDialog.getOpenFileName(self, tr("Compare documents"), os.path.dirname(t.pdf.path or ""), "PDF (*.pdf)")
        if not fn:
            return
        from .ops import compare_documents
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out, stats = compare_documents(t.doc, fitz.open(fn))
        finally:
            QApplication.restoreOverrideCursor()
        pdf = PdfDocument(doc=out)
        pdf.suggested = os.path.splitext(t.pdf.title)[0] + "_compare.pdf"
        pdf.set_modified(True)
        self.add_tab(pdf)
        QMessageBox.information(self, tr("Compare documents"),
                                f"{tr('Inserted')}: {stats['inserted']}\n{tr('Deleted')}: {stats['deleted']}\n"
                                f"{tr('Changed pages')}: {stats['pages']}")

    def _tts(self):
        if not hasattr(self, "_speech"):
            try:
                from PySide6.QtTextToSpeech import QTextToSpeech
                self._speech = QTextToSpeech(self)
                for loc in self._speech.availableLocales():
                    if loc.name().startswith("ar") and i18n.LANG == "ar":
                        self._speech.setLocale(loc)
            except Exception:
                self._speech = None
        return self._speech

    def _speak(self, text):
        sp = self._tts()
        if sp is None:
            QMessageBox.warning(self, tr("Read aloud"), tr("Text-to-speech is not available on this system."))
            return
        sp.say(text[:20000])

    def do_read_aloud(self):
        t = self._need()
        t and self._speak(t.doc[t.view.current].get_text("text", sort=True))

    def do_read_selection(self):
        t = self._need()
        if t:
            txt = t.view.selected_text()
            self._speak(txt) if txt else self.statusBar().showMessage(tr("Select text first (Select text tool)"), 4000)

    def do_stop_reading(self):
        sp = self._tts()
        sp and sp.stop()

    def do_help(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for c in (os.path.join(here, "README.md"), os.path.join(os.path.dirname(sys.executable), "README.md")):
            if os.path.exists(c):
                QDesktopServices.openUrl(QUrl.fromLocalFile(c))
                return
        self.do_shortcuts()

    def do_shortcuts(self):
        rows = [("Ctrl+O", tr("Open")), ("Ctrl+S", tr("Save")), ("Ctrl+Shift+S", tr("Save As")), ("Ctrl+P", tr("Print")),
                ("Ctrl+F / F3", tr("Search")), ("Ctrl+Z / Ctrl+Y", tr("Undo") + " / " + tr("Redo")),
                ("H / V", tr("Hand") + " / " + tr("Select")), ("Ctrl+Shift+H", tr("Highlight")), ("Ctrl+T", tr("Add text")),
                ("Ctrl+Shift+R / L", tr("Rotate right") + " / " + tr("Rotate left")), ("Ctrl+Shift+D", tr("Delete")),
                ("Ctrl+Shift+I", tr("Insert")), ("Ctrl+D", tr("Document properties")),
                ("Ctrl+0 / 1 / 2", tr("Fit page") + " / " + tr("Actual size") + " / " + tr("Fit width")),
                ("Alt+← / Alt+→", tr("Previous view") + " / " + tr("Next view")), ("F11", tr("Full screen")),
                ("Delete", tr("Delete") + " (" + tr("Comment") + ")"), ("Esc", tr("Cancel"))]
        ReportDialog(self, tr("Keyboard shortcuts"), "\n".join(f"{k:<22} {v}" for k, v in rows)).exec()

    def do_about(self):
        from . import __version__
        QMessageBox.about(self, tr("About"), f"<h3>Waraq PDF {__version__}</h3><p>{tr('PDF editor and tools')}</p>"
                                             f"<p>Python · PySide6 · PyMuPDF</p>")

    # ================================================================== command dispatch
    def cmd(self, c, checked=False):
        if c in TOOLS:
            if c in ("digital_sign",) and not self._need():
                return
            return self.set_tool(c)
        fn = getattr(self, "do_" + c, None)
        if fn is None:
            self.statusBar().showMessage(f"{c}: not available", 3000)
            return
        try:
            fn()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, tr("Error"), str(e))
        self._update_state()

    def _need(self):
        t = self.tab()
        if not t:
            self.statusBar().showMessage(tr("No document"), 3000)
        return t

    def quick_tool(self, c):
        """Start-screen tools: if no document is open, ask for one first where needed."""
        needs_doc = {"split", "compress", "to_images", "to_word", "ocr", "password", "watermark"}
        if c in needs_doc and not self.tab():
            fn, _ = QFileDialog.getOpenFileName(self, tr("Open"), "", "PDF (*.pdf)")
            if not fn:
                return
            self.open_files([fn])
        self.cmd(c)

    # ---- file
    def do_open(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Open"), self.settings.value("lastdir", ""), OPEN_FILTER)
        if files:
            self.settings.setValue("lastdir", os.path.dirname(files[0]))
            self.open_files(files)

    def save(self, t, as_new=False, path=None):
        if not path and (as_new or not t.pdf.path):
            sugg = t.pdf.path or getattr(t.pdf, "suggested", "") or os.path.join(self.settings.value("lastdir", ""), t.pdf.title)
            path, _ = QFileDialog.getSaveFileName(self, tr("Save As"), sugg, "PDF (*.pdf)")
            if not path:
                return False
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            t.pdf.save(path)
        finally:
            QApplication.restoreOverrideCursor()
        t.view.invalidate(-1)
        self._add_recent(t.pdf.path)
        self.statusBar().showMessage(f"{tr('Save')}: {t.pdf.path}", 5000)
        self._update_state()
        return True

    def do_save(self):
        if self._need():
            self.save(self.tab())

    def do_saveas(self):
        if self._need():
            self.save(self.tab(), as_new=True)

    def do_close(self):
        self.close_tab(self.tabs.currentIndex())

    def do_next_tab(self):
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % self.tabs.count())

    def do_start(self):
        self.stack.setCurrentWidget(self.start)

    def do_print(self, pages=None):
        t = self._need()
        if not t:
            return
        self.print_doc(pages)

    def print_doc(self, pages=None):
        t = self.tab()
        doc = t.doc
        pr = QPrinter(QPrinter.HighResolution)
        pr.setDocName(t.pdf.title)
        dlg = QPrintDialog(pr, self)
        dlg.setMinMax(1, doc.page_count)
        dlg.setOption(QPrintDialog.PrintPageRange, True)
        dlg.setOption(QPrintDialog.PrintCurrentPage, True)
        if pages:
            pr.setFromTo(pages[0] + 1, pages[-1] + 1)
        if dlg.exec() != QDialog.Accepted:
            return
        if pr.printRange() == QPrinter.PageRange:
            pages = list(range(pr.fromPage() - 1, pr.toPage()))
        elif pr.printRange() == QPrinter.CurrentPage:
            pages = [t.view.current]
        elif not pages:
            pages = list(range(doc.page_count))
        dpi = min(300, pr.resolution())
        painter = QPainter()
        if not painter.begin(pr):
            return
        prog = QProgressDialog(tr("Print") + "…", tr("Cancel"), 0, len(pages), self)
        prog.setWindowModality(Qt.WindowModal)
        try:
            for k, i in enumerate(pages):
                if prog.wasCanceled():
                    break
                prog.setValue(k)
                if k:
                    pr.newPage()
                pm = doc[i].get_pixmap(dpi=dpi, alpha=False)
                img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888)
                area = painter.viewport()
                landscape_img = img.width() > img.height()
                if landscape_img and area.width() < area.height():
                    from PySide6.QtGui import QTransform
                    img = img.transformed(QTransform().rotate(90))
                s = min(area.width() / img.width(), area.height() / img.height())
                w, h = img.width() * s, img.height() * s
                painter.drawImage(QRectF((area.width() - w) / 2, (area.height() - h) / 2, w, h), img)
        finally:
            painter.end()
            prog.setValue(len(pages))
        self.statusBar().showMessage(f"{len(pages)} pages sent to printer.", 5000)

    def do_properties(self):
        t = self._need()
        if not t:
            return
        d = DocPropertiesDialog(self, t.doc, t.pdf.path)
        if d.exec():
            t.pdf.checkpoint()
            ops.set_properties(t.doc, **d.values())
            if d.front.value():
                ops.page_labels_roman_front(t.doc, d.front.value())
            t.done(-2, tr("Document properties") + " ✓")

    def do_settings(self):
        v = ask(self, tr("Settings"), [
            ("author", tr("Author"), "text", self.style["author"]),
            ("lang", tr("Language"), "choice", i18n.LANG, [("en", "English"), ("ar", "العربية")]),
            ("dark", tr("Dark mode"), "bool", self.dark),
            ("native", tr("Use Windows title bar"), "bool", not self.frameless)])
        if v:
            self.style["author"] = v["author"]
            self.settings.setValue("author", v["author"])
            if v["dark"] != self.dark:
                self.do_dark(v["dark"])
            if v["native"] == self.frameless:
                self.settings.setValue("native_titlebar", v["native"])
                QMessageBox.information(self, tr("Settings"), tr("Restart Waraq PDF to apply."))
            if v["lang"] != i18n.LANG:
                self.settings.setValue("lang", v["lang"])
                QMessageBox.information(self, tr("Language"), "Restart Waraq PDF to apply the language. \nأعد تشغيل البرنامج لتطبيق اللغة.")

    def do_language(self):
        new = "ar" if i18n.LANG == "en" else "en"
        self.settings.setValue("lang", new)
        QMessageBox.information(self, "Language / اللغة",
                                "The interface language will change after restarting Waraq PDF.\n"
                                "ستتغير لغة الواجهة بعد إعادة تشغيل البرنامج.")

    # ---- edit
    def do_undo(self):
        t = self._need()
        if t and t.pdf.can_undo():
            t.pdf.undo()
            self.statusBar().showMessage(tr("Undo"), 2000)

    def do_redo(self):
        t = self._need()
        if t and t.pdf.can_redo():
            t.pdf.redo()

    def do_find(self):
        t = self._need()
        if t:
            t.show_panel(3) if not (t.stack.isVisible() and t.stack.currentIndex() == 3) else t.search.focus()

    def do_find_next(self):
        t = self._need()
        if t:
            t.search.step(1)

    # ---- navigation & view
    def do_first(self):
        t = self._need()
        t and t.view.go_to(0)

    def do_last(self):
        t = self._need()
        t and t.view.go_to(t.doc.page_count - 1)

    def do_prev(self):
        t = self._need()
        t and t.view.go_to(t.view.current - 1)

    def do_next(self):
        t = self._need()
        t and t.view.go_to(t.view.current + 1)

    def do_zoomin(self):
        t = self._need()
        t and t.view.set_zoom(t.view.zoom * 1.2)

    def do_zoomout(self):
        t = self._need()
        t and t.view.set_zoom(t.view.zoom / 1.2)

    def do_fitwidth(self):
        t = self._need()
        t and t.view.set_fit("width")

    def do_fitpage(self):
        t = self._need()
        t and t.view.set_fit("page")

    def do_actual(self):
        t = self._need()
        t and t.view.set_zoom(1.0)

    def _layout(self, mode):
        for t in self.doc_tabs():
            t.view.set_layout(mode)

    def do_layout_single(self):
        self._layout("single")

    def do_layout_continuous(self):
        self._layout("continuous")

    def do_layout_two(self):
        self._layout("two")

    def do_dark(self, on=None):
        on = self.actions["dark"].isChecked() if on is None else on
        self.actions["dark"].setChecked(on)
        self.dark = on
        self.settings.setValue("dark", on)
        from .theme import apply_theme
        apply_theme(QApplication.instance(), on)
        for a in self.actions.values():
            if a.data():
                a.setIcon(icon(a.data()))
        for b in self.findChildren(QToolButton):
            if b.property("ic"):
                b.setIcon(icon(b.property("ic")))
        for t in self.doc_tabs():
            t.view.setBackgroundBrush(QColor_("#2B2F36" if on else "#C9D0DA"))

    def do_night(self):
        on = self.actions["night"].isChecked()
        for t in self.doc_tabs():
            t.view.set_night(on)

    def do_hide_comments(self):
        on = self.actions["hide_comments"].isChecked()
        for t in self.doc_tabs():
            t.view.show_annots = not on
            t.view.rendered.clear()
            t.view._render_visible()

    def do_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.ribbon.setVisible(True)
            self.titlebar and self.titlebar.setVisible(True)
            self.actions["fullscreen"].setChecked(False)
        else:
            self.showFullScreen()
            self.ribbon.setVisible(False)
            self.titlebar and self.titlebar.setVisible(False)
            self.actions["fullscreen"].setChecked(True)
            self.statusBar().showMessage("F11 to leave full screen", 4000)

    def do_toggle_props(self):
        on = self.actions["toggle_props"].isChecked()
        self.settings.setValue("props_pane", on)
        for t in self.doc_tabs():
            t.props.setVisible(on)

    # ---- comments
    def do_summarize(self):
        t = self._need()
        if not t:
            return
        html = ops.summarize_comments(t.doc, f"{tr('Comments summary')} — {t.pdf.title}")
        fn, _ = QFileDialog.getSaveFileName(self, tr("Summarize"), os.path.splitext(t.pdf.title)[0] + "_comments.html",
                                            "HTML (*.html);;PDF (*.pdf)")
        if not fn:
            return
        if fn.lower().endswith(".pdf"):
            tmp = os.path.join(tempfile.mkdtemp(), "s.html")
            open(tmp, "w", encoding="utf-8").write(html)
            ops.text_to_pdf(tmp).save(fn)
        else:
            open(fn, "w", encoding="utf-8").write(html)
        QDesktopServices.openUrl(QUrl.fromLocalFile(fn))

    def do_export_comments(self):
        t = self._need()
        if not t:
            return
        fn, _ = QFileDialog.getSaveFileName(self, tr("Export comments"), os.path.splitext(t.pdf.title)[0] + "_comments.pdf",
                                            "PDF containing only comments (*.pdf);;JSON list (*.json)")
        if not fn:
            return
        if fn.lower().endswith(".json"):
            json.dump(ops.list_comments(t.doc), open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        else:
            # copy of the document holding only the annotations (re-importable)
            out = fitz.open("pdf", t.doc.tobytes())
            for p in out:
                for x in p.get_contents():
                    out.update_stream(x, b"")
            out.save(fn, garbage=4, deflate=True)
        self.statusBar().showMessage(f"{tr('Export comments')}: {fn}", 5000)

    def do_import_comments(self):
        t = self._need()
        if not t:
            return
        fn, _ = QFileDialog.getOpenFileName(self, tr("Import comments"), "", "PDF (*.pdf)")
        if not fn:
            return
        src = fitz.open(fn)
        t.pdf.checkpoint()
        n = 0
        for i in range(min(src.page_count, t.doc.page_count)):
            sp, dp = src[i], t.doc[i]
            for a in sp.annots():
                typ = a.type[1]
                info = a.info
                cols = a.colors
                try:
                    if typ in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
                        q = a.vertices
                        quads = [fitz.Quad(q[k:k + 4]) for k in range(0, len(q), 4)]
                        fn_ = {"Highlight": dp.add_highlight_annot, "Underline": dp.add_underline_annot,
                               "StrikeOut": dp.add_strikeout_annot, "Squiggly": dp.add_squiggly_annot}[typ]
                        na = fn_(quads=quads)
                    elif typ == "Text":
                        na = dp.add_text_annot(a.rect.tl, info.get("content", ""))
                    elif typ == "Square":
                        na = dp.add_rect_annot(a.rect)
                    elif typ == "Circle":
                        na = dp.add_circle_annot(a.rect)
                    elif typ == "FreeText":
                        na = dp.add_freetext_annot(a.rect, info.get("content", ""), fontsize=11)
                    elif typ == "Ink":
                        na = dp.add_ink_annot(a.vertices)
                    elif typ == "Line":
                        v = a.vertices
                        na = dp.add_line_annot(v[0], v[1])
                    elif typ == "Polygon":
                        na = dp.add_polygon_annot(a.vertices)
                    elif typ == "PolyLine":
                        na = dp.add_polyline_annot(a.vertices)
                    else:
                        continue
                    try:
                        na.set_colors(stroke=cols.get("stroke"), fill=cols.get("fill") or None)
                    except Exception:
                        pass
                    na.set_opacity(a.opacity if a.opacity >= 0 else 1)
                    na.set_info(info)
                    na.update()
                    n += 1
                except Exception:
                    continue
        t.done(-1, f"{n} comments imported.")

    def do_flatten(self):
        t = self._need()
        if not t:
            return
        if QMessageBox.question(self, tr("Flatten"), "Make all comments, stamps and form fields a permanent part of the "
                                                     "pages? They can no longer be edited.") != QMessageBox.Yes:
            return
        t.pdf.checkpoint()
        ops.flatten(t.doc)
        t.done(-1, tr("Flatten") + " ✓")

    def do_delete_comments(self):
        t = self._need()
        if not t:
            return
        if QMessageBox.question(self, tr("Delete all"), "Delete all comments in this document?") != QMessageBox.Yes:
            return
        t.pdf.checkpoint()
        n = ops.delete_annotations(t.doc)
        t.done(-1, f"{n} comments deleted.")

    # ---- page organisation
    def _ask_pages(self, title, extra=(), default=None):
        t = self.tab()
        sel = t.thumbs.selected_pages() if t.thumbs.isVisible() else [t.view.current]
        if default is None:
            default = ",".join(str(p + 1) for p in sel) if sel else str(t.view.current + 1)
        v = ask(self, title, [("pages", tr("Pages to process"), "text", default)] + list(extra), help_text=PAGES_HELP)
        if not v:
            return None, None
        pages = ops.parse_ranges(v["pages"], t.doc.page_count)
        if not pages:
            QMessageBox.warning(self, title, "No valid pages.")
            return None, None
        return pages, v

    def rotate_pages(self, angle, pages=None):
        t = self._need()
        if not t:
            return
        pages = pages if pages is not None else (t.thumbs.selected_pages() or [t.view.current])
        t.pdf.checkpoint()
        ops.rotate_pages(t.doc, pages, angle)
        t.done(-1, f"{len(pages)} pages rotated.")

    def do_rotate_right(self):
        t = self._need()
        if t:
            pages, _ = self._ask_pages(tr("Rotate right"))
            if pages:
                self.rotate_pages(90, pages)

    def do_rotate_left(self):
        t = self._need()
        if t:
            pages, _ = self._ask_pages(tr("Rotate left"))
            if pages:
                self.rotate_pages(-90, pages)

    def delete_pages(self, pages):
        t = self._need()
        if not t:
            return
        if QMessageBox.question(self, tr("Delete"), f"Delete {len(pages)} page(s)?") != QMessageBox.Yes:
            return
        t.pdf.checkpoint()
        ops.delete_pages(t.doc, pages)
        t.done(-1, f"{len(pages)} pages deleted.")

    def do_delete_pages(self):
        if self._need():
            pages, _ = self._ask_pages(tr("Delete"))
            if pages:
                self.delete_pages(pages)

    def extract_pages(self, pages, delete_after=False):
        t = self.tab()
        out = ops.extract_pages(t.doc, pages)
        r = QMessageBox.question(self, tr("Extract"), "Open the extracted pages in a new tab?\n(No = save to a file)",
                                 QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return
        if r == QMessageBox.Yes:
            pdf = PdfDocument(doc=out)
            pdf.suggested = os.path.splitext(t.pdf.path or t.pdf.title)[0] + "_extract.pdf"
            pdf.set_modified(True)
            self.add_tab(pdf, os.path.basename(pdf.suggested))
        else:
            fn, _ = QFileDialog.getSaveFileName(self, tr("Extract"),
                                                os.path.splitext(t.pdf.path or t.pdf.title)[0] + "_extract.pdf", "PDF (*.pdf)")
            if fn:
                out.save(fn, garbage=3, deflate=True)
        if delete_after:
            t.pdf.checkpoint()
            ops.delete_pages(t.doc, pages)
            t.done(-1)

    def do_extract_pages(self):
        if self._need():
            pages, v = self._ask_pages(tr("Extract"), [("delete", "Delete pages after extracting", "bool", False)])
            if pages:
                self.extract_pages(pages, v["delete"])

    def insert_file(self, at=None):
        t = self._need()
        if not t:
            return
        fn, _ = QFileDialog.getOpenFileName(self, tr("Insert pages from file"), "", OPEN_FILTER)
        if not fn:
            return
        if at is None:
            v = ask(self, tr("Insert"), [("where", "Insert", "choice", "after",
                                          [("after", "After current page"), ("before", "Before current page"),
                                           ("start", "At the beginning"), ("end", "At the end")])])
            if not v:
                return
            at = {"after": t.view.current + 1, "before": t.view.current, "start": 0, "end": t.doc.page_count}[v["where"]]
        t.pdf.checkpoint()
        n = ops.insert_file(t.doc, fn, at)
        t.done(-1, f"{n} pages inserted.")

    def do_insert_file(self):
        self.insert_file()

    def do_insert_blank(self):
        t = self._need()
        if not t:
            return
        v = ask(self, tr("Blank page"), [("count", "Count", "int", 1, (1, 500)),
                                         ("size", "Size", "choice", "same", [("same", "Same as current")] + list(ops.PAPER)),
                                         ("where", "Insert", "choice", "after", [("after", "After current page"),
                                                                                 ("before", "Before current page"),
                                                                                 ("end", "At the end")])])
        if not v:
            return
        at = {"after": t.view.current + 1, "before": t.view.current, "end": t.doc.page_count}[v["where"]]
        t.pdf.checkpoint()
        ops.insert_blank(t.doc, at, v["count"], None if v["size"] == "same" else v["size"])
        t.done(-1)
        t.view.go_to(at)

    def do_duplicate(self):
        t = self._need()
        if t:
            pages, _ = self._ask_pages(tr("Duplicate"))
            if pages:
                t.pdf.checkpoint()
                ops.duplicate_pages(t.doc, pages)
                t.done(-1)

    def do_move_pages(self):
        t = self._need()
        if not t:
            return
        pages, v = self._ask_pages(tr("Move"), [("to", "Move before page (0 = end)", "int", 1, (0, t.doc.page_count))])
        if not pages:
            return
        rest = [i for i in range(t.doc.page_count) if i not in pages]
        target = v["to"] - 1 if v["to"] else t.doc.page_count
        pos = len([i for i in rest if i < target])
        order = rest[:pos] + pages + rest[pos:]
        t.pdf.checkpoint()
        t.doc.select(order)
        t.done(-1, "Pages moved.")

    def do_reverse(self):
        t = self._need()
        if t:
            t.pdf.checkpoint()
            ops.reverse_pages(t.doc)
            t.done(-1)

    def do_crop(self):
        t = self._need()
        if not t:
            return
        r = QMessageBox.question(self, tr("Crop"), "Draw the area to keep on the page?\n\n(No = enter margins in mm)",
                                 QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if r == QMessageBox.Yes:
            self.set_tool("crop_area")
            return
        if r == QMessageBox.Cancel:
            return
        pages, v = self._ask_pages(tr("Crop"), [("l", "Left (mm)", "float", 10, (0, 500)), ("t", "Top (mm)", "float", 10, (0, 500)),
                                                ("r", "Right (mm)", "float", 10, (0, 500)), ("b", "Bottom (mm)", "float", 10, (0, 500))],
                                   default="all")
        if pages:
            t.pdf.checkpoint()
            ops.crop_pages(t.doc, pages, v["l"], v["t"], v["r"], v["b"])
            t.done(-1)

    def _replace_doc(self, t, newdoc, msg=""):
        t.pdf.checkpoint()
        old = t.pdf.doc
        t.pdf.doc = newdoc
        old.close()
        t.done(-1, msg)

    def do_resize(self):
        t = self._need()
        if not t:
            return
        pages, v = self._ask_pages(tr("Resize"), [("size", "Paper", "choice", "A4", list(ops.PAPER))], default="all")
        if pages:
            self._replace_doc(t, ops.resize_pages(t.doc, v["size"], pages), "Pages resized.")

    def do_nup(self):
        t = self._need()
        if not t:
            return
        v = ask(self, tr("N-up"), [("n", "Pages per sheet", "choice", 2, [2, 4, 6, 8, 9, 16]),
                                   ("size", "Sheet", "choice", "A4", list(ops.PAPER))])
        if v:
            out = ops.nup(t.doc, v["n"], v["size"])
            pdf = PdfDocument(doc=out)
            pdf.suggested = os.path.splitext(t.pdf.path or t.pdf.title)[0] + f"_{v['n']}up.pdf"
            pdf.set_modified(True)
            self.add_tab(pdf, os.path.basename(pdf.suggested))

    def do_delete_blank(self):
        t = self._need()
        if t:
            t.pdf.checkpoint()
            n = ops.delete_blank_pages(t.doc)
            t.done(-1, f"{n} blank pages deleted.")

    def do_merge(self):
        files = [self.tab().pdf.path] if self.tab() and self.tab().pdf.path else []
        d = MergeDialog(self, files)
        if not d.exec():
            return
        files = d.fl.files()
        if len(files) < 1:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = ops.merge_files(files, d.bm.isChecked())
        finally:
            QApplication.restoreOverrideCursor()
        pdf = PdfDocument(doc=out)
        pdf.suggested = os.path.join(os.path.dirname(files[0]), "Merged.pdf")
        pdf.set_modified(True)
        self.add_tab(pdf, "Merged.pdf")

    def do_files_to_pdf(self):
        self.do_merge()

    def do_split(self):
        t = self._need()
        if not t:
            return
        base = os.path.splitext(t.pdf.path or t.pdf.title)[0]
        v = ask(self, tr("Split"), [
            ("mode", "Split by", "choice", "every", [("every", "Every N pages"), ("ranges", "Page ranges"),
                                                     ("bookmarks", "Top-level bookmarks")]),
            ("value", "N or ranges (1-3;4-9)", "text", "1"),
            ("folder", tr("Output folder"), "folder", os.path.dirname(base) if t.pdf.path else ""),
            ("name", "File name prefix", "text", os.path.basename(base))])
        if not v or not v["folder"]:
            return
        parts, idx = ops.split_doc(t.doc, v["mode"], v["value"])
        names = []
        toc = {e[2] - 1: e[1] for e in t.doc.get_toc() if e[0] == 1}
        for k, (p, pages) in enumerate(zip(parts, idx)):
            suffix = f"{k + 1:03d}"
            if v["mode"] == "bookmarks" and pages and pages[0] in toc:
                suffix += "_" + "".join(c for c in toc[pages[0]] if c not in '\\/:*?"<>|')[:40]
            fn = os.path.join(v["folder"], f"{v['name']}_{suffix}.pdf")
            p.save(fn, garbage=3, deflate=True)
            names.append(fn)
        QMessageBox.information(self, tr("Split"), f"{len(names)} files created in\n{v['folder']}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(v["folder"]))

    def do_compress(self):
        t = self._need()
        if not t:
            return
        v = ask(self, tr("Compress"), [("dpi", "Image resolution (dpi)", "choice", 150, [72, 96, 120, 150, 200, 300]),
                                       ("q", "JPEG quality", "int", 70, (10, 100)),
                                       ("out", "Save to", "file_save",
                                        os.path.splitext(t.pdf.path or t.pdf.title)[0] + "_compressed.pdf", "PDF (*.pdf)")])
        if not v or not v["out"]:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            d = fitz.open("pdf", t.doc.tobytes())
            before = len(t.doc.tobytes(garbage=3, deflate=True))
            ops.compress(d, v["dpi"], v["q"])
            d.save(v["out"], **ops.SAVE_OPTIMIZED)
            after = os.path.getsize(v["out"])
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, tr("Compress"),
                                f"{before / 1024:,.0f} KB → {after / 1024:,.0f} KB  ({100 - after * 100 / max(before, 1):.0f}% smaller)\n{v['out']}")

    # ---- edit content
    def do_watermark(self):
        t = self._need()
        if not t:
            return
        v = ask(self, tr("Watermark"), [
            ("text", tr("Text"), "multiline", "CONFIDENTIAL"),
            ("image", "…or image", "file_open", "", "Images (*.png *.jpg *.jpeg)"),
            ("size", tr("Font size"), "int", 60, (6, 300)), ("color", tr("Color"), "color", "#9CA3AF"),
            ("opacity", tr("Opacity") + " %", "int", 30, (5, 100)), ("angle", "Angle", "int", 45, (-180, 180)),
            ("position", "Position", "choice", "center", ["center", "top", "bottom"]),
            ("behind", "Behind page content", "bool", False),
            ("pages", tr("Pages to process"), "text", "all")])
        if not v:
            return
        pages = ops.parse_ranges(v["pages"], t.doc.page_count)
        t.pdf.checkpoint()
        if v["image"]:
            ops.image_watermark(t.doc, v["image"], 0.5, pages, v["behind"])
        else:
            ops.watermark(t.doc, v["text"], v["size"], v["color"], v["opacity"] / 100, v["angle"], pages,
                          v["position"], v["behind"])
        t.done(-1, tr("Watermark") + " ✓")

    def do_background(self):
        t = self._need()
        if not t:
            return
        v = ask(self, tr("Background"), [("color", tr("Color"), "color", "#FFFBEB"),
                                         ("pages", tr("Pages to process"), "text", "all")])
        if v:
            t.pdf.checkpoint()
            ops.background_color(t.doc, v["color"], ops.parse_ranges(v["pages"], t.doc.page_count))
            t.done(-1)

    def do_header_footer(self, preset=None):
        t = self._need()
        if not t:
            return
        p = preset or {}
        v = ask(self, tr("Header/Footer"), [
            ("hl", "Header left", "text", p.get("hl", "")), ("hc", "Header center", "text", p.get("hc", "")),
            ("hr", "Header right", "text", p.get("hr", "")), ("fl", "Footer left", "text", p.get("fl", "")),
            ("fc", "Footer center", "text", p.get("fc", "")), ("fr", "Footer right", "text", p.get("fr", "")),
            ("size", tr("Font size"), "int", 9, (5, 40)), ("color", tr("Color"), "color", "#374151"),
            ("margin", "Margin (mm)", "float", 10, (0, 60)), ("start", "First page number", "int", 1, (1, 100000)),
            ("bp", "Bates prefix", "text", p.get("bp", "")), ("bs", "Bates start", "int", 1, (0, 10 ** 8)),
            ("bd", "Bates digits", "int", 6, (1, 12)),
            ("pages", tr("Pages to process"), "text", "all")],
            help_text="Tokens: {page} {pages} {date} {time} {file} {author} {bates}. Arabic text is supported.", width=520)
        if not v:
            return
        t.pdf.checkpoint()
        ops.header_footer(t.doc, (v["hl"], v["hc"], v["hr"]), (v["fl"], v["fc"], v["fr"]), v["size"], v["color"],
                          v["margin"], ops.parse_ranges(v["pages"], t.doc.page_count), v["start"],
                          t.pdf.path or t.pdf.title, v["bp"], v["bs"], v["bd"], self.style["author"])
        t.done(-1, tr("Header/Footer") + " ✓")

    def do_page_numbers(self):
        t = self._need()
        if not t:
            return
        v = ask(self, tr("Page numbers"), [
            ("fmt", "Format", "choice", "Page {page} of {pages}",
             ["Page {page} of {pages}", "{page}", "{page} / {pages}", "- {page} -", "صفحة {page} من {pages}", "{page} من {pages}"]),
            ("pos", "Position", "choice", "bottom-center", ["bottom-center", "bottom-right", "bottom-left", "top-center",
                                                            "top-right", "top-left"]),
            ("size", tr("Font size"), "int", 10, (5, 40)), ("start", "Start at", "int", 1, (1, 100000)),
            ("pages", tr("Pages to process"), "text", "all")])
        if v:
            t.pdf.checkpoint()
            ops.page_numbers(t.doc, v["fmt"], v["pos"], v["size"], pages=ops.parse_ranges(v["pages"], t.doc.page_count),
                             start=v["start"])
            t.done(-1, tr("Page numbers") + " ✓")

    def do_bates(self):
        self.do_header_footer({"fr": "{bates}", "bp": "DOC-"})

    def do_bookmarks_from_text(self):
        t = self._need()
        if not t:
            return
        v = ask(self, "Auto bookmarks", [("min", "Minimum heading font size", "float", 14, (6, 100))],
                help_text="Creates bookmarks from text lines whose font is larger than the size given (e.g. headings).")
        if not v:
            return
        toc = []
        sizes = set()
        for i, p in enumerate(t.doc):
            for b in p.get_text("dict")["blocks"]:
                for ln in b.get("lines", []):
                    if abs(ln.get("dir", (1, 0))[1]) > 0.01:
                        continue
                    import unicodedata
                    txt = unicodedata.normalize("NFKC", "".join(s["text"] for s in ln["spans"])).strip()
                    if not txt or len(txt) > 120:
                        continue
                    sz = max(s["size"] for s in ln["spans"])
                    if sz >= v["min"]:
                        toc.append([sz, txt, i + 1])
                        sizes.add(round(sz))
        levels = {s: k + 1 for k, s in enumerate(sorted(sizes, reverse=True)[:3])}
        out = []
        for sz, txt, pg in toc:
            lvl = levels.get(round(sz), 3)
            if out and lvl > out[-1][0] + 1:
                lvl = out[-1][0] + 1
            if not out:
                lvl = 1
            out.append([lvl, txt, pg])
        if not out:
            QMessageBox.information(self, "Auto bookmarks", "No headings found at that size.")
            return
        t.pdf.checkpoint()
        t.doc.set_toc(out)
        t.done(-1, f"{len(out)} bookmarks created.")
        t.show_panel(1)

    # ---- forms
    def do_reset_form(self):
        t = self._need()
        t and t.reset_form()

    def do_export_form(self):
        t = self._need()
        if not t:
            return
        fn, _ = QFileDialog.getSaveFileName(self, tr("Export data"), os.path.splitext(t.pdf.title)[0] + "_data.json",
                                            "JSON (*.json);;CSV (*.csv)")
        if not fn:
            return
        data = t.form_data()
        if fn.lower().endswith(".csv"):
            import csv
            with open(fn, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(list(data.keys()))
                w.writerow(list(data.values()))
        else:
            json.dump(data, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        self.statusBar().showMessage(f"{len(data)} fields exported.", 4000)

    def do_import_form(self):
        t = self._need()
        if not t:
            return
        fn, _ = QFileDialog.getOpenFileName(self, tr("Import data"), "", "JSON (*.json);;CSV (*.csv)")
        if not fn:
            return
        if fn.lower().endswith(".csv"):
            import csv
            rows = list(csv.reader(open(fn, encoding="utf-8-sig")))
            data = dict(zip(rows[0], rows[1])) if len(rows) > 1 else {}
        else:
            data = json.load(open(fn, encoding="utf-8"))
        t.set_form_data(data)

    def do_flatten_forms(self):
        t = self._need()
        if t:
            t.pdf.checkpoint()
            ops.flatten(t.doc, annots=False, widgets=True)
            t.done(-1, tr("Flatten") + " ✓")

    # ---- protect
    def do_password(self):
        t = self._need()
        if not t:
            return
        v = ask(self, tr("Password"), [
            ("user", "Password to open (optional)", "password", ""),
            ("owner", "Permissions password", "password", ""),
            ("print", "Allow printing", "bool", True), ("copy", "Allow copying text", "bool", True),
            ("modify", "Allow editing", "bool", False), ("annotate", "Allow comments", "bool", True),
            ("forms", "Allow form filling", "bool", True), ("assemble", "Allow page changes", "bool", False),
            ("out", "Save to", "file_save", os.path.splitext(t.pdf.path or t.pdf.title)[0] + "_protected.pdf", "PDF (*.pdf)")],
            help_text="Encryption: AES-256.")
        if not v or not v["out"]:
            return
        allow = [k for k in ("print", "copy", "modify", "annotate", "forms", "assemble") if v[k]]
        if "print" in allow:
            allow.append("print_hq")
        allow.append("accessibility")
        kw = ops.encryption_kwargs(v["user"], v["owner"], allow)
        t.doc.save(v["out"], garbage=3, deflate=True, **kw)
        QMessageBox.information(self, tr("Password"), f"Protected copy saved:\n{v['out']}")

    def do_remove_security(self):
        t = self._need()
        if not t:
            return
        if not t.pdf.was_encrypted:
            QMessageBox.information(self, tr("Remove security"), "This document is not protected.")
            return
        t.pdf.was_encrypted = False
        t.pdf.set_modified(True)
        self.statusBar().showMessage("Security will be removed when you save.", 6000)

    def do_search_redact(self):
        t = self._need()
        if not t:
            return
        v = ask(self, tr("Search & redact"), [
            ("text", "Words or phrases (one per line)", "multiline", ""),
            ("email", "Email addresses", "bool", False), ("phone", "Phone numbers", "bool", False),
            ("dates", "Dates", "bool", False), ("urls", "Web addresses", "bool", False),
            ("pages", tr("Pages to process"), "text", "all")],
            help_text="Found text is permanently removed and covered with black boxes.")
        if not v:
            return
        pages = ops.parse_ranges(v["pages"], t.doc.page_count)
        t.pdf.checkpoint()
        n = 0
        for line in v["text"].split("\n"):
            if line.strip():
                n += ops.redact_text(t.doc, line.strip(), pages)
        for k, name in (("email", "Email addresses"), ("phone", "Phone numbers"), ("dates", "Dates"), ("urls", "URLs")):
            if v[k]:
                n += ops.redact_pattern(t.doc, ops.REDACT_PATTERNS[name], pages)
        t.done(-1, f"{n} items redacted.")
        QMessageBox.information(self, tr("Redact"), f"{n} items redacted.")

    def do_apply_redactions(self):
        t = self._need()
        if not t:
            return
        n = sum(1 for p in t.doc for a in p.annots(types=[fitz.PDF_ANNOT_REDACT]))
        if not n:
            QMessageBox.information(self, tr("Apply redactions"), "Use the Redact tool to mark areas first.")
            return
        if QMessageBox.question(self, tr("Apply redactions"),
                                f"Permanently remove the content under {n} marked area(s)?") != QMessageBox.Yes:
            return
        t.pdf.checkpoint()
        for p in t.doc:
            p.apply_redactions()
        t.done(-1, f"{n} areas redacted.")

    def do_sanitize(self):
        t = self._need()
        if not t:
            return
        v = ask(self, tr("Sanitize"), [("meta", "Remove metadata", "bool", True), ("js", "Remove JavaScript", "bool", True),
                                       ("att", "Remove attachments", "bool", True), ("hidden", "Remove hidden text", "bool", True),
                                       ("links", "Remove links", "bool", False)])
        if v:
            t.pdf.checkpoint()
            ops.sanitize(t.doc, v["meta"], v["js"], v["att"], v["hidden"], v["links"])
            t.done(-1, tr("Sanitize") + " ✓")

    def new_signature(self):
        d = SignatureDialog(self)
        if d.exec():
            for t in self.doc_tabs():
                t.signature_path = d.result_path
            self._sig = d.result_path
            self.set_tool("signature")

    def do_create_cert(self):
        v = ask(self, tr("Certificate"), [("name", "Name", "text", self.style["author"]), ("org", "Organization", "text", ""),
                                          ("email", "Email", "text", ""), ("pw", tr("Password"), "password", ""),
                                          ("years", "Valid for (years)", "int", 5, (1, 30)),
                                          ("out", "Save to", "file_save", os.path.join(app_data_dir(), "my_certificate.pfx"),
                                           "Certificate (*.pfx *.p12)")],
                help_text="Creates a self-signed digital ID. Others will see it as 'not trusted' unless they trust "
                          "your certificate; for legally recognised signatures use a certificate from a trusted provider.")
        if not v or not v["out"] or not v["pw"]:
            return
        convert.make_self_signed_pfx(v["out"], v["name"], v["pw"], v["org"], v["email"], v["years"])
        self.settings.setValue("pfx", v["out"])
        QMessageBox.information(self, tr("Certificate"), f"Digital ID saved:\n{v['out']}")

    def digital_sign(self, page, rect):
        t = self.tab()
        if t.pdf.is_modified() or not t.pdf.path:
            QMessageBox.information(self, tr("Digital sign"), "Save the document first — signing creates a new signed copy.")
            if not self.save(t):
                return
        v = ask(self, tr("Digital sign"), [
            ("pfx", "Digital ID (.pfx/.p12)", "file_open", self.settings.value("pfx", ""), "Certificate (*.pfx *.p12)"),
            ("pw", tr("Password"), "password", ""), ("reason", "Reason", "text", "I approve this document"),
            ("location", "Location", "text", ""), ("tsa", "Timestamp server (optional)", "text",
                                                    self.settings.value("tsa", "")),
            ("out", "Save signed file", "file_save", os.path.splitext(t.pdf.path)[0] + "_signed.pdf", "PDF (*.pdf)")],
            help_text="Timestamp server example: http://timestamp.digicert.com (needs internet).")
        if not v or not v["pfx"] or not v["out"]:
            return
        self.settings.setValue("pfx", v["pfx"])
        self.settings.setValue("tsa", v["tsa"])
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            convert.sign_pdf(t.pdf.path, v["out"], v["pfx"], v["pw"], page, tuple(rect) if rect is not None else None,
                             v["reason"], v["location"], tsa_url=v["tsa"], visible=rect is not None)
        finally:
            QApplication.restoreOverrideCursor()
        self.set_tool("select")
        self.open_files([v["out"]])
        QMessageBox.information(self, tr("Digital sign"), "Signed copy created and opened.")

    def do_verify(self):
        t = self._need()
        if not t or not t.pdf.path:
            return
        import logging
        logging.disable(logging.CRITICAL)
        res = convert.verify_signatures(t.pdf.path)
        if not res:
            QMessageBox.information(self, tr("Verify"), "This document has no digital signatures.")
            return
        lines = []
        for r in res:
            state = "✔ intact & valid" if r["intact"] and r["valid"] else "✖ INVALID or modified"
            trust = "trusted" if r["trusted"] else "certificate not in a trusted list"
            lines.append(f"{r['field']}: {r['signer']}\n  {state} — {trust}\n  time: {r['time']}  coverage: {r['coverage']}\n")
        ReportDialog(self, tr("Verify"), "\n".join(lines)).exec()

    # ---- convert
    def to_images(self, pages=None):
        t = self.tab()
        v = ask(self, tr("To images"), [
            ("pages", tr("Pages to process"), "text", ",".join(str(p + 1) for p in pages) if pages else "all"),
            ("fmt", "Format", "choice", "png", ["png", "jpg"]), ("dpi", "Resolution (dpi)", "choice", 150, [72, 96, 150, 200, 300, 600]),
            ("folder", tr("Output folder"), "folder", os.path.dirname(t.pdf.path) if t.pdf.path else "")])
        if not v or not v["folder"]:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            files = ops.to_images(t.doc, v["folder"], os.path.splitext(t.pdf.title)[0], v["dpi"], v["fmt"],
                                  ops.parse_ranges(v["pages"], t.doc.page_count))
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"{len(files)} images saved.", 5000)
        QDesktopServices.openUrl(QUrl.fromLocalFile(v["folder"]))

    def do_to_images(self):
        if self._need():
            self.to_images()

    def do_to_word(self):
        t = self._need()
        if not t:
            return
        from . import pdfconv
        A = (lambda en, ar: ar if i18n.LANG == "ar" else en)
        engines = [("auto", A("Automatic (best available)", "تلقائي (الأفضل المتاح)"))]
        if pdfconv.word_available():
            engines.append(("word", A("Microsoft Word — best layout", "Microsoft Word — أفضل حفاظ على التنسيق")))
        engines += [("layout", A("Keep layout (Waraq + pdf2docx)", "الحفاظ على التخطيط")),
                    ("structured", A("Accurate text & tables (Arabic, borderless tables, scans)",
                                     "نص وجداول دقيقة (عربي، جداول بلا حدود، صفحات ممسوحة)"))]
        v = ask(self, A("Convert to Word", "تحويل إلى Word"), [
            ("engine", A("Engine", "المحرك"), "choice", "auto", engines),
            ("pages", tr("Pages to process"), "text", "all"),
            ("out", A("Save to", "حفظ إلى"), "file_save", os.path.splitext(t.pdf.path or t.pdf.title)[0] + ".docx", "Word (*.docx)")],
            help_text=A("Scanned pages are recognised with OCR first (Tesseract).",
                        "الصفحات الممسوحة ضوئياً يتم التعرف عليها بـ OCR أولاً (Tesseract)."), width=520)
        if not v or not v["out"]:
            return
        src = t.pdf.path
        if t.pdf.is_modified() or not src:
            src = os.path.join(tempfile.mkdtemp(), "doc.pdf")
            t.doc.save(src)
        pages = ops.parse_ranges(v["pages"], t.doc.page_count)
        if len(pages) != t.doc.page_count:
            sub = os.path.join(tempfile.mkdtemp(), "part.pdf")
            ops.extract_pages(fitz.open(src), pages).save(sub)
            src = sub
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            import logging
            logging.disable(logging.WARNING)
            used = pdfconv.pdf_to_docx(src, v["out"], v["engine"])
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(A(f"Converted with: {used}", f"تم التحويل باستخدام: {used}"), 6000)
        QDesktopServices.openUrl(QUrl.fromLocalFile(v["out"]))

    def do_to_text(self):
        t = self._need()
        if not t:
            return
        fn, _ = QFileDialog.getSaveFileName(self, tr("To text"), os.path.splitext(t.pdf.path or t.pdf.title)[0] + ".txt", "Text (*.txt)")
        if fn:
            open(fn, "w", encoding="utf-8").write(ops.to_text(t.doc))
            QDesktopServices.openUrl(QUrl.fromLocalFile(fn))

    def do_to_html(self):
        t = self._need()
        if not t:
            return
        fn, _ = QFileDialog.getSaveFileName(self, tr("To HTML"), os.path.splitext(t.pdf.path or t.pdf.title)[0] + ".html", "HTML (*.html)")
        if fn:
            open(fn, "w", encoding="utf-8").write(ops.to_html(t.doc))
            QDesktopServices.openUrl(QUrl.fromLocalFile(fn))

    def do_extract_images(self):
        t = self._need()
        if not t:
            return
        folder = QFileDialog.getExistingDirectory(self, tr("Output folder"))
        if folder:
            files = ops.extract_images(t.doc, folder, os.path.splitext(t.pdf.title)[0])
            QMessageBox.information(self, tr("Extract images"), f"{len(files)} images saved.")

    def do_images_to_pdf(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Images to PDF"), "",
                                                "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp)")
        if not files:
            return
        v = ask(self, tr("Images to PDF"), [("size", "Page size", "choice", "image", [("image", "Same as image")] + list(ops.PAPER)),
                                            ("margin", "Margin (mm)", "float", 0, (0, 50))])
        if not v:
            return
        out = ops.images_to_pdf(files, None if v["size"] == "image" else v["size"], v["margin"])
        pdf = PdfDocument(doc=out)
        pdf.suggested = os.path.join(os.path.dirname(files[0]), "Images.pdf")
        pdf.set_modified(True)
        self.add_tab(pdf, "Images.pdf")

    def do_scan(self):
        tmp = tempfile.mkdtemp()
        files = []
        while True:
            got = convert.scan_to_images(tmp)
            files += got
            if not got or QMessageBox.question(self, tr("Scan"), "Scan another page?") != QMessageBox.Yes:
                break
        if files:
            pdf = PdfDocument(doc=ops.images_to_pdf(files))
            pdf.suggested = "Scan.pdf"
            pdf.set_modified(True)
            self.add_tab(pdf, "Scan.pdf")
            if QMessageBox.question(self, tr("OCR"), "Make the scan searchable (OCR)?") == QMessageBox.Yes:
                self.do_ocr()

    def do_ocr(self):
        t = self._need()
        if not t:
            return
        langs = convert.ocr_languages()
        if not langs:
            QMessageBox.warning(self, tr("OCR"), "Tesseract OCR is not installed.\n\nDownload it from:\n"
                                                 "https://github.com/UB-Mannheim/tesseract/wiki\n"
                                                 "and select the Arabic language during installation.")
            return
        default = "+".join(l for l in ("ara", "eng") if l in langs) or langs[0]
        v = ask(self, tr("OCR"), [("lang", "Languages (e.g. ara+eng)", "text", default),
                                  ("dpi", "Resolution (dpi)", "choice", 300, [200, 300, 400]),
                                  ("pages", tr("Pages to process"), "text", "all"),
                                  ("skip", "Skip pages that already have text", "bool", True)],
                help_text="Installed languages: " + ", ".join(langs))
        if not v:
            return
        pages = ops.parse_ranges(v["pages"], t.doc.page_count)
        prog = QProgressDialog(tr("OCR") + "…", tr("Cancel"), 0, t.doc.page_count, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.show()

        def progress(i, n):
            prog.setValue(i)
            QApplication.processEvents()
            return not prog.wasCanceled()
        out = convert.ocr_document(t.doc, v["lang"], v["dpi"], pages, progress, v["skip"])
        prog.close()
        self._replace_doc(t, out, "OCR complete — text is now searchable and selectable.")

    def do_batch(self):
        from .tools_app import ToolsWindow
        if not hasattr(self, "_tools") or self._tools is None:
            self._tools = ToolsWindow()
        self._tools.show()
        self._tools.raise_()
        self._tools.activateWindow()


def QColor_(c):
    from PySide6.QtGui import QColor
    return QColor(c)


def app_icon():
    from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#1D4ED8"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(16, 16, 224, 224, 48, 48)
    p.setPen(QColor("#FFFFFF"))
    f = QFont("Segoe UI", 120)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "و")
    p.end()
    return QIcon(pm)
