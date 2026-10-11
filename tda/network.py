"""Serverless LAN networking: UDP discovery + TCP messaging + file transfer.

Everything runs on the Qt event loop (no threads), so signals can be wired
straight into the UI.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import (QAbstractSocket, QHostAddress, QNetworkInterface,
                               QTcpServer, QTcpSocket, QUdpSocket)

from . import APP_VERSION, PROTOCOL_VERSION
from .config import Settings
from .crypto import Cipher
from .protocol import (CHUNK_SIZE, FrameBuffer, ProtocolError, encode_bin,
                       encode_json, safe_relpath)

ANNOUNCE_INTERVAL_MS = 5000
PEER_TIMEOUT_S = 18
REQUEST_TIMEOUT_MS = 8000


# ----------------------------------------------------------------------------- models
@dataclass
class Peer:
    id: str
    name: str
    group: str
    status: str
    host: str
    tcp_port: int
    hostname: str = ""
    os: str = ""
    version: str = ""
    last_seen: float = 0.0


@dataclass
class Transfer:
    tid: str
    direction: str                 # "out" | "in"
    peer_id: str
    peer_name: str
    files: List[dict]              # [{"rel": str, "size": int}]
    total: int
    title: str
    state: str = "offered"         # offered|active|done|failed|declined|canceled
    done: int = 0
    error: str = ""
    sources: List[str] = field(default_factory=list)   # absolute paths (out)
    dest_paths: List[str] = field(default_factory=list)  # absolute paths (in)
    dest_root: str = ""
    started: float = 0.0

    @property
    def finished(self) -> bool:
        return self.state in ("done", "failed", "declined", "canceled")


def _clean_host(addr: QHostAddress) -> str:
    s = addr.toString()
    if s.lower().startswith("::ffff:"):
        s = s[7:]
    return s.split("%")[0]


def _numbered(name: str, i: int, is_dir: bool) -> str:
    """'report.pdf' -> 'report (1).pdf'; folders get the number at the end."""
    stem, dot, ext = name.rpartition(".")
    if is_dir or not dot or not stem:
        return f"{name} ({i})"
    return f"{stem} ({i}).{ext}"


# ----------------------------------------------------------------------------- outgoing request
class _Request(QObject):
    """Open a connection, send one JSON frame, wait for {"type":"ack"}."""

    def __init__(self, core: "NetworkCore", host: str, port: int, obj: dict,
                 on_ok: Optional[Callable] = None, on_fail: Optional[Callable] = None):
        super().__init__(core)
        self.core, self.obj, self.on_ok, self.on_fail = core, obj, on_ok, on_fail
        self.done = False
        self.fb = FrameBuffer(core.cipher)
        self.sock = QTcpSocket(self)
        self.sock.connected.connect(self._connected)
        self.sock.readyRead.connect(self._read)
        self.sock.errorOccurred.connect(lambda _e: self._finish(False, self.sock.errorString()))
        self.sock.disconnected.connect(lambda: self._finish(False, "disconnected"))
        self.timer = QTimer(self, singleShot=True, interval=REQUEST_TIMEOUT_MS)
        self.timer.timeout.connect(lambda: self._finish(False, "timeout"))
        core._live.add(self)
        self.timer.start()
        self.sock.connectToHost(host, port)

    def _connected(self):
        self.sock.write(encode_json(self.core.cipher, self.obj))

    def _read(self):
        self.fb.feed(bytes(self.sock.readAll()))
        try:
            for kind, obj in self.fb.frames():
                if kind == "json" and obj.get("type") == "ack":
                    self._finish(True, "")
                    return
                if kind == "json" and obj.get("type") == "nack":
                    self._finish(False, obj.get("reason", "rejected"))
                    return
        except ProtocolError as e:
            self._finish(False, str(e))

    def _finish(self, ok: bool, err: str):
        if self.done:
            return
        self.done = True
        self.timer.stop()
        self.sock.abort()
        self.core._live.discard(self)
        cb = self.on_ok if ok else self.on_fail
        if cb:
            cb() if ok else cb(err)
        self.deleteLater()


# ----------------------------------------------------------------------------- file sender
class _FileSender(QObject):
    def __init__(self, core: "NetworkCore", tr: Transfer, peer: Peer):
        super().__init__(core)
        self.core, self.tr = core, tr
        self.idx = -1
        self.fh = None
        self.all_written = False
        self.closed = False
        self.fb = FrameBuffer(core.cipher)
        self.sock = QTcpSocket(self)
        self.sock.connected.connect(self._connected)
        self.sock.bytesWritten.connect(lambda _n: self._pump())
        self.sock.readyRead.connect(self._read)
        self.sock.errorOccurred.connect(lambda _e: self._end(False, self.sock.errorString()))
        self.sock.disconnected.connect(lambda: self._end(False, "disconnected"))
        core._live.add(self)
        tr.state, tr.started = "active", time.time()
        core.transfer_changed.emit(tr.tid)
        self.sock.connectToHost(peer.host, peer.tcp_port)

    def _connected(self):
        self.sock.write(encode_json(self.core.cipher, {"type": "file_data", "tid": self.tr.tid,
                                                       "from": self.core.settings.user_id}))
        self._pump()

    def _pump(self):
        if self.closed or self.all_written:
            return
        try:
            while self.sock.bytesToWrite() < 4 * CHUNK_SIZE:
                if self.fh is None:
                    self.idx += 1
                    if self.idx >= len(self.tr.sources):
                        self.all_written = True
                        return
                    self.fh = open(self.tr.sources[self.idx], "rb")
                data = self.fh.read(CHUNK_SIZE)
                if not data:
                    self.fh.close()
                    self.fh = None
                    continue
                self.sock.write(encode_bin(self.core.cipher, data))
                self.tr.done += len(data)
            self.core.transfer_changed.emit(self.tr.tid)
        except OSError as e:
            self._end(False, str(e))

    def _read(self):
        self.fb.feed(bytes(self.sock.readAll()))
        try:
            for kind, obj in self.fb.frames():
                if kind == "json" and obj.get("type") == "file_done":
                    self._end(True, "")
                    return
        except ProtocolError as e:
            self._end(False, str(e))

    def cancel(self):
        self._end(False, "canceled", state="canceled")

    def _end(self, ok: bool, err: str, state: Optional[str] = None):
        if self.closed:
            return
        self.closed = True
        if self.fh:
            self.fh.close()
        self.sock.abort()
        self.tr.state = state or ("done" if ok else ("canceled" if self.tr.state == "canceled" else "failed"))
        self.tr.error = err
        self.core._senders.pop(self.tr.tid, None)
        self.core._live.discard(self)
        self.core.transfer_changed.emit(self.tr.tid)
        self.deleteLater()


# ----------------------------------------------------------------------------- incoming connection
class _Incoming(QObject):
    def __init__(self, core: "NetworkCore", sock: QTcpSocket):
        super().__init__(core)
        self.core, self.sock = core, sock
        sock.setParent(self)
        self.fb = FrameBuffer(core.cipher)
        self.rx: Optional[Transfer] = None
        self.fh = None
        self.fidx = -1
        self.remaining = 0
        self.closed = False
        sock.readyRead.connect(self._read)
        sock.disconnected.connect(self._disconnected)
        core._live.add(self)
        self.idle = QTimer(self, singleShot=True, interval=60000)
        self.idle.timeout.connect(self.close)
        self.idle.start()

    def reply(self, obj: dict):
        self.sock.write(encode_json(self.core.cipher, obj))

    def _read(self):
        self.idle.start()
        self.fb.feed(bytes(self.sock.readAll()))
        try:
            for kind, obj in self.fb.frames():
                if self.rx is not None:
                    if kind != "bin":
                        raise ProtocolError("expected data")
                    self._write(obj)
                    continue
                if kind != "json":
                    raise ProtocolError("expected json")
                self.core._dispatch(self, obj)
                if self.closed:
                    return
        except (ProtocolError, OSError, ValueError) as e:
            if self.rx:
                self._fail_rx(str(e))
            self.close()

    # --- file receive
    def start_receive(self, tr: Transfer):
        self.rx = tr
        self.idle.setInterval(30000)
        tr.state, tr.started = "active", time.time()
        self.core._receivers[tr.tid] = self
        self.core.transfer_changed.emit(tr.tid)
        self._next_file()
        self._check_complete()

    def _check_complete(self):
        tr = self.rx
        if tr and self.fh is None and self.fidx >= len(tr.files):
            tr.state = "done"
            self.reply({"type": "file_done", "tid": tr.tid})
            self.sock.flush()
            self.core._receivers.pop(tr.tid, None)
            self.core.transfer_changed.emit(tr.tid)
            self.rx = None
            QTimer.singleShot(1500, self.close)
            return True
        return False

    def _next_file(self):
        while True:
            if self.fh:
                self.fh.close()
                self.fh = None
            self.fidx += 1
            if self.fidx >= len(self.rx.files):
                return
            path = Path(self.rx.dest_paths[self.fidx])
            path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = open(path, "wb")
            self.remaining = int(self.rx.files[self.fidx]["size"])
            if self.remaining > 0:
                return

    def _write(self, data: bytes):
        tr = self.rx
        view = memoryview(data)
        while view:
            if self.fh is None:
                raise ProtocolError("too much data")
            n = min(len(view), self.remaining)
            self.fh.write(view[:n])
            view = view[n:]
            self.remaining -= n
            tr.done += n
            if self.remaining == 0:
                self._next_file()
        if not self._check_complete():
            self.core.transfer_changed.emit(tr.tid)

    def _fail_rx(self, err: str, state: str = "failed"):
        tr = self.rx
        if not tr:
            return
        if self.fh:
            self.fh.close()
            self.fh = None
            try:
                os.remove(tr.dest_paths[self.fidx])   # remove the partial file
            except OSError:
                pass
        tr.state = state if tr.state != "canceled" else "canceled"
        tr.error = err
        self.rx = None
        self.core._receivers.pop(tr.tid, None)
        self.core.transfer_changed.emit(tr.tid)

    def cancel(self):
        if self.rx:
            self.rx.state = "canceled"
            self._fail_rx("canceled", "canceled")
        self.close()

    def _disconnected(self):
        if self.rx:
            self._fail_rx("connection lost")
        self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.fh:
            self.fh.close()
            self.fh = None
        self.sock.abort()
        self.core._live.discard(self)
        self.deleteLater()


# ----------------------------------------------------------------------------- core
class NetworkCore(QObject):
    peer_updated = Signal(object)          # Peer
    peer_removed = Signal(str)             # peer id
    message_received = Signal(dict)        # {"id","from","from_name","text","ts","multi"}
    message_status = Signal(str, bool, str)  # msg id, delivered?, error
    transfer_added = Signal(str)           # tid
    transfer_changed = Signal(str)         # tid
    error = Signal(str)
    call_message = Signal(str, dict)       # sender id, call_* control message

    def __init__(self, settings: Settings, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.settings = settings
        self.cipher = Cipher(settings.password)
        self.peers: Dict[str, Peer] = {}
        self.transfers: Dict[str, Transfer] = {}
        self._senders: Dict[str, _FileSender] = {}
        self._receivers: Dict[str, _Incoming] = {}
        self._live: set = set()
        self.udp = QUdpSocket(self)
        self.tcp = QTcpServer(self)
        self.announce_timer = QTimer(self, interval=ANNOUNCE_INTERVAL_MS)
        self.announce_timer.timeout.connect(lambda: self.announce("hello"))
        self.prune_timer = QTimer(self, interval=3000)
        self.prune_timer.timeout.connect(self._prune)
        self.running = False

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        s = self.settings
        ok_udp = self.udp.bind(QHostAddress(QHostAddress.SpecialAddress.AnyIPv4), s.udp_port,
                               QUdpSocket.BindFlag.ShareAddress | QUdpSocket.BindFlag.ReuseAddressHint)
        if not ok_udp:
            self.error.emit(f"UDP {s.udp_port}: {self.udp.errorString()}")
            return False
        self.udp.readyRead.connect(self._read_udp)
        if not self.tcp.listen(QHostAddress(QHostAddress.SpecialAddress.AnyIPv4), s.tcp_port):
            self.error.emit(f"TCP {s.tcp_port}: {self.tcp.errorString()}")
            return False
        self.tcp.newConnection.connect(self._accept)
        self.running = True
        self.announce("hello")
        self.announce_timer.start()
        self.prune_timer.start()
        return True

    def stop(self):
        if not self.running:
            return
        self.announce("bye")
        for snd in list(self._senders.values()):
            snd.cancel()
        for rcv in list(self._receivers.values()):
            rcv.cancel()
        self.announce_timer.stop()
        self.prune_timer.stop()
        self.tcp.close()
        self.udp.close()
        self.running = False

    def apply_settings(self):
        """Call after the user changed name/group/status/password."""
        self.cipher = Cipher(self.settings.password)
        self.announce("hello")

    # ---------------------------------------------------------------- discovery
    def _hello(self, kind: str) -> dict:
        s = self.settings
        return {"t": kind, "id": s.user_id, "name": s.name, "group": s.group, "status": s.status,
                "port": s.tcp_port, "host": socket.gethostname(),
                "os": f"{platform.system()} {platform.release()}", "v": APP_VERSION, "pv": PROTOCOL_VERSION}

    def _targets(self):
        port = self.settings.udp_port
        seen = set()
        addrs = [QHostAddress(QHostAddress.SpecialAddress.Broadcast)]
        for iface in QNetworkInterface.allInterfaces():
            flags = iface.flags()
            if not (flags & QNetworkInterface.InterfaceFlag.IsUp) or not (flags & QNetworkInterface.InterfaceFlag.CanBroadcast):
                continue
            for entry in iface.addressEntries():
                bc = entry.broadcast()
                if not bc.isNull() and bc.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                    addrs.append(bc)
        for a in addrs:
            key = (a.toString(), port)
            if key not in seen:
                seen.add(key)
                yield a, port
        for entry in self.settings.extra_hosts:
            entry = str(entry).strip()
            if not entry:
                continue
            host, _, p = entry.partition(":")
            try:
                yield QHostAddress(host), int(p) if p else port
            except ValueError:
                continue

    def announce(self, kind: str = "hello"):
        if not self.running and kind != "bye":
            return
        data = self.cipher.seal(json.dumps(self._hello(kind), ensure_ascii=False).encode("utf-8"))
        for addr, port in self._targets():
            self.udp.writeDatagram(data, addr, port)

    def _read_udp(self):
        while self.udp.hasPendingDatagrams():
            dg = self.udp.receiveDatagram(65535)
            plain = self.cipher.open(bytes(dg.data()))
            if plain is None:
                continue
            try:
                msg = json.loads(plain.decode("utf-8"))
                pid = msg["id"]
            except Exception:
                continue
            if pid == self.settings.user_id:
                continue
            kind = msg.get("t")
            if kind == "bye":
                if self.peers.pop(pid, None):
                    self.peer_removed.emit(pid)
                continue
            if kind not in ("hello", "here"):
                continue
            host = _clean_host(dg.senderAddress())
            is_new = pid not in self.peers
            peer = Peer(id=pid, name=str(msg.get("name", "?"))[:64], group=str(msg.get("group", ""))[:64],
                        status=str(msg.get("status", "available")), host=host, tcp_port=int(msg.get("port", 0)),
                        hostname=str(msg.get("host", "")), os=str(msg.get("os", "")), version=str(msg.get("v", "")),
                        last_seen=time.time())
            old = self.peers.get(pid)
            self.peers[pid] = peer
            if is_new and kind == "hello":
                # answer directly so the newcomer sees us immediately
                reply = self.cipher.seal(json.dumps(self._hello("here"), ensure_ascii=False).encode("utf-8"))
                self.udp.writeDatagram(reply, dg.senderAddress(), dg.senderPort())
            if is_new or (old and (old.name, old.group, old.status, old.host) != (peer.name, peer.group, peer.status, peer.host)):
                self.peer_updated.emit(peer)

    def _prune(self):
        now = time.time()
        for pid, p in list(self.peers.items()):
            if now - p.last_seen > PEER_TIMEOUT_S:
                del self.peers[pid]
                self.peer_removed.emit(pid)

    # ---------------------------------------------------------------- incoming tcp
    def _accept(self):
        while self.tcp.hasPendingConnections():
            _Incoming(self, self.tcp.nextPendingConnection())

    def _dispatch(self, conn: _Incoming, obj: dict):
        t = obj.get("type")
        sender = str(obj.get("from", ""))
        peer = self.peers.get(sender)
        if t == "msg":
            text = str(obj.get("text", ""))[:100_000]
            conn.reply({"type": "ack", "id": obj.get("id")})
            self.message_received.emit({
                "id": str(obj.get("id") or uuid.uuid4().hex), "from": sender,
                "from_name": peer.name if peer else str(obj.get("from_name", "?")),
                "text": text, "ts": float(obj.get("ts", time.time())), "multi": bool(obj.get("multi"))})
        elif t == "file_offer":
            files = []
            try:
                for f in obj["files"][:100_000]:
                    files.append({"rel": str(safe_relpath(f["rel"])), "size": max(0, int(f["size"]))})
            except (KeyError, TypeError, ValueError, ProtocolError):
                conn.reply({"type": "nack", "reason": "bad offer"})
                return
            tid = str(obj.get("tid"))
            if tid in self.transfers:
                conn.reply({"type": "ack"})
                return
            tr = Transfer(tid=tid, direction="in", peer_id=sender,
                          peer_name=peer.name if peer else str(obj.get("from_name", "?")), files=files,
                          total=sum(f["size"] for f in files), title=str(obj.get("title", ""))[:200])
            self.transfers[tid] = tr
            conn.reply({"type": "ack"})
            self.transfer_added.emit(tid)
        elif t in ("file_accept", "file_reject", "file_cancel"):
            tid = str(obj.get("tid"))
            tr = self.transfers.get(tid)
            conn.reply({"type": "ack"})
            if not tr or tr.peer_id != sender or tr.state != "offered":
                return
            if t == "file_accept" and tr.direction == "out":
                if peer is None:
                    tr.state, tr.error = "failed", "peer offline"
                    self.transfer_changed.emit(tid)
                else:
                    self._senders[tid] = _FileSender(self, tr, peer)
            else:
                tr.state = "declined" if t == "file_reject" else "canceled"
                self.transfer_changed.emit(tid)
        elif t == "file_data":
            tid = str(obj.get("tid"))
            tr = self.transfers.get(tid)
            if not tr or tr.direction != "in" or tr.state != "accepted" or tr.peer_id != sender:
                conn.close()
                return
            conn.start_receive(tr)
        elif isinstance(t, str) and t.startswith("call_"):
            conn.reply({"type": "ack"})
            if peer is not None:
                self.call_message.emit(sender, obj)
        elif t == "ping":
            conn.reply({"type": "ack"})
        else:
            conn.close()

    # ---------------------------------------------------------------- outgoing api
    def _request(self, peer_id: str, obj: dict, on_ok=None, on_fail=None) -> bool:
        peer = self.peers.get(peer_id)
        if not peer:
            if on_fail:
                on_fail("offline")
            return False
        obj.setdefault("from", self.settings.user_id)
        obj.setdefault("from_name", self.settings.name)
        _Request(self, peer.host, peer.tcp_port, obj, on_ok, on_fail)
        return True

    def send_control(self, peer_id: str, obj: dict, on_ok=None, on_fail=None) -> bool:
        """Send one control message (used by calls)."""
        return self._request(peer_id, dict(obj), on_ok, on_fail)

    def send_message(self, peer_id: str, text: str, multi: bool = False, msg_id: Optional[str] = None) -> str:
        msg_id = msg_id or uuid.uuid4().hex
        obj = {"type": "msg", "id": msg_id, "text": text, "ts": time.time(), "multi": multi}
        self._request(peer_id, obj,
                      on_ok=lambda: self.message_status.emit(msg_id, True, ""),
                      on_fail=lambda err: self.message_status.emit(msg_id, False, err))
        return msg_id

    def offer_files(self, peer_id: str, paths: List[str]) -> Optional[str]:
        peer = self.peers.get(peer_id)
        if not peer:
            return None
        sources, files = [], []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                for root, _dirs, names in os.walk(p):
                    for n in sorted(names):
                        fp = Path(root) / n
                        try:
                            size = fp.stat().st_size
                        except OSError:
                            continue
                        sources.append(str(fp))
                        files.append({"rel": (Path(p.name) / fp.relative_to(p)).as_posix(), "size": size})
            elif p.is_file():
                sources.append(str(p))
                files.append({"rel": p.name, "size": p.stat().st_size})
        if not files:
            return None
        tid = uuid.uuid4().hex
        title = Path(paths[0]).name if len(paths) == 1 else f"{len(files)}"
        tr = Transfer(tid=tid, direction="out", peer_id=peer_id, peer_name=peer.name, files=files,
                      total=sum(f["size"] for f in files), title=title, sources=sources)
        self.transfers[tid] = tr
        self.transfer_added.emit(tid)

        def failed(err):
            tr.state, tr.error = "failed", err
            self.transfer_changed.emit(tid)

        self._request(peer_id, {"type": "file_offer", "tid": tid, "files": files, "title": title},
                      on_fail=failed)
        return tid

    def accept_transfer(self, tid: str, dest_dir: Optional[str] = None):
        tr = self.transfers.get(tid)
        if not tr or tr.direction != "in" or tr.state != "offered":
            return
        root = Path(dest_dir or self.settings.download_dir)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            tr.state, tr.error = "failed", str(e)
            self.transfer_changed.emit(tid)
            return
        # rename top-level entries that already exist: "file.txt" -> "file (1).txt"
        renames: Dict[str, str] = {}
        for f in tr.files:
            top = f["rel"].split("/")[0]
            if top in renames:
                continue
            is_dir = "/" in f["rel"]
            cand, i = top, 1
            while (root / cand).exists() or cand in renames.values():
                cand = _numbered(top, i, is_dir)
                i += 1
            renames[top] = cand
        tr.dest_paths = []
        for f in tr.files:
            parts = f["rel"].split("/")
            parts[0] = renames[parts[0]]
            tr.dest_paths.append(str(root.joinpath(*parts)))
        tr.dest_root = str(root)
        tr.state = "accepted"
        self.transfer_changed.emit(tid)

        def failed(err):
            tr.state, tr.error = "failed", err
            self.transfer_changed.emit(tid)

        self._request(tr.peer_id, {"type": "file_accept", "tid": tid}, on_fail=failed)

    def reject_transfer(self, tid: str):
        tr = self.transfers.get(tid)
        if not tr or tr.state != "offered" or tr.direction != "in":
            return
        tr.state = "declined"
        self.transfer_changed.emit(tid)
        self._request(tr.peer_id, {"type": "file_reject", "tid": tid})

    def cancel_transfer(self, tid: str):
        tr = self.transfers.get(tid)
        if not tr or tr.finished:
            return
        if tid in self._senders:
            self._senders[tid].cancel()
            return
        if tid in self._receivers:
            self._receivers[tid].cancel()
            return
        if tr.direction == "in" and tr.state == "offered":
            self.reject_transfer(tid)
            return
        prev = tr.state
        tr.state = "canceled"
        self.transfer_changed.emit(tid)
        if tr.direction == "out" and prev == "offered":
            self._request(tr.peer_id, {"type": "file_cancel", "tid": tid})
