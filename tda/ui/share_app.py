"""Share the TDA installer with a colleague: save a copy, send it to TDA users on the LAN,
Telegram / WhatsApp (file copied to the clipboard), e-mail (attached), Bluetooth."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from .. import APP_NAME, APP_VERSION, updates
from ..i18n import human_size, tr
from .theme import status_icon


def app_package() -> Path:
    """The installer of this version, or (portable / developer copy) a zip of the program folder."""
    pkg = updates.update_package()
    if pkg:
        return pkg
    out = Path(tempfile.gettempdir()) / f"TDA-{APP_VERSION}-portable.zip"
    if out.exists():
        return out
    root = updates.install_dir()
    skip = {".git", "download", "setup", "__pycache__", ".venv", "build", "dist"}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                p = Path(base) / f
                z.write(p, Path("TDA") / p.relative_to(root))
    return out


def copy_file_to_clipboard(path: Path):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(path))])
    md.setText(str(path))
    QApplication.clipboard().setMimeData(md)


def show_in_folder(path: Path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def mapi_send(path: Path, subject: str, body: str) -> bool:
    """Open the default e-mail program (Outlook, Thunderbird...) with the file attached."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class FileDesc(ctypes.Structure):
        _fields_ = [("ulReserved", wintypes.ULONG), ("flFlags", wintypes.ULONG), ("nPosition", wintypes.ULONG),
                    ("lpszPathName", wintypes.LPCWSTR), ("lpszFileName", wintypes.LPCWSTR),
                    ("lpFileType", ctypes.c_void_p)]

    class Message(ctypes.Structure):
        _fields_ = [("ulReserved", wintypes.ULONG), ("lpszSubject", wintypes.LPCWSTR),
                    ("lpszNoteText", wintypes.LPCWSTR), ("lpszMessageType", wintypes.LPCWSTR),
                    ("lpszDateReceived", wintypes.LPCWSTR), ("lpszConversationID", wintypes.LPCWSTR),
                    ("flFlags", wintypes.ULONG), ("lpOriginator", ctypes.c_void_p),
                    ("nRecipCount", wintypes.ULONG), ("lpRecips", ctypes.c_void_p),
                    ("nFileCount", wintypes.ULONG), ("lpFiles", ctypes.POINTER(FileDesc))]
    try:
        mapi = ctypes.WinDLL("mapi32.dll")
        fn = mapi.MAPISendMailW
    except (OSError, AttributeError):
        return False
    f = FileDesc(0, 0, 0xFFFFFFFF, str(path), path.name, None)
    msg = Message(0, subject, body, None, None, None, 0, None, 0, None, 1, ctypes.pointer(f))
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(Message), wintypes.ULONG, wintypes.ULONG]
    MAPI_LOGON_UI, MAPI_DIALOG = 0x1, 0x8
    try:
        return fn(None, None, ctypes.byref(msg), MAPI_LOGON_UI | MAPI_DIALOG, 0) in (0, 1)   # 1 = user canceled
    except OSError:
        return False


class ShareAppDialog(QDialog):
    def __init__(self, core=None, parent=None):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle(tr("share_app_title"))
        self.setMinimumWidth(520)
        if not updates.update_package():
            QMessageBox.information(self, APP_NAME, tr("share_no_package"))
        self.pkg = app_package()

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{APP_NAME} {APP_VERSION}</b> — {self.pkg.name}"))
        lay.addWidget(QLabel(tr("share_app_hint", size=human_size(self.pkg.stat().st_size)),
                             objectName="Muted", wordWrap=True))
        grid = QGridLayout()
        buttons = [("share_save", self.save_copy), ("share_tda", self.send_tda),
                   ("share_telegram", lambda: self.messenger("Telegram", "tg://")),
                   ("share_whatsapp", lambda: self.messenger("WhatsApp", "whatsapp://")),
                   ("share_email", self.email), ("share_bluetooth", self.bluetooth),
                   ("share_show", lambda: show_in_folder(self.pkg))]
        for i, (key, slot) in enumerate(buttons):
            b = QPushButton(tr(key))
            b.setMinimumHeight(44)
            b.setStyleSheet("text-align:left;padding:6px 12px;font-size:10.5pt")
            b.clicked.connect(slot)
            if key == "share_tda" and core is None:
                b.setEnabled(False)
            grid.addWidget(b, i // 2, i % 2)
        lay.addLayout(grid)
        close = QPushButton(tr("close_tab"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)

    # ------------------------------------------------------------------ ways to share
    def save_copy(self):
        d = QFileDialog.getExistingDirectory(self, tr("share_save"))
        if not d:
            return
        dest = Path(d) / self.pkg.name
        try:
            shutil.copy2(self.pkg, dest)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        QMessageBox.information(self, APP_NAME, tr("share_saved", path=str(dest)))
        show_in_folder(dest)

    def send_tda(self):
        peers = sorted(self.core.peers.values(), key=lambda p: p.name.lower())
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("share_tda"))
        dlg.resize(420, 460)
        lst = QListWidget()
        for p in peers:
            it = QListWidgetItem(status_icon(p.status), f"{p.name}   —   {p.group}   {p.version}")
            it.setData(Qt.ItemDataRole.UserRole, p.id)
            it.setCheckState(Qt.CheckState.Unchecked)
            lst.addItem(it)
        ok = QPushButton(tr("send"), objectName="Primary")
        ok.clicked.connect(dlg.accept)
        v = QVBoxLayout(dlg)
        v.addWidget(lst, 1)
        v.addWidget(ok)
        if not dlg.exec():
            return
        ids = [lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())
               if lst.item(i).checkState() == Qt.CheckState.Checked]
        for pid in ids:
            self.core.offer_files(pid, [str(self.pkg)])
        if ids:
            QMessageBox.information(self, APP_NAME, tr("share_sent", n=len(ids)))

    def messenger(self, app: str, url: str):
        copy_file_to_clipboard(self.pkg)
        QDesktopServices.openUrl(QUrl(url))
        QMessageBox.information(self, APP_NAME, tr("share_pasted", app=app))

    def email(self):
        if mapi_send(self.pkg, tr("share_email_subject"), tr("share_email_body")):
            return
        # no e-mail program registered for attachments: open a new mail and show the file to attach
        from urllib.parse import quote
        copy_file_to_clipboard(self.pkg)
        QDesktopServices.openUrl(QUrl(f"mailto:?subject={quote(tr('share_email_subject'))}"
                                      f"&body={quote(tr('share_email_body'))}"))
        show_in_folder(self.pkg)

    def bluetooth(self):
        copy_file_to_clipboard(self.pkg)
        QApplication.clipboard().setText(str(self.pkg))
        fsquirt = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "fsquirt.exe"
        if sys.platform == "win32" and fsquirt.exists():
            subprocess.Popen([str(fsquirt)])
        else:
            QDesktopServices.openUrl(QUrl("ms-settings:bluetooth"))
        QMessageBox.information(self, APP_NAME, tr("share_bt_hint"))
