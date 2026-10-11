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

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QMenu, QPlainTextEdit,
                               QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from ..i18n import human_size, lang, tr
from .theme import ACCENT, GOLD, chat_pattern, send_icon, status_icon

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
FILE_ICONS = {".pdf": "📕", ".doc": "📘", ".docx": "📘", ".xls": "📗", ".xlsx": "📗", ".csv": "📗",
              ".ppt": "📙", ".pptx": "📙", ".zip": "🗜️", ".rar": "🗜️", ".7z": "🗜️", ".mp3": "🎵",
              ".wav": "🎵", ".mp4": "🎬", ".avi": "🎬", ".mkv": "🎬", ".exe": "⚙️", ".txt": "📄",
              ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️", ".gif": "🖼️", ".bmp": "🖼️", ".webp": "🖼️"}


_size_cache: dict = {}


def image_size(path: str):
    """Width/height from the file header only (fast), cached."""
    from PySide6.QtGui import QImageReader
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _size_cache:
        r = QImageReader(path)
        r.setAutoTransform(True)
        sz = r.size()
        _size_cache[key] = (sz.width(), sz.height()) if sz.isValid() else None
    return _size_cache[key]


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


class ChatView(QTextBrowser):
    """Message area with an optional fixed background (pattern or picture) at adjustable opacity."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatView")
        self._bg: QPixmap | None = None
        self._tile = True
        self._opacity = 1.0
        self.viewport().setAutoFillBackground(False)

    def set_background(self, mode: str, image: str = "", opacity: int = 100):
        """mode: "pattern" | "image" | "none"."""
        self._opacity = max(0.0, min(1.0, opacity / 100))
        self._bg, self._tile = None, True
        if mode == "pattern":
            self._bg = chat_pattern()
        elif mode == "image" and image and os.path.exists(image):
            pm = QPixmap(image)
            if not pm.isNull():
                self._bg, self._tile = pm, False
        self.viewport().update()

    def paintEvent(self, e):
        p = QPainter(self.viewport())
        r = self.viewport().rect()
        p.fillRect(r, QColor("#F8FAFC"))
        if self._bg is not None and not self._bg.isNull() and self._opacity > 0:
            p.setOpacity(self._opacity)
            if self._tile:
                p.drawTiledPixmap(r, self._bg)
            else:   # cover the whole area, keep proportions
                sc = self._bg.scaled(r.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
                p.drawPixmap(QRect((r.width() - sc.width()) // 2, (r.height() - sc.height()) // 2,
                                   sc.width(), sc.height()), sc)
        p.end()
        super().paintEvent(e)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.viewport().update()          # keep the background fixed while scrolling


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
    manage_group = Signal(str)          # chat key "g:<gid>"

    def __init__(self, peer_id: str, peer_name: str, my_name: str, parent=None, is_group: bool = False):
        super().__init__(parent)
        self.peer_id, self.peer_name, self.my_name = peer_id, peer_name, my_name
        self.is_group = is_group
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
        self.btn_manage = QPushButton(tr("group_manage"))
        self.btn_manage.clicked.connect(lambda: self.manage_group.emit(self.peer_id))
        hl.addWidget(self.btn_manage)
        self.btn_call.setVisible(not is_group)
        self.btn_manage.setVisible(is_group)

        self.view = ChatView()
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

        # ---- WhatsApp-style compose bar:  [📎 | text that grows | ➤]
        self.input = MessageInput()
        self.input.setObjectName("Compose")
        self.input.setPlaceholderText(tr("type_message_short"))
        self.input.setToolTip(tr("drop_hint"))
        self.input.setFrameShape(QFrame.Shape.NoFrame)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input.setFixedHeight(40)
        self.input.document().documentLayout().documentSizeChanged.connect(lambda _s: self._grow())
        self.input.submit.connect(self._submit)
        self.input.files_pasted.connect(self._send_paths)

        self.btn_attach = QPushButton("📎")
        self.btn_attach.setObjectName("Attach")
        self.btn_attach.setToolTip(tr("attach"))
        self.btn_attach.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_attach.setFixedSize(40, 40)
        menu = QMenu(self.btn_attach)
        menu.addAction("🖼  " + tr("attach_image"), self._pick_images)
        menu.addAction("📄  " + tr("attach_file"), self._pick_files)
        menu.addAction("📁  " + tr("attach_folder"), self._pick_folder)
        self.btn_attach.setMenu(menu)

        self.btn_send = QPushButton()
        self.btn_send.setObjectName("SendRound")
        self.btn_send.setIcon(send_icon(lang() == "ar"))
        self.btn_send.setIconSize(QSize(22, 22))
        self.btn_send.setFixedSize(44, 44)
        self.btn_send.setToolTip(tr("send"))
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.clicked.connect(self._submit)

        box = QFrame(objectName="ComposeBox")
        bx = QHBoxLayout(box)
        bx.setContentsMargins(6, 3, 6, 3)
        bx.setSpacing(4)
        bx.addWidget(self.btn_attach, 0, Qt.AlignmentFlag.AlignBottom)
        bx.addWidget(self.input, 1)
        bx.addWidget(self.btn_send, 0, Qt.AlignmentFlag.AlignBottom)

        bottom = QFrame(objectName="ComposeBar")
        bv = QHBoxLayout(bottom)
        bv.setContentsMargins(12, 8, 12, 10)
        bv.addWidget(box)

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
        self.btn_call.setEnabled(self.online)     # messages and files can wait; calls cannot
        self.input.setPlaceholderText(tr("type_message_short") if self.online else tr("peer_offline_queue"))

    def set_group(self, name: str, members: int, online: int):
        self.peer_name = name
        self.title.setText("👥 " + name)
        self.online = True
        self.status_lbl.setPixmap(status_icon("available" if online else "offline").pixmap(18, 18))
        self.sub.setText(tr("group_members", n=members, online=online))
        self.input.setPlaceholderText(tr("type_message_short"))

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

    def _grow(self):
        h = int(self.input.document().size().height()) + 14
        self.input.setFixedHeight(max(40, min(140, h)))
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if h > 140
                                              else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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
                        f' <span style="color:#B45309">⏳ {tr("queued")}</span>' if st == "queued" else
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
        if not live and state in ("offered", "accepted", "active", "queued"):
            state = "failed"            # app was restarted mid-transfer
        title = d.get("title", "?")
        n = int(d.get("count", 1))
        icon = "📁" if d.get("is_dir") else FILE_ICONS.get(os.path.splitext(title)[1].lower(), "📄")
        name = html.escape(title if n == 1 or not title.isdigit() else tr("files_n", n=n))
        size = human_size(int(d.get("size", 0)))
        a = lambda act, label, color=ACCENT: (f'<a href="tda:{act}:{tid}" style="color:{color};'
                                              f'text-decoration:none"><b>{label}</b></a>')
        if state == "queued":
            line = (f'<span style="color:#B45309">⏳ {tr("tr_queued")}</span> &nbsp; '
                    f'{a("cancel", "✖ " + tr("cancel"), "#B91C1C")}')
        elif state == "offered":
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
        if n == 1 and not d.get("is_dir") and os.path.splitext(title)[1].lower() in IMAGE_EXT:
            return self._image_card(it, d, tid, state, live, mine, hhmm, side, bg, who, line, a)
        return (f'<table align="{side}" cellspacing="0" cellpadding="10" '
                f'style="background:{bg};margin:4px 10px;border:1px solid #D6E4DD">'
                f'<tr><td><span style="color:{ACCENT};font-size:8.5pt"><b>{who}</b></span>'
                f'<span style="color:#9CA3AF;font-size:8pt">  {hhmm}</span><br>'
                f'<span style="font-size:20pt">{icon}</span> <span style="font-size:10.5pt;color:#111827"><b>{emb}{name}\u202c</b></span>'
                f'\u200f <span style="color:#6B7280;font-size:9pt">\u200f({size})\u200f</span>{thumb}<br>'
                f'<span style="font-size:9.5pt">{line}</span></td></tr></table><br clear="all">')

    def _image_card(self, it, d, tid, state, live, mine, hhmm, side, bg, who, line, a) -> str:
        """WhatsApp-style picture bubble: the photo itself, a small time/status line under it."""
        src = d.get("source", "") if mine else (d.get("open", "") if state == "done" else "")
        size = image_size(src) if src and os.path.exists(src) else None
        if size:
            w, h = size
            scale = min(1.0, 300 / max(1, w), 340 / max(1, h))
            w, h = max(40, int(w * scale)), max(40, int(h * scale))
            pic = (f'<a href="tda:open:{tid}"><img src="{QUrl.fromLocalFile(src).toString()}" '
                   f'width="{w}" height="{h}"></a>')
        else:   # not downloaded yet
            pic = (f'<table cellpadding="26" style="background:#E2E8F0"><tr><td align="center">'
                   f'<span style="font-size:30pt">🖼</span><br><span style="color:#64748B;font-size:9pt">'
                   f'{human_size(int(d.get("size", 0)))}</span></td></tr></table>')
        if state == "done":
            status = '<span style="color:#16A34A">✓✓</span>' if mine else ""
        elif state in ("accepted", "active"):
            pct = int(100 * live.done / live.total) if (live and live.total) else 0
            status = f'<span style="color:{ACCENT}">{pct}%</span> {a("cancel", "✖", "#B91C1C")}'
        else:
            status = line
        head = "" if mine or not self.is_group else f'<span style="color:{ACCENT};font-size:8.5pt"><b>{who}</b></span><br>'
        return (f'<table align="{side}" cellspacing="0" cellpadding="4" '
                f'style="background:{bg};margin:4px 10px;border:1px solid #D6E4DD">'
                f'<tr><td>{head}{pic}<br>'
                f'<span style="color:#9CA3AF;font-size:8pt">{hhmm}</span> &nbsp;<span style="font-size:9pt">{status}</span>'
                f'</td></tr></table><br clear="all">')

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
        if not text:
            return
        self.input.clear()
        self.send_text.emit(self.peer_id, text)

    def _send_paths(self, paths):
        paths = [p for p in (paths or []) if p]
        if not paths:
            return
        if all(os.path.isfile(p) and os.path.splitext(p)[1].lower() in IMAGE_EXT for p in paths):
            from .dialogs import ImageSendDialog          # WhatsApp-style preview + caption
            dlg = ImageSendDialog(paths, self.peer_name, self)
            if not dlg.exec():
                return
            self.send_paths.emit(self.peer_id, list(paths))
            if dlg.caption():
                self.send_text.emit(self.peer_id, dlg.caption())
            return
        self.send_paths.emit(self.peer_id, list(paths))

    def _pick_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("attach_image"), "", f"{tr('images')} (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.heic *.tif *.tiff)")
        self._send_paths(paths)

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("send_file"))
        self._send_paths(paths)

    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, tr("send_folder"))
        if path:
            self._send_paths([path])

    # drag & drop: any file type, any number of files, folders too
    def dragEnterEvent(self, e):
        if local_paths(e.mimeData()):
            e.acceptProposedAction()
            self.overlay.setText("📥\n" + tr("drop_here", name=self.peer_name))
            self.overlay.setGeometry(self.view.rect().adjusted(12, 12, -12, -12))
            self.overlay.show()
            self.overlay.raise_()

    def dragMoveEvent(self, e):
        if local_paths(e.mimeData()):
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.overlay.hide()

    def dropEvent(self, e):
        self.overlay.hide()
        paths = local_paths(e.mimeData())
        if paths:
            e.acceptProposedAction()
            self._send_paths(paths)
