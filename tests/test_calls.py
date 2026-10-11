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
from PySide6.QtCore import QCoreApplication, QEventLoop  # noqa: E402

from tda.calls import FRAME_SAMPLES, AudioBackend, CallController  # noqa: E402
from tda.config import Settings  # noqa: E402
from tda.network import NetworkCore  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication(sys.argv)


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
    c = NetworkCore(s)
    assert c.start()
    return c


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
