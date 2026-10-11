"""Serverless LAN networking: UDP discovery + TCP messaging + file transfer.

Everything runs on the Qt event loop (no threads), so signals can be wired
straight into the UI.
"""
from __future__ import annotations

import json
import os
import platform
import random
import socket
import sqlite3
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

ANNOUNCE_MIN_S = 5          # small networks: announce every 5 s
ANNOUNCE_MAX_S = 30         # 1000+ users: every 30 s (~35 packets/s for the whole LAN)
PEERS_PER_SECOND = 25       # interval grows by 1 s for every 25 known peers
PEER_TIMEOUT_MIN_S = 18
REQUEST_TIMEOUT_MS = 8000
OUTBOX_RETRY_MS = 60_000


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
    iv: float = ANNOUNCE_MIN_S          # the peer's announce interval

    @property
    def timeout(self) -> float:
        return max(PEER_TIMEOUT_MIN_S, self.iv * 3.2)


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
    gid: str = ""                      # group the files were shared in ("" = private chat)

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

    def detach(self):
        """Hand the raw socket (and any frames already buffered) to someone else, e.g. a call's video link."""
        self.closed = True
        self.idle.stop()
        try:
            self.sock.readyRead.disconnect(self._read)
            self.sock.disconnected.disconnect(self._disconnected)
        except (RuntimeError, TypeError):
            pass
        self.core._live.discard(self)
        sock, fb = self.sock, self.fb
        sock.setParent(None)
        self.deleteLater()
        return sock, fb

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


# ----------------------------------------------------------------------------- persistent stores
class Store:
    """SQLite: outbox (store-and-forward for offline users) and groups."""

    def __init__(self, path: Path):
        self.db = sqlite3.connect(str(path))
        self.db.execute("""CREATE TABLE IF NOT EXISTS outbox(
            id TEXT, peer_id TEXT, obj TEXT, extra TEXT, created REAL, PRIMARY KEY(id, peer_id))""")
        self.db.execute("CREATE TABLE IF NOT EXISTS groups(gid TEXT PRIMARY KEY, data TEXT)")
        self.db.commit()

    # outbox
    def queue(self, item_id, peer_id, obj, extra=None):
        self.db.execute("INSERT OR REPLACE INTO outbox VALUES(?,?,?,?,?)",
                        (item_id, peer_id, json.dumps(obj, ensure_ascii=False),
                         json.dumps(extra or {}, ensure_ascii=False), time.time()))
        self.db.commit()

    def pending(self, peer_id=None):
        q = "SELECT id, peer_id, obj, extra FROM outbox"
        rows = self.db.execute(q + (" WHERE peer_id=?" if peer_id else "") + " ORDER BY created",
                               (peer_id,) if peer_id else ()).fetchall()
        return [(r[0], r[1], json.loads(r[2]), json.loads(r[3] or "{}")) for r in rows]

    def done(self, item_id, peer_id):
        self.db.execute("DELETE FROM outbox WHERE id=? AND peer_id=?", (item_id, peer_id))
        self.db.commit()

    def peers_with_pending(self):
        return {r[0] for r in self.db.execute("SELECT DISTINCT peer_id FROM outbox")}

    # groups
    def save_group(self, g: dict):
        self.db.execute("INSERT OR REPLACE INTO groups VALUES(?,?)", (g["gid"], json.dumps(g, ensure_ascii=False)))
        self.db.commit()

    def delete_group(self, gid):
        self.db.execute("DELETE FROM groups WHERE gid=?", (gid,))
        self.db.commit()

    def groups(self):
        return {r[0]: json.loads(r[1]) for r in self.db.execute("SELECT gid, data FROM groups")}


# ----------------------------------------------------------------------------- core
class NetworkCore(QObject):
    peer_updated = Signal(object)          # Peer
    peer_removed = Signal(str)             # peer id
    message_received = Signal(dict)        # {"id","from","from_name","text","ts","multi"}
    message_status = Signal(str, str, str)   # msg id, "delivered" | "queued" | "failed", peer id
    transfer_added = Signal(str)           # tid
    transfer_changed = Signal(str)         # tid
    error = Signal(str)
    call_message = Signal(str, dict)       # sender id, call_* control message
    media_socket = Signal(str, str, object, object)   # sender id, call id, QTcpSocket, FrameBuffer
    group_updated = Signal(str)            # gid
    group_removed = Signal(str)            # gid

    def __init__(self, settings: Settings, parent: Optional[QObject] = None, data_dir=None):
        super().__init__(parent)
        self.settings = settings
        from .config import config_dir
        self.data_dir = Path(data_dir) if data_dir else config_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data_dir / "network.db")
        self.groups: Dict[str, dict] = self.store.groups()
        self._flushing: set = set()
        self.cipher = Cipher(settings.password)
        self.peers: Dict[str, Peer] = {}
        self.transfers: Dict[str, Transfer] = {}
        self._senders: Dict[str, _FileSender] = {}
        self._receivers: Dict[str, _Incoming] = {}
        self._live: set = set()
        self.udp = QUdpSocket(self)
        self.tcp = QTcpServer(self)
        self.announce_timer = QTimer(self, singleShot=True)
        self.announce_timer.timeout.connect(self._periodic_announce)
        self.retry_timer = QTimer(self, interval=OUTBOX_RETRY_MS)
        self.retry_timer.timeout.connect(self._retry_outbox)
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
        self.udp.setSocketOption(QAbstractSocket.SocketOption.ReceiveBufferSizeSocketOption, 4 * 1024 * 1024)
        self.udp.readyRead.connect(self._read_udp)
        if not self.tcp.listen(QHostAddress(QHostAddress.SpecialAddress.AnyIPv4), s.tcp_port):
            self.error.emit(f"TCP {s.tcp_port}: {self.tcp.errorString()}")
            return False
        self.tcp.newConnection.connect(self._accept)
        self.running = True
        self._restore_queued_transfers()
        self.announce("hello")
        self._schedule_announce()
        self.prune_timer.start()
        self.retry_timer.start()
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
        self.retry_timer.stop()
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
                "os": f"{platform.system()} {platform.release()}", "v": APP_VERSION, "pv": PROTOCOL_VERSION,
                "iv": round(self.announce_interval(), 1)}

    def announce_interval(self) -> float:
        """Grows with the number of users so 1000+ computers do not flood the LAN."""
        return max(ANNOUNCE_MIN_S, min(ANNOUNCE_MAX_S, len(self.peers) / PEERS_PER_SECOND))

    def _schedule_announce(self):
        iv = self.announce_interval()
        self.announce_timer.start(int(iv * 1000 * random.uniform(0.8, 1.2)))   # jitter avoids bursts

    def _periodic_announce(self):
        self.announce("hello")
        self._schedule_announce()

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
            old = self.peers.get(pid)
            name = str(msg.get("name", "?"))[:64]
            group = str(msg.get("group", ""))[:64]
            status = str(msg.get("status", "available"))
            try:
                port = int(msg.get("port", 0))
                iv = min(120.0, max(1.0, float(msg.get("iv", ANNOUNCE_MIN_S))))
            except (TypeError, ValueError):
                continue
            if old and (old.name, old.group, old.status, old.host, old.tcp_port) == (name, group, status, host, port):
                old.last_seen, old.iv = time.time(), iv          # fast path: nothing changed
                continue
            peer = Peer(id=pid, name=name, group=group, status=status, host=host, tcp_port=port,
                        hostname=str(msg.get("host", ""))[:64], os=str(msg.get("os", ""))[:64],
                        version=str(msg.get("v", ""))[:16], last_seen=time.time(), iv=iv)
            self.peers[pid] = peer
            if is_new and kind == "hello":
                # answer the newcomer directly; a random delay spreads 1000 replies over ~1.5 s
                addr, prt = QHostAddress(dg.senderAddress()), dg.senderPort()
                QTimer.singleShot(random.randint(0, 1500), lambda a=addr, p=prt: self._reply_here(a, p))
            self.peer_updated.emit(peer)
            if is_new and self.store.pending(pid):
                QTimer.singleShot(random.randint(500, 2000), lambda x=pid: self.flush_outbox(x))

    def _reply_here(self, addr, port):
        if self.running:
            reply = self.cipher.seal(json.dumps(self._hello("here"), ensure_ascii=False).encode("utf-8"))
            self.udp.writeDatagram(reply, addr, port)

    def _prune(self):
        now = time.time()
        for pid, p in list(self.peers.items()):
            if now - p.last_seen > p.timeout:
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
            gid = str(obj.get("gid", ""))[:64]
            if gid and gid not in self.groups:     # group we have not heard of yet
                self._apply_group({"gid": gid, "name": str(obj.get("gname", "?"))[:80], "version": 0,
                                   "owner": sender, "members": {sender: str(obj.get("from_name", "?"))[:64],
                                                                self.settings.user_id: self.settings.name}})
            try:
                ts = float(obj.get("ts", time.time()))
            except (TypeError, ValueError):
                ts = time.time()
            self.message_received.emit({
                "id": str(obj.get("id") or uuid.uuid4().hex), "from": sender,
                "from_name": peer.name if peer else str(obj.get("from_name", "?")),
                "text": text, "ts": ts, "multi": bool(obj.get("multi")), "gid": gid})
        elif t == "group_update":
            conn.reply({"type": "ack"})
            g = obj.get("group")
            if isinstance(g, dict) and isinstance(g.get("members"), dict):
                self._apply_group(g)
        elif t == "group_leave":
            conn.reply({"type": "ack"})
            g = self.groups.get(str(obj.get("gid", "")))
            if g and sender in g["members"]:
                g["members"].pop(sender, None)
                g["version"] = int(g.get("version", 0)) + 1
                self.store.save_group(g)
                self.group_updated.emit(g["gid"])
        elif t == "media":
            conn.reply({"type": "ack"})
            sock, fb = conn.detach()
            self.media_socket.emit(sender, str(obj.get("call_id", "")), sock, fb)
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
                          total=sum(f["size"] for f in files), title=str(obj.get("title", ""))[:200],
                          gid=str(obj.get("gid", ""))[:64])
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

    # ---------------------------------------------------------------- messages (with offline outbox)
    def send_message(self, peer_id: str, text: str, multi: bool = False, msg_id: Optional[str] = None,
                     gid: str = "") -> str:
        """Deliver now if the user is online; otherwise keep it and deliver when they come back."""
        msg_id = msg_id or uuid.uuid4().hex
        obj = {"type": "msg", "id": msg_id, "text": text, "ts": time.time(), "multi": multi}
        if gid and gid in self.groups:
            obj["gid"], obj["gname"] = gid, self.groups[gid]["name"]
        self._send_or_queue(peer_id, msg_id, obj)
        return msg_id

    def _send_or_queue(self, peer_id: str, item_id: str, obj: dict, extra: Optional[dict] = None):
        obj.setdefault("from", self.settings.user_id)
        obj.setdefault("from_name", self.settings.name)
        self.store.queue(item_id, peer_id, obj, extra)     # written first: survives a crash or restart
        if peer_id in self.peers and peer_id not in self._flushing:
            self._deliver(item_id, peer_id, obj)
        elif obj.get("type") == "msg":
            self.message_status.emit(item_id, "queued", peer_id)

    def _deliver(self, item_id: str, peer_id: str, obj: dict, on_done=None):
        def ok():
            self.store.done(item_id, peer_id)
            if obj.get("type") == "msg":
                self.message_status.emit(item_id, "delivered", peer_id)
            elif obj.get("type") == "file_offer":
                tr = self.transfers.get(obj.get("tid"))
                if tr and tr.state == "queued":
                    tr.state = "offered"
                    self.transfer_changed.emit(tr.tid)
            if on_done:
                on_done(True)

        def fail(_err):
            if obj.get("type") == "msg":
                self.message_status.emit(item_id, "queued", peer_id)
            if on_done:
                on_done(False)

        if not self._request(peer_id, dict(obj), ok, fail):
            pass   # _request already called fail("offline")

    def flush_outbox(self, peer_id: str):
        """Send everything waiting for this user, in the original order."""
        if peer_id in self._flushing or peer_id not in self.peers:
            return
        items = self.store.pending(peer_id)
        if not items:
            return
        self._flushing.add(peer_id)

        def step(i=0):
            if i >= len(items) or peer_id not in self.peers:
                self._flushing.discard(peer_id)
                if i >= len(items) and self.store.pending(peer_id):    # new items arrived meanwhile
                    QTimer.singleShot(100, lambda: self.flush_outbox(peer_id))
                return
            item_id, _pid, obj, _extra = items[i]
            self._deliver(item_id, peer_id, obj, on_done=lambda ok: step(i + 1) if ok else self._flushing.discard(peer_id))
        step()

    def _retry_outbox(self):
        for pid in self.store.peers_with_pending():
            if pid in self.peers:
                self.flush_outbox(pid)

    def pending_count(self, peer_id: str) -> int:
        return len(self.store.pending(peer_id))

    # ---------------------------------------------------------------- files (queued when offline)
    def offer_files(self, peer_id: str, paths: List[str], gid: str = "", peer_name: str = "") -> Optional[str]:
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
        peer = self.peers.get(peer_id)
        tr = Transfer(tid=tid, direction="out", peer_id=peer_id, peer_name=peer.name if peer else peer_name,
                      files=files, total=sum(f["size"] for f in files), title=title, sources=sources,
                      state="offered" if peer else "queued", gid=gid)
        self.transfers[tid] = tr
        self.transfer_added.emit(tid)
        obj = {"type": "file_offer", "tid": tid, "files": files, "title": title}
        if gid:
            obj["gid"] = gid
        self._send_or_queue(peer_id, tid, obj, extra={"sources": sources, "peer_name": tr.peer_name})
        return tid

    def _restore_queued_transfers(self):
        """After a restart, files that were waiting for an offline user are still waiting."""
        for item_id, pid, obj, extra in self.store.pending():
            if obj.get("type") != "file_offer" or item_id in self.transfers:
                continue
            sources = extra.get("sources", [])
            if not sources or not all(os.path.exists(x) for x in sources):
                self.store.done(item_id, pid)
                continue
            self.transfers[item_id] = Transfer(
                tid=item_id, direction="out", peer_id=pid, peer_name=extra.get("peer_name", ""),
                files=obj.get("files", []), total=sum(int(f.get("size", 0)) for f in obj.get("files", [])),
                title=obj.get("title", ""), sources=sources, state="queued", gid=obj.get("gid", ""))

    # ---------------------------------------------------------------- groups
    def _apply_group(self, g: dict):
        gid = str(g.get("gid", ""))[:64]
        if not gid:
            return
        members = {str(k)[:64]: str(v)[:64] for k, v in list(g.get("members", {}).items())[:5000]}
        cur = self.groups.get(gid)
        if self.settings.user_id not in members:          # we were removed / left
            if cur:
                del self.groups[gid]
                self.store.delete_group(gid)
                self.group_removed.emit(gid)
            return
        if cur and int(cur.get("version", 0)) > int(g.get("version", 0)):
            return
        new = {"gid": gid, "name": str(g.get("name", "?"))[:80], "owner": str(g.get("owner", "")),
               "version": int(g.get("version", 0)), "members": members}
        self.groups[gid] = new
        self.store.save_group(new)
        self.group_updated.emit(gid)

    def _broadcast_group(self, g: dict, extra_recipients=()):
        for pid in set(g["members"]) | set(extra_recipients):
            if pid != self.settings.user_id:
                self._send_or_queue(pid, f"grp-{g['gid']}-{g['version']}",
                                    {"type": "group_update", "group": g})

    def create_group(self, name: str, member_ids: Dict[str, str]) -> str:
        gid = uuid.uuid4().hex
        members = dict(member_ids)
        members[self.settings.user_id] = self.settings.name
        g = {"gid": gid, "name": name.strip()[:80] or "Group", "owner": self.settings.user_id,
             "version": 1, "members": members}
        self.groups[gid] = g
        self.store.save_group(g)
        self.group_updated.emit(gid)
        self._broadcast_group(g)
        return gid

    def update_group(self, gid: str, name: Optional[str] = None, add: Optional[Dict[str, str]] = None,
                     remove=()):
        g = self.groups.get(gid)
        if not g:
            return
        removed = [r for r in remove if r in g["members"] and r != self.settings.user_id]
        if name:
            g["name"] = name.strip()[:80]
        g["members"].update(add or {})
        for r in removed:
            g["members"].pop(r, None)
        g["version"] = int(g.get("version", 0)) + 1
        self.store.save_group(g)
        self.group_updated.emit(gid)
        self._broadcast_group(g, extra_recipients=removed)    # removed members learn they are out

    def leave_group(self, gid: str):
        g = self.groups.pop(gid, None)
        if not g:
            return
        self.store.delete_group(gid)
        for pid in g["members"]:
            if pid != self.settings.user_id:
                self._send_or_queue(pid, f"leave-{gid}", {"type": "group_leave", "gid": gid})
        self.group_removed.emit(gid)

    def send_group_message(self, gid: str, text: str, msg_id: Optional[str] = None) -> str:
        msg_id = msg_id or uuid.uuid4().hex
        for pid in self.groups.get(gid, {}).get("members", {}):
            if pid != self.settings.user_id:
                self.send_message(pid, text, msg_id=msg_id, gid=gid)
        return msg_id

    def offer_group_files(self, gid: str, paths: List[str]) -> List[str]:
        g = self.groups.get(gid)
        if not g:
            return []
        return [t for pid, name in g["members"].items() if pid != self.settings.user_id
                for t in [self.offer_files(pid, paths, gid=gid, peer_name=name)] if t]

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
        if prev == "queued":
            self.store.done(tid, tr.peer_id)
        tr.state = "canceled"
        self.transfer_changed.emit(tid)
        if tr.direction == "out" and prev == "offered":
            self._request(tr.peer_id, {"type": "file_cancel", "tid": tid})
