"""Voice-call test with a fake audio device (no microphone needed).

Run:  python -m tests.test_calls
"""
import math
import os
import struct
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402

from tda.calls import FRAME_SAMPLES, AudioBackend, CallController  # noqa: E402
from tda.config import Settings  # noqa: E402
from tda.network import NetworkCore  # noqa: E402

app = QGuiApplication.instance() or QGuiApplication(sys.argv)


class FakeAudio(AudioBackend):
    """Produces a sine tone every 20 ms (from a thread) and records what it is asked to play."""

    def __init__(self, freq):
        self.freq, self.played, self.run = freq, [], False
        self.input_ok = self.output_ok = True

    def start(self, on_frame):
        import threading
        self.run = True

        def loop():
            n = 0
            while self.run:
                pcm = struct.pack("<%dh" % FRAME_SAMPLES, *(int(8000 * math.sin(2 * math.pi * self.freq * (n + i) / 16000))
                                                             for i in range(FRAME_SAMPLES)))
                n += FRAME_SAMPLES
                on_frame(pcm)
                time.sleep(0.02)
        threading.Thread(target=loop, daemon=True).start()

    def play(self, frame):
        self.played.append(frame)

    def stop(self):
        self.run = False


def wait(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.01)
    return cond()


def dominant_freq(frames):
    """Rough frequency estimate by counting zero crossings."""
    data = b"".join(frames[-25:])
    s = struct.unpack("<%dh" % (len(data) // 2), data)
    z = sum(1 for a, b in zip(s, s[1:]) if (a < 0) != (b < 0))
    return z / 2 / (len(s) / 16000)


def make(name, base, peer, pw):
    tmp = tempfile.mkdtemp()
    s = Settings(name=name, udp_port=base, tcp_port=base + 1, password=pw,
                 extra_hosts=[f"127.0.0.1:{peer}"], download_dir=str(Path(tmp) / "dl"))
    c = NetworkCore(s, data_dir=Path(tmp) / "data")
    assert c.start()
    return c


class FakeVideo(QObject):
    """Stands in for a webcam / screen: emits solid-colour frames."""
    image = Signal(object)

    def __init__(self, color, size):
        super().__init__()
        self.color, self.size = color, size
        self.timer = QTimer(self, interval=100)
        self.timer.timeout.connect(self._emit)

    def start(self):
        self.timer.start()
        return True

    def stop(self):
        self.timer.stop()

    def _emit(self):
        img = QImage(*self.size, QImage.Format.Format_RGB32)
        img.fill(QColor(self.color))
        self.image.emit(img)


def main():
    a, b = make("Ali", 48600, 48610, "k"), make("Bana", 48610, 48600, "k")
    assert wait(lambda: b.settings.user_id in a.peers and a.settings.user_id in b.peers)
    fa, fb = FakeAudio(440), FakeAudio(1000)
    ca, cb = CallController(a, lambda: fa), CallController(b, lambda: fb)
    ends = []
    ca.ended.connect(lambda *x: ends.append(("A",) + x))
    cb.ended.connect(lambda *x: ends.append(("B",) + x))

    # 1) call, accept, talk both ways
    assert ca.start_call(b.settings.user_id)
    assert wait(lambda: cb.state == "incoming"), cb.state
    print("ringing ok:", ca.state, "/", cb.state)
    cb.accept()
    assert wait(lambda: ca.state == "active" and cb.state == "active")
    assert wait(lambda: len(fa.played) > 60 and len(fb.played) > 60, 8), (len(fa.played), len(fb.played))
    fa_hears, fb_hears = dominant_freq(fa.played), dominant_freq(fb.played)
    print(f"audio ok: A hears ~{fa_hears:.0f} Hz (B sends 1000), B hears ~{fb_hears:.0f} Hz (A sends 440)")
    assert 900 < fa_hears < 1100 and 380 < fb_hears < 500
    # mute
    ca.toggle_mute()
    wait(lambda: False, 0.6)
    silent = all(f == bytes(len(f)) for f in fb.played[-10:])
    assert silent, "mute should send silence"
    print("mute ok")

    # video: A shares its screen (1920x1080 red), B turns its camera on (640x480 blue)
    ca.screen_factory = lambda parent: FakeVideo("#ff0000", (1920, 1080))
    cb.camera_factory = lambda parent: FakeVideo("#0000ff", (640, 480))
    assert wait(lambda: ca.link is not None and cb.link is not None, 5), "media link not established"
    got_b, got_a = [], []
    cb.video_frame.connect(lambda k, img: got_b.append((k, img)))
    ca.video_frame.connect(lambda k, img: got_a.append((k, img)))
    assert ca.toggle_video("screen") and cb.toggle_video("camera")
    assert wait(lambda: len(got_b) > 5 and len(got_a) > 5, 8), (len(got_a), len(got_b))
    k, img = got_b[-1]
    px = img.pixelColor(img.width() // 2, img.height() // 2)
    assert k == "screen" and img.width() == 1600 and px.red() > 200 and px.blue() < 60, (k, img.size(), px.name())
    k, img = got_a[-1]
    px = img.pixelColor(10, 10)
    assert k == "camera" and img.width() == 640 and px.blue() > 200 and px.red() < 60, (k, img.size(), px.name())
    assert wait(lambda: cb.remote_video["screen"] and ca.remote_video["camera"])
    print(f"video ok: screen share {len(got_b)} frames (scaled to 1600 px), camera {len(got_a)} frames")
    ca.toggle_video("screen")
    assert wait(lambda: not cb.remote_video["screen"])
    print("screen share stop ok")
    ca.hangup()
    assert wait(lambda: ca.state == "idle" and cb.state == "idle")
    assert any(e[0] == "B" and e[3] == "remote_hangup" for e in ends), ends
    print("hangup ok:", [(e[0], e[3], round(e[4], 1)) for e in ends])

    # 2) decline
    ends.clear()
    ca.start_call(b.settings.user_id)
    assert wait(lambda: cb.state == "incoming")
    cb.reject()
    assert wait(lambda: ca.state == "idle")
    assert any(e[0] == "A" and e[3] == "declined" for e in ends), ends
    print("decline ok")

    # 3) caller cancels -> callee sees missed call
    ends.clear()
    ca.start_call(b.settings.user_id)
    assert wait(lambda: cb.state == "incoming")
    ca.hangup()
    assert wait(lambda: cb.state == "idle")
    assert any(e[0] == "B" and e[3] == "missed" for e in ends), ends
    print("missed call ok")

    # 4) busy: a third user calls B while A and B talk
    c = make("Carla", 48620, 48610, "k")
    assert wait(lambda: c.settings.user_id in b.peers and b.settings.user_id in c.peers)
    cc = CallController(c, lambda: FakeAudio(300))
    ends.clear()
    cc.ended.connect(lambda *x: ends.append(("C",) + x))
    ca.start_call(b.settings.user_id)
    assert wait(lambda: cb.state == "incoming")
    cb.accept()
    assert wait(lambda: ca.state == "active")
    cc.start_call(b.settings.user_id)
    assert wait(lambda: cc.state == "idle")
    assert any(e[0] == "C" and e[3] == "busy" for e in ends), ends
    print("busy ok")

    # 5) the other side disappears -> call ends
    b.stop()
    assert wait(lambda: ca.state == "idle", 25)
    print("lost-connection ok:", [e[3] for e in ends if e[0] == "A"][-1])
    for x in (a, c):
        x.stop()
    print("\nCALL TESTS PASSED")


if __name__ == "__main__":
    main()
