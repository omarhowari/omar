"""Group info & administration window (WhatsApp / Telegram style)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from .. import APP_NAME
from .. import groups as G
from ..i18n import tr
from .theme import status_icon


class GroupInfoDialog(QDialog):
    def __init__(self, core, gid: str, people: dict, start_call=None, open_chat=None, parent=None):
        super().__init__(parent)
        self.core, self.gid, self.people = core, gid, people
        self.start_call, self.open_chat = start_call, open_chat
        self.me = core.settings.user_id
        self.setWindowTitle(tr("group_info"))
        self.resize(560, 680)

        self.name = QLineEdit()
        self.desc = QPlainTextEdit()
        self.desc.setFixedHeight(64)
        self.desc.setPlaceholderText(tr("group_desc"))
        self.save_info = QPushButton(tr("save"), objectName="Primary")
        self.save_info.clicked.connect(self._save_info)
        info = QGroupBox(tr("group_name"))
        fl = QVBoxLayout(info)
        fl.addWidget(self.name)
        fl.addWidget(self.desc)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.save_info)
        fl.addLayout(row)

        self.count = QLabel()
        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._member_menu)
        self.list.itemDoubleClicked.connect(lambda it: self._member_menu_at(it))
        self.add_btn = QPushButton("➕  " + tr("group_add_members"))
        self.add_btn.clicked.connect(self._add_members)
        hint = QLabel(tr("group_member_hint"), objectName="Muted", wordWrap=True)
        members = QGroupBox(tr("group_choose_members"))
        ml = QVBoxLayout(members)
        top = QHBoxLayout()
        top.addWidget(self.count, 1)
        top.addWidget(self.add_btn)
        ml.addLayout(top)
        ml.addWidget(self.list, 1)
        ml.addWidget(hint)

        # group-wide settings (admins)
        self.settings_box = QGroupBox(tr("group_settings"))
        sf = QFormLayout(self.settings_box)
        self.set_send = self._combo()
        self.set_edit = self._combo()
        self.set_add = self._combo()
        sf.addRow(tr("perm_send"), self.set_send)
        sf.addRow(tr("perm_edit"), self.set_edit)
        sf.addRow(tr("perm_add"), self.set_add)
        for key, box in (("send", self.set_send), ("edit", self.set_edit), ("add", self.set_add)):
            box.currentIndexChanged.connect(lambda _i, k=key, b=box: self._set_setting(k, b.currentData()))

        leave = QPushButton(tr("group_leave"))
        leave.setStyleSheet("color:#B91C1C")
        leave.clicked.connect(self._leave)
        close = QPushButton(tr("close_tab"))
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addWidget(leave)
        bottom.addStretch(1)
        bottom.addWidget(close)

        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(members, 1)
        lay.addWidget(self.settings_box)
        lay.addLayout(bottom)
        core.group_updated.connect(self._on_update)
        core.group_removed.connect(lambda g: self.reject() if g == self.gid else None)
        self.refresh()

    def _combo(self):
        c = QComboBox()
        c.addItem(tr("perm_all"), "all")
        c.addItem(tr("perm_admins"), "admins")
        return c

    @property
    def g(self):
        return self.core.groups.get(self.gid)

    def _on_update(self, gid):
        if gid == self.gid:
            self.refresh()

    def refresh(self):
        g = self.g
        if not g:
            return
        admin = G.is_admin(g, self.me)
        can_edit = G.can(g, self.me, "edit")
        self.name.setText(g["name"])
        if self.desc.toPlainText() != g.get("desc", ""):
            self.desc.setPlainText(g.get("desc", ""))
        for w in (self.name, self.desc):
            w.setReadOnly(not can_edit)
        self.save_info.setVisible(can_edit)
        self.add_btn.setVisible(G.can(g, self.me, "add"))
        self.settings_box.setEnabled(admin)
        for key, box in (("send", self.set_send), ("edit", self.set_edit), ("add", self.set_add)):
            box.blockSignals(True)
            box.setCurrentIndex(box.findData(g["settings"].get(key, "all")))
            box.blockSignals(False)
        online = sum(1 for m in g["members"] if m in self.core.peers)
        self.count.setText(tr("group_members", n=len(g["members"]), online=online))
        self.list.clear()
        order = {"owner": 0, "admin": 1, "member": 2}
        for uid, name in sorted(g["members"].items(), key=lambda kv: (order.get(G.role(g, kv[0]), 3), kv[1].lower())):
            r = G.role(g, uid)
            badges = []
            if r == "owner":
                badges.append("👑 " + tr("role_owner"))
            elif r == "admin":
                badges.append("⭐ " + tr("role_admin"))
            blocked = g["restricted"].get(uid, {})
            if blocked.get("write"):
                badges.append("🔇 " + tr("perm_write"))
            if blocked.get("media"):
                badges.append("🚫 " + tr("perm_media"))
            if blocked.get("call"):
                badges.append("📵 " + tr("perm_call"))
            label = (tr("me") + " — " if uid == self.me else "") + name
            if badges:
                label += "    " + "  ·  ".join(badges)
            it = QListWidgetItem(status_icon("available" if uid in self.core.peers else "offline"), label)
            it.setData(Qt.ItemDataRole.UserRole, uid)
            self.list.addItem(it)

    # ---------------------------------------------------------------- actions
    def _save_info(self):
        if not self.core.update_group(self.gid, name=self.name.text(), desc=self.desc.toPlainText()):
            self.refresh()

    def _set_setting(self, key, value):
        self.core.update_group(self.gid, settings={key: value})

    def _member_menu(self, pos):
        it = self.list.itemAt(pos)
        if it:
            self._member_menu_at(it, self.list.viewport().mapToGlobal(pos))

    def _member_menu_at(self, it, gpos=None):
        from PySide6.QtGui import QCursor
        g = self.g
        uid = it.data(Qt.ItemDataRole.UserRole)
        if not g or uid == self.me:
            return
        m = QMenu(self)
        name = g["members"].get(uid, "?")
        if self.open_chat:
            m.addAction("💬  " + tr("private_message"), lambda: (self.open_chat(uid), self.accept()))
        if self.start_call and uid in self.core.peers:
            a = m.addAction("📞  " + tr("call_btn"), lambda: self.start_call(uid, self.gid))
            a.setEnabled(G.can(g, self.me, "call"))
        if G.is_admin(g, self.me) and G.role(g, uid) != "owner":
            m.addSeparator()
            mine_owner = G.role(g, self.me) == "owner"
            if G.role(g, uid) == "admin":
                a = m.addAction("⭐  " + tr("demote_admin"), lambda: self.core.update_group(self.gid, admins_remove=[uid]))
                a.setEnabled(mine_owner)
            else:
                m.addAction("⭐  " + tr("make_admin"), lambda: self.core.update_group(self.gid, admins_add=[uid]))
            if G.role(g, uid) == "member":
                blocked = dict(g["restricted"].get(uid, {}))
                for key, label in (("write", tr("block_write")), ("media", tr("block_media")),
                                   ("call", tr("block_call"))):
                    act = m.addAction(label)
                    act.setCheckable(True)
                    act.setChecked(bool(blocked.get(key)))
                    act.toggled.connect(lambda on, k=key, b=blocked: self._restrict(uid, b, k, on))
            m.addSeparator()
            m.addAction("🚪  " + tr("remove_member"), lambda: self._remove(uid, name))
            if mine_owner:
                m.addAction("👑  " + tr("transfer_owner"), lambda: self._transfer(uid, name))
        m.exec(gpos or QCursor.pos())

    def _restrict(self, uid, blocked, key, on):
        flags = {k: bool(blocked.get(k)) for k in G.RESTRICTIONS}
        flags[key] = on
        self.core.update_group(self.gid, restrict={uid: flags})

    def _remove(self, uid, name):
        if QMessageBox.question(self, APP_NAME, tr("remove_member_confirm", name=name)) == QMessageBox.StandardButton.Yes:
            self.core.update_group(self.gid, remove=[uid])

    def _transfer(self, uid, name):
        if QMessageBox.question(self, APP_NAME, tr("transfer_owner_confirm", name=name)) == QMessageBox.StandardButton.Yes:
            self.core.update_group(self.gid, owner=uid, admins_add=[uid])

    def _add_members(self):
        from .dialogs import GroupDialog
        g = self.g
        people = {pid: v for pid, v in self.people.items() if pid not in g["members"]}
        dlg = GroupDialog(people, set(self.core.peers), my_id=self.me, parent=self)
        dlg.name.setText(g["name"])
        dlg.name.setReadOnly(True)
        if dlg.exec():
            self.core.update_group(self.gid, add=dlg.members())

    def _leave(self):
        if QMessageBox.question(self, APP_NAME, tr("group_leave_confirm", name=self.g["name"])) == QMessageBox.StandardButton.Yes:
            self.core.leave_group(self.gid)
            self.accept()
