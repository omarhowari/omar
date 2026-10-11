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
from . import groups as G
from . import theme_share, updates
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
    upd: bool = False                   # can give us its installer (in-place update)
    thv: int = 0                        # version of the administrator's appearance it has

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
    purpose: str = ""                  # "" = user files | "update" = installer of a newer TDA

    @property
    def finished(self) -> bool:
        return self.state in ("done", "failed", "declined", "canceled")


def _clean_reply(r) -> Optional[dict]:
    """The quoted message a reply points to: {"id", "name", "text"} (short)."""
    if not isinstance(r, dict) or not r.get("id"):
        return None
    return {"id": str(r["id"])[:64], "name": str(r.get("name", ""))[:64], "text": str(r.get("text", ""))[:200]}


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
    group_message_deleted = Signal(str, str, str)   # gid, msg id, deleted by (user id)
    message_deleted = Signal(str, str)     # private chat: sender id, msg id (sender deleted it for everyone)
    message_read = Signal(str, list, str)   # reader id, msg ids, gid ("" = private)
    chat_setting = Signal(str, str, dict)  # sender, gid, {"disappear": seconds}
    message_edited = Signal(dict)          # {"from","gid","msg_id","text"}
    reaction = Signal(dict)                # {"gid","from","from_name","msg_id","emoji"} ("" emoji = removed)
    update_available = Signal(str, str)    # newer version, peer id that has it
    update_progress = Signal(int, int)     # bytes done, total
    update_ready = Signal(str, str)        # installer path, version
    update_failed = Signal(str)
    theme_applied = Signal(dict)           # the administrator's appearance arrived and was applied

    def __init__(self, settings: Settings, parent: Optional[QObject] = None, data_dir=None):
        super().__init__(parent)
        self.settings = settings
        from .config import config_dir
        self.data_dir = Path(data_dir) if data_dir else config_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data_dir / "network.db")
        self.groups: Dict[str, dict] = {k: G.normalize(v) for k, v in self.store.groups().items()}
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
        self.version = APP_VERSION              # (tests may pretend another version)
        self.update_package = updates.update_package
        self._update_seen: set = set()          # versions already offered to the user
        self._update_from: Dict[str, float] = {}  # peer id -> time we asked it for its installer
        self._update_tid = ""
        self._theme_asked: Dict[tuple, float] = {}
        self.transfer_changed.connect(self._update_transfer_changed)

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
                "os": f"{platform.system()} {platform.release()}", "v": self.version, "pv": PROTOCOL_VERSION,
                "iv": round(self.announce_interval(), 1),
                "upd": 1 if self.update_package() else 0, "thv": int(s.theme_version or 0)}

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
            version = str(msg.get("v", ""))[:16]
            upd = bool(msg.get("upd"))
            try:
                thv = int(msg.get("thv", 0))
            except (TypeError, ValueError):
                thv = 0
            if old and (old.name, old.group, old.status, old.host, old.tcp_port, old.version, old.upd, old.thv) == \
                    (name, group, status, host, port, version, upd, thv):
                old.last_seen, old.iv = time.time(), iv          # fast path: nothing changed
                continue
            peer = Peer(id=pid, name=name, group=group, status=status, host=host, tcp_port=port,
                        hostname=str(msg.get("host", ""))[:64], os=str(msg.get("os", ""))[:64],
                        version=version, last_seen=time.time(), iv=iv, upd=upd, thv=thv)
            self.peers[pid] = peer
            self._check_peer_news(peer)
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
        if peer is None and sender and sender != self.settings.user_id and obj.get("from_port"):
            # someone we have not discovered yet (their announcement is still on its way): learn them now
            try:
                port = int(obj["from_port"])
            except (TypeError, ValueError):
                port = 0
            if 0 < port < 65536:
                peer = Peer(id=sender[:64], name=str(obj.get("from_name", "?"))[:64],
                            group=str(obj.get("from_group", ""))[:64], status="available",
                            host=_clean_host(conn.sock.peerAddress()), tcp_port=port, last_seen=time.time())
                self.peers[peer.id] = peer
                self.peer_updated.emit(peer)
        if t == "msg":
            text = str(obj.get("text", ""))[:100_000]
            conn.reply({"type": "ack", "id": obj.get("id")})
            gid = str(obj.get("gid", ""))[:64]
            if gid and gid not in self.groups:     # group we have not heard of yet
                self._apply_group({"gid": gid, "name": str(obj.get("gname", "?"))[:80], "version": 0,
                                   "owner": sender, "members": {sender: str(obj.get("from_name", "?"))[:64],
                                                                self.settings.user_id: self.settings.name}},
                                  sender)
            if gid and not G.can(self.groups.get(gid, {}), sender, "write"):
                return                              # muted by an admin / admins-only group: drop
            try:
                ts = float(obj.get("ts", time.time()))
            except (TypeError, ValueError):
                ts = time.time()
            self.message_received.emit({
                "id": str(obj.get("id") or uuid.uuid4().hex), "from": sender,
                "from_name": peer.name if peer else str(obj.get("from_name", "?")),
                "text": text, "ts": ts, "multi": bool(obj.get("multi")), "gid": gid,
                "reply": _clean_reply(obj.get("reply")), "fwd": bool(obj.get("fwd"))})
        elif t == "react":
            conn.reply({"type": "ack"})
            gid = str(obj.get("gid", ""))[:64]
            if gid and sender not in self.groups.get(gid, {}).get("members", {}):
                return
            emoji = str(obj.get("emoji", ""))[:16]
            self.reaction.emit({"gid": gid, "from": sender, "msg_id": str(obj.get("msg_id", ""))[:64],
                                "from_name": peer.name if peer else str(obj.get("from_name", "?"))[:64],
                                "emoji": emoji})
        elif t == "read":
            conn.reply({"type": "ack"})
            ids = [str(x)[:64] for x in (obj.get("ids") or [])[:500]]
            if ids:
                self.message_read.emit(sender, ids, str(obj.get("gid", ""))[:64])
        elif t == "chat_setting":
            conn.reply({"type": "ack"})
            gid = str(obj.get("gid", ""))[:64]
            if gid and sender not in self.groups.get(gid, {}).get("members", {}):
                return
            try:
                secs = max(0, min(10 ** 8, int(obj.get("disappear", 0))))
            except (TypeError, ValueError):
                return
            self.chat_setting.emit(sender, gid, {"disappear": secs})
        elif t == "msg_edit":
            conn.reply({"type": "ack"})
            gid = str(obj.get("gid", ""))[:64]
            if gid and not G.can(self.groups.get(gid, {}), sender, "write"):
                return
            self.message_edited.emit({"from": sender, "gid": gid, "msg_id": str(obj.get("msg_id", ""))[:64],
                                      "text": str(obj.get("text", ""))[:100_000]})
        elif t == "msg_delete":
            conn.reply({"type": "ack"})
            self.message_deleted.emit(sender, str(obj.get("msg_id", ""))[:64])
        elif t == "group_update":
            conn.reply({"type": "ack"})
            g = obj.get("group")
            if isinstance(g, dict) and isinstance(g.get("members"), dict):
                self._apply_group(g, sender)
        elif t == "group_leave":
            conn.reply({"type": "ack"})
            g = self.groups.get(str(obj.get("gid", "")))
            if g and sender in g["members"]:
                g = G.after_leave(g, sender)
                self.groups[g["gid"]] = g
                self.store.save_group(g)
                self.group_updated.emit(g["gid"])
        elif t == "group_delete":
            conn.reply({"type": "ack"})
            g = self.groups.get(str(obj.get("gid", "")))
            if g and (G.is_admin(g, sender) or (obj.get("own") and sender in g["members"])):
                # "own": a member deleting his own message (the UI checks the message is really his)
                self.group_message_deleted.emit(g["gid"], str(obj.get("msg_id", ""))[:64], sender)
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
            purpose = str(obj.get("purpose", ""))
            if purpose == "update":
                # only an installer we asked for, and only one file
                if time.time() - self._update_from.get(sender, 0) > 120 or len(files) != 1 \
                        or files[0]["size"] > updates.MAX_SETUP:
                    conn.reply({"type": "ack"})
                    return
            elif purpose:
                conn.reply({"type": "ack"})
                return
            ogid = str(obj.get("gid", ""))[:64]
            if ogid and ogid in self.groups and not G.can(self.groups[ogid], sender, "media"):
                conn.reply({"type": "ack"})          # restricted from sending media in this group: drop
                return
            tr = Transfer(tid=tid, direction="in", peer_id=sender,
                          peer_name=peer.name if peer else str(obj.get("from_name", "?")), files=files,
                          total=sum(f["size"] for f in files), title=str(obj.get("title", ""))[:200],
                          gid=str(obj.get("gid", ""))[:64], purpose=purpose)
            self.transfers[tid] = tr
            conn.reply({"type": "ack"})
            if purpose == "update":
                self._update_from.pop(sender, None)
                self._accept_update(tr)
                return
            self.transfer_added.emit(tid)
        elif t in ("file_accept", "file_reject", "file_cancel"):
            tid = str(obj.get("tid"))
            tr = self.transfers.get(tid)
            conn.reply({"type": "ack"})
            # "queued": the receiver may answer before our own delivery confirmation is processed
            if not tr or tr.peer_id != sender or tr.state not in ("offered", "queued"):
                return
            if tr.state == "queued":
                self.store.done(tid, sender)
                tr.state = "offered"
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
        elif t == "update_req":
            conn.reply({"type": "ack"})
            pkg = self.update_package()
            if pkg and peer is not None:
                self.offer_files(sender, [str(pkg)], purpose="update")
        elif t == "theme_req":
            conn.reply({"type": "ack"})
            pkg = self.theme_package()
            if pkg and peer is not None:
                self._request(sender, {"type": "theme", "pkg": pkg})
        elif t == "theme":
            conn.reply({"type": "ack"})
            self.receive_theme(obj.get("pkg"))
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
        obj.setdefault("from_port", self.settings.tcp_port)      # lets the receiver answer before discovery
        obj.setdefault("from_group", self.settings.group)
        _Request(self, peer.host, peer.tcp_port, obj, on_ok, on_fail)
        return True

    def send_control(self, peer_id: str, obj: dict, on_ok=None, on_fail=None) -> bool:
        """Send one control message (used by calls)."""
        return self._request(peer_id, dict(obj), on_ok, on_fail)

    # ---------------------------------------------------------------- messages (with offline outbox)
    def send_message(self, peer_id: str, text: str, multi: bool = False, msg_id: Optional[str] = None,
                     gid: str = "", reply: Optional[dict] = None, fwd: bool = False) -> str:
        """Deliver now if the user is online; otherwise keep it and deliver when they come back."""
        msg_id = msg_id or uuid.uuid4().hex
        obj = {"type": "msg", "id": msg_id, "text": text, "ts": time.time(), "multi": multi}
        if reply:
            obj["reply"] = _clean_reply(reply)
        if fwd:
            obj["fwd"] = True
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
    def offer_files(self, peer_id: str, paths: List[str], gid: str = "", peer_name: str = "",
                    purpose: str = "") -> Optional[str]:
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
                      state="offered" if peer else "queued", gid=gid, purpose=purpose)
        self.transfers[tid] = tr
        obj = {"type": "file_offer", "tid": tid, "files": files, "title": title}
        if purpose:                       # internal transfer (installer): never queued, not shown in chats
            obj["purpose"] = purpose
            if not peer:
                del self.transfers[tid]
                return None
            self._deliver(tid, peer_id, obj)
            return tid
        self.transfer_added.emit(tid)
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
    def _apply_group(self, g: dict, sender: str):
        new = G.normalize(g)
        gid = new["gid"]
        if not gid:
            return
        cur = self.groups.get(gid)
        if not G.update_allowed(cur, new, sender):
            return                                     # not allowed to make this change: ignore
        if self.settings.user_id not in new["members"]:    # we were removed
            if cur:
                del self.groups[gid]
                self.store.delete_group(gid)
                self.group_removed.emit(gid)
            return
        self.groups[gid] = new
        self.store.save_group(new)
        self.group_updated.emit(gid)

    def _broadcast_group(self, g: dict, extra_recipients=()):
        for pid in set(g["members"]) | set(extra_recipients):
            if pid != self.settings.user_id:
                self._send_or_queue(pid, f"grp-{g['gid']}-{g['version']}",
                                    {"type": "group_update", "group": g})

    def my_role(self, gid: str) -> str:
        return G.role(self.groups.get(gid, {}), self.settings.user_id)

    def can(self, gid: str, action: str, uid: Optional[str] = None) -> bool:
        return G.can(self.groups.get(gid, {}), uid or self.settings.user_id, action)

    def create_group(self, name: str, member_ids: Dict[str, str], desc: str = "") -> str:
        gid = uuid.uuid4().hex
        members = dict(member_ids)
        members[self.settings.user_id] = self.settings.name
        g = G.normalize({"gid": gid, "name": name.strip()[:80] or "Group", "desc": desc,
                         "author": self.settings.user_id,
                         "owner": self.settings.user_id, "admins": [self.settings.user_id],
                         "version": 1, "members": members})
        self.groups[gid] = g
        self.store.save_group(g)
        self.group_updated.emit(gid)
        self._broadcast_group(g)
        return gid

    def update_group(self, gid: str, name: Optional[str] = None, add: Optional[Dict[str, str]] = None,
                     remove=(), desc: Optional[str] = None, admins_add=(), admins_remove=(),
                     settings: Optional[dict] = None, restrict: Optional[Dict[str, dict]] = None,
                     owner: Optional[str] = None) -> bool:
        """Apply a change if *we* are allowed to make it (same rules the receivers check)."""
        cur = self.groups.get(gid)
        if not cur:
            return False
        import copy
        g = copy.deepcopy(cur)
        me = self.settings.user_id
        if name is not None:
            g["name"] = name.strip()[:80] or g["name"]
        if desc is not None:
            g["desc"] = desc.strip()[:500]
        g["members"].update(add or {})
        removed = [r for r in remove if r in g["members"] and r != me]
        for r in removed:
            g["members"].pop(r, None)
            g["restricted"].pop(r, None)
            if r in g["admins"]:
                g["admins"].remove(r)
        for a_ in admins_add:
            if a_ in g["members"] and a_ not in g["admins"]:
                g["admins"].append(a_)
        for a_ in admins_remove:
            if a_ in g["admins"] and a_ != g["owner"]:
                g["admins"].remove(a_)
        if settings:
            g["settings"].update({k: v for k, v in settings.items() if k in G.DEFAULT_SETTINGS})
        for uid, flags in (restrict or {}).items():
            g["restricted"][uid] = {r: bool(flags.get(r)) for r in G.RESTRICTIONS}
        if owner and owner in g["members"]:
            g["owner"] = owner
        g = G.normalize(g)
        skip = ("version", "author")
        if {k: v for k, v in g.items() if k not in skip} == {k: v for k, v in cur.items() if k not in skip}:
            return False                       # nothing actually changes (e.g. trying to demote the owner)
        g["version"] = cur["version"] + 1
        g["author"] = me
        if not G.update_allowed(cur, g, me):
            return False
        self.groups[gid] = g
        self.store.save_group(g)
        self.group_updated.emit(gid)
        self._broadcast_group(g, extra_recipients=removed)    # removed members learn they are out
        return True

    def leave_group(self, gid: str):
        g = self.groups.pop(gid, None)
        if not g:
            return
        self.store.delete_group(gid)
        for pid in g["members"]:
            if pid != self.settings.user_id:
                self._send_or_queue(pid, f"leave-{gid}", {"type": "group_leave", "gid": gid})
        self.group_removed.emit(gid)

    def delete_group_message(self, gid: str, msg_id: str) -> bool:
        """Admins: delete a message for everyone in the group."""
        g = self.groups.get(gid)
        if not g or not G.is_admin(g, self.settings.user_id):
            return False
        for pid in g["members"]:
            if pid != self.settings.user_id:
                self._send_or_queue(pid, f"del-{msg_id}", {"type": "group_delete", "gid": gid, "msg_id": msg_id})
        self.group_message_deleted.emit(gid, msg_id, self.settings.user_id)
        return True

    def send_group_message(self, gid: str, text: str, msg_id: Optional[str] = None,
                           reply: Optional[dict] = None, fwd: bool = False) -> str:
        msg_id = msg_id or uuid.uuid4().hex
        if not self.can(gid, "write"):
            return ""
        for pid in self.groups.get(gid, {}).get("members", {}):
            if pid != self.settings.user_id:
                self.send_message(pid, text, msg_id=msg_id, gid=gid, reply=reply, fwd=fwd)
        return msg_id

    def react(self, peer_or_group: str, msg_id: str, emoji: str):
        """WhatsApp-style reaction (👍 ❤️ ...) to a message; "" removes my reaction.
        peer_or_group: a user id, or "g:<gid>" for a group (everyone in the group sees it)."""
        if peer_or_group.startswith("g:"):
            gid = peer_or_group[2:]
            targets = [p for p in self.groups.get(gid, {}).get("members", {}) if p != self.settings.user_id]
        else:
            gid, targets = "", [peer_or_group]
        for pid in targets:
            obj = {"type": "react", "msg_id": msg_id, "emoji": emoji}
            if gid:
                obj["gid"] = gid
            # one outbox slot per (message, me): a newer reaction replaces an undelivered older one
            self._send_or_queue(pid, f"re-{msg_id}", obj)

    def send_read(self, sender: str, ids: List[str], gid: str = ""):
        """Blue ticks: tell the sender I have seen his messages."""
        if not ids:
            return
        obj = {"type": "read", "ids": list(ids)}
        if gid:
            obj["gid"] = gid
        self._send_or_queue(sender, f"read-{ids[-1]}", obj)

    def send_chat_setting(self, peer_or_group: str, disappear: int):
        if peer_or_group.startswith("g:"):
            gid = peer_or_group[2:]
            targets = [p for p in self.groups.get(gid, {}).get("members", {}) if p != self.settings.user_id]
        else:
            gid, targets = "", [peer_or_group]
        for pid in targets:
            obj = {"type": "chat_setting", "disappear": int(disappear)}
            if gid:
                obj["gid"] = gid
            self._send_or_queue(pid, f"cs-{gid or pid}", obj)

    def edit_message(self, peer_or_group: str, msg_id: str, text: str):
        if peer_or_group.startswith("g:"):
            gid = peer_or_group[2:]
            targets = [p for p in self.groups.get(gid, {}).get("members", {}) if p != self.settings.user_id]
        else:
            gid, targets = "", [peer_or_group]
        for pid in targets:
            obj = {"type": "msg_edit", "msg_id": msg_id, "text": text}
            if gid:
                obj["gid"] = gid
            self._send_or_queue(pid, f"edit-{msg_id}", obj)

    def delete_message(self, peer_or_group: str, msg_id: str, own: bool = True) -> bool:
        """Delete for everyone: my own message (private or group), or any group message if I am an admin."""
        if peer_or_group.startswith("g:"):
            gid = peer_or_group[2:]
            g = self.groups.get(gid)
            if not g:
                return False
            if not own and not G.is_admin(g, self.settings.user_id):
                return False
            for pid in g["members"]:
                if pid != self.settings.user_id:
                    self._send_or_queue(pid, f"del-{msg_id}", {"type": "group_delete", "gid": gid,
                                                              "msg_id": msg_id, "own": bool(own)})
            self.group_message_deleted.emit(gid, msg_id, self.settings.user_id)
            return True
        self._send_or_queue(peer_or_group, f"del-{msg_id}", {"type": "msg_delete", "msg_id": msg_id})
        return True

    def offer_group_files(self, gid: str, paths: List[str]) -> List[str]:
        g = self.groups.get(gid)
        if not g or not self.can(gid, "media"):
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

    # ---------------------------------------------------------------- in-place updates & shared appearance
    def _check_peer_news(self, peer: Peer):
        if peer.upd and peer.version and updates.newer(peer.version, self.version) \
                and peer.version not in self._update_seen:
            self._update_seen.add(peer.version)
            self.update_available.emit(peer.version, peer.id)
        if peer.thv > int(self.settings.theme_version or 0):
            key = (peer.id, peer.thv)
            if time.time() - self._theme_asked.get(key, 0) > 60:
                self._theme_asked[key] = time.time()
                QTimer.singleShot(random.randint(200, 3000),
                                  lambda pid=peer.id: self._request(pid, {"type": "theme_req"}))

    def best_update_source(self) -> Optional[Peer]:
        """The online colleague with the newest version that can give us its installer."""
        cands = [p for p in self.peers.values() if p.upd and updates.newer(p.version, self.version)]
        return max(cands, key=lambda p: updates.version_tuple(p.version)) if cands else None

    def request_update(self, peer_id: Optional[str] = None) -> bool:
        peer = self.peers.get(peer_id) if peer_id else self.best_update_source()
        if not peer:
            return False
        self._update_from[peer.id] = time.time()
        self._update_version = peer.version
        return self._request(peer.id, {"type": "update_req"},
                             on_fail=lambda err: self.update_failed.emit(str(err)))

    def _accept_update(self, tr: Transfer):
        from .config import config_dir
        d = Path(self.data_dir) / "updates"
        try:
            if d.exists():
                for f in d.iterdir():
                    if f.is_file():
                        f.unlink()
        except OSError:
            pass
        tr.files[0]["rel"] = updates.SETUP_NAME
        self._update_tid = tr.tid
        self.accept_transfer(tr.tid, str(d))

    def _update_transfer_changed(self, tid: str):
        if tid != self._update_tid:
            return
        tr = self.transfers.get(tid)
        if not tr:
            return
        if tr.state == "done":
            path = tr.dest_paths[0] if tr.dest_paths else ""
            if path and updates.looks_like_installer(path):
                self.update_ready.emit(path, getattr(self, "_update_version", ""))
            else:
                self.update_failed.emit("invalid installer")
        elif tr.state in ("failed", "canceled", "declined"):
            self.update_failed.emit(tr.error or tr.state)
        else:
            self.update_progress.emit(tr.done, tr.total)

    def _theme_file(self) -> Path:
        return Path(self.data_dir) / "theme_package.json"

    def theme_package(self) -> Optional[dict]:
        try:
            return json.loads(self._theme_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def receive_theme(self, pkg) -> bool:
        """A signed appearance from the administrator: verify, apply, keep it to pass on to others."""
        if not isinstance(pkg, dict):
            return False
        theme = theme_share.verify(pkg, self.settings.theme_pin)
        if theme is None:
            return False
        try:
            v = int(theme.get("v", 0))
        except (TypeError, ValueError):
            return False
        if v <= int(self.settings.theme_version or 0):
            return False
        self.settings.theme_pin = str(pkg["pub"])
        try:
            self._theme_file().write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        theme_share.apply(theme, self.settings)
        self.theme_applied.emit(theme)
        self.announce("hello")                  # others now see we have it and can fetch it from us too
        return True

    def publish_theme(self, password: str, lock: bool) -> Optional[dict]:
        """Administrator: sign the current appearance with the admin password and spread it."""
        v = max(int(self.settings.theme_version or 0),
                max((p.thv for p in self.peers.values()), default=0)) + 1
        pkg = theme_share.sign(theme_share.build(self.settings, v, lock), password)
        if self.settings.theme_pin and pkg["pub"] != self.settings.theme_pin:
            return None                         # a different password than the one everybody trusts
        if not self.receive_theme(pkg):
            return None
        self.settings.theme_lock = False        # the administrator's own computer is never locked
        self.settings.save()
        return pkg
