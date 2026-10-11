"""Call window (incoming / outgoing / in-call) and ringtone."""
from __future__ import annotations

import math
import struct
import sys
import wave

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from ..config import config_dir
from ..i18n import tr
from .theme import ACCENT, GOLD, draw_avatar, draw_logo


# ------------------------------------------------------------------ ringtone (generated, no asset needed)
def _ring_file(kind: str) -> str:
    path = config_dir() / f"ring_{kind}.wav"
    if path.exists():
        return str(path)
    rate = 16000
    frames = []
    if kind == "in":        # classic double ring: 0.4 on, 0.2 off, 0.4 on, 2 s off
        pattern = [(0.4, True), (0.2, False), (0.4, True), (2.0, False)]
        f1, f2, vol = 440, 480, 9000
    else:                   # ring-back tone heard by the caller
        pattern = [(1.0, True), (3.0, False)]
        f1, f2, vol = 425, 425, 4000
    for dur, on in pattern:
        for i in range(int(rate * dur)):
            v = int(vol * (math.sin(2 * math.pi * f1 * i / rate) + math.sin(2 * math.pi * f2 * i / rate)) / 2) if on else 0
            frames.append(struct.pack("<h", v))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(frames))
    return str(path)


class Ringer:
    def __init__(self):
        self.timer = QTimer(interval=3000)
        self.timer.timeout.connect(QApplication.beep)
        self.active = False

    def start(self, kind: str):
        self.stop()
        self.active = True
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(_ring_file(kind), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
                return
            except Exception:
                pass
        if kind == "in":
            QApplication.beep()
            self.timer.start()

    def stop(self):
        if not self.active:
            return
        self.active = False
        self.timer.stop()
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except Exception:
                pass


# ------------------------------------------------------------------ window
BTN = ("QPushButton {{ background:{bg}; color:white; border:none; border-radius:26px; font-size:13pt;"
       " font-weight:600; min-width:52px; min-height:52px; padding:0 18px; }}"
       " QPushButton:hover {{ background:{hover}; }}")


class CallWindow(QWidget):
    closed = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.c = controller
        self.setWindowTitle(tr("call"))
        self.setFixedSize(340, 430)
        self.setObjectName("CallWindow")
        self.setStyleSheet(f"#CallWindow {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {ACCENT}, stop:1 #031F18); }}"
                           f" QLabel {{ color: white; }}")

        self.logo = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.logo.setPixmap(draw_logo(54))
        self.avatar = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.name = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.name.setStyleSheet("font-size:17pt; font-weight:700;")
        self.status = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet(f"font-size:11pt; color:{GOLD};")
        self.warn = QLabel(alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True)
        self.warn.setStyleSheet("color:#FCA5A5; font-size:9pt;")

        self.btn_accept = QPushButton("📞  " + tr("answer"))
        self.btn_accept.setStyleSheet(BTN.format(bg="#16A34A", hover="#15803D"))
        self.btn_accept.clicked.connect(self.c.accept)
        self.btn_mute = QPushButton("🎤")
        self.btn_mute.setToolTip(tr("mute"))
        self.btn_mute.setStyleSheet(BTN.format(bg="#334155", hover="#475569"))
        self.btn_mute.clicked.connect(self._mute)
        self.btn_cam = QPushButton("📷")
        self.btn_cam.setToolTip(tr("camera"))
        self.btn_cam.setStyleSheet(BTN.format(bg="#334155", hover="#475569"))
        self.btn_cam.clicked.connect(lambda: self._toggle("camera"))
        self.btn_screen = QPushButton("🖥")
        self.btn_screen.setToolTip(tr("share_screen"))
        self.btn_screen.setStyleSheet(BTN.format(bg="#334155", hover="#475569"))
        self.btn_screen.clicked.connect(lambda: self._toggle("screen"))
        self.btn_end = QPushButton("✆  " + tr("hang_up"))
        self.btn_end.setStyleSheet(BTN.format(bg="#DC2626", hover="#B91C1C"))
        self.btn_end.clicked.connect(self.c.hangup)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_accept)
        row.addWidget(self.btn_mute)
        row.addWidget(self.btn_cam)
        row.addWidget(self.btn_screen)
        row.addWidget(self.btn_end)
        row.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 22)
        lay.addWidget(self.logo)
        lay.addStretch(1)
        lay.addWidget(self.avatar)
        lay.addWidget(self.name)
        lay.addWidget(self.status)
        lay.addWidget(self.warn)
        lay.addStretch(2)
        lay.addLayout(row)

        self.ringer = Ringer()
        self.tick = QTimer(self, interval=1000)
        self.tick.timeout.connect(self._update_timer)
        self.c.state_changed.connect(self.refresh)
        self.c.audio_warning.connect(lambda e: self.warn.setText(tr("audio_problem")))
        self.video = VideoWindow(controller)
        self.c.video_state.connect(self._video_state)

    def refresh(self, *_):
        st = self.c.state
        self.name.setText(self.c.peer_name)
        self.avatar.setPixmap(draw_avatar(self.c.peer_name, 96))
        self.btn_accept.setVisible(st == "incoming")
        self.btn_mute.setVisible(st == "active")
        self.btn_cam.setVisible(st == "active")
        self.btn_screen.setVisible(st == "active")
        self.btn_end.setText("✆  " + (tr("decline") if st == "incoming" else tr("hang_up")))
        if st == "incoming":
            self.status.setText(tr("call_incoming"))
            self.ringer.start("in")
        elif st == "outgoing":
            self.status.setText(tr("call_calling"))
            self.ringer.start("out")
        elif st == "active":
            self.ringer.stop()
            self.tick.start()
            self._update_timer()
        else:
            self.ringer.stop()
            self.tick.stop()
            self.warn.clear()
            self.video.hide()
            self.hide()
            self.closed.emit()
            return
        if not self.isVisible():
            self._place()
            self.show()
        self.raise_()
        self.activateWindow()

    def _place(self):
        scr = QApplication.primaryScreen()
        if scr:
            g = scr.availableGeometry()
            self.move(g.right() - self.width() - 24, g.bottom() - self.height() - 24)

    def _update_timer(self):
        d = int(self.c.duration)
        self.status.setText(f"{d // 60:02d}:{d % 60:02d}" + ("   🔇" if self.c.muted else ""))

    def _toggle(self, kind):
        from ..video import CameraSource
        if kind == "camera" and not self.c.is_on("camera") and not CameraSource.available():
            QMessageBox.information(self, tr("call"), tr("no_camera"))
            return
        self.c.toggle_video(kind)

    def _video_state(self):
        on_bg, off_bg = "#0E4D3C", "#334155"
        for kind, btn in (("camera", self.btn_cam), ("screen", self.btn_screen)):
            bg = on_bg if self.c.is_on(kind) else off_bg
            btn.setStyleSheet(BTN.format(bg=bg, hover="#475569"))
        self.btn_screen.setToolTip(tr("stop_share") if self.c.is_on("screen") else tr("share_screen"))
        any_video = self.c.is_on("camera") or self.c.is_on("screen") or any(self.c.remote_video.values())
        if self.c.state == "active" and any_video:
            if not self.video.isVisible():
                self.video.open_for(self.c.peer_name)
        elif not any_video:
            self.video.hide()

    def _mute(self):
        m = self.c.toggle_mute()
        self.btn_mute.setText("🔇" if m else "🎤")
        self._update_timer()

    def closeEvent(self, e):
        if self.c.state != "idle":
            self.c.hangup()
        e.accept()


# ------------------------------------------------------------------ video
class VideoView(QWidget):
    """Paints the latest frame scaled to fit (letterboxed)."""

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self.img = None
        self.placeholder = placeholder
        self.setMinimumSize(160, 90)

    def set_image(self, img):
        self.img = img
        self.update()

    def clear(self):
        self.img = None
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0B1512"))
        if self.img is not None and not self.img.isNull():
            sz = self.img.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            r = QRect((self.width() - sz.width()) // 2, (self.height() - sz.height()) // 2, sz.width(), sz.height())
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(r, self.img)
        elif self.placeholder:
            p.setPen(QColor("#94A3B8"))
            f = QFont()
            f.setPointSize(13)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder)
        p.end()


class VideoWindow(QWidget):
    """Large remote video (screen share takes priority) with a small preview of our own camera."""

    def __init__(self, controller, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.c = controller
        self.resize(960, 600)
        self.setStyleSheet("background:#0B1512;")
        self.remote = {"camera": None, "screen": None}
        self.main = VideoView(tr("waiting_video"), self)
        self.pip = VideoView("", self)          # remote camera while they share the screen
        self.me = VideoView("", self)           # our own camera / screen preview
        for v in (self.pip, self.me):
            v.setFixedSize(220, 132)
            v.hide()

        def btn(text, tip, slot, bg="#334155"):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setStyleSheet(BTN.format(bg=bg, hover="#475569"))
            b.clicked.connect(slot)
            return b
        self.b_cam = btn("📷", tr("camera"), lambda: self._toggle("camera"))
        self.b_scr = btn("🖥", tr("share_screen"), lambda: self._toggle("screen"))
        self.b_full = btn("⛶", tr("fullscreen"), self._fullscreen)
        self.b_end = btn("✆  " + tr("hang_up"), tr("hang_up"), self.c.hangup, bg="#DC2626")
        bar = QHBoxLayout()
        bar.addStretch(1)
        for b in (self.b_cam, self.b_scr, self.b_full, self.b_end):
            bar.addWidget(b)
        bar.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 10)
        lay.addWidget(self.main, 1)
        lay.addLayout(bar)
        controller.video_frame.connect(self._remote_frame)
        controller.local_frame.connect(self._local_frame)
        controller.video_state.connect(self._state)

    def open_for(self, name):
        self.setWindowTitle(tr("video_title", name=name))
        self.main.clear()
        self.show()
        self.raise_()

    def _toggle(self, kind):
        from ..video import CameraSource
        if kind == "camera" and not self.c.is_on("camera") and not CameraSource.available():
            QMessageBox.information(self, tr("call"), tr("no_camera"))
            return
        self.c.toggle_video(kind)

    def _fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _remote_frame(self, kind, img):
        self.remote[kind] = img
        self._compose()

    def _local_frame(self, kind, img):
        if kind == "camera" or not self.c.is_on("camera"):
            self.me.set_image(img)

    def _state(self):
        rv = self.c.remote_video
        for k in ("camera", "screen"):
            if not rv.get(k):
                self.remote[k] = None
        if not (self.c.is_on("camera") or self.c.is_on("screen")):
            self.me.clear()
        for kind, b in (("camera", self.b_cam), ("screen", self.b_scr)):
            b.setStyleSheet(BTN.format(bg="#0E4D3C" if self.c.is_on(kind) else "#334155", hover="#475569"))
        self._compose()

    def _compose(self):
        scr, cam = self.remote["screen"], self.remote["camera"]
        self.main.set_image(scr if scr is not None else cam)
        self.pip.setVisible(scr is not None and cam is not None)
        if scr is not None and cam is not None:
            self.pip.set_image(cam)
        self.me.setVisible(self.c.is_on("camera") or self.c.is_on("screen"))
        self._place_overlays()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_overlays()

    def _place_overlays(self):
        g = self.main.geometry()
        self.me.move(g.right() - self.me.width() - 10, g.bottom() - self.me.height() - 10)
        self.pip.move(g.left() + 10, g.bottom() - self.pip.height() - 10)
        self.me.raise_()
        self.pip.raise_()

    def closeEvent(self, e):
        e.accept()          # closing the video window keeps the voice call running
