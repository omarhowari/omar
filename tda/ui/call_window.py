"""Call window (incoming / outgoing / in-call) and ringtone."""
from __future__ import annotations

import math
import struct
import sys
import wave

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

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
        self.btn_end = QPushButton("✆  " + tr("hang_up"))
        self.btn_end.setStyleSheet(BTN.format(bg="#DC2626", hover="#B91C1C"))
        self.btn_end.clicked.connect(self.c.hangup)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_accept)
        row.addWidget(self.btn_mute)
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

    def refresh(self, *_):
        st = self.c.state
        self.name.setText(self.c.peer_name)
        self.avatar.setPixmap(draw_avatar(self.c.peer_name, 96))
        self.btn_accept.setVisible(st == "incoming")
        self.btn_mute.setVisible(st == "active")
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

    def _mute(self):
        m = self.c.toggle_mute()
        self.btn_mute.setText("🔇" if m else "🎤")
        self._update_timer()

    def closeEvent(self, e):
        if self.c.state != "idle":
            self.c.hangup()
        e.accept()
