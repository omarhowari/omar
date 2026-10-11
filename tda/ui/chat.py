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

SLIM_SCROLLBAR = """
QScrollBar:vertical { background: transparent; width: 7px; margin: 0px; border: none; }
QScrollBar::handle:vertical { background: rgba(0,0,0,0.22); border-radius: 3px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: rgba(0,0,0,0.38); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; border: none; background: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
"""
_res_cache: dict = {}


def _resource(key: str):
    """Images drawn by TDA for the chat (cached)."""
    from urllib.parse import unquote
    if key in _res_cache:
        return _res_cache[key]
    img = None
    if key.startswith("tick/"):
        img = _tick_image(key[5:])
    elif key.startswith("round/"):
        try:
            _, size, path = key.split("/", 2)
            w, h = (int(x) for x in size.split("x"))
            img = _rounded_image(unquote(path), w, h)
        except ValueError:
            img = None
    if len(_res_cache) > 400:
        _res_cache.clear()
    _res_cache[key] = img
    return img


def _rounded_image(path: str, w: int, h: int):
    from PySide6.QtGui import QPainterPath
    src = QImage(path)
    if src.isNull():
        return None
    dpr = 2
    src = src.scaled(w * dpr, h * dpr, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    out = QImage(w * dpr, h * dpr, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, w * dpr, h * dpr, 9 * dpr, 9 * dpr)
    p.setClipPath(clip)
    p.drawImage((w * dpr - src.width()) // 2, (h * dpr - src.height()) // 2, src)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


def _tick_image(kind: str):
    """WhatsApp-style ticks: sent (one grey), delivered (two grey), read (two blue), pending (clock)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen
    dpr = 3
    w, h = (18, 11) if kind in ("delivered", "read") else (12, 11)
    img = QImage(w * dpr, h * dpr, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(dpr, dpr)
    color = QColor("#53BDEB") if kind == "read" else QColor("#DC2626") if kind == "failed" else QColor("#8696A0")
    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    if kind == "pending":
        p.drawEllipse(QPointF(6, 5.5), 4.3, 4.3)
        p.drawLine(QPointF(6, 5.5), QPointF(6, 3))
        p.drawLine(QPointF(6, 5.5), QPointF(7.8, 6.6))
    elif kind == "failed":
        p.drawEllipse(QPointF(6, 5.5), 4.5, 4.5)
        p.drawLine(QPointF(6, 3), QPointF(6, 6.2))
        p.drawPoint(QPointF(6, 8))
    else:
        p.drawPolyline([QPointF(1.5, 6), QPointF(4.3, 8.8), QPointF(10.5, 2)])
        if kind in ("delivered", "read"):
            p.drawPolyline([QPointF(7.6, 8.4), QPointF(8.2, 8.8), QPointF(14.6, 2)])
    p.end()
    img.setDevicePixelRatio(dpr)
    return img


def tick_html(status: str) -> str:
    kind = {"read": "read", "delivered": "delivered", "queued": "sent", "sent": "sent",
            "failed": "failed"}.get(status or "", "pending")
    w = 18 if kind in ("delivered", "read") else 12
    return f'<img src="tdaimg:tick/{kind}" width="{w}" height="11">'


REACTIONS = ("👍", "❤️", "😂", "😮", "😢", "🙏")
MORE_EMOJIS = ("👍", "👎", "❤️", "🔥", "👏", "🎉", "😂", "🤣", "😊", "😍", "🤔", "😮", "😢", "😡", "🙏", "💯",
               "✅", "❌", "👌", "🤝", "💪", "🌹", "☕", "⭐")


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
        # no horizontal bar: everything wraps to the window width (like WhatsApp)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # thin WhatsApp-like scroll bar (no arrows, light grey handle)
        self.verticalScrollBar().setStyleSheet(SLIM_SCROLLBAR)

    message_menu = Signal(str, object)      # msg id, global QPoint

    def msg_at(self, pos) -> str:
        """Id of the message bubble under a point of the viewport ("" if none)."""
        from PySide6.QtGui import QTextCursor, QTextTable
        cur = self.cursorForPosition(pos)
        table = cur.currentTable()
        while table is not None:
            cell = table.cellAt(cur)
            if cell.isValid():
                c = QTextCursor(cell.firstCursorPosition())
                for _ in range(3):
                    c.movePosition(QTextCursor.MoveOperation.NextCharacter)
                    for name in c.charFormat().anchorNames():
                        if name.startswith("m_"):
                            return name[2:]
            parent = table.parentFrame()
            cur = QTextCursor(table.firstCursorPosition())
            cur.movePosition(QTextCursor.MoveOperation.PreviousCharacter)
            table = parent if isinstance(parent, QTextTable) else None
        return ""

    def contextMenuEvent(self, e):
        mid = self.msg_at(e.pos())
        if mid:
            self.message_menu.emit(mid, e.globalPos())
            return
        super().contextMenuEvent(e)

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
        p.setOpacity(1.0)
        self._paint_bubbles(p)
        p.end()
        super().paintEvent(e)

    # ---- WhatsApp-like rounded bubbles: Qt rich text can only draw square table backgrounds, so the
    #      tables are made transparent and their rounded shapes (with a small tail) are painted here.
    BUBBLE_RADIUS = 8.0
    bubble_border = False

    def setHtml(self, text):
        super().setHtml(text)
        self._collect_bubbles()

    def _collect_bubbles(self):
        from PySide6.QtGui import QTextFrameFormat, QTextTable
        self._bubbles = []

        def walk(frame, depth):
            for child in frame.childFrames():
                if isinstance(child, QTextTable):
                    fmt = child.format()
                    brush = fmt.background()
                    if brush.style() != Qt.BrushStyle.NoBrush:
                        color = QColor(brush.color())
                        al = fmt.alignment()
                        side = ("right" if (al & Qt.AlignmentFlag.AlignRight or
                                            fmt.position() == QTextFrameFormat.Position.FloatRight) else
                                "left" if (al & Qt.AlignmentFlag.AlignLeft or
                                           fmt.position() == QTextFrameFormat.Position.FloatLeft) else "")
                        fmt.setBackground(Qt.BrushStyle.NoBrush)
                        fmt.setBorder(0)
                        fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_None)
                        child.setFormat(fmt)
                        self._bubbles.append((child, color, depth == 0 and bool(side), side))
                walk(child, depth + 1)

        walk(self.document().rootFrame(), 0)

    def _paint_bubbles(self, p):
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QPainterPath, QPen
        if not getattr(self, "_bubbles", None):
            return
        layout = self.document().documentLayout()
        dx, dy = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        view_h = self.viewport().height()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for table, color, top, side in self._bubbles:
            fmt = table.format()
            r = layout.frameBoundingRect(table)
            # (Qt reports the box shifted by the cell padding and including the margins)
            pad = fmt.cellPadding()
            r = QRectF(r.x() - pad - dx, r.y() - pad - dy,
                       r.width() - fmt.leftMargin() - fmt.rightMargin(),
                       r.height() - fmt.topMargin() - fmt.bottomMargin())
            if r.bottom() < 0 or r.top() > view_h or r.width() <= 0:
                continue
            rad = self.BUBBLE_RADIUS if top else 6.0
            path = QPainterPath()
            path.addRoundedRect(r, rad, rad)
            if top:
                tail = QPainterPath()          # small tail at the top outer corner
                if side == "right":
                    tail.moveTo(r.right() - rad, r.top())
                    tail.lineTo(r.right() + 7, r.top())
                    tail.lineTo(r.right(), r.top() + 9)
                else:
                    tail.moveTo(r.left() + rad, r.top())
                    tail.lineTo(r.left() - 7, r.top())
                    tail.lineTo(r.left(), r.top() + 9)
                tail.closeSubpath()
                path = path.united(tail)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 28))       # soft shadow
                p.drawPath(path.translated(0, 1))
            p.setBrush(color)
            p.setPen(QPen(QColor("#D1D5DB"), 0.8) if (top and self.bubble_border) else Qt.PenStyle.NoPen)
            p.drawPath(path)

    def loadResource(self, rtype, url):
        """tdaimg:round/<w>x<h>/<path>  -> picture with rounded corners;  tdaimg:tick/<kind> -> ✓ / ✓✓ icons."""
        u = url.toString()
        if u.startswith("tdaimg:"):
            return _resource(u[7:])
        return super().loadResource(rtype, url)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.viewport().update()          # keep the background fixed while scrolling


class MessageInput(QPlainTextEdit):
    submit = Signal()
    escape = Signal()
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
        if e.key() == Qt.Key.Key_Escape:
            self.escape.emit()
        super().keyPressEvent(e)


_NAME_COLORS = ("#428177", "#C2410C", "#7C3AED", "#0E7490", "#BE185D", "#4D7C0F", "#B45309", "#1D4ED8")


def _name_color(name: str) -> str:
    """Each sender keeps the same colour in group chats (like WhatsApp)."""
    import zlib
    return _NAME_COLORS[zlib.crc32(name.encode("utf-8")) % len(_NAME_COLORS)]


def _is_dark(color: str) -> bool:
    c = QColor(color)
    return c.isValid() and (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) < 140


class ChatWidget(QWidget):
    # message bubble appearance, shared by all chats (settings or the administrator's published look)
    APPEARANCE = {"me": "#D9FDD3", "them": "#FFFFFF", "pt": 10.5, "border": True}

    @classmethod
    def set_appearance(cls, me: str, them: str, pt: float, border: bool):
        cls.APPEARANCE = {"me": me if QColor(me).isValid() else "#D9FDD3",
                          "them": them if QColor(them).isValid() else "#FFFFFF",
                          "pt": max(8.0, min(20.0, float(pt or 10.5))), "border": bool(border)}

    def _bubble(self, mine: bool):
        a = self.APPEARANCE
        bg = a["me"] if mine else a["them"]
        if _is_dark(bg):
            fg = {"text": "#F9FAFB", "name": "#FDE68A", "muted": "#D1D5DB"}
        else:
            fg = {"text": "#111827", "name": ACCENT, "muted": "#9CA3AF"}
        border = "border:1px solid #D1D5DB" if a["border"] else "border:0px"
        return bg, fg, border, a["pt"]

    send_text = Signal(str, str)        # peer_id, text
    send_paths = Signal(str, list)      # peer_id, [paths]
    start_call = Signal(str)            # peer_id
    transfer_action = Signal(str, str)  # action, tid
    manage_group = Signal(str)          # chat key "g:<gid>"
    header_menu = Signal(str, object)    # chat key, global position of the ⋮ button
    message_action = Signal(str, str, str)   # action (react|forward|star|delete_me|delete_all|download), msg id, arg

    def __init__(self, peer_id: str, peer_name: str, my_name: str, parent=None, is_group: bool = False):
        super().__init__(parent)
        self.peer_id, self.peer_name, self.my_name = peer_id, peer_name, my_name
        self.is_group = is_group
        self.is_admin = False
        self.can_write = self.can_media = True
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
        # WhatsApp-style header icons:  📞  🔍  ⋮
        from .theme import svg_icon

        def icon_btn(name, tip):
            b = QPushButton(objectName="HeadIcon")
            b.setIcon(svg_icon(name))
            b.setIconSize(QSize(22, 22))
            b.setFixedSize(40, 40)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton#HeadIcon{border:none;border-radius:20px;background:transparent}"
                            "QPushButton#HeadIcon:hover{background:#E9EDEF}"
                            "QPushButton#HeadIcon:disabled{background:transparent}")
            return b

        self.btn_call = icon_btn("call", tr("call_btn"))
        self.btn_call.clicked.connect(lambda: self.start_call.emit(self.peer_id))
        self.btn_search = icon_btn("search", tr("search"))
        self.btn_search.clicked.connect(self.toggle_search)
        self.btn_more = icon_btn("more", tr("more_options"))
        self.btn_more.clicked.connect(lambda: self.header_menu.emit(
            self.peer_id, self.btn_more.mapToGlobal(self.btn_more.rect().bottomLeft())))
        hl.addWidget(self.btn_call)
        hl.addWidget(self.btn_search)
        hl.addWidget(self.btn_more)
        self.btn_manage = self.btn_more          # (kept for older code)
        self.btn_call.setVisible(not is_group)
        self.my_id = ""
        self.reply_to: dict | None = None

        self.search_bar = QFrame(objectName="SearchBar")
        self.search_bar.setStyleSheet("#SearchBar{background:#F0F2F5;border-bottom:1px solid #E5E7EB}")
        sl = QHBoxLayout(self.search_bar)
        sl.setContentsMargins(12, 6, 12, 6)
        from PySide6.QtWidgets import QLineEdit
        self.search_box = QLineEdit(placeholderText=tr("search_in_chat"))
        self.search_box.setClearButtonEnabled(True)
        self.search_box.returnPressed.connect(lambda: self.find_text(False))
        self.search_box.textChanged.connect(lambda _t: self.find_text(False, restart=True))
        up, down, close = QPushButton("▲"), QPushButton("▼"), QPushButton("✕")
        for b in (up, down, close):
            b.setFixedSize(32, 30)
            b.setStyleSheet("border:none;background:transparent;font-size:11pt;color:#54656F;padding:0")
        up.clicked.connect(lambda: self.find_text(True))
        down.clicked.connect(lambda: self.find_text(False))
        close.clicked.connect(self.toggle_search)
        self.search_count = QLabel(objectName="Muted")
        sl.addWidget(self.search_box, 1)
        sl.addWidget(self.search_count)
        sl.addWidget(up)
        sl.addWidget(down)
        sl.addWidget(close)
        self.search_bar.hide()

        self.view = ChatView()
        self.view.message_menu.connect(self.message_menu)
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
        self.input.escape.connect(self.cancel_reply)
        self.input.files_pasted.connect(self._send_paths)

        from .theme import svg_icon as _svg
        self.btn_attach = QPushButton()
        self.btn_attach.setIcon(_svg("attach", "#54656F", rotate=45))
        self.btn_attach.setIconSize(QSize(24, 24))
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

        # "replying to ..." strip shown above the text box (WhatsApp style)
        self.reply_bar = QFrame(objectName="ReplyBar")
        edge = "right" if lang() == "ar" else "left"
        self.reply_bar.setStyleSheet("#ReplyBar{background:#F0F2F5;border-radius:10px}"
                                     f"#ReplyQuote{{background:white;border-radius:6px;border-{edge}:4px solid #0E8F6F}}"
                                     "#ReplyX{border:none;background:transparent;color:#54656F;font-size:14pt;"
                                     "padding:0px;min-width:0px}#ReplyX:hover{color:#B91C1C}")
        rb = QHBoxLayout(self.reply_bar)
        rb.setContentsMargins(8, 6, 8, 6)
        self.reply_lbl = QLabel(objectName="ReplyQuote")
        self.reply_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.reply_lbl.setContentsMargins(10, 6, 10, 6)
        x = QPushButton("✕", objectName="ReplyX")
        x.setToolTip(tr("cancel"))
        x.setFixedSize(32, 32)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.clicked.connect(self.cancel_reply)
        rb.addWidget(self.reply_lbl, 1)
        rb.addWidget(x)
        self.reply_bar.hide()

        bottom = QFrame(objectName="ComposeBar")
        bvv = QVBoxLayout(bottom)
        bvv.setContentsMargins(12, 8, 12, 10)
        bvv.setSpacing(6)
        bvv.addWidget(self.reply_bar)
        bv = QHBoxLayout()
        bvv.addLayout(bv)
        bv.addWidget(box)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(header)
        lay.addWidget(self.search_bar)
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

    def set_permissions(self, can_write: bool, can_media: bool, reason: str = "", admin: bool = False):
        changed = admin != self.is_admin
        self.can_write, self.can_media, self.is_admin = can_write, can_media, admin
        self.input.setReadOnly(not can_write)
        self.btn_send.setEnabled(can_write)
        self.btn_attach.setEnabled(can_media)
        if not can_write:
            self.input.clear()
            self.input.setPlaceholderText(reason)
        if changed:
            self.schedule_render()

    def set_group(self, name: str, members: int, online: int):
        self.peer_name = name
        self.title.setText("👥 " + name)
        self.online = True
        self.status_lbl.setPixmap(status_icon("available" if online else "offline").pixmap(18, 18))
        self.sub.setText(tr("group_members", n=members, online=online))
        if self.can_write:
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
            if it.get("kind") == "deleted":
                side = mine_side if it.get("outgoing") else theirs_side
                parts.append(f'<table align="{side}" cellspacing="0" cellpadding="8" style="background:#F1F5F9;'
                             f'margin:4px 10px;border:1px solid #E5E7EB"><tr><td><span style="color:#64748B;'
                             f'font-size:9.5pt"><i>{tr("msg_deleted")}</i></span> <span style="color:#9CA3AF;'
                             f'font-size:8pt">{hhmm}</span></td></tr></table><br clear="all">')
                continue
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
                             f'<span style="color:#9CA3AF">{hhmm}</span>  ·  {emb}{html.escape(it["text"])}\u202c</p>')
                continue
            mine = bool(it.get("outgoing"))
            bg, fg, _border, pt = self._bubble(mine)
            ex = it.get("extra") or {}
            mid = it.get("id", "")
            head = ""
            if not mine and self.is_group:      # like WhatsApp: names only in groups
                who = html.escape(it.get("peer_name") or self.peer_name)
                head = (f'<span style="color:{_name_color(it.get("peer_name") or "")};font-size:{pt - 1.5:.1f}pt">'
                        f'<b>{who}</b></span><br>')
            multi = (f'<span style="color:#7C3AED;font-size:{pt - 2.5:.1f}pt">[{tr("multi_tag")}]</span><br>'
                     if it.get("multi") else "")
            fwd = (f'<span style="color:{fg["muted"]};font-size:{pt - 2.5:.1f}pt"><i>↪ {tr("forwarded")}</i></span><br>'
                   if ex.get("fwd") else "")
            parts.append(
                f'<table align="{mine_side if mine else theirs_side}" cellspacing="0" cellpadding="7" '
                f'style="background:{bg};margin:3px 16px">'
                f'<tr><td><a name="m_{mid}">\u200b</a>{head}{multi}{fwd}{self._quote(ex.get("reply"), bg, pt)}'
                f'<span style="font-size:{pt:.1f}pt;color:{fg["text"]}">{_render_text(it.get("text", ""))}</span>'
                f'{self._footer(it, ex, hhmm, fg["muted"], pt)}{self._reactions(ex, pt)}</td></tr></table>'
                f'<br clear="all">')
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
                   "lost": "call_log_lost", "canceled": "call_log_canceled",
                   "restricted": "call_log_restricted"}.get(reason, "call_log_canceled")
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
        bg, _fg, _border, _pt = self._bubble(mine)
        who = tr("me") if mine else html.escape(it.get("peer_name") or self.peer_name)
        emb = "\u202b" if lang() == "ar" else "\u202a"
        if n == 1 and not d.get("is_dir") and os.path.splitext(title)[1].lower() in IMAGE_EXT:
            return self._image_card(it, d, tid, state, live, mine, hhmm, side, bg, who, line, a)
        ex = it.get("extra") or {}
        head = (f'<span style="color:{_name_color(it.get("peer_name") or "")};font-size:8.5pt"><b>{who}</b></span><br>'
                if (not mine and self.is_group) else "")
        foot_item = dict(it, status="delivered" if state == "done" else "queued" if state in ("queued", "offered")
                         else "failed" if state in ("failed", "canceled", "declined") else "")
        return (f'<table align="{side}" cellspacing="0" cellpadding="9" '
                f'style="background:{bg};margin:3px 16px">'
                f'<tr><td><a name="m_{tid}">\u200b</a>{head}'
                f'<span style="font-size:20pt">{icon}</span> <span style="font-size:10.5pt;color:#111827"><b>{emb}{name}\u202c</b></span>'
                f'\u200f <span style="color:#6B7280;font-size:9pt">\u200f({size})\u200f</span>{thumb}<br>'
                f'<span style="font-size:9.5pt">{line}</span>'
                f'{self._footer(foot_item, ex, hhmm, "#8696A0", 10.5)}{self._reactions(ex, 10.5)}'
                f'</td></tr></table><br clear="all">')

    def _image_card(self, it, d, tid, state, live, mine, hhmm, side, bg, who, line, a) -> str:
        """Picture message without a frame, sized like WhatsApp (max 330 px wide, 330 px tall)."""
        src = d.get("source", "") if mine else (d.get("open", "") if state == "done" else "")
        size = image_size(src) if src and os.path.exists(src) else None
        if size:
            w, h = size
            scale = min(330 / max(1, w), 330 / max(1, h))
            w, h = max(60, int(w * scale)), max(60, int(h * scale))
            from urllib.parse import quote
            pic = (f'<a href="tda:open:{tid}"><img src="tdaimg:round/{w}x{h}/{quote(src)}" '
                   f'width="{w}" height="{h}"></a>')
        else:   # not downloaded yet
            pic = (f'<table cellpadding="30" style="background:#DFE5E7"><tr><td align="center">'
                   f'<span style="font-size:30pt">🖼</span><br><span style="color:#64748B;font-size:9pt">'
                   f'{human_size(int(d.get("size", 0)))}</span></td></tr></table>')
        if state == "done":
            status = tick_html(it.get("status") or "delivered") if mine else ""
        elif state in ("accepted", "active"):
            pct = int(100 * live.done / live.total) if (live and live.total) else 0
            status = f'<span style="color:{ACCENT}">{pct}%</span> {a("cancel", "✖", "#B91C1C")}'
        else:
            status = line
        head = "" if mine or not self.is_group else f'<span style="color:{ACCENT};font-size:8.5pt"><b>{who}</b></span><br>'
        ex = it.get("extra") or {}
        return (f'<table align="{side}" cellspacing="0" cellpadding="0" style="margin:6px 12px">'
                f'<tr><td><a name="m_{tid}">\u200b</a>{head}{pic}</td></tr>'
                f'<tr><td align="{"left" if side == "right" else "right"}">'
                f'<span style="color:#667781;font-size:8pt">{self._star(ex)}{hhmm}</span> <span style="font-size:9pt">{status}</span>'
                f'{self._menu_link(tid)}{self._reactions(ex, 10.5)}'
                f'</td></tr></table><br clear="all">')

    def _link(self, url: QUrl):
        s = url.toString()
        if s.startswith("tda:"):
            _, action, tid = s.split(":", 2)
            if action == "menu":
                from PySide6.QtGui import QCursor
                self.message_menu(tid, QCursor.pos())
            elif action == "goto":
                self.view.scrollToAnchor("m_" + tid)
                self._stick = False
            else:
                self.transfer_action.emit(action, tid)
        else:
            QDesktopServices.openUrl(url)

    # ------------------------------------------------------------------ message pieces
    @staticmethod
    def _menu_link(mid: str, color: str = "#8696A0") -> str:
        """The small ⌄ (like WhatsApp) that opens the message menu: react, reply, forward..."""
        return (f'<a href="tda:menu:{mid}" style="color:{color};text-decoration:none;font-size:10pt">'
                f'⌄</a>&nbsp;')

    def _footer(self, it, ex, hhmm, muted, pt) -> str:
        """Bottom line of a bubble, at its end corner like WhatsApp:  ⌄  (edited) ★ 11:38 ✓✓"""
        end = "left" if lang() == "ar" else "right"
        edited = f'<i>{tr("edited")}</i> ' if ex.get("edited") else ""
        tick = (" " + tick_html(it.get("status", ""))) if it.get("outgoing") else ""
        return (f'<p align="{end}" style="margin-top:1px;margin-bottom:0px">'
                f'<span style="color:{muted};font-size:{max(7.5, pt - 2.5):.1f}pt">'
                f'{self._menu_link(it.get("id", ""), muted)} {edited}{self._star(ex)}{hhmm}</span>{tick}</p>')

    @staticmethod
    def _star(ex: dict) -> str:
        return '<span style="color:#F59E0B">★</span> ' if ex.get("star") else ""

    def _quote(self, reply, bg: str, pt: float) -> str:
        """The message being answered, shown at the top of a reply (click: jump to it)."""
        if not reply:
            return ""
        shade = QColor(bg).darker(112).name()
        name = html.escape(reply.get("name") or "")
        text = html.escape((reply.get("text") or "")[:160]).replace("\n", " ")
        return (f'<table width="100%" cellspacing="0" cellpadding="6" style="background:{shade};margin-bottom:4px">'
                f'<tr><td><a href="tda:goto:{reply.get("id", "")}" style="text-decoration:none">'
                f'<span style="color:#0E8F6F;font-size:{pt - 2:.1f}pt"><b>{name}</b></span><br>'
                f'<span style="color:#54656F;font-size:{pt - 1.5:.1f}pt">{text}</span></a></td></tr></table>')

    @staticmethod
    def _reactions(ex: dict, pt: float) -> str:
        r = ex.get("reactions") or {}
        if not r:
            return ""
        counts: dict = {}
        for v in r.values():
            e = v.get("e") if isinstance(v, dict) else v
            if e:
                counts[e] = counts.get(e, 0) + 1
        if not counts:
            return ""
        chips = " ".join(f"{e}{'' if n == 1 else ' ' + str(n)}" for e, n in counts.items())
        return f'<br><span style="color:#54656F;font-size:{pt + 1:.1f}pt">{chips}</span>'

    def item(self, mid: str):
        return next((it for it in self.items if it.get("id") == mid), None)

    def snippet(self, it: dict) -> str:
        """Short text describing a message (for a reply quote / forward)."""
        if it.get("kind") == "file":
            try:
                d = json.loads(it.get("text") or "{}")
            except ValueError:
                d = {}
            title = d.get("title", "")
            if os.path.splitext(title)[1].lower() in IMAGE_EXT:
                return "🖼 " + tr("photo")
            return "📄 " + (title if not title.isdigit() else tr("files_n", n=title))
        return (it.get("text") or "")[:200]

    def message_menu(self, mid: str, gpos):
        m = self.build_message_menu(mid)
        if m is not None:
            m.exec(gpos)

    def build_message_menu(self, mid: str):
        """WhatsApp-style menu: a row of reactions, then reply / copy / download / forward / star / delete."""
        it = self.item(mid)
        if not it or it.get("kind") not in ("msg", "file"):
            return None
        from PySide6.QtWidgets import QToolButton, QWidgetAction
        m = QMenu(self)
        m.setStyleSheet("QMenu{background:white;border:1px solid #E5E7EB;border-radius:12px;padding:6px}"
                        "QMenu::item{padding:8px 26px;border-radius:6px;font-size:10.5pt}"
                        "QMenu::item:selected{background:#F0F2F5}")
        ex = it.get("extra") or {}
        mine_reaction = (ex.get("reactions") or {}).get(self.my_id, {})
        mine_reaction = mine_reaction.get("e") if isinstance(mine_reaction, dict) else mine_reaction
        row = QWidget()
        row.setStyleSheet("QToolButton{border:none;border-radius:17px;font-size:17pt;padding:2px}"
                          "QToolButton:hover{background:#F0F2F5}"
                          "QToolButton:checked{background:#D9FDD3}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(6, 2, 6, 6)
        rl.setSpacing(2)

        def react(e):
            m.close()
            self.message_action.emit("react", mid, "" if e == mine_reaction else e)

        for e in REACTIONS:
            b = QToolButton()
            b.setText(e)
            b.setCheckable(True)
            b.setChecked(e == mine_reaction)
            b.setFixedSize(38, 38)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, x=e: react(x))
            rl.addWidget(b)
        more = QToolButton()
        more.setText("+")
        more.setFixedSize(38, 38)
        more.setToolTip(tr("more_emojis"))
        more.clicked.connect(lambda: (m.close(), self._emoji_grid(mid, mine_reaction)))
        rl.addWidget(more)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(row)
        m.addAction(wa)
        m.addSeparator()
        if self.can_write:
            m.addAction("↩  " + tr("reply"), lambda: self.start_reply(mid))
        if it.get("outgoing") and it.get("kind") == "msg" and self.can_write:
            m.addAction("✎  " + tr("edit"), lambda: self.start_edit(mid))
        m.addAction("⧉  " + tr("copy"), lambda: self.copy_message(mid))
        m.addAction("☺  " + tr("react"), lambda: self._emoji_grid(mid, mine_reaction))
        if it.get("kind") == "file":
            m.addAction("⤓  " + tr("download"), lambda: self.message_action.emit("download", mid, ""))
        m.addAction("↪  " + tr("forward"), lambda: self.message_action.emit("forward", mid, ""))
        m.addAction("☆  " + (tr("unstar") if ex.get("star") else tr("star")),
                    lambda: self.message_action.emit("star", mid, "0" if ex.get("star") else "1"))
        m.addSeparator()
        m.addAction("🗑  " + tr("delete_me"), lambda: self.message_action.emit("delete_me", mid, ""))
        if (it.get("outgoing") and it.get("kind") == "msg") or (self.is_group and self.is_admin):
            a = m.addAction("🗑  " + tr("delete_all"), lambda: self.message_action.emit("delete_all", mid, ""))
            a.setEnabled(it.get("kind") == "msg" or self.is_admin)
        return m

    def _emoji_grid(self, mid, current):
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QGridLayout, QToolButton, QWidgetAction
        m = QMenu(self)
        m.setStyleSheet("QMenu{background:white;border:1px solid #E5E7EB;border-radius:12px;padding:6px}")
        w = QWidget()
        w.setStyleSheet("QToolButton{border:none;border-radius:6px;font-size:17pt}"
                        "QToolButton:hover{background:#F0F2F5}")
        g = QGridLayout(w)
        g.setSpacing(2)
        for i, e in enumerate(MORE_EMOJIS):
            b = QToolButton()
            b.setText(e)
            b.setFixedSize(40, 40)
            b.clicked.connect(lambda _=False, x=e: (m.close(), self.message_action.emit(
                "react", mid, "" if x == current else x)))
            g.addWidget(b, i // 8, i % 8)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(w)
        m.addAction(wa)
        m.exec(QCursor.pos())

    def copy_message(self, mid):
        from PySide6.QtCore import QMimeData
        from PySide6.QtWidgets import QApplication
        it = self.item(mid)
        if not it:
            return
        if it.get("kind") == "file":
            path = self.file_path(it)
            md = QMimeData()
            if path and os.path.exists(path):
                md.setUrls([QUrl.fromLocalFile(path)])
                if os.path.splitext(path)[1].lower() in IMAGE_EXT:
                    img = QImage(path)
                    if not img.isNull():
                        md.setImageData(img)
            md.setText(self.snippet(it))
            QApplication.clipboard().setMimeData(md)
        else:
            QApplication.clipboard().setText(it.get("text") or "")

    @staticmethod
    def file_path(it) -> str:
        """Local path of a sent / received file message ("" if not downloaded yet)."""
        try:
            d = json.loads(it.get("text") or "{}")
        except ValueError:
            return ""
        return d.get("source", "") if it.get("outgoing") else d.get("open", "")

    def start_reply(self, mid):
        it = self.item(mid)
        if not it:
            return
        name = tr("me") if it.get("outgoing") else (it.get("peer_name") or self.peer_name)
        self.reply_to = {"id": mid, "name": name, "text": self.snippet(it)}
        self.reply_lbl.setText(f'<span style="color:#0E8F6F"><b>{html.escape(name)}</b></span><br>'
                               f'<span style="color:#54656F">{html.escape(self.reply_to["text"][:120])}</span>')
        self.reply_bar.show()
        self.input.setFocus()

    def start_edit(self, mid):
        it = self.item(mid)
        if not it:
            return
        self.reply_to = None
        self.editing = mid
        self.reply_lbl.setText(f'<span style="color:#0E8F6F"><b>✎ {tr("editing")}</b></span><br>'
                               f'<span style="color:#54656F">{html.escape((it.get("text") or "")[:120])}</span>')
        self.reply_bar.show()
        self.input.setPlainText(it.get("text") or "")
        self.input.setFocus()
        c = self.input.textCursor()
        c.movePosition(c.MoveOperation.End)
        self.input.setTextCursor(c)

    def cancel_reply(self):
        if getattr(self, "editing", None):
            self.input.clear()
        self.reply_to = None
        self.editing = None
        self.reply_bar.hide()

    def take_reply(self):
        r = self.reply_to
        self.cancel_reply()
        return r

    def update_extra(self, mid, extra: dict) -> bool:
        it = self.item(mid)
        if it is None:
            return False
        it["extra"] = extra
        self.schedule_render()
        return True

    def remove_item(self, mid):
        self.items = [it for it in self.items if it.get("id") != mid]
        self.schedule_render()

    # ------------------------------------------------------------------ search in this chat
    def toggle_search(self):
        show = not self.search_bar.isVisible()
        self.search_bar.setVisible(show)
        if show:
            self.search_box.setFocus()
            self.search_box.selectAll()
        else:
            self.search_box.clear()
            self.search_count.clear()

    def find_text(self, backward: bool, restart: bool = False):
        from PySide6.QtGui import QTextDocument
        q = self.search_box.text().strip()
        if not q:
            self.search_count.clear()
            return
        doc = self.view.document()
        n, c = 0, doc.find(q)
        while not c.isNull() and n < 999:
            n += 1
            c = doc.find(q, c)
        self.search_count.setText(str(n) if n else "0")
        if restart:     # newest match first (bottom of the chat)
            cur = self.view.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            self.view.setTextCursor(cur)
            backward = True
        self._stick = False
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if not self.view.find(q, flags):
            cur = self.view.textCursor()     # wrap around
            cur.movePosition(cur.MoveOperation.End if backward else cur.MoveOperation.Start)
            self.view.setTextCursor(cur)
            self.view.find(q, flags)

    # ------------------------------------------------------------------ actions
    def _submit(self):
        text = self.input.toPlainText().strip()
        if not text:
            return
        if getattr(self, "editing", None):
            mid = self.editing
            self.editing = None
            self.input.clear()
            self.cancel_reply()
            it = self.item(mid)
            if it and text != it.get("text"):
                self.message_action.emit("edit", mid, text)
            return
        self.input.clear()
        self.send_text.emit(self.peer_id, text)

    def _send_paths(self, paths):
        """Every attachment goes through the preview screen (like WhatsApp); each item is then sent on
        its own, so pictures appear as pictures in the chat."""
        paths = [p for p in (paths or []) if p]
        if not paths:
            return
        from .dialogs import ImageSendDialog
        dlg = ImageSendDialog(paths, self.peer_name, self)
        if not dlg.exec():
            return
        for p in dlg.paths():
            self.send_paths.emit(self.peer_id, [p])
        if dlg.caption():
            self.send_text.emit(self.peer_id, dlg.caption())

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
