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
from PySide6.QtGui import QAction, QFont, QPixmap
from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter, QStackedWidget,
                               QStatusBar, QSystemTrayIcon, QTabWidget, QToolBar, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import APP_NAME, APP_VERSION, branding, updates
from ..config import Settings
from ..history import History
from ..i18n import human_size, tr
from ..calls import CallController
from .. import groups as G
from ..network import NetworkCore, Peer
from .call_window import CallWindow
from .chat import IMAGE_EXT, ChatWidget, local_paths
from .dialogs import (BroadcastDialog, GroupDialog, HistorySearchDialog, SettingsDialog,
                      TransfersDialog, about_html, open_path)
from .theme import app_icon, draw_avatar, draw_logo, status_icon

STATUSES = ("available", "away", "busy")
OFFLINE_GROUP = "\x00offline"
GROUPS_HEAD = "\x00groups"
STATUS_RANK = {"": 0, "failed": 1, "queued": 2, "delivered": 3}


def is_group_key(key: str) -> bool:
    return key.startswith("g:")


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
        core.group_updated.connect(self.on_group_updated)
        core.group_removed.connect(self.on_group_removed)
        core.group_message_deleted.connect(self.on_group_message_deleted)
        core.message_deleted.connect(self.on_peer_message_deleted)
        core.reaction.connect(self.on_reaction)
        core.update_available.connect(self.on_update_available)
        core.update_progress.connect(self.on_update_progress)
        core.update_ready.connect(self.on_update_ready)
        core.update_failed.connect(self.on_update_failed)
        core.theme_applied.connect(self.on_theme_applied)
        self._update_target = ("", "")
        self.apply_appearance(render=False)
        self._tree_timer = QTimer(self, singleShot=True, interval=400)   # 1000 users: rebuild at most 2-3x/s
        self._tree_timer.timeout.connect(self.refresh_tree)

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
        act("👥", tr("new_group"), self.new_group)
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
        self.search.textChanged.connect(lambda _t: self.schedule_tree())
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

        # "a new version is available" bar (in-place update over the LAN)
        self.update_bar = QFrame(objectName="UpdateBar")
        self.update_bar.setStyleSheet("#UpdateBar{background:#FEF3C7;border-bottom:1px solid #F59E0B}")
        ub = QHBoxLayout(self.update_bar)
        ub.setContentsMargins(12, 6, 12, 6)
        self.update_lbl = QLabel()
        self.update_btn = QPushButton(tr("update_now"), objectName="Primary")
        self.update_btn.clicked.connect(self.start_update)
        later = QPushButton(tr("later"))
        later.clicked.connect(self.update_bar.hide)
        ub.addWidget(self.update_lbl, 1)
        ub.addWidget(self.update_btn)
        ub.addWidget(later)
        self.update_bar.hide()
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.update_bar)
        rl.addWidget(self.stack, 1)

        split = QSplitter()
        split.addWidget(side)
        split.addWidget(right)
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
        # only a custom welcome picture is shown; the logo stays as the app icon, not as a background
        self.welcome_img.setPixmap(pic if pic is not None else QPixmap())
        self.welcome_img.setVisible(pic is not None)
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

    def schedule_tree(self):
        if not self._tree_timer.isActive():
            self._tree_timer.start()

    def refresh_tree(self):
        self._tree_timer.stop()
        self.tree.setUpdatesEnabled(False)
        try:
            self._rebuild_tree()
        finally:
            self.tree.setUpdatesEnabled(True)

    def _rebuild_tree(self):
        q = self.search.text().strip().lower()
        expanded = {self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 1)
                    for i in range(self.tree.topLevelItemCount()) if not self.tree.topLevelItem(i).isExpanded()}
        selected = {it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()}
        self.tree.clear()
        # --- chat groups first
        grp_items = [(gid, g) for gid, g in self.core.groups.items() if not q or q in g["name"].lower()]
        if grp_items:
            head = QTreeWidgetItem([f"👥 {tr('groups')}  ({len(grp_items)})"])
            head.setData(0, Qt.ItemDataRole.UserRole + 1, GROUPS_HEAD)
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            head.setForeground(0, Qt.GlobalColor.darkGray)
            self.tree.addTopLevelItem(head)
            for gid, g in sorted(grp_items, key=lambda x: x[1]["name"].lower()):
                key = "g:" + gid
                n = self.unread.get(key, 0)
                online = sum(1 for m in g["members"] if m in self.core.peers)
                it = QTreeWidgetItem([f"{g['name']}  ({n})" if n else g["name"]])
                it.setIcon(0, status_icon("available" if online else "offline"))
                it.setData(0, Qt.ItemDataRole.UserRole, key)
                it.setToolTip(0, f"{g['name']}\n" + tr("group_members", n=len(g["members"]), online=online))
                if n:
                    fb = it.font(0)
                    fb.setBold(True)
                    it.setFont(0, fb)
                head.addChild(it)
            head.setExpanded(GROUPS_HEAD not in expanded)
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
        return [i for i in ids if i and not is_group_key(i) and (not online_only or i in self.core.peers)]

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
        if is_group_key(pid):
            m.addAction(tr("send_file"), lambda: self.open_chat(pid)._pick_files())
            m.addAction(tr("group_manage"), lambda: self.manage_group(pid))
            m.addSeparator()
            m.addAction(tr("clear_history"), lambda: self.clear_history(pid))
            m.exec(self.tree.viewport().mapToGlobal(pos))
            return
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
            if is_group_key(pid):
                name = self.core.groups.get(pid[2:], {}).get("name", "?")
            else:
                name = self.core.peers[pid].name if pid in self.core.peers else self.known.get(pid, {}).get("name", "?")
            chat = ChatWidget(pid, name, self.s.name, is_group=is_group_key(pid))
            chat.view.set_background(self.s.chat_bg, self.s.chat_bg_image, self.s.chat_bg_opacity)
            chat.manage_group.connect(self.manage_group)
            chat.send_text.connect(self.send_text)
            chat.send_paths.connect(self.send_paths)
            chat.start_call.connect(self.start_call)
            chat.transfer_action.connect(self.transfer_action)
            chat.my_id = self.s.user_id
            chat.message_action.connect(lambda a, m, x, k=pid: self.on_message_action(k, a, m, x))
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
        if is_group_key(pid):
            g = self.core.groups.get(pid[2:])
            if g:
                online = sum(1 for m in g["members"] if m in self.core.peers)
                chat.set_group(g["name"], len(g["members"]), online)
                me = self.s.user_id
                reason = ""
                if not self.core.can(g["gid"], "write"):
                    reason = tr("frozen_admins_only") if g["settings"].get("send") == "admins" else tr("frozen_you")
                chat.set_permissions(self.core.can(g["gid"], "write"), self.core.can(g["gid"], "media"),
                                     reason, admin=self.core.my_role(g["gid"]) in ("owner", "admin"))
                i = self.tabs.indexOf(chat)
                n = self.unread.get(pid, 0)
                self.tabs.setTabText(i, f"👥 {g['name']} ({n})" if n else f"👥 {g['name']}")
                self.tabs.setTabIcon(i, status_icon("available" if online else "offline"))
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
            self.schedule_tree()

    def clear_history(self, pid):
        self.history.clear(pid)
        if pid in self.chats:
            self.chats[pid].load([])

    # ======================================================================= sending
    def send_text(self, pid: str, text: str, multi=False, fwd=False):
        mid = uuid.uuid4().hex
        reply = self.chats[pid].take_reply() if (pid in self.chats and not fwd and not multi) else None
        extra = {k: v for k, v in (("reply", reply), ("fwd", fwd), ("sender", self.s.user_id)) if v}
        item = {"id": mid, "outgoing": 1, "text": text, "ts": time.time(), "status": "", "multi": multi,
                "kind": "msg", "peer_name": self.s.name, "extra": extra}
        name = self.core.peers[pid].name if pid in self.core.peers else self.known.get(pid, {}).get("name", "")
        self.history.add(mid, pid, name, True, text, item["ts"], "", multi, extra=extra)
        if pid in self.chats:
            self.chats[pid].add(item)
        if is_group_key(pid):
            self.core.send_group_message(pid[2:], text, msg_id=mid, reply=reply, fwd=fwd)
        else:
            self.core.send_message(pid, text, multi=multi, msg_id=mid, reply=reply, fwd=fwd)   # queued if offline

    def send_paths(self, pid: str, paths: list):
        if is_group_key(pid):
            tids = self.core.offer_group_files(pid[2:], paths)
            if tids:
                t = self.core.transfers[tids[0]]
                title = t.title if not t.title.isdigit() else tr("files_n", n=t.title)
                self.open_chat(pid)
                self._sys_line(pid, tr("group_sent_files", title=title, size=human_size(t.total)))
            return
        self.open_chat(pid)
        # works for offline users too: the offer waits in the outbox until they connect
        self.core.offer_files(pid, paths, peer_name=self.known.get(pid, {}).get("name", ""))

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
        k = self.known.get(p.id)
        if not k or k.get("name") != p.name or k.get("group") != p.group:
            self.known[p.id] = {"id": p.id, "name": p.name, "group": p.group}
            self.history.remember_contact(p.id, p.name, p.group)
        self._update_chat_peer(p.id)
        self.schedule_tree()

    def on_peer_removed(self, pid):
        self._update_chat_peer(pid)
        self.schedule_tree()

    # ---- groups
    def _people(self) -> dict:
        people = {pid: (c.get("name", "?"), c.get("group", "")) for pid, c in self.known.items()}
        people.update({pid: (p.name, p.group) for pid, p in self.core.peers.items()})
        return people

    def new_group(self):
        dlg = GroupDialog(self._people(), set(self.core.peers), my_id=self.s.user_id, parent=self)
        if dlg.exec():
            gid = self.core.create_group(dlg.name.text(), dlg.members())
            self.open_chat("g:" + gid)
            self._sys_line("g:" + gid, tr("group_created", name=self.s.name))

    def manage_group(self, key: str):
        from .group_info import GroupInfoDialog
        gid = key[2:] if is_group_key(key) else key
        if gid not in self.core.groups:
            return
        GroupInfoDialog(self.core, gid, self._people(), start_call=self.start_call,
                        open_chat=self.open_chat, parent=self).exec()

    def on_group_message_deleted(self, gid, msg_id, by):
        g = self.core.groups.get(gid)
        if by != self.s.user_id and not (g and G.is_admin(g, by)):
            if self.history.get_extra(msg_id).get("sender") != by:
                return                      # a member may only delete his own messages
        self._mark_deleted("g:" + gid, msg_id)

    def on_peer_message_deleted(self, sender, msg_id):
        row = self.history.get(msg_id)
        if row and row["peer_id"] == sender and not row["outgoing"]:
            self._mark_deleted(sender, msg_id)

    def _mark_deleted(self, key, msg_id):
        self.history.set_kind(msg_id, "deleted")
        self.history.set_extra(msg_id, {})
        chat = self.chats.get(key)
        if chat:
            for it in chat.items:
                if it.get("id") == msg_id:
                    it["kind"], it["extra"] = "deleted", {}
            chat.schedule_render()

    # ======================================================================= message menu actions
    def on_message_action(self, key, action, mid, arg):
        chat = self.chats.get(key)
        it = chat.item(mid) if chat else None
        if it is None:
            return
        if action == "react":
            ex = dict(it.get("extra") or {})
            r = dict(ex.get("reactions") or {})
            if arg:
                r[self.s.user_id] = {"e": arg, "n": self.s.name}
            else:
                r.pop(self.s.user_id, None)
            ex["reactions"] = r
            self.history.set_extra(mid, ex)
            chat.update_extra(mid, ex)
            self.core.react(key, mid, arg)
        elif action == "star":
            ex = dict(it.get("extra") or {})
            ex["star"] = arg == "1"
            self.history.set_extra(mid, ex)
            chat.update_extra(mid, ex)
        elif action == "delete_me":
            if QMessageBox.question(self, APP_NAME, tr("delete_me_confirm")) == QMessageBox.StandardButton.Yes:
                self.history.delete(mid)
                chat.remove_item(mid)
        elif action == "delete_all":
            if QMessageBox.question(self, APP_NAME, tr("delete_all_confirm")) != QMessageBox.StandardButton.Yes:
                return
            own = bool(it.get("outgoing"))
            if self.core.delete_message(key, mid, own=own) and not is_group_key(key):
                self._mark_deleted(key, mid)
        elif action == "forward":
            self.forward(chat, it)
        elif action == "download":
            self.download(it)

    def forward(self, chat, it):
        from PySide6.QtWidgets import QDialog, QListWidget, QListWidgetItem, QVBoxLayout
        targets = []
        for gid, g in self.core.groups.items():
            if self.core.can(gid, "write"):
                targets.append(("g:" + gid, "👥 " + g["name"], True))
        seen = set()
        for p in sorted(self.core.peers.values(), key=lambda p: p.name.lower()):
            targets.append((p.id, f"{p.name}   —   {p.group}", True))
            seen.add(p.id)
        for c in sorted(self.known.values(), key=lambda c: (c.get("name") or "").lower()):
            if c["id"] not in seen and c["id"] != self.s.user_id:
                targets.append((c["id"], f'{c.get("name", "?")}   ({tr("status_offline")})', False))
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("forward_title"))
        dlg.resize(420, 480)
        lst = QListWidget()
        for key, label, online in targets:
            x = QListWidgetItem(status_icon("available" if online else "offline"), label)
            x.setData(Qt.ItemDataRole.UserRole, key)
            x.setCheckState(Qt.CheckState.Unchecked)
            lst.addItem(x)
        ok = QPushButton(tr("send"), objectName="Primary")
        ok.clicked.connect(dlg.accept)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(f"<b>{tr('forward_title')}</b>  <span style='color:#6B7280'>"
                           f"{chat.snippet(it)[:60]}</span>"))
        v.addWidget(lst, 1)
        v.addWidget(ok)
        if not dlg.exec():
            return
        keys = [lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())
                if lst.item(i).checkState() == Qt.CheckState.Checked]
        if not keys:
            return
        if it.get("kind") == "file":
            path = chat.file_path(it)
            if not path or not os.path.exists(path):
                QMessageBox.information(self, APP_NAME, tr("file_not_ready"))
                return
            for k in keys:
                self.send_paths(k, [path])
        else:
            for k in keys:
                self.send_text(k, it.get("text") or "", fwd=True)
        self.statusBar().showMessage(tr("forward_done", n=len(keys)), 4000)

    def download(self, it):
        import shutil
        from PySide6.QtWidgets import QFileDialog
        t = self.core.transfers.get(it["id"])
        if t and t.direction == "in" and t.state == "offered":
            self.core.accept_transfer(t.tid)
            return
        path = ChatWidget.file_path(it)
        if not path or not os.path.exists(path):
            QMessageBox.information(self, APP_NAME, tr("file_not_ready"))
            return
        if os.path.isdir(path):
            dest = QFileDialog.getExistingDirectory(self, tr("download"))
            if dest:
                shutil.copytree(path, os.path.join(dest, os.path.basename(path)), dirs_exist_ok=True)
            return
        dest, _ = QFileDialog.getSaveFileName(self, tr("download"),
                                              os.path.join(os.path.expanduser("~"), os.path.basename(path)))
        if dest:
            try:
                shutil.copy2(path, dest)
            except OSError as e:
                QMessageBox.warning(self, APP_NAME, str(e))

    def on_reaction(self, r: dict):
        key = "g:" + r["gid"] if r["gid"] else r["from"]
        mid = r["msg_id"]
        row = self.history.get(mid)
        if not row or row["peer_id"] != key:
            return
        ex = self.history.get_extra(mid)
        rx = dict(ex.get("reactions") or {})
        if r["emoji"]:
            rx[r["from"]] = {"e": r["emoji"], "n": r["from_name"]}
        else:
            rx.pop(r["from"], None)
        ex["reactions"] = rx
        self.history.set_extra(mid, ex)
        chat = self.chats.get(key)
        if chat:
            chat.update_extra(mid, ex)
        if r["emoji"] and row["outgoing"]:
            visible = chat is not None and self.isActiveWindow() and self.tabs.currentWidget() is chat
            if not visible:
                self._alert(APP_NAME, tr("reacted", name=r["from_name"], e=r["emoji"]))

    def on_group_updated(self, gid):
        self._update_chat_peer("g:" + gid)
        self.schedule_tree()

    def on_group_removed(self, gid):
        key = "g:" + gid
        chat = self.chats.get(key)
        if chat is not None:
            self._close_tab(self.tabs.indexOf(chat))
        self.schedule_tree()

    def on_message(self, m: dict):
        sender = m["from"]
        if sender not in self.known:
            self.known[sender] = {"id": sender, "name": m["from_name"], "group": ""}
        pid = "g:" + m["gid"] if m.get("gid") else sender
        chat = self.open_chat(pid, focus=False)   # loads history first, then we append
        if chat.has_item(m["id"]):
            return                                  # duplicate (re-delivered after a lost ack)
        extra = {k: v for k, v in (("reply", m.get("reply")), ("fwd", m.get("fwd")), ("sender", sender)) if v}
        self.history.add(m["id"], pid, m["from_name"], False, m["text"], m["ts"], "", m["multi"], extra=extra)
        chat.add({"id": m["id"], "outgoing": 0, "text": m["text"], "ts": m["ts"], "multi": m["multi"],
                  "kind": "msg", "peer_name": m["from_name"], "extra": extra})
        visible = self.isActiveWindow() and self.tabs.currentWidget() is chat and self.stack.currentIndex() == 1
        if self.tabs.count() == 1 and not self.isVisible():
            self.tabs.setCurrentWidget(chat)
        if not visible:
            self.unread[pid] = self.unread.get(pid, 0) + 1
            self._update_chat_peer(pid)
            self.schedule_tree()
            self._alert(tr("new_message_from", name=m["from_name"]), m["text"][:200])

    def on_message_status(self, mid, status, _peer):
        # group messages report once per member: keep the best state reached so far
        for c in self.chats.values():
            for it in c.items:
                if it.get("id") == mid:
                    if STATUS_RANK.get(status, 0) > STATUS_RANK.get(it.get("status", ""), 0):
                        c.set_status(mid, status)
                        self.history.set_status(mid, status)
                    return
        self.history.set_status(mid, status)

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

    def _transfer_key(self, t) -> str:
        return "g:" + t.gid if t.gid else t.peer_id

    def on_transfer_added(self, tid):
        t = self.core.transfers[tid]
        if t.purpose or (t.gid and t.direction == "out"):
            return          # one summary line in the group chat instead of a card per member
        ts = time.time()
        key = self._transfer_key(t)
        self.history.add(tid, key, t.peer_name, t.direction == "out", self._card_json(t), ts, "", False, "file")
        chat = self.open_chat(key, focus=t.direction == "out")
        if not chat.has_item(tid):
            chat.add({"id": tid, "kind": "file", "outgoing": t.direction == "out", "text": self._card_json(t),
                      "ts": ts, "peer_name": t.peer_name})
        if t.direction == "in" and self.s.auto_images and t.total <= 25 * 1024 * 1024 and all(
                os.path.splitext(f["rel"])[1].lower() in IMAGE_EXT and "/" not in f["rel"] for f in t.files):
            self.core.accept_transfer(tid)          # pictures download by themselves, like WhatsApp
        if t.direction == "in":
            title = t.title if not t.title.isdigit() else tr("files_n", n=t.title)
            msg = tr("incoming_files", name=t.peer_name, title=title, size=human_size(t.total))
            visible = self.isActiveWindow() and self.tabs.currentWidget() is chat
            if not visible:
                self.unread[key] = self.unread.get(key, 0) + 1
                self._update_chat_peer(key)
                self.schedule_tree()
            self._alert(tr("transfers"), msg)

    def on_transfer_changed(self, tid):
        t = self.core.transfers.get(tid)
        if not t or t.purpose or (t.gid and t.direction == "out"):
            return
        chat = self.chats.get(self._transfer_key(t))
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
        if action == "delmsg":
            chat = self.tabs.currentWidget()
            if isinstance(chat, ChatWidget) and is_group_key(chat.peer_id):
                if QMessageBox.question(self, APP_NAME, tr("delete_for_all")) == QMessageBox.StandardButton.Yes:
                    self.core.delete_group_message(chat.peer_id[2:], tid)
            return
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
    def start_call(self, pid, gid=""):
        if self.calls.state != "idle":
            QMessageBox.information(self, APP_NAME, tr("call_busy_now"))
            return
        if gid and not self.core.can(gid, "call"):
            QMessageBox.information(self, APP_NAME, tr("call_log_restricted"))
            return
        if self.calls.start_call(pid, gid=gid):
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
            self.schedule_tree()
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
        dlg = SettingsDialog(self.s, self, core=self.core)
        dlg.branding_changed.connect(self.apply_appearance)
        dlg.update_requested.connect(lambda: self.check_updates(dlg))
        dlg.install_file.connect(lambda path: self.install_update(path, "", dlg))
        if not dlg.exec():
            return
        restart = dlg.apply()
        apply_autostart(self.s.autostart)
        self.me_name.setText(self.s.name)
        self.avatar.setPixmap(draw_avatar(self.s.name, 42))
        self.me_group.setText(self.s.group)
        self.lbl_sec.setText("🔒 AES-256" if self.s.password else "🔓 " + ("بدون تشفير" if self.s.language == "ar" else "Not encrypted"))
        self.core.apply_settings()
        self.apply_appearance()
        if restart:
            QMessageBox.information(self, APP_NAME, tr("restart_needed"))

    # ======================================================================= appearance
    def apply_appearance(self, render=True):
        s = self.s
        ChatWidget.set_appearance(s.bubble_me, s.bubble_them, s.font_pt, s.bubble_border)
        self.setWindowTitle(self.app_title())
        if render:
            self.apply_branding()
        for chat in self.chats.values():
            chat.view.set_background(s.chat_bg, s.chat_bg_image, s.chat_bg_opacity)
            if render:
                chat.schedule_render()

    def on_theme_applied(self, _theme):
        self.apply_appearance()
        if self.tray.isVisible():
            self.tray.showMessage(self.app_title(), tr("theme_received"), app_icon(), 4000)

    # ======================================================================= updates (over the LAN)
    def on_update_available(self, version, pid):
        if not self.s.update_auto or self._update_target[0]:
            return
        if updates.newer(self._update_target[1] or "0", version):
            return
        p = self.core.peers.get(pid)
        self._update_target = ("", version)
        self.update_lbl.setText(tr("update_banner", v=version, name=p.name if p else "?"))
        self.update_btn.setEnabled(True)
        self.update_bar.show()

    def start_update(self, pid=None):
        src = self.core.peers.get(pid) if pid else self.core.best_update_source()
        if src is None:
            self.update_bar.hide()
            return
        if sys.platform != "win32":
            QMessageBox.information(self, APP_NAME, tr("update_windows_only"))
            return
        self._update_target = (src.id, src.version)
        self.update_btn.setEnabled(False)
        self.update_lbl.setText(tr("update_downloading", v=src.version, p=0))
        self.update_bar.show()
        if not self.core.request_update(src.id):
            self.on_update_failed("offline")

    def on_update_progress(self, done, total):
        v = self._update_target[1]
        self.update_lbl.setText(tr("update_downloading", v=v, p=int(100 * done / total) if total else 0))

    def on_update_failed(self, err):
        self._update_target = ("", self._update_target[1])
        self.update_btn.setEnabled(True)
        self.update_lbl.setText(tr("update_failed", e=err))
        self.update_bar.show()

    def on_update_ready(self, path, version):
        self.update_bar.hide()
        self.install_update(path, version or self._update_target[1])
        self._update_target = ("", self._update_target[1])

    def install_update(self, path, version="", parent=None):
        if sys.platform != "win32":
            QMessageBox.information(parent or self, APP_NAME, tr("update_windows_only"))
            return
        if QMessageBox.question(parent or self, APP_NAME, tr("update_ready", v=version or "")) \
                != QMessageBox.StandardButton.Yes:
            return
        if updates.run_installer(path, silent=True):
            self.tray.showMessage(APP_NAME, tr("update_started"), app_icon(), 3000)
            if parent is not None:
                parent.reject()
            QTimer.singleShot(800, self.quit)      # the installer also closes TDA if it is still running
        else:
            QMessageBox.warning(parent or self, APP_NAME, tr("update_failed", e="UAC"))

    def check_updates(self, parent=None):
        src = self.core.best_update_source()
        if src is None:
            QMessageBox.information(parent or self, APP_NAME, tr("update_none", v=APP_VERSION))
            return
        if parent is not None:
            parent.reject()
        self.start_update(src.id)

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
