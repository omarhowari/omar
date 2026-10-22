"""PDF document model: wraps a PyMuPDF document with undo/redo and safe saving."""
import os
import tempfile

import pymupdf as fitz
from PySide6.QtCore import QObject, Signal

MAX_UNDO = 30


class PdfDocument(QObject):
    # page index that changed, or -1 when page structure changed (pages added/removed/moved)
    changed = Signal(int)
    modifiedChanged = Signal(bool)

    def __init__(self, path=None, doc=None, password=None):
        super().__init__()
        self.path = path
        self.password = password
        self.was_encrypted = False
        if doc is not None:
            self.doc = doc
        else:
            self.doc = fitz.open(path)
            if self.doc.needs_pass:
                self.was_encrypted = True
                if not password or not self.doc.authenticate(password):
                    raise PermissionError("password")
        self._undo = []
        self._redo = []
        self._modified = False

    # ---- info ---------------------------------------------------------
    @property
    def title(self):
        if self.path:
            return os.path.basename(self.path)
        sug = getattr(self, "suggested", None)
        return os.path.basename(sug) if sug else "Untitled.pdf"

    @property
    def page_count(self):
        return self.doc.page_count

    def is_modified(self):
        return self._modified

    def set_modified(self, v=True):
        if v != self._modified:
            self._modified = v
            self.modifiedChanged.emit(v)

    # ---- undo / redo --------------------------------------------------
    def checkpoint(self):
        """Call BEFORE changing the document."""
        self._undo.append(self.doc.tobytes())
        if len(self._undo) > MAX_UNDO:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def _reload(self, data):
        old = self.doc
        self.doc = fitz.open("pdf", data)
        old.close()
        self.set_modified(True)
        self.changed.emit(-1)

    def undo(self):
        if not self._undo:
            return
        self._redo.append(self.doc.tobytes())
        self._reload(self._undo.pop())

    def redo(self):
        if not self._redo:
            return
        self._undo.append(self.doc.tobytes())
        self._reload(self._redo.pop())

    def touched(self, page=-1):
        self.set_modified(True)
        self.changed.emit(page)

    # ---- saving -------------------------------------------------------
    def save(self, path=None):
        path = path or self.path
        if not path:
            raise ValueError("no path")
        kw = dict(garbage=3, deflate=True)
        if self.was_encrypted and self.password:
            kw.update(encryption=fitz.PDF_ENCRYPT_AES_256,
                      user_pw=self.password, owner_pw=self.password)
        data = self.doc.tobytes(**kw)
        folder = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=folder)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # Re-open from memory first so the original file is no longer locked (Windows)
        new_doc = fitz.open("pdf", data)
        if new_doc.needs_pass and self.password:
            new_doc.authenticate(self.password)
        self.doc.close()
        self.doc = new_doc
        os.replace(tmp, path)
        self.path = path
        self.set_modified(False)

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass
