"""LAN voice calls.

Signaling (invite / accept / reject / end) travels over the normal encrypted TCP
control channel. Audio travels as encrypted UDP packets straight between the two
computers: 16 kHz, 16-bit mono PCM in 20 ms frames (~260 kbit/s, trivial on a LAN).
No server and no internet are involved.
"""
from __future__ import annotations

import array
import collections
import socket
import struct
import threading
import time
import uuid
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

RATE = 16000
FRAME_SAMPLES = 320                 # 20 ms
FRAME_BYTES = FRAME_SAMPLES * 2
RING_TIMEOUT_MS = 45_000
LOST_AFTER_S = 10
SILENCE = bytes(FRAME_BYTES)


# =============================================================================== audio backends
class AudioBackend:
    """Interface: start(on_frame) delivers captured 20 ms frames; play(frame) queues one for output."""
    input_ok = False
    output_ok = False
    error = ""

    def start(self, on_frame: Callable[[bytes], None]) -> None: ...
    def play(self, frame: bytes) -> None: ...
    def stop(self) -> None: ...


class SoundDeviceBackend(AudioBackend):
    """Microphone / speakers through PortAudio (python-sounddevice)."""

    def __init__(self):
        self.jitter: collections.deque = collections.deque(maxlen=15)
        self.playing = False
        self.streams = []
        self.error = ""

    def start(self, on_frame):
        try:
            import sounddevice as sd
        except Exception as e:  # PortAudio missing
            self.error = f"sounddevice: {e}"
            return

        def mic_cb(factor):
            def cb(indata, frames, _t, _status):
                data = bytes(indata)
                if factor > 1:
                    a = array.array("h")
                    a.frombytes(data)
                    data = array.array("h", (sum(a[i:i + factor]) // factor
                                             for i in range(0, len(a), factor))).tobytes()
                on_frame(data)
            return cb

        def spk_cb(factor):
            def cb(outdata, frames, _t, _status):
                if not self.playing and len(self.jitter) >= 3:     # 60 ms of buffer before starting
                    self.playing = True
                frame = self.jitter.popleft() if (self.playing and self.jitter) else None
                if frame is None:
                    self.playing = False
                    frame = SILENCE
                if factor > 1:
                    a = array.array("h")
                    a.frombytes(frame)
                    b = array.array("h", bytes(len(frame) * factor))
                    for k in range(factor):
                        b[k::factor] = a
                    frame = b.tobytes()
                need = frames * 2
                outdata[:] = frame[:need].ljust(need, b"\0")
            return cb

        errors = []
        for rate in (16000, 48000, 32000):
            f = rate // RATE
            try:
                s = sd.RawInputStream(samplerate=rate, channels=1, dtype="int16",
                                      blocksize=FRAME_SAMPLES * f, callback=mic_cb(f), latency="low")
                s.start()
                self.streams.append(s)
                self.input_ok = True
                break
            except Exception as e:
                errors.append(f"mic@{rate}: {e}")
        for rate in (16000, 48000, 32000):
            f = rate // RATE
            try:
                s = sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16",
                                       blocksize=FRAME_SAMPLES * f, callback=spk_cb(f), latency="low")
                s.start()
                self.streams.append(s)
                self.output_ok = True
                break
            except Exception as e:
                errors.append(f"speaker@{rate}: {e}")
        if not (self.input_ok and self.output_ok):
            self.error = "; ".join(errors[-2:])

    def play(self, frame):
        self.jitter.append(frame)

    def stop(self):
        for s in self.streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self.streams.clear()


# =============================================================================== media session
class CallSession:
    """Encrypted UDP audio between two hosts. Runs its own receive thread."""

    def __init__(self, cipher, call_id: str, backend: AudioBackend):
        self.cipher = cipher
        self.cid = bytes.fromhex(call_id)
        self.backend = backend
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))           # any free port; it is sent in the signaling
        self.port = self.sock.getsockname()[1]
        self.remote: Optional[tuple] = None
        self.muted = False
        self.running = False
        self.seq = 0
        self.last_rx_seq = -1
        self.last_rx = time.time()
        self.last_tx = 0.0
        self.rx_frames = 0
        self.tx_frames = 0
        self.thread: Optional[threading.Thread] = None

    def set_remote(self, host: str, port: int):
        self.remote = (host, int(port))

    def start(self):
        self.running = True
        self.last_rx = time.time()
        self.thread = threading.Thread(target=self._rx_loop, name="tda-call-rx", daemon=True)
        self.thread.start()
        self.backend.start(self._on_capture)

    def _send(self, kind: bytes, payload: bytes = b""):
        if not self.remote or not self.running:
            return
        self.seq += 1
        pkt = self.cipher.seal(kind + self.cid + struct.pack(">I", self.seq) + payload)
        try:
            self.sock.sendto(pkt, self.remote)
            self.last_tx = time.time()
        except OSError:
            pass

    def _on_capture(self, frame: bytes):
        self._send(b"V", SILENCE if self.muted else frame)
        self.tx_frames += 1

    def _rx_loop(self):
        self.sock.settimeout(0.3)
        while self.running:
            if time.time() - self.last_tx > 0.5:      # keep-alive when no microphone / muted device
                self._send(b"K")
            try:
                data, _addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            plain = self.cipher.open(data)
            if not plain or len(plain) < 21 or plain[1:17] != self.cid:
                continue
            seq = struct.unpack(">I", plain[17:21])[0]
            self.last_rx = time.time()
            if plain[:1] == b"V" and seq > self.last_rx_seq:
                self.last_rx_seq = seq
                self.backend.play(plain[21:21 + FRAME_BYTES])
                self.rx_frames += 1

    def stop(self):
        self.running = False
        try:
            self.backend.stop()
        except Exception:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# =============================================================================== call state machine
class CallController(QObject):
    """One call at a time. States: idle | outgoing | incoming | active."""

    state_changed = Signal(str)                 # new state
    incoming = Signal(str, str)                 # peer_id, peer_name
    ended = Signal(str, str, str, float)        # peer_id, direction("in"/"out"), reason, duration seconds
    audio_warning = Signal(str)

    def __init__(self, core, backend_factory: Callable[[], AudioBackend] = SoundDeviceBackend, parent=None):
        super().__init__(parent)
        self.core = core
        self.backend_factory = backend_factory
        self.state = "idle"
        self.peer_id = ""
        self.peer_name = ""
        self.direction = ""
        self.call_id = ""
        self.remote_port = 0
        self.session: Optional[CallSession] = None
        self.started_at = 0.0
        self.ring_timer = QTimer(self, singleShot=True, interval=RING_TIMEOUT_MS)
        self.ring_timer.timeout.connect(self._ring_timeout)
        self.watch = QTimer(self, interval=1000)
        self.watch.timeout.connect(self._watchdog)
        core.call_message.connect(self._on_message)
        core.peer_removed.connect(self._on_peer_removed)

    # ------------------------------------------------------------ helpers
    @property
    def duration(self) -> float:
        return time.time() - self.started_at if self.state == "active" else 0.0

    @property
    def muted(self) -> bool:
        return bool(self.session and self.session.muted)

    def _set(self, st):
        self.state = st
        self.state_changed.emit(st)

    def _send(self, kind, **extra):
        obj = {"type": kind, "call_id": self.call_id, **extra}
        self.core.send_control(self.peer_id, obj)

    def _new_session(self) -> CallSession:
        return CallSession(self.core.cipher, self.call_id, self.backend_factory())

    def _start_media(self, host, port):
        self.session.set_remote(host, port)
        self.session.start()
        b = self.session.backend
        if b.error or not (b.input_ok and b.output_ok):
            self.audio_warning.emit(b.error or "audio device")
        self.started_at = time.time()
        self.watch.start()
        self._set("active")

    def _finish(self, reason: str):
        if self.state == "idle":
            return
        dur = self.duration
        self.ring_timer.stop()
        self.watch.stop()
        if self.session:
            self.session.stop()
            self.session = None
        pid, direction = self.peer_id, self.direction
        self.call_id = ""
        self._set("idle")
        self.ended.emit(pid, direction, reason, dur)

    # ------------------------------------------------------------ user actions
    def start_call(self, peer_id: str) -> bool:
        if self.state != "idle" or peer_id not in self.core.peers:
            return False
        self.peer_id = peer_id
        self.peer_name = self.core.peers[peer_id].name
        self.direction = "out"
        self.call_id = uuid.uuid4().hex
        self.session = self._new_session()
        self._set("outgoing")
        self.ring_timer.start()
        cid = self.call_id
        self.core.send_control(peer_id, {"type": "call_invite", "call_id": cid, "port": self.session.port},
                               on_fail=lambda err: self._finish("unreachable") if self.call_id == cid else None)
        return True

    def accept(self):
        if self.state != "incoming":
            return
        peer = self.core.peers.get(self.peer_id)
        if not peer:
            self._finish("lost")
            return
        self.ring_timer.stop()
        self.session = self._new_session()
        self._send("call_accept", port=self.session.port)
        self._start_media(peer.host, self.remote_port)

    def reject(self):
        if self.state != "incoming":
            return
        self._send("call_reject", reason="declined")
        self._finish("declined_by_me")

    def hangup(self):
        if self.state == "idle":
            return
        if self.state == "incoming":
            self.reject()
            return
        self._send("call_end")
        self._finish("hangup" if self.state == "active" else "canceled")

    def toggle_mute(self) -> bool:
        if self.session:
            self.session.muted = not self.session.muted
        return self.muted

    # ------------------------------------------------------------ network events
    def _on_message(self, sender: str, obj: dict):
        t = obj.get("type")
        cid = str(obj.get("call_id", ""))
        if t == "call_invite":
            if self.state != "idle":
                self.core.send_control(sender, {"type": "call_reject", "call_id": cid, "reason": "busy"})
                return
            peer = self.core.peers.get(sender)
            if not peer:
                return
            self.peer_id, self.peer_name, self.direction = sender, peer.name, "in"
            self.call_id = cid
            try:
                self.remote_port = int(obj.get("port", 0))
            except (TypeError, ValueError):
                return
            self._set("incoming")
            self.ring_timer.start()
            self.incoming.emit(sender, peer.name)
            return
        if sender != self.peer_id or cid != self.call_id:
            return
        if t == "call_accept" and self.state == "outgoing":
            peer = self.core.peers.get(sender)
            if not peer:
                self._finish("lost")
                return
            self.ring_timer.stop()
            self._start_media(peer.host, int(obj.get("port", 0)))
        elif t == "call_reject" and self.state == "outgoing":
            self._finish("busy" if obj.get("reason") == "busy" else "declined")
        elif t == "call_end":
            self._finish("missed" if self.state == "incoming" else "remote_hangup")

    def _on_peer_removed(self, pid):
        if self.state != "idle" and pid == self.peer_id:
            self._finish("lost")

    def _ring_timeout(self):
        if self.state == "outgoing":
            self._send("call_end")
            self._finish("no_answer")
        elif self.state == "incoming":
            self._finish("missed")

    def _watchdog(self):
        if self.state == "active" and self.session and time.time() - self.session.last_rx > LOST_AFTER_S:
            self._send("call_end")
            self._finish("lost")
