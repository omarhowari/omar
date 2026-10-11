"""Choose what to share during a call: a whole screen, one application window, or a folder."""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .. import winshare
from ..i18n import tr

THUMB = QSize(220, 138)


def _thumb(img) -> QIcon:
    if img is None or img.isNull():
        pm = QPixmap(THUMB)
        pm.fill(Qt.GlobalColor.lightGray)
        return QIcon(pm)
    return QIcon(QPixmap.fromImage(img.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation)))


def _grid() -> QListWidget:
    w = QListWidget()
    w.setViewMode(QListWidget.ViewMode.IconMode)
    w.setIconSize(THUMB)
    w.setGridSize(QSize(THUMB.width() + 24, THUMB.height() + 46))
    w.setResizeMode(QListWidget.ResizeMode.Adjust)
    w.setMovement(QListWidget.Movement.Static)
    w.setWordWrap(True)
    w.setSpacing(6)
    return w


class SharePickerDialog(QDialog):
    def __init__(self, parent=None, exclude_titles=()):
        super().__init__(parent)
        self.setWindowTitle(tr("share_choose"))
        self.resize(820, 560)
        self.target = None
        self.tabs = QTabWidget()

        # 1) whole screens
        self.screens = _grid()
        for i, scr in enumerate(QGuiApplication.screens()):
            pm = scr.grabWindow(0)
            it = QListWidgetItem(_thumb(pm.toImage() if not pm.isNull() else None),
                                 f"{tr('share_screen_n', n=i + 1)}\n{scr.geometry().width()}×{scr.geometry().height()}")
            it.setData(Qt.ItemDataRole.UserRole, {"kind": "screen", "index": i, "title": scr.name()})
            self.screens.addItem(it)
        self.tabs.addTab(self.screens, "🖥  " + tr("share_whole_screen"))

        # 2) application windows (Windows)
        self.windows = _grid()
        self.exclude = tuple(exclude_titles)
        self._fill_windows()
        self.tabs.addTab(self.windows, "🪟  " + tr("share_app_window"))

        # 3) a folder: open it in Explorer and share that window
        folder_tab = QWidget()
        fl = QVBoxLayout(folder_tab)
        fl.addStretch(1)
        lbl = QLabel(tr("share_folder_hint"), alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True)
        lbl.setObjectName("Muted")
        pick = QPushButton("📁  " + tr("share_pick_folder"), objectName="Primary")
        pick.clicked.connect(self._pick_folder)
        fl.addWidget(lbl)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(pick)
        row.addStretch(1)
        fl.addLayout(row)
        fl.addStretch(2)
        self.tabs.addTab(folder_tab, "📁  " + tr("share_folder"))
        if not winshare.AVAILABLE:
            self.tabs.setTabEnabled(1, False)
            self.tabs.setTabEnabled(2, False)

        for g in (self.screens, self.windows):
            g.itemDoubleClicked.connect(lambda it: self._choose(it))
        self.share_btn = QPushButton(tr("share_start"), objectName="Primary")
        self.share_btn.clicked.connect(self._share_selected)
        refresh = QPushButton("⟳  " + tr("refresh"))
        refresh.clicked.connect(self._fill_windows)
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(refresh)
        bottom.addStretch(1)
        bottom.addWidget(cancel)
        bottom.addWidget(self.share_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{tr('share_choose')}</b>"))
        lay.addWidget(self.tabs, 1)
        lay.addLayout(bottom)
        if self.screens.count():
            self.screens.setCurrentRow(0)

    def _fill_windows(self):
        self.windows.clear()
        for hwnd, title in winshare.list_windows(self.exclude):
            it = QListWidgetItem(_thumb(winshare.capture_window(hwnd)), title[:60])
            it.setToolTip(title)
            it.setData(Qt.ItemDataRole.UserRole, {"kind": "window", "hwnd": hwnd, "title": title})
            self.windows.addItem(it)

    def _choose(self, it):
        if it is not None:
            self.target = it.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def _share_selected(self):
        grid = self.tabs.currentWidget()
        if isinstance(grid, QListWidget):
            self._choose(grid.currentItem())

    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, tr("share_pick_folder"))
        if not path:
            return
        before = {h for h, _t in winshare.list_windows()}
        name = os.path.basename(os.path.normpath(path)) or path
        try:
            os.startfile(os.path.normpath(path))          # opens the folder in File Explorer
        except Exception:
            pass
        # wait (up to 6 s) for the Explorer window showing that folder
        deadline = time.time() + 6
        while time.time() < deadline:
            QApplication.processEvents()
            time.sleep(0.2)
            for hwnd, title in winshare.list_windows():
                if hwnd not in before and (name in title or os.path.normpath(path) in title):
                    self.target = {"kind": "window", "hwnd": hwnd, "title": title}
                    self.accept()
                    return
        QMessageBox.information(self, tr("share_folder"), tr("share_folder_not_found"))
        self.tabs.setCurrentIndex(1)
        self._fill_windows()
