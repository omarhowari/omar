"""Dialogs. Most are built from the generic FormDialog to keep things consistent."""
import os

from PySide6.QtCore import Qt, QPointF, QSize, QStandardPaths
from PySide6.QtGui import QPainter, QPen, QColor, QImage, QPainterPath, QFont
from PySide6.QtWidgets import (QDialog, QFormLayout, QVBoxLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QSpinBox,
                               QDoubleSpinBox, QCheckBox, QComboBox, QDialogButtonBox, QPushButton, QFileDialog,
                               QListWidget, QLabel, QWidget, QTabWidget, QTableWidget, QTableWidgetItem,
                               QHeaderView, QAbstractItemView, QListWidgetItem, QMessageBox)

from .i18n import tr
from .icons import icon
from .panels import ColorButton
from . import ops


class _PathEdit(QWidget):
    def __init__(self, kind, value="", filt="All files (*)"):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        b = QPushButton("…")
        b.setFixedWidth(40)
        b.setStyleSheet("padding: 4px 0")
        h.addWidget(self.edit)
        h.addWidget(b)

        def pick():
            if kind == "folder":
                p = QFileDialog.getExistingDirectory(self, "", self.edit.text())
            elif kind == "file_save":
                p, _ = QFileDialog.getSaveFileName(self, "", self.edit.text(), filt)
            else:
                p, _ = QFileDialog.getOpenFileName(self, "", self.edit.text(), filt)
            if p:
                self.edit.setText(p)
        b.clicked.connect(pick)

    def value(self):
        return self.edit.text()


class FormDialog(QDialog):
    """fields: list of (key, label, type, default, extra)
    types: text, password, multiline, int, float, bool, choice, color, file_open, file_save, folder, label"""

    def __init__(self, parent, title, fields, help_text="", width=440):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        v = QVBoxLayout(self)
        if help_text:
            h = QLabel(help_text)
            h.setWordWrap(True)
            h.setObjectName("muted")
            v.addWidget(h)
        form = QFormLayout()
        self.w = {}
        for f in fields:
            key, label, typ, default = f[:4]
            extra = f[4] if len(f) > 4 else None
            if typ == "text":
                w = QLineEdit(str(default or ""))
            elif typ == "password":
                w = QLineEdit(str(default or ""))
                w.setEchoMode(QLineEdit.Password)
            elif typ == "multiline":
                w = QPlainTextEdit(str(default or ""))
                w.setFixedHeight(90)
            elif typ == "int":
                w = QSpinBox()
                lo, hi = extra or (0, 100000)
                w.setRange(lo, hi)
                w.setValue(int(default))
            elif typ == "float":
                w = QDoubleSpinBox()
                lo, hi = extra or (0, 100000)
                w.setRange(lo, hi)
                w.setDecimals(2)
                w.setValue(float(default))
            elif typ == "bool":
                w = QCheckBox()
                w.setChecked(bool(default))
            elif typ == "choice":
                w = QComboBox()
                for o in extra:
                    if isinstance(o, tuple):
                        w.addItem(o[1], o[0])
                    else:
                        w.addItem(str(o), o)
                idx = w.findData(default)
                w.setCurrentIndex(max(0, idx))
            elif typ == "color":
                w = ColorButton(default, allow_none=bool(extra))
            elif typ in ("file_open", "file_save", "folder"):
                w = _PathEdit(typ, default or "", extra or "All files (*)")
            elif typ == "label":
                w = QLabel(str(default))
                w.setWordWrap(True)
            else:
                raise ValueError(typ)
            self.w[key] = (typ, w)
            form.addRow(label, w)
        v.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("OK"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self):
        out = {}
        for k, (typ, w) in self.w.items():
            if typ in ("text", "password"):
                out[k] = w.text()
            elif typ == "multiline":
                out[k] = w.toPlainText()
            elif typ in ("int", "float"):
                out[k] = w.value()
            elif typ == "bool":
                out[k] = w.isChecked()
            elif typ == "choice":
                out[k] = w.currentData()
            elif typ == "color":
                out[k] = w.color()
            elif typ in ("file_open", "file_save", "folder"):
                out[k] = w.value()
        return out


def ask(parent, title, fields, help_text="", width=440):
    d = FormDialog(parent, title, fields, help_text, width)
    if d.exec() == QDialog.Accepted:
        return d.values()
    return None


PAGES_HELP = "Pages: all, odd, even, 1-3,5,8-  (\"last\" = last page)"


# ------------------------------------------------------------------ file list (merge / batch)
class FileListWidget(QWidget):
    def __init__(self, filt="PDF files (*.pdf);;All files (*)", files=None):
        super().__init__()
        self.filt = filt
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setAcceptDrops(True)
        h.addWidget(self.list)
        col = QVBoxLayout()
        for label, slot in ((tr("Add files"), self.add), (tr("Add folder"), self.add_folder),
                            ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1)),
                            (tr("Remove"), self.remove), (tr("Clear"), self.list.clear)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            col.addWidget(b)
        col.addStretch()
        h.addLayout(col)
        for f in files or []:
            self._add(f)

    def _add(self, f):
        it = QListWidgetItem(os.path.basename(f))
        it.setToolTip(f)
        it.setData(Qt.UserRole, f)
        self.list.addItem(it)

    def add(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Add files"), "", self.filt)
        for f in files:
            self._add(f)

    def add_folder(self, folder=None, exts=(".pdf",)):
        folder = folder or QFileDialog.getExistingDirectory(self, tr("Add folder"))
        if not folder:
            return
        for root, _, names in os.walk(folder):
            for n in sorted(names):
                if os.path.splitext(n)[1].lower() in exts:
                    self._add(os.path.join(root, n))

    def move(self, d):
        r = self.list.currentRow()
        if r < 0:
            return
        nr = r + d
        if 0 <= nr < self.list.count():
            it = self.list.takeItem(r)
            self.list.insertItem(nr, it)
            self.list.setCurrentRow(nr)

    def remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def files(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]


class MergeDialog(QDialog):
    def __init__(self, parent, files=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Merge"))
        self.resize(620, 420)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("PDF, images, Office, text and Markdown files can be combined. Drag to reorder."))
        self.fl = FileListWidget("Documents (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.docx *.doc *.xlsx "
                                 "*.xls *.pptx *.txt *.md *.html *.xps *.epub);;All files (*)", files)
        v.addWidget(self.fl)
        self.bm = QCheckBox("Add a bookmark for each file")
        self.bm.setChecked(True)
        v.addWidget(self.bm)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


# ------------------------------------------------------------------ signature pad
def app_data_dir():
    p = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    os.makedirs(p, exist_ok=True)
    return p


class SignaturePad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(460, 170)
        self.paths = []
        self.setCursor(Qt.CrossCursor)
        self.color = QColor("#1E3A8A")

    def clear(self):
        self.paths = []
        self.update()

    def mousePressEvent(self, e):
        self.paths.append(QPainterPath(e.position()))
        self.update()

    def mouseMoveEvent(self, e):
        if self.paths:
            self.paths[-1].lineTo(e.position())
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#FFFFFF"))
        p.setPen(QPen(QColor("#CBD5E1"), 1, Qt.DashLine))
        p.drawLine(20, self.height() - 40, self.width() - 20, self.height() - 40)
        p.setPen(QPen(self.color, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for path in self.paths:
            p.drawPath(path)

    def to_image(self):
        if not self.paths:
            return None
        br = self.paths[0].boundingRect()
        for pth in self.paths[1:]:
            br = br.united(pth.boundingRect())
        br = br.adjusted(-6, -6, 6, 6)
        scale = 3
        img = QImage(int(br.width() * scale), int(br.height() * scale), QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(scale, scale)
        p.translate(-br.topLeft())
        p.setPen(QPen(self.color, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for path in self.paths:
            p.drawPath(path)
        p.end()
        return img


class SignatureDialog(QDialog):
    """Draw, type or load a hand signature. Saves PNG to app data; returns its path."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("Signature"))
        self.result_path = None
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        # draw
        dw = QWidget()
        dv = QVBoxLayout(dw)
        self.pad = SignaturePad()
        dv.addWidget(self.pad)
        clr = QPushButton(tr("Clear"))
        clr.clicked.connect(self.pad.clear)
        dv.addWidget(clr, 0, Qt.AlignRight)
        self.tabs.addTab(dw, "Draw")
        # type
        tw = QWidget()
        tv = QFormLayout(tw)
        self.typed = QLineEdit()
        self.font = QComboBox()
        self.font.addItems(["Segoe Script", "Brush Script MT", "Lucida Handwriting", "Gabriola", "Arial"])
        tv.addRow("Name", self.typed)
        tv.addRow("Font", self.font)
        self.tabs.addTab(tw, "Type")
        # image
        iw = QWidget()
        iv = QVBoxLayout(iw)
        self.img = _PathEdit("file_open", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        iv.addWidget(QLabel("Use a scanned signature (PNG with transparent background works best)."))
        iv.addWidget(self.img)
        iv.addStretch()
        self.tabs.addTab(iw, "Image")
        # saved
        self.saved = QListWidget()
        self.saved.setIconSize(QSize(160, 60))
        self.saved.setViewMode(QListWidget.IconMode)
        self._load_saved()
        self.tabs.addTab(self.saved, "Saved")
        if self.saved.count():
            self.tabs.setCurrentIndex(3)
        v.addWidget(self.tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _sig_dir(self):
        d = os.path.join(app_data_dir(), "signatures")
        os.makedirs(d, exist_ok=True)
        return d

    def _load_saved(self):
        from PySide6.QtGui import QIcon, QPixmap
        for n in sorted(os.listdir(self._sig_dir())):
            p = os.path.join(self._sig_dir(), n)
            it = QListWidgetItem(QIcon(QPixmap(p)), "")
            it.setData(Qt.UserRole, p)
            self.saved.addItem(it)

    def _new_path(self):
        import time
        return os.path.join(self._sig_dir(), f"sig_{int(time.time())}.png")

    def _ok(self):
        t = self.tabs.currentIndex()
        if t == 0:
            img = self.pad.to_image()
            if img is None:
                return
            p = self._new_path()
            img.save(p)
        elif t == 1:
            name = self.typed.text().strip()
            if not name:
                return
            f = QFont(self.font.currentText(), 64)
            from PySide6.QtGui import QFontMetrics
            fm = QFontMetrics(f)
            w, h = fm.horizontalAdvance(name) + 40, fm.height() + 20
            img = QImage(w, h, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            pa = QPainter(img)
            pa.setRenderHint(QPainter.Antialiasing)
            pa.setFont(f)
            pa.setPen(QColor("#1E3A8A"))
            pa.drawText(img.rect(), Qt.AlignCenter, name)
            pa.end()
            p = self._new_path()
            img.save(p)
        elif t == 2:
            p = self.img.value()
            if not os.path.exists(p):
                return
        else:
            it = self.saved.currentItem()
            if not it:
                return
            p = it.data(Qt.UserRole)
        self.result_path = p
        self.accept()


# ------------------------------------------------------------------ document properties
class DocPropertiesDialog(QDialog):
    def __init__(self, parent, doc, path):
        super().__init__(parent)
        self.setWindowTitle(tr("Document properties"))
        self.resize(560, 520)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        info = ops.doc_info(doc, path)
        t = QTableWidget(len(info), 2)
        t.horizontalHeader().setVisible(False)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for r, (k, val) in enumerate(info.items()):
            t.setItem(r, 0, QTableWidgetItem(k))
            it = QTableWidgetItem(str(val))
            it.setToolTip(str(val))
            t.setItem(r, 1, it)
        t.resizeColumnToContents(0)
        tabs.addTab(t, "Info")
        w = QWidget()
        f = QFormLayout(w)
        md = doc.metadata or {}
        self.fields = {}
        for k in ("title", "author", "subject", "keywords", "creator", "producer"):
            e = QLineEdit(md.get(k, ""))
            self.fields[k] = e
            f.addRow(tr(k.capitalize()), e)
        self.front = QSpinBox()
        self.front.setRange(0, 999)
        f.addRow("Roman-numbered front pages", self.front)
        tabs.addTab(w, tr("Properties"))
        v.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self):
        return {k: e.text() for k, e in self.fields.items()}


class ReportDialog(QDialog):
    def __init__(self, parent, title, text):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(600, 400)
        v = QVBoxLayout(self)
        e = QPlainTextEdit(text)
        e.setReadOnly(True)
        v.addWidget(e)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)
