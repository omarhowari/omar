"""Settings, broadcast, transfers and history-search windows."""
from __future__ import annotations

import os
import sys
from datetime import datetime

import time

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QMessageBox,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from .. import APP_NAME, APP_VERSION, branding
from ..config import Settings
from ..i18n import human_size, tr
from .theme import draw_logo, status_icon


def open_path(path: str):
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# ============================================================================ settings
class SettingsDialog(QDialog):
    branding_changed = Signal()

    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.s = s
        self.setWindowTitle(tr("settings"))
        self.setMinimumWidth(520)

        self.name = QLineEdit(s.name)
        self.group = QLineEdit(s.group)
        self.lang = QComboBox()
        self.lang.addItem("العربية", "ar")
        self.lang.addItem("English", "en")
        self.lang.setCurrentIndex(0 if s.language == "ar" else 1)

        self.dl = QLineEdit(s.download_dir)
        b = QPushButton(tr("browse"))
        b.clicked.connect(self._browse)
        dl_row = QHBoxLayout()
        dl_row.addWidget(self.dl, 1)
        dl_row.addWidget(b)

        self.pw = QLineEdit(s.password)
        self.pw.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.hosts = QPlainTextEdit("\n".join(s.extra_hosts))
        self.hosts.setFixedHeight(70)
        self.udp = QSpinBox(minimum=1024, maximum=65535, value=s.udp_port)
        self.tcp = QSpinBox(minimum=1024, maximum=65535, value=s.tcp_port)
        ports = QHBoxLayout()
        ports.addWidget(self.udp)
        ports.addWidget(self.tcp)
        self.away = QSpinBox(minimum=0, maximum=240, value=s.auto_away_minutes)
        self.notify = QCheckBox(tr("notify"), checked=s.notify)
        self.sound = QCheckBox(tr("sound"), checked=s.sound)
        self.minimized = QCheckBox(tr("start_minimized"), checked=s.start_minimized)
        self.autostart = QCheckBox(tr("autostart"), checked=s.autostart)
        self.autostart.setEnabled(sys.platform == "win32")

        g1 = QGroupBox(tr("user"))
        f1 = QFormLayout(g1)
        f1.addRow(tr("name"), self.name)
        f1.addRow(tr("group"), self.group)
        f1.addRow(tr("language"), self.lang)
        f1.addRow(tr("download_dir"), dl_row)

        g2 = QGroupBox("Network")
        f2 = QFormLayout(g2)
        f2.addRow(tr("password"), self.pw)
        hint = QLabel(tr("password_hint"), objectName="Muted", wordWrap=True)
        f2.addRow("", hint)
        f2.addRow(tr("extra_hosts"), self.hosts)
        f2.addRow("", QLabel(tr("extra_hosts_hint"), objectName="Muted", wordWrap=True))
        f2.addRow(tr("ports"), ports)

        g3 = QGroupBox(tr("system"))
        f3 = QFormLayout(g3)
        f3.addRow(tr("auto_away"), self.away)
        f3.addRow(self.notify)
        f3.addRow(self.sound)
        f3.addRow(self.minimized)
        f3.addRow(self.autostart)

        g4 = QGroupBox(tr("branding"))
        f4 = QHBoxLayout(g4)
        brand_btn = QPushButton(tr("branding_btn"))
        brand_btn.clicked.connect(self._open_branding)
        f4.addWidget(brand_btn)
        f4.addWidget(QLabel(tr("branding_hint"), objectName="Muted"), 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("ok"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        for w in (g1, g2, g3, g4):
            lay.addWidget(w)
        lay.addWidget(bb)

    def _open_branding(self):
        if not admin_unlock(self.s, self):
            return
        dlg = BrandingDialog(self.s, self)
        if dlg.exec():
            self.branding_changed.emit()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("download_dir"), self.dl.text())
        if d:
            self.dl.setText(d)

    def apply(self) -> bool:
        """Write values into settings. Returns True if a restart is needed."""
        s = self.s
        restart = (s.language != self.lang.currentData() or s.udp_port != self.udp.value()
                   or s.tcp_port != self.tcp.value())
        s.name = self.name.text().strip()[:64] or s.name
        s.group = self.group.text().strip()[:64] or "General"
        s.language = self.lang.currentData()
        s.download_dir = self.dl.text().strip() or s.download_dir
        s.password = self.pw.text()
        s.extra_hosts = [h.strip() for h in self.hosts.toPlainText().splitlines() if h.strip()]
        s.udp_port, s.tcp_port = self.udp.value(), self.tcp.value()
        s.auto_away_minutes = self.away.value()
        s.notify, s.sound = self.notify.isChecked(), self.sound.isChecked()
        s.start_minimized = self.minimized.isChecked()
        s.autostart = self.autostart.isChecked()
        s.save()
        return restart


# ============================================================================ admin password + branding
_failed: list = []


def _ask_password(parent, label: str) -> str | None:
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(tr("branding"))
    dlg.setLabelText(label)
    dlg.setTextEchoMode(QLineEdit.EchoMode.Password)
    dlg.setOkButtonText(tr("ok"))
    dlg.setCancelButtonText(tr("cancel"))
    return dlg.textValue() if dlg.exec() else None


def _create_password(s: Settings, parent, title_key="admin_pw_create_text") -> bool:
    while True:
        pw = _ask_password(parent, tr(title_key))
        if pw is None:
            return False
        if len(pw) < 4:
            QMessageBox.warning(parent, APP_NAME, tr("admin_pw_short"))
            continue
        again = _ask_password(parent, tr("admin_pw_confirm"))
        if again is None:
            return False
        if again != pw:
            QMessageBox.warning(parent, APP_NAME, tr("admin_pw_mismatch"))
            continue
        branding.set_admin_password(s, pw)
        QMessageBox.information(parent, APP_NAME, tr("admin_pw_saved"))
        return True


def admin_unlock(s: Settings, parent) -> bool:
    """First use: create the admin password. Afterwards: ask for it (5 tries, then 60 s lock)."""
    if not branding.has_admin_password(s):
        return _create_password(s, parent)
    now = time.time()
    _failed[:] = [t for t in _failed if now - t < 60]
    if len(_failed) >= 5:
        QMessageBox.warning(parent, APP_NAME, tr("admin_locked"))
        return False
    pw = _ask_password(parent, tr("admin_pw_enter"))
    if pw is None:
        return False
    if branding.check_admin_password(s, pw):
        _failed.clear()
        return True
    _failed.append(now)
    QMessageBox.warning(parent, APP_NAME, tr("admin_pw_wrong"))
    return False


class BrandingDialog(QDialog):
    """Logo, welcome picture and displayed name. Changes are applied on OK."""

    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.s = s
        self.new_logo: str | None = None      # path chosen, "" = restore default, None = unchanged
        self.new_welcome: str | None = None
        self.setWindowTitle(tr("branding"))
        self.setMinimumWidth(560)

        # logo
        self.logo_prev = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.logo_prev.setFixedSize(110, 110)
        self.logo_prev.setStyleSheet("background:white;border:1px solid #E5E7EB;border-radius:8px")
        b1 = QPushButton(tr("choose_image"), objectName="Primary")
        b1.clicked.connect(self._pick_logo)
        r1 = QPushButton(tr("restore_default"))
        r1.clicked.connect(lambda: self._set_logo(""))
        col1 = QVBoxLayout()
        col1.addWidget(QLabel(tr("logo_hint"), objectName="Muted", wordWrap=True))
        row = QHBoxLayout()
        row.addWidget(b1)
        row.addWidget(r1)
        row.addStretch(1)
        col1.addLayout(row)
        col1.addStretch(1)
        g1 = QGroupBox(tr("logo"))
        h1 = QHBoxLayout(g1)
        h1.addWidget(self.logo_prev)
        h1.addLayout(col1, 1)

        # welcome picture
        self.wel_prev = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.wel_prev.setFixedSize(200, 120)
        self.wel_prev.setStyleSheet("background:white;border:1px solid #E5E7EB;border-radius:8px")
        b2 = QPushButton(tr("choose_image"), objectName="Primary")
        b2.clicked.connect(self._pick_welcome)
        r2 = QPushButton(tr("restore_default"))
        r2.clicked.connect(lambda: self._set_welcome(""))
        col2 = QVBoxLayout()
        row2 = QHBoxLayout()
        row2.addWidget(b2)
        row2.addWidget(r2)
        row2.addStretch(1)
        col2.addLayout(row2)
        col2.addStretch(1)
        g2 = QGroupBox(tr("welcome_image"))
        h2 = QHBoxLayout(g2)
        h2.addWidget(self.wel_prev)
        h2.addLayout(col2, 1)

        # name + admin password
        self.title = QLineEdit(s.app_title, placeholderText=f"{tr('default')}  {tr('app_title')}")
        g3 = QGroupBox(tr("app_name_shown"))
        f3 = QVBoxLayout(g3)
        f3.addWidget(self.title)
        chg = QPushButton(tr("admin_pw_change"))
        chg.clicked.connect(lambda: _create_password(self.s, self, "admin_pw_new"))

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("ok"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(chg)
        bottom.addStretch(1)
        bottom.addWidget(bb)

        lay = QVBoxLayout(self)
        lay.addWidget(g1)
        lay.addWidget(g2)
        lay.addWidget(g3)
        lay.addLayout(bottom)
        self._refresh()

    # previews -------------------------------------------------------------
    def _refresh(self):
        from PySide6.QtGui import QPixmap
        if self.new_logo:
            pm = QPixmap(self.new_logo)
        elif self.new_logo == "":
            pm = None
        else:
            pm = branding.custom_logo()
        if pm is None or pm.isNull():
            pm = draw_logo(96, allow_custom=False)
        self.logo_prev.setPixmap(pm.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        if self.new_welcome:
            wp = QPixmap(self.new_welcome)
        elif self.new_welcome == "":
            wp = None
        else:
            wp = branding.custom_welcome()
        if wp is None or wp.isNull():
            self.wel_prev.setPixmap(QPixmap())
            self.wel_prev.setText(tr("default"))
        else:
            self.wel_prev.setPixmap(wp.scaled(190, 110, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _choose(self) -> str | None:
        path, _ = QFileDialog.getOpenFileName(self, tr("choose_image"), "",
                                              f"{tr('images')} (*.png *.jpg *.jpeg *.bmp *.gif *.ico *.webp)")
        if not path:
            return None
        from PySide6.QtGui import QImage
        if QImage(path).isNull():
            QMessageBox.warning(self, APP_NAME, tr("bad_image"))
            return None
        return path

    def _pick_logo(self):
        p = self._choose()
        if p:
            self._set_logo(p)

    def _pick_welcome(self):
        p = self._choose()
        if p:
            self._set_welcome(p)

    def _set_logo(self, p):
        self.new_logo = p
        self._refresh()

    def _set_welcome(self, p):
        self.new_welcome = p
        self._refresh()

    def _save(self):
        if self.new_logo == "":
            branding.remove_logo()
        elif self.new_logo and not branding.install_logo(self.new_logo):
            QMessageBox.warning(self, APP_NAME, tr("bad_image"))
            return
        if self.new_welcome == "":
            branding.remove_welcome()
        elif self.new_welcome and not branding.install_welcome(self.new_welcome):
            QMessageBox.warning(self, APP_NAME, tr("bad_image"))
            return
        self.s.app_title = self.title.text().strip()[:60]
        self.s.save()
        self.accept()


# ============================================================================ broadcast
class BroadcastDialog(QDialog):
    def __init__(self, peers, preselect=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("broadcast_title"))
        self.resize(560, 460)
        self.list = QListWidget()
        for p in sorted(peers, key=lambda p: (p.group.lower(), p.name.lower())):
            it = QListWidgetItem(status_icon(p.status), f"{p.name}   —   {p.group}")
            it.setData(Qt.ItemDataRole.UserRole, p.id)
            it.setCheckState(Qt.CheckState.Checked if (not preselect or p.id in preselect) else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        all_b, none_b = QPushButton(tr("select_all")), QPushButton(tr("select_none"))
        all_b.clicked.connect(lambda: self._check(True))
        none_b.clicked.connect(lambda: self._check(False))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(tr("type_message"))
        send = QPushButton(tr("send"), objectName="Primary")
        send.clicked.connect(self._send)
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)

        top = QHBoxLayout()
        top.addWidget(QLabel(f"<b>{tr('recipients')}</b>"))
        top.addStretch(1)
        top.addWidget(all_b)
        top.addWidget(none_b)
        bot = QHBoxLayout()
        bot.addStretch(1)
        bot.addWidget(cancel)
        bot.addWidget(send)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.list, 2)
        lay.addWidget(self.text, 1)
        lay.addLayout(bot)

    def _check(self, on):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def recipients(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def message(self):
        return self.text.toPlainText().strip()

    def _send(self):
        if self.message() and self.recipients():
            self.accept()


# ============================================================================ transfers
class TransfersDialog(QDialog):
    COLS = 6

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.rows: dict[str, int] = {}
        self.setWindowTitle(tr("transfers"))
        self.resize(860, 380)
        self.table = QTableWidget(0, self.COLS)
        self.table.setHorizontalHeaderLabels(["", tr("user"), tr("file"), tr("size"), tr("progress"), tr("state")])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(4, 170)
        self.table.setColumnWidth(5, 260)
        clear = QPushButton(tr("clear"))
        clear.clicked.connect(self.clear_finished)
        bl = QHBoxLayout()
        bl.addStretch(1)
        bl.addWidget(clear)
        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        lay.addLayout(bl)
        for tid in core.transfers:
            self.add(tid)
        core.transfer_added.connect(self.add)
        core.transfer_changed.connect(self.update_row)

    def add(self, tid):
        if tid in self.rows:
            return
        tr_ = self.core.transfers[tid]
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.rows[tid] = r
        self.table.setItem(r, 0, QTableWidgetItem("⬆" if tr_.direction == "out" else "⬇"))
        self.table.setItem(r, 1, QTableWidgetItem(tr_.peer_name))
        title = tr_.title if not tr_.title.isdigit() else tr("files_n", n=tr_.title)
        self.table.setItem(r, 2, QTableWidgetItem(title))
        self.table.setItem(r, 3, QTableWidgetItem(human_size(tr_.total)))
        bar = QProgressBar()
        bar.setRange(0, 1000)
        self.table.setCellWidget(r, 4, bar)
        self.update_row(tid)

    def update_row(self, tid):
        r = self.rows.get(tid)
        t = self.core.transfers.get(tid)
        if r is None or t is None:
            return
        bar = self.table.cellWidget(r, 4)
        bar.setValue(1000 if t.state == "done" else int(1000 * t.done / t.total) if t.total else 0)
        bar.setFormat(f"{human_size(t.done)}" if t.state == "active" else "%p%")
        # status cell with actions
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(4, 0, 4, 0)
        if t.state == "offered":
            label = tr("tr_offered_in") if t.direction == "in" else tr("tr_offered_out")
        else:
            label = tr("tr_" + t.state)
        if t.state == "failed" and t.error:
            label += f" ({t.error[:40]})"
        lbl = QLabel(label)
        hl.addWidget(lbl, 1)
        if t.direction == "in" and t.state == "offered":
            a, d = QPushButton(tr("accept"), objectName="Primary"), QPushButton(tr("decline"))
            a.clicked.connect(lambda _=False, x=tid: self.core.accept_transfer(x))
            d.clicked.connect(lambda _=False, x=tid: self.core.reject_transfer(x))
            hl.addWidget(a)
            hl.addWidget(d)
        elif not t.finished:
            c = QPushButton(tr("cancel"))
            c.clicked.connect(lambda _=False, x=tid: self.core.cancel_transfer(x))
            hl.addWidget(c)
        elif t.direction == "in" and t.state == "done":
            o = QPushButton(tr("open_folder"))
            o.clicked.connect(lambda _=False, p=t.dest_root: open_path(p))
            hl.addWidget(o)
        old = self.table.cellWidget(r, 5)
        if old is None or getattr(old, "_state", None) != (t.state, t.error):
            w._state = (t.state, t.error)
            self.table.setCellWidget(r, 5, w)
            self.table.setRowHeight(r, 40)

    def clear_finished(self):
        keep = [tid for tid, t in self.core.transfers.items() if not t.finished]
        for tid in list(self.core.transfers):
            if tid not in keep:
                del self.core.transfers[tid]
        self.table.setRowCount(0)
        self.rows.clear()
        for tid in keep:
            self.add(tid)


# ============================================================================ history search
class HistorySearchDialog(QDialog):
    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.history = history
        self.setWindowTitle(tr("history_search"))
        self.resize(640, 480)
        self.q = QLineEdit(placeholderText=tr("search"))
        self.q.returnPressed.connect(self.run)
        b = QPushButton(tr("search"), objectName="Primary")
        b.clicked.connect(self.run)
        top = QHBoxLayout()
        top.addWidget(self.q, 1)
        top.addWidget(b)
        self.out = QTextBrowser()
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.out)

    def run(self):
        import html
        q = self.q.text().strip()
        if not q:
            return
        rows = self.history.search(q)
        parts = [f"<p><b>{tr('results')}: {len(rows)}</b></p>"]
        for r in rows:
            who = tr("me") + " → " + html.escape(r["peer_name"] or "") if r["outgoing"] else html.escape(r["peer_name"] or "")
            ts = datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M")
            txt = html.escape(r["text"]).replace(html.escape(q), f"<span style='background:#FEF08A'>{html.escape(q)}</span>")
            parts.append(f"<p><span style='color:#0F766E'><b>{who}</b></span> <span style='color:#9CA3AF'>{ts}</span><br>{txt}</p><hr>")
        self.out.setHtml("".join(parts))


def about_html() -> str:
    return tr("about_text", v=APP_VERSION)
