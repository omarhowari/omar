"""Video for calls: camera and screen sharing.

Frames are JPEG images sent over an encrypted TCP "media link" that is opened
between the two computers when a call becomes active. Everything stays on the LAN.

frame payload (inside an encrypted binary frame):  1 byte source ("C" camera | "S" screen) + JPEG bytes
control (encrypted JSON frame):                     {"type": "video_state", "camera": bool, "screen": bool}
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QCursor, QColor
from PySide6.QtNetwork import QTcpSocket

from .protocol import FrameBuffer, ProtocolError, encode_bin, encode_json

MAX_BACKLOG = 768 * 1024          # skip frames while the network is still busy with older ones
SCREEN_FPS = 5
SCREEN_MAX_W = 1600
CAMERA_FPS = 12
CAMERA_MAX_W = 640


def to_jpeg(img: QImage, max_w: int, quality: int) -> bytes:
    if img.width() > max_w:
        img = img.scaledToWidth(max_w)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPG", quality)
    buf.close()
    return bytes(ba)


def from_jpeg(data: bytes) -> QImage:
    img = QImage()
    img.loadFromData(data, "JPG")
    return img


# ============================================================================ transport
class MediaLink(QObject):
    """Bidirectional encrypted channel for video frames during one call."""
    frame = Signal(str, object)       # "camera" | "screen", QImage
    state = Signal(dict)              # remote {"camera": bool, "screen": bool}
    closed = Signal()

    def __init__(self, cipher, sock: QTcpSocket, fb: Optional[FrameBuffer] = None, parent=None):
        super().__init__(parent)
        self.cipher = cipher
        self.sock = sock
        sock.setParent(self)
        self.fb = fb or FrameBuffer(cipher)
        self.is_closed = False
        self.sent = self.received = self.skipped = 0
        sock.readyRead.connect(self._read)
        sock.disconnected.connect(self.close)
        if self.fb.buf:                       # frames that arrived together with the handshake
            QTimer.singleShot(0, self._parse)

    @classmethod
    def connect_to(cls, cipher, host: str, port: int, hello: dict, parent=None) -> "MediaLink":
        sock = QTcpSocket()
        link = cls(cipher, sock, parent=parent)
        sock.connected.connect(lambda: sock.write(encode_json(cipher, hello)))
        sock.connectToHost(host, port)
        return link

    def _read(self):
        self.fb.feed(bytes(self.sock.readAll()))
        self._parse()

    def _parse(self):
        try:
            for kind, body in self.fb.frames():
                if kind == "bin" and len(body) > 1:
                    img = from_jpeg(body[1:])
                    if not img.isNull():
                        self.received += 1
                        self.frame.emit("camera" if body[:1] == b"C" else "screen", img)
                elif kind == "json" and body.get("type") == "video_state":
                    self.state.emit({"camera": bool(body.get("camera")), "screen": bool(body.get("screen"))})
        except ProtocolError:
            self.close()

    def send_image(self, source: str, img: QImage) -> bool:
        if self.is_closed or self.sock.state() != QTcpSocket.SocketState.ConnectedState:
            return False
        if self.sock.bytesToWrite() > MAX_BACKLOG:
            self.skipped += 1
            return False
        if source == "screen":
            data = to_jpeg(img, SCREEN_MAX_W, 60)
        else:
            data = to_jpeg(img, CAMERA_MAX_W, 65)
        self.sock.write(encode_bin(self.cipher, (b"S" if source == "screen" else b"C") + data))
        self.sent += 1
        return True

    def send_state(self, camera: bool, screen: bool):
        if not self.is_closed and self.sock.state() == QTcpSocket.SocketState.ConnectedState:
            self.sock.write(encode_json(self.cipher, {"type": "video_state", "camera": camera, "screen": screen}))

    def close(self):
        if self.is_closed:
            return
        self.is_closed = True
        self.sock.abort()
        self.closed.emit()


# ============================================================================ sources
class ScreenSource(QObject):
    """Captures what the user chose to share a few times per second (with the mouse pointer):
    target = {"kind": "screen", "index": n}  -> a whole monitor
             {"kind": "window", "hwnd": h}   -> one application / folder window (Windows)"""
    image = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None, target: Optional[dict] = None, fps: int = SCREEN_FPS):
        super().__init__(parent)
        self.target = target or {"kind": "screen", "index": 0}
        self.timer = QTimer(self, interval=int(1000 / fps))
        self.timer.timeout.connect(self._grab)
        self.screen = None

    @staticmethod
    def available() -> bool:
        return QGuiApplication.primaryScreen() is not None

    def start(self) -> bool:
        if self.target.get("kind") == "window":
            from . import winshare
            if not winshare.is_alive(self.target.get("hwnd")):
                return False
        else:
            screens = QGuiApplication.screens()
            i = int(self.target.get("index", 0))
            self.screen = screens[i] if 0 <= i < len(screens) else QGuiApplication.primaryScreen()
            if self.screen is None:
                return False
        self.timer.start()
        self._grab()
        return True

    def stop(self):
        self.timer.stop()

    def _grab(self):
        if self.target.get("kind") == "window":
            from . import winshare
            hwnd = self.target.get("hwnd")
            if not winshare.is_alive(hwnd):
                self.stop()
                self.error.emit("window closed")
                return
            img = winshare.capture_window(hwnd)
            if img is None:          # minimized: keep the last frame on the other side
                return
            rect = winshare.window_rect(hwnd)
            cur = winshare.cursor_pos()
            ox, oy = (rect[0], rect[1]) if rect else (0, 0)
            x, y = (cur[0] - ox, cur[1] - oy) if cur else (-1, -1)
            ratio = 1.0
        else:
            if self.screen is None:
                return
            pm = self.screen.grabWindow(0)
            if pm.isNull():
                return
            img = pm.toImage()
            cur = QCursor.pos() - self.screen.geometry().topLeft()
            ratio = pm.devicePixelRatio() or 1.0
            x, y = int(cur.x() * ratio), int(cur.y() * ratio)
        if 0 <= x < img.width() and 0 <= y < img.height():
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QColor("white"))
            p.setBrush(QColor(220, 38, 38, 220))
            r = max(6, int(8 * ratio))
            p.drawEllipse(x - r, y - r, 2 * r, 2 * r)
            p.end()
        self.image.emit(img)


class CameraSource(QObject):
    """Webcam through Qt Multimedia (Windows Media Foundation backend)."""
    image = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None, fps: int = CAMERA_FPS):
        super().__init__(parent)
        self.min_gap_ms = int(1000 / fps)
        self.camera = self.session = self.sink = None
        self._last = 0

    @staticmethod
    def available() -> bool:
        try:
            from PySide6.QtMultimedia import QMediaDevices
            return len(QMediaDevices.videoInputs()) > 0
        except Exception:
            return False

    def start(self) -> bool:
        try:
            from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
        except Exception as e:
            self.error.emit(str(e))
            return False
        devices = QMediaDevices.videoInputs()
        if not devices:
            self.error.emit("no camera")
            return False
        self.camera = QCamera(QMediaDevices.defaultVideoInput() or devices[0], self)
        self.sink = QVideoSink(self)
        self.session = QMediaCaptureSession(self)
        self.session.setCamera(self.camera)
        self.session.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._frame)
        self.camera.errorOccurred.connect(lambda _e, msg: self.error.emit(msg))
        self.camera.start()
        return True

    def _frame(self, frame):
        from PySide6.QtCore import QDateTime
        now = QDateTime.currentMSecsSinceEpoch()
        if now - self._last < self.min_gap_ms:
            return
        self._last = now
        img = frame.toImage()
        if not img.isNull():
            self.image.emit(img)

    def stop(self):
        if self.camera is not None:
            self.camera.stop()
            self.camera.deleteLater()
            self.camera = None
