"""One chat conversation (a tab)."""
from __future__ import annotations

import html
import json
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from ..i18n import human_size, lang, tr
from .theme import ACCENT, GOLD, status_icon

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
FILE_ICONS = {".pdf": "📕", ".doc": "📘", ".docx": "📘", ".xls": "📗", ".xlsx": "📗", ".csv": "📗",
              ".ppt": "📙", ".pptx": "📙", ".zip": "🗜️", ".rar": "🗜️", ".7z": "🗜️", ".mp3": "🎵",
              ".wav": "🎵", ".mp4": "🎬", ".avi": "🎬", ".mkv": "🎬", ".exe": "⚙️", ".txt": "📄",
              ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️", ".gif": "🖼️", ".bmp": "🖼️", ".webp": "🖼️"}


def local_paths(mime) -> list[str]:
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and u.toLocalFile()] if mime.hasUrls() else []

_URL = re.compile(r"(https?://[^\s<]+|www\.[^\s<]+)")


def _render_text(text: str) -> str:
    out = []
    pos = 0
    for m in _URL.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        url = m.group(0)
        href = url if url.startswith("http") else "http://" + url
        out.append(f'<a href="{html.escape(href)}" style="color:{ACCENT}">{html.escape(url)}</a>')
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out).replace("\n", "<br>")


class MessageInput(QPlainTextEdit):
    submit = Signal()
    files_pasted = Signal(list)

    def canInsertFromMimeData(self, mime):
        return bool(local_paths(mime)) or mime.hasImage() or super().canInsertFromMimeData(mime)

    def insertFromMimeData(self, mime):
        """Ctrl+V of copied files sends them; a pasted screenshot is saved as PNG and sent."""
        paths = local_paths(mime)
        if paths:
            self.files_pasted.emit(paths)
            return
        if mime.hasImage():
            img = QImage(mime.imageData())
            if not img.isNull():
                path = Path(tempfile.gettempdir()) / f"TDA-{datetime.now():%Y%m%d-%H%M%S}.png"
                img.save(str(path), "PNG")
                self.files_pasted.emit([str(path)])
                return
        super().insertFromMimeData(mime)

    # files dragged onto the text box go to the chat, not into the text
    def dragEnterEvent(self, e):
        if local_paths(e.mimeData()):
            e.ignore()
            return
        super().dragEnterEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submit.emit()
            return
        super().keyPressEvent(e)


class ChatWidget(QWidget):
    send_text = Signal(str, str)        # peer_id, text
    send_paths = Signal(str, list)      # peer_id, [paths]
    start_call = Signal(str)            # peer_id
    transfer_action = Signal(str, str)  # action, tid

    def __init__(self, peer_id: str, peer_name: str, my_name: str, parent=None):
        super().__init__(parent)
        self.peer_id, self.peer_name, self.my_name = peer_id, peer_name, my_name
        self.items: list[dict] = []
        self.online = False
        self.transfer_lookup = lambda tid: None
        self.setAcceptDrops(True)
        self._render_timer = QTimer(self, singleShot=True, interval=250)
        self._render_timer.timeout.connect(self.render)

        header = QFrame(objectName="ChatHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 8, 14, 8)
        self.status_lbl = QLabel()
        self.title = QLabel(peer_name, objectName="ChatTitle")
        self.sub = QLabel(objectName="Muted")
        tl = QVBoxLayout()
        tl.setSpacing(0)
        tl.addWidget(self.title)
        tl.addWidget(self.sub)
        hl.addWidget(self.status_lbl)
        hl.addLayout(tl, 1)
        self.btn_call = QPushButton(tr("call_btn"), objectName="Primary")
        self.btn_call.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_call.clicked.connect(lambda: self.start_call.emit(self.peer_id))
        hl.addWidget(self.btn_call)

        self.view = QTextBrowser(objectName="ChatView")
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.view.setAcceptDrops(False)
        self._stick = True       # follow new messages unless the user scrolled up
        sb = self.view.verticalScrollBar()
        sb.actionTriggered.connect(lambda _a: QTimer.singleShot(0, self._scrolled))   # user scrolling only
        sb.rangeChanged.connect(lambda *_: self._stick and self._to_bottom())

        self.overlay = QLabel(self.view)
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.setWordWrap(True)
        self.overlay.setStyleSheet(f"background: rgba(14,77,60,0.88); color: white; font-size: 15pt; font-weight: 600;"
                                   f" border: 3px dashed {GOLD}; border-radius: 14px;")
        self.overlay.hide()

        self.input = MessageInput()
        self.input.setPlaceholderText(tr("type_message"))
        self.input.setFixedHeight(84)
        self.input.submit.connect(self._submit)
        self.input.files_pasted.connect(self._send_paths)

        self.btn_send = QPushButton(tr("send"), objectName="Primary")
        self.btn_send.clicked.connect(self._submit)
        self.btn_file = QPushButton(tr("send_file"))
        self.btn_file.clicked.connect(self._pick_files)
        self.btn_folder = QPushButton(tr("send_folder"))
        self.btn_folder.clicked.connect(self._pick_folder)

        bl = QHBoxLayout()
        bl.addWidget(self.btn_file)
        bl.addWidget(self.btn_folder)
        bl.addStretch(1)
        bl.addWidget(QLabel(tr("drop_hint"), objectName="Muted"))
        bl.addStretch(1)
        bl.addWidget(self.btn_send)

        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(10, 8, 10, 10)
        bv.addWidget(self.input)
        bv.addLayout(bl)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(header)
        lay.addWidget(self.view, 1)
        lay.addWidget(bottom)

    # ------------------------------------------------------------------ state
    def set_peer(self, name: str, status: str, info: str):
        self.peer_name = name
        self.title.setText(name)
        self.online = status != "offline"
        self.status_lbl.setPixmap(status_icon(status).pixmap(18, 18))
        self.sub.setText(f"{tr('status_' + status)}  ·  {info}" if info else tr("status_" + status))
        for w in (self.btn_send, self.btn_file, self.btn_folder, self.btn_call):
            w.setEnabled(self.online)
        self.input.setPlaceholderText(tr("type_message") if self.online else tr("peer_offline"))

    def load(self, rows: list[dict]):
        self.items = rows
        self.render()

    def add(self, item: dict):
        self.items.append(item)
        self.render()

    def set_status(self, msg_id: str, status: str):
        for it in self.items:
            if it.get("id") == msg_id:
                it["status"] = status
                self.render()
                return True
        return False

    def _scrolled(self):
        sb = self.view.verticalScrollBar()
        self._stick = sb.value() >= sb.maximum() - 30

    def _to_bottom(self):
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def schedule_render(self):
        if not self._render_timer.isActive():
            self._render_timer.start()

    def has_item(self, item_id: str) -> bool:
        return any(it.get("id") == item_id for it in self.items)

    def focus_input(self):
        self.input.setFocus()

    # ------------------------------------------------------------------ rendering
    def render(self):
        mine_side = "left" if lang() == "ar" else "right"
        theirs_side = "right" if lang() == "ar" else "left"
        parts = []
        last_day = None
        for it in self.items[-400:]:
            dt = datetime.fromtimestamp(it.get("ts") or time.time())
            day = dt.date()
            if day != last_day:
                last_day = day
                label = tr("today") if day == datetime.now().date() else dt.strftime("%Y-%m-%d")
                parts.append(f'<p align="center" style="color:#6B7280;font-size:8.5pt;margin:10px">— {label} —</p>')
            hhmm = dt.strftime("%H:%M")
            if it.get("kind") == "call":
                parts.append(self._call_line(it, hhmm))
                continue
            if it.get("kind") == "file":
                mine = bool(it.get("outgoing"))
                parts.append(self._file_card(it, hhmm, mine_side if mine else theirs_side))
                continue
            if it.get("kind") == "sys":
                emb = "\u202b" if lang() == "ar" else "\u202a"   # embed the line in the UI direction
                parts.append(f'<p align="center" style="color:#475569;font-size:9pt;margin:6px">'
                             f'<span style="color:#9CA3AF">{hhmm}</span>  ·  {emb}📎 {html.escape(it["text"])}\u202c</p>')
                continue
            mine = bool(it.get("outgoing"))
            bg = "#D1FAE5" if mine else "#FFFFFF"
            who = tr("me") if mine else html.escape(it.get("peer_name") or self.peer_name)
            tick = ""
            if mine:
                st = it.get("status")
                tick = (' <span style="color:#16A34A">✓</span>' if st == "delivered" else
                        f' <span style="color:#DC2626">✗ {tr("not_delivered")}</span>' if st == "failed" else
                        ' <span style="color:#9CA3AF">…</span>')
            multi = f' <span style="color:#7C3AED">[{tr("multi_tag")}]</span>' if it.get("multi") else ""
            parts.append(
                f'<table align="{mine_side if mine else theirs_side}" cellspacing="0" cellpadding="9" '
                f'style="background:{bg};margin:4px 10px;border:1px solid #E5E7EB">'
                f'<tr><td><span style="color:{ACCENT};font-size:8.5pt"><b>{who}</b>{multi}</span>'
                f'<span style="color:#9CA3AF;font-size:8pt">  {hhmm}</span>{tick}<br>'
                f'<span style="font-size:10.5pt;color:#111827">{_render_text(it.get("text", ""))}</span>'
                f'</td></tr></table><br clear="all">')
        sb = self.view.verticalScrollBar()
        old = sb.value()
        self.view.setHtml("".join(parts))
        if self._stick:
            self._to_bottom()
        else:
            sb.setValue(old)

    def _call_line(self, it, hhmm) -> str:
        try:
            d = json.loads(it.get("text") or "{}")
        except ValueError:
            d = {}
        reason, dur = d.get("reason", ""), int(d.get("duration", 0))
        if dur > 0:
            label = tr("call_log_out" if d.get("direction") == "out" else "call_log_in") + f" · {dur // 60:02d}:{dur % 60:02d}"
            color = "#166534"
        else:
            key = {"missed": "call_log_missed", "no_answer": "call_log_no_answer", "declined": "call_log_declined",
                   "declined_by_me": "call_log_declined", "busy": "call_log_busy", "unreachable": "call_log_unreachable",
                   "lost": "call_log_lost", "canceled": "call_log_canceled"}.get(reason, "call_log_canceled")
            label, color = tr(key), "#B91C1C" if reason == "missed" else "#6B7280"
        emb = "\u202b" if lang() == "ar" else "\u202a"
        return (f'<p align="center" style="margin:8px"><span style="background:#F1F5F9;color:{color};font-size:9.5pt">'
                f'&nbsp;{emb}📞 {html.escape(label)}\u202c&nbsp;&nbsp;<span style="color:#9CA3AF">{hhmm}</span>&nbsp;</span></p>')

    def _file_card(self, it, hhmm, side) -> str:
        try:
            d = json.loads(it.get("text") or "{}")
        except ValueError:
            d = {}
        tid = it.get("id", "")
        live = self.transfer_lookup(tid)
        mine = bool(it.get("outgoing"))
        state = live.state if live else d.get("state", "failed")
        if not live and state in ("offered", "accepted", "active"):
            state = "failed"            # app was restarted mid-transfer
        title = d.get("title", "?")
        n = int(d.get("count", 1))
        icon = "📁" if d.get("is_dir") else FILE_ICONS.get(os.path.splitext(title)[1].lower(), "📄")
        name = html.escape(title if n == 1 or not title.isdigit() else tr("files_n", n=n))
        size = human_size(int(d.get("size", 0)))
        a = lambda act, label, color=ACCENT: (f'<a href="tda:{act}:{tid}" style="color:{color};'
                                              f'text-decoration:none"><b>{label}</b></a>')
        if state == "offered":
            if mine:
                line = f'{tr("tr_offered_out")} &nbsp; {a("cancel", "✖ " + tr("cancel"), "#B91C1C")}'
            else:
                line = f'{a("accept", "✔ " + tr("accept"), "#15803D")} &nbsp;&nbsp; {a("decline", "✖ " + tr("decline"), "#B91C1C")}'
        elif state in ("accepted", "active"):
            pct = int(100 * live.done / live.total) if (live and live.total) else 0
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            line = (f'<span style="font-family:Consolas,monospace;color:{ACCENT}">{bar}</span> {pct}% '
                    f'&nbsp; {a("cancel", "✖ " + tr("cancel"), "#B91C1C")}')
        elif state == "done":
            if mine:
                line = f'<span style="color:#15803D">✓ {tr("sent_ok")}</span>'
            else:
                line = f'<span style="color:#15803D">✓</span> {a("open", tr("open"))} &nbsp;·&nbsp; {a("folder", tr("open_folder"))}'
        else:
            line = f'<span style="color:#B91C1C">{tr("tr_" + state)}</span>'
        thumb = ""
        target = d.get("open", "")
        if (state == "done" and n == 1 and os.path.splitext(title)[1].lower() in IMAGE_EXT):
            src = d.get("source", "") if mine else target
            if src and os.path.exists(src):
                img = QImage(src)
                if not img.isNull():
                    w = min(240, img.width())
                    thumb = f'<br><a href="tda:open:{tid}"><img src="{QUrl.fromLocalFile(src).toString()}" width="{w}"></a>'
        bg = "#E7F3EE" if mine else "#FFFFFF"
        who = tr("me") if mine else html.escape(it.get("peer_name") or self.peer_name)
        emb = "\u202b" if lang() == "ar" else "\u202a"
        return (f'<table align="{side}" cellspacing="0" cellpadding="10" '
                f'style="background:{bg};margin:4px 10px;border:1px solid #D6E4DD">'
                f'<tr><td><span style="color:{ACCENT};font-size:8.5pt"><b>{who}</b></span>'
                f'<span style="color:#9CA3AF;font-size:8pt">  {hhmm}</span><br>'
                f'<span style="font-size:20pt">{icon}</span> <span style="font-size:10.5pt;color:#111827"><b>{emb}{name}\u202c</b></span>'
                f'\u200f <span style="color:#6B7280;font-size:9pt">\u200f({size})\u200f</span>{thumb}<br>'
                f'<span style="font-size:9.5pt">{line}</span></td></tr></table><br clear="all">')

    def _link(self, url: QUrl):
        s = url.toString()
        if s.startswith("tda:"):
            _, action, tid = s.split(":", 2)
            self.transfer_action.emit(action, tid)
        else:
            QDesktopServices.openUrl(url)

    # ------------------------------------------------------------------ actions
    def _submit(self):
        text = self.input.toPlainText().strip()
        if not text or not self.online:
            return
        self.input.clear()
        self.send_text.emit(self.peer_id, text)

    def _send_paths(self, paths):
        if paths and self.online:
            self.send_paths.emit(self.peer_id, list(paths))

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("send_file"))
        self._send_paths(paths)

    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, tr("send_folder"))
        if path:
            self._send_paths([path])

    # drag & drop: any file type, any number of files, folders too
    def dragEnterEvent(self, e):
        if local_paths(e.mimeData()) and self.online:
            e.acceptProposedAction()
            self.overlay.setText("📥\n" + tr("drop_here", name=self.peer_name))
            self.overlay.setGeometry(self.view.rect().adjusted(12, 12, -12, -12))
            self.overlay.show()
            self.overlay.raise_()

    def dragMoveEvent(self, e):
        if local_paths(e.mimeData()) and self.online:
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.overlay.hide()

    def dropEvent(self, e):
        self.overlay.hide()
        paths = local_paths(e.mimeData())
        if paths:
            e.acceptProposedAction()
            self._send_paths(paths)
