"""Main window: user list, chat tabs, toolbar, tray icon."""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QSplitter, QStackedWidget,
                               QStatusBar, QSystemTrayIcon, QTabWidget, QToolBar, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import APP_NAME, branding
from ..config import Settings
from ..history import History
from ..i18n import human_size, tr
from ..calls import CallController
from ..network import NetworkCore, Peer
from .call_window import CallWindow
from .chat import ChatWidget, local_paths
from .dialogs import (BroadcastDialog, HistorySearchDialog, SettingsDialog, TransfersDialog,
                      about_html, open_path)
from .theme import app_icon, draw_avatar, draw_logo, status_icon

STATUSES = ("available", "away", "busy")
OFFLINE_GROUP = "\x00offline"


def idle_seconds() -> float:
    """Seconds since last keyboard/mouse input (Windows only, 0 elsewhere)."""
    if sys.platform != "win32":
        return 0.0
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0


def local_ips() -> list[str]:
    out = []
    for a in QNetworkInterface.allAddresses():
        if a.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol and not a.isLoopback():
            out.append(a.toString())
    return out


class PeerTree(QTreeWidget):
    """User list that also accepts files dropped onto a user's name."""
    files_dropped = Signal(str, list)   # peer_id, paths

    def __init__(self, online_check):
        super().__init__()
        self.online_check = online_check
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def _target(self, e):
        it = self.itemAt(e.position().toPoint())
        pid = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        return (pid, it) if pid and self.online_check(pid) else (None, None)

    def dragEnterEvent(self, e):
        if local_paths(e.mimeData()):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        pid, it = self._target(e)
        if pid and local_paths(e.mimeData()):
            self.setCurrentItem(it)
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        pid, _ = self._target(e)
        paths = local_paths(e.mimeData())
        if pid and paths:
            e.acceptProposedAction()
            self.files_dropped.emit(pid, paths)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, core: NetworkCore, history: History):
        super().__init__()
        self.s, self.core, self.history = settings, core, history
        self.chats: dict[str, ChatWidget] = {}
        self.unread: dict[str, int] = {}
        self.known: dict[str, dict] = {c["id"]: c for c in history.contacts()}
        self.transfers_dlg: TransfersDialog | None = None
        self.auto_away = False
        self.quitting = False

        self.setWindowTitle(self.app_title())
        self.setWindowIcon(app_icon())
        self.resize(1080, 700)

        self._build_toolbar()
        self._build_body()
        self._build_status()
        self._build_tray()

        core.peer_updated.connect(self.on_peer)
        core.peer_removed.connect(self.on_peer_removed)
        core.message_received.connect(self.on_message)
        core.message_status.connect(self.on_message_status)
        core.transfer_added.connect(self.on_transfer_added)
        core.transfer_changed.connect(self.on_transfer_changed)

        self.calls = CallController(core, parent=self)
        self.call_win = CallWindow(self.calls)
        self.call_win.setWindowIcon(app_icon())
        self.calls.incoming.connect(self.on_incoming_call)
        self.calls.ended.connect(self.on_call_ended)

        self.idle_timer = QTimer(self, interval=15000)
        self.idle_timer.timeout.connect(self._check_idle)
        self.idle_timer.start()
        self.refresh_tree()

    # ======================================================================= build
    def _build_toolbar(self):
        tb = QToolBar(movable=False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)

        def act(symbol, text, slot):
            a = QAction(f"{symbol}  {text}", self)
            a.triggered.connect(slot)
            tb.addAction(a)
            return a

        act("📢", tr("broadcast"), lambda: self.broadcast())
        act("📎", tr("send_file"), self.send_file_to_selected)
        act("⇅", tr("transfers"), self.show_transfers)
        act("🔍", tr("history_search"), self.search_history)
        tb.addSeparator()
        act("⚙", tr("settings"), self.open_settings)
        act("ℹ", tr("about"), self.about)

    def _build_body(self):
        side = QFrame(objectName="SidePanel")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 10, 10, 10)

        card = QFrame(objectName="MeCard")
        cl = QHBoxLayout(card)
        self.avatar = QLabel()
        self.avatar.setPixmap(draw_avatar(self.s.name, 42))
        self.me_name = QLabel(self.s.name, objectName="MeName")
        self.me_group = QLabel(self.s.group)
        nl = QVBoxLayout()
        nl.setSpacing(0)
        nl.addWidget(self.me_name)
        nl.addWidget(self.me_group)
        cl.addWidget(self.avatar)
        cl.addLayout(nl, 1)
        sl.addWidget(card)

        self.status_box = QComboBox()
        for st in STATUSES:
            self.status_box.addItem(status_icon(st), tr("status_" + st), st)
        self.status_box.setCurrentIndex(max(0, STATUSES.index(self.s.status) if self.s.status in STATUSES else 0))
        self.status_box.currentIndexChanged.connect(lambda _i: self.set_status(self.status_box.currentData()))
        sl.addWidget(self.status_box)

        self.search = QLineEdit(placeholderText=tr("search_users"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.refresh_tree())
        sl.addWidget(self.search)

        self.tree = PeerTree(lambda pid: pid in self.core.peers)
        self.tree.files_dropped.connect(self.send_paths)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.setIconSize(QSize(14, 14))
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.itemActivated.connect(self._tree_open)
        self.tree.itemDoubleClicked.connect(self._tree_open)
        sl.addWidget(self.tree, 1)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)

        welcome = QWidget()
        wl = QVBoxLayout(welcome)
        wl.addStretch(1)
        big = self.welcome_img = QLabel()
        big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = self.welcome_title = QLabel(objectName="WelcomeTitle")
        f = QFont()
        f.setPointSize(18)
        f.setBold(True)
        t.setFont(f)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b = QLabel(tr("welcome_body"), objectName="Muted")
        b.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (big, t, b):
            wl.addWidget(w)
        wl.addStretch(2)
        self._paint_welcome()

        self.stack = QStackedWidget()
        self.stack.addWidget(welcome)
        self.stack.addWidget(self.tabs)

        split = QSplitter()
        split.addWidget(side)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([290, 790])
        split.setChildrenCollapsible(False)
        self.setCentralWidget(split)

    def _build_status(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_online = QLabel()
        self.lbl_sec = QLabel("🔒 AES-256" if self.s.password else "🔓 " + ("بدون تشفير" if self.s.language == "ar" else "Not encrypted"))
        self.lbl_ip = QLabel(f"{socket.gethostname()}  ·  {', '.join(local_ips()) or '-'}", objectName="Muted")
        sb.addWidget(self.lbl_online)
        sb.addWidget(self.lbl_sec)
        sb.addPermanentWidget(self.lbl_ip)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(self.s.app_title or APP_NAME)
        m = QMenu()
        m.addAction(tr("show"), self.show_normal)
        sm = m.addMenu(tr("my_status"))
        for st in STATUSES:
            sm.addAction(status_icon(st), tr("status_" + st), lambda x=st: self.set_status(x))
        m.addAction(tr("broadcast"), self.broadcast)
        m.addSeparator()
        m.addAction(tr("quit"), self.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_normal() if r in (
            QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.messageClicked.connect(self.show_normal)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    # ======================================================================= branding
    def app_title(self) -> str:
        return self.s.app_title.strip() or tr("app_title")

    def _paint_welcome(self):
        pic = branding.custom_welcome()
        if pic is not None:
            pic = pic.scaled(420, 260, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.welcome_img.setPixmap(pic if pic is not None else draw_logo(200))
        self.welcome_title.setText(tr("welcome_title", name=self.s.app_title.strip() or APP_NAME))

    def apply_branding(self):
        icon = app_icon()
        QApplication.instance().setWindowIcon(icon)
        self.setWindowIcon(icon)
        self.tray.setIcon(app_icon(None if self.s.status == "available" else self.s.status))
        self.tray.setToolTip(self.s.app_title or APP_NAME)
        self._paint_welcome()
        self.refresh_tree()
        for dlg in (self.transfers_dlg,):
            if dlg is not None:
                dlg.setWindowIcon(icon)
        branding.update_shortcut_icons()

    # ======================================================================= user list
    def _peer_info(self, p: Peer) -> str:
        return f"{p.hostname} · {p.host}" if p.hostname else p.host

    def refresh_tree(self):
        q = self.search.text().strip().lower()
        expanded = {self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 1)
                    for i in range(self.tree.topLevelItemCount()) if not self.tree.topLevelItem(i).isExpanded()}
        selected = {it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()}
        self.tree.clear()
        groups: dict[str, list] = {}
        for p in self.core.peers.values():
            groups.setdefault(p.group or "General", []).append((p.id, p.name, p.status, self._peer_info(p)))
        for pid, c in self.known.items():
            if pid not in self.core.peers:
                groups.setdefault(OFFLINE_GROUP, []).append((pid, c["name"], "offline", c.get("group", "")))
        online = len(self.core.peers)
        for g in sorted(groups, key=lambda x: (x == OFFLINE_GROUP, x.lower())):
            members = [m for m in groups[g] if not q or q in m[1].lower() or q in (m[3] or "").lower()]
            if not members:
                continue
            title = tr("status_offline") if g == OFFLINE_GROUP else g
            head = QTreeWidgetItem([f"{title}  ({len(members)})"])
            head.setData(0, Qt.ItemDataRole.UserRole + 1, g)
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            head.setForeground(0, Qt.GlobalColor.darkGray)
            self.tree.addTopLevelItem(head)
            for pid, name, st, info in sorted(members, key=lambda m: m[1].lower()):
                n = self.unread.get(pid, 0)
                it = QTreeWidgetItem([f"{name}  ({n})" if n else name])
                it.setIcon(0, status_icon(st))
                it.setData(0, Qt.ItemDataRole.UserRole, pid)
                it.setToolTip(0, f"{name}\n{tr('status_' + st)}\n{info}")
                if n:
                    fb = it.font(0)
                    fb.setBold(True)
                    it.setFont(0, fb)
                if st == "offline":
                    it.setForeground(0, Qt.GlobalColor.gray)
                head.addChild(it)
                if pid in selected:
                    it.setSelected(True)
            head.setExpanded(g not in expanded)
        self.lbl_online.setText("  " + tr("online_count", n=online))
        total_unread = sum(self.unread.values())
        self.setWindowTitle(f"({total_unread}) {self.app_title()}" if total_unread else self.app_title())

    def _selected_peer_ids(self, online_only=True):
        ids = [it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()]
        return [i for i in ids if i and (not online_only or i in self.core.peers)]

    def _tree_open(self, item, _col=0):
        pid = item.data(0, Qt.ItemDataRole.UserRole)
        if pid:
            self.open_chat(pid)

    def _tree_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item or not item.data(0, Qt.ItemDataRole.UserRole):
            return
        pid = item.data(0, Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction(tr("send"), lambda: self.open_chat(pid))
        if pid in self.core.peers:
            m.addAction(tr("call_btn"), lambda: self.start_call(pid))
            m.addAction(tr("send_file"), lambda: self.open_chat(pid)._pick_files())
            m.addAction(tr("send_folder"), lambda: self.open_chat(pid)._pick_folder())
            ids = self._selected_peer_ids()
            if len(ids) > 1:
                m.addAction(f"{tr('broadcast')} ({len(ids)})", lambda: self.broadcast(ids))
            p = self.core.peers[pid]
            m.addSeparator()
            m.addAction(tr("info"), lambda: QMessageBox.information(
                self, p.name, f"{tr('user')}: {p.name}\n{tr('group')}: {p.group}\n{tr('computer')}: {p.hostname}\n"
                              f"{tr('address')}: {p.host}\n{tr('system')}: {p.os}\nTDA {p.version}"))
        m.addSeparator()
        m.addAction(tr("clear_history"), lambda: self.clear_history(pid))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # ======================================================================= chats
    def open_chat(self, pid: str, focus=True) -> ChatWidget:
        chat = self.chats.get(pid)
        if chat is None:
            name = self.core.peers[pid].name if pid in self.core.peers else self.known.get(pid, {}).get("name", "?")
            chat = ChatWidget(pid, name, self.s.name)
            chat.send_text.connect(self.send_text)
            chat.send_paths.connect(self.send_paths)
            chat.start_call.connect(self.start_call)
            chat.transfer_action.connect(self.transfer_action)
            chat.transfer_lookup = self.core.transfers.get
            chat.load(self.history.load(pid))
            self.chats[pid] = chat
            self.tabs.addTab(chat, status_icon("offline"), name)
            self._update_chat_peer(pid)
        self.stack.setCurrentIndex(1)
        if focus:
            self.tabs.setCurrentWidget(chat)
            chat.focus_input()
            self._mark_read(pid)
        return chat

    def _update_chat_peer(self, pid):
        chat = self.chats.get(pid)
        if not chat:
            return
        p = self.core.peers.get(pid)
        st = p.status if p else "offline"
        name = p.name if p else chat.peer_name
        chat.set_peer(name, st, self._peer_info(p) if p else "")
        i = self.tabs.indexOf(chat)
        n = self.unread.get(pid, 0)
        self.tabs.setTabText(i, f"{name} ({n})" if n else name)
        self.tabs.setTabIcon(i, status_icon(st))

    def _close_tab(self, i):
        w = self.tabs.widget(i)
        self.tabs.removeTab(i)
        self.chats.pop(w.peer_id, None)
        w.deleteLater()
        if not self.tabs.count():
            self.stack.setCurrentIndex(0)

    def _tab_changed(self, _i):
        w = self.tabs.currentWidget()
        if w is not None:
            self._mark_read(w.peer_id)

    def _mark_read(self, pid):
        if self.unread.pop(pid, None):
            self._update_chat_peer(pid)
            self.refresh_tree()

    def clear_history(self, pid):
        self.history.clear(pid)
        if pid in self.chats:
            self.chats[pid].load([])

    # ======================================================================= sending
    def send_text(self, pid: str, text: str, multi=False):
        mid = uuid.uuid4().hex
        item = {"id": mid, "outgoing": 1, "text": text, "ts": time.time(), "status": "", "multi": multi,
                "kind": "msg", "peer_name": self.s.name}
        name = self.core.peers[pid].name if pid in self.core.peers else ""
        self.history.add(mid, pid, name, True, text, item["ts"], "", multi)
        if pid in self.chats:
            self.chats[pid].add(item)
        self.core.send_message(pid, text, multi=multi, msg_id=mid)

    def send_paths(self, pid: str, paths: list):
        if pid not in self.core.peers:
            return
        self.open_chat(pid)
        self.core.offer_files(pid, paths)     # the file card is added by on_transfer_added

    def send_file_to_selected(self):
        ids = self._selected_peer_ids()
        if not ids and isinstance(self.tabs.currentWidget(), ChatWidget) and self.stack.currentIndex() == 1:
            ids = [self.tabs.currentWidget().peer_id] if self.tabs.currentWidget().peer_id in self.core.peers else []
        if not ids:
            QMessageBox.information(self, APP_NAME, tr("welcome_body"))
            return
        from PySide6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(self, tr("send_file"))
        for pid in ids if paths else []:
            self.send_paths(pid, paths)

    def broadcast(self, preselect=None):
        peers = list(self.core.peers.values())
        if not peers:
            QMessageBox.information(self, APP_NAME, tr("online_count", n=0))
            return
        dlg = BroadcastDialog(peers, preselect or self._selected_peer_ids(), self)
        if dlg.exec():
            text = dlg.message()
            for pid in dlg.recipients():
                self.send_text(pid, text, multi=True)

    def _sys_line(self, pid, text):
        mid = uuid.uuid4().hex
        self.history.add(mid, pid, "", False, text, time.time(), "", False, "sys")
        if pid in self.chats:
            self.chats[pid].add({"id": mid, "kind": "sys", "text": text, "ts": time.time()})

    # ======================================================================= network events
    def on_peer(self, p: Peer):
        self.known[p.id] = {"id": p.id, "name": p.name, "group": p.group}
        self.history.remember_contact(p.id, p.name, p.group)
        self._update_chat_peer(p.id)
        self.refresh_tree()

    def on_peer_removed(self, pid):
        self._update_chat_peer(pid)
        self.refresh_tree()

    def on_message(self, m: dict):
        pid = m["from"]
        if pid not in self.known:
            self.known[pid] = {"id": pid, "name": m["from_name"], "group": ""}
        chat = self.open_chat(pid, focus=False)   # loads history first, then we append
        self.history.add(m["id"], pid, m["from_name"], False, m["text"], m["ts"], "", m["multi"])
        chat.add({"id": m["id"], "outgoing": 0, "text": m["text"], "ts": m["ts"], "multi": m["multi"],
                  "kind": "msg", "peer_name": m["from_name"]})
        visible = self.isActiveWindow() and self.tabs.currentWidget() is chat and self.stack.currentIndex() == 1
        if self.tabs.count() == 1 and not self.isVisible():
            self.tabs.setCurrentWidget(chat)
        if not visible:
            self.unread[pid] = self.unread.get(pid, 0) + 1
            self._update_chat_peer(pid)
            self.refresh_tree()
            self._alert(tr("new_message_from", name=m["from_name"]), m["text"][:200])

    def on_message_status(self, mid, ok, err):
        status = "delivered" if ok else "failed"
        self.history.set_status(mid, status)
        for c in self.chats.values():
            if c.set_status(mid, status):
                break

    # ---- files appear in the conversation as cards with accept / open buttons
    def _card_json(self, t) -> str:
        top = t.files[0]["rel"].split("/")[0] if t.files else ""
        single_top = all(f["rel"].split("/")[0] == top for f in t.files)
        d = {"title": t.title, "size": t.total, "count": len(t.files), "state": t.state,
             "is_dir": single_top and "/" in t.files[0]["rel"]}
        if t.direction == "out" and len(t.sources) == 1:
            d["source"] = t.sources[0]
        if t.direction == "in" and t.dest_paths:
            d["folder"] = t.dest_root
            first = Path(t.dest_paths[0])
            d["open"] = str(first if len(t.files) == 1 else (Path(t.dest_root) / first.relative_to(t.dest_root).parts[0]
                                                            if single_top else Path(t.dest_root)))
        return json.dumps(d, ensure_ascii=False)

    def on_transfer_added(self, tid):
        t = self.core.transfers[tid]
        ts = time.time()
        self.history.add(tid, t.peer_id, t.peer_name, t.direction == "out", self._card_json(t), ts, "", False, "file")
        chat = self.open_chat(t.peer_id, focus=t.direction == "out")
        if not chat.has_item(tid):
            chat.add({"id": tid, "kind": "file", "outgoing": t.direction == "out", "text": self._card_json(t),
                      "ts": ts, "peer_name": t.peer_name})
        if t.direction == "in":
            title = t.title if not t.title.isdigit() else tr("files_n", n=t.title)
            msg = tr("incoming_files", name=t.peer_name, title=title, size=human_size(t.total))
            visible = self.isActiveWindow() and self.tabs.currentWidget() is chat
            if not visible:
                self.unread[t.peer_id] = self.unread.get(t.peer_id, 0) + 1
                self._update_chat_peer(t.peer_id)
                self.refresh_tree()
            self._alert(tr("transfers"), msg)

    def on_transfer_changed(self, tid):
        t = self.core.transfers.get(tid)
        if not t:
            return
        chat = self.chats.get(t.peer_id)
        if getattr(t, "_saved_state", None) != t.state:      # persist state changes, not every progress tick
            t._saved_state = t.state
            text = self._card_json(t)
            self.history.set_text(tid, text)
            for it in (chat.items if chat else []):
                if it.get("id") == tid:
                    it["text"] = text
        if chat:
            chat.schedule_render()

    def transfer_action(self, action, tid):
        if action == "accept":
            self.core.accept_transfer(tid)
        elif action == "decline":
            self.core.reject_transfer(tid)
        elif action == "cancel":
            self.core.cancel_transfer(tid)
        elif action in ("open", "folder"):
            item = next((it for c in self.chats.values() for it in c.items if it.get("id") == tid), None)
            if not item:
                return
            try:
                d = json.loads(item.get("text") or "{}")
            except ValueError:
                return
            if item.get("outgoing"):
                src = d.get("source", "")
                target = src if action == "open" else os.path.dirname(src)
            else:
                target = d.get("open") if action == "open" else d.get("folder")
            if target and os.path.exists(target):
                open_path(target)

    # ======================================================================= calls
    def start_call(self, pid):
        if self.calls.state != "idle":
            QMessageBox.information(self, APP_NAME, tr("call_busy_now"))
            return
        if self.calls.start_call(pid):
            self.call_win.refresh()

    def on_incoming_call(self, pid, name):
        self.call_win.refresh()
        QApplication.alert(self, 0)
        if self.s.notify and self.tray.isVisible():
            self.tray.showMessage(tr("call"), tr("incoming_call_from", name=name), app_icon(), 8000)

    def on_call_ended(self, pid, direction, reason, duration):
        cid = uuid.uuid4().hex
        text = json.dumps({"direction": direction, "reason": reason, "duration": int(duration)})
        ts = time.time()
        name = self.core.peers[pid].name if pid in self.core.peers else self.known.get(pid, {}).get("name", "")
        self.history.add(cid, pid, name, direction == "out", text, ts, "", False, "call")
        chat = self.open_chat(pid, focus=False)
        chat.add({"id": cid, "kind": "call", "outgoing": direction == "out", "text": text, "ts": ts})
        if reason == "missed":
            self.unread[pid] = self.unread.get(pid, 0) + 1
            self._update_chat_peer(pid)
            self.refresh_tree()
            self._alert(tr("call_log_missed"), name)

    def _alert(self, title, body):
        if self.s.status == "busy":
            return
        QApplication.alert(self, 0)
        if self.s.notify and self.tray.isVisible():
            self.tray.showMessage(title, body, app_icon(), 5000)
        if self.s.sound:
            QApplication.beep()

    # ======================================================================= status
    def set_status(self, st, auto=False):
        if st not in STATUSES:
            return
        self.auto_away = auto
        self.s.status = st
        if not auto:
            self.s.save()
        self.status_box.blockSignals(True)
        self.status_box.setCurrentIndex(STATUSES.index(st))
        self.status_box.blockSignals(False)
        self.tray.setIcon(app_icon(None if st == "available" else st))
        self.core.announce("hello")

    def _check_idle(self):
        mins = self.s.auto_away_minutes
        if not mins:
            return
        idle = idle_seconds()
        if self.s.status == "available" and idle > mins * 60:
            self.set_status("away", auto=True)
        elif self.auto_away and idle < 30:
            self.set_status("available")

    # ======================================================================= dialogs
    def show_transfers(self):
        if self.transfers_dlg is None:
            self.transfers_dlg = TransfersDialog(self.core, self)
        self.transfers_dlg.show()
        self.transfers_dlg.raise_()

    def search_history(self):
        HistorySearchDialog(self.history, self).exec()

    def open_settings(self):
        dlg = SettingsDialog(self.s, self)
        dlg.branding_changed.connect(self.apply_branding)
        if not dlg.exec():
            return
        restart = dlg.apply()
        apply_autostart(self.s.autostart)
        self.me_name.setText(self.s.name)
        self.avatar.setPixmap(draw_avatar(self.s.name, 42))
        self.me_group.setText(self.s.group)
        self.lbl_sec.setText("🔒 AES-256" if self.s.password else "🔓 " + ("بدون تشفير" if self.s.language == "ar" else "Not encrypted"))
        self.core.apply_settings()
        if restart:
            QMessageBox.information(self, APP_NAME, tr("restart_needed"))

    def about(self):
        box = QMessageBox(self)
        box.setWindowTitle(tr("about"))
        box.setIconPixmap(draw_logo(72))
        box.setText(about_html())
        box.exec()

    # ======================================================================= window
    def show_normal(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()
        w = self.tabs.currentWidget()
        if w is not None:
            self._mark_read(w.peer_id)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.ActivationChange and self.isActiveWindow():
            w = self.tabs.currentWidget()
            if w is not None and self.stack.currentIndex() == 1:
                self._mark_read(w.peer_id)

    def closeEvent(self, e):
        if self.quitting or not self.tray.isVisible():
            self.core.stop()
            e.accept()
            QApplication.quit()
            return
        e.ignore()
        self.hide()
        if not getattr(self, "_tray_hinted", False):
            self._tray_hinted = True
            self.tray.showMessage(APP_NAME, tr("tray_running"), app_icon(), 3000)

    def quit(self):
        self.quitting = True
        self.calls.hangup()
        self.core.stop()
        self.tray.hide()
        QApplication.quit()


def apply_autostart(enabled: bool):
    if sys.platform != "win32":
        return
    reg = QSettings(r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run", QSettings.Format.NativeFormat)
    if enabled:
        import os
        if getattr(sys, "frozen", False) or os.path.basename(sys.executable).lower() == "tda.exe":
            cmd = f'"{sys.executable}" --minimized'
        else:
            import os
            cmd = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}" --minimized'
        reg.setValue("TDA", cmd)
    else:
        reg.remove("TDA")
