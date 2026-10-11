"""TDA - LAN Messenger. Entry point."""
from __future__ import annotations

import getpass
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from tda import APP_NAME, APP_VERSION
from tda.config import Settings
from tda.history import History
from tda.i18n import set_language, tr
from tda.network import NetworkCore
from tda.ui.main_window import MainWindow
from tda.ui.theme import STYLE, app_icon


def _install_crash_log():
    """Without a console (TDA.exe / pythonw) errors would vanish: log them and show a box."""
    from tda.config import config_dir
    log = config_dir() / "error.log"

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        try:
            QMessageBox.critical(None, "TDA", f"{exc_type.__name__}: {exc}\n\n{log}")
        except Exception:
            pass

    sys.excepthook = hook


def _show_other_instance(key: str, wait_ms: int = 1500) -> bool:
    """If TDA is already running for this user, bring its window forward."""
    probe = QLocalSocket()
    probe.connectToServer(key)
    if probe.waitForConnected(wait_ms):
        probe.write(b"show")
        probe.waitForBytesWritten(500)
        return True
    return False


def _start_network(core, settings, key, errors) -> bool:
    """Start networking. If the TCP port is busy: wait a moment (an old copy may still be closing after an
    update), check whether another TDA is already running (then just show it), otherwise use the next
    free port - the port is announced to everybody, so colleagues still reach us."""
    import time
    from PySide6.QtWidgets import QApplication
    for _ in range(8):
        if core.start():
            errors.clear()
            return True
        if any(e.startswith("UDP") for e in errors):
            return False
        end = time.time() + 0.6
        while time.time() < end:
            QApplication.processEvents()
            time.sleep(0.05)
    if _show_other_instance(key):
        errors[:] = ["__other_instance__"]
        return False
    for port in range(settings.tcp_port + 1, settings.tcp_port + 40):
        if core.start(tcp_port=port):
            errors.clear()
            return True
    return False


def main() -> int:
    _install_crash_log()
    if sys.platform == "win32":
        os.environ.setdefault("QT_MEDIA_BACKEND", "windows")   # camera via Windows Media Foundation
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())

    # --- single instance: a second launch just brings the first window forward
    key = f"TDA-{getpass.getuser()}"
    if _show_other_instance(key, 600):
        return 0
    QLocalServer.removeServer(key)
    server = QLocalServer()
    # also reachable from a copy started "as administrator" (e.g. by the installer) and vice versa
    server.setSocketOptions(QLocalServer.SocketOption.WorldAccessOption)
    server.listen(key)

    settings = Settings.load()
    set_language(settings.language)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if settings.language == "ar" else Qt.LayoutDirection.LeftToRight)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    # Arabic / English texts for Qt's own buttons (Yes / No / Cancel ...)
    from PySide6.QtCore import QLibraryInfo, QTranslator
    qt_tr = QTranslator(app)
    if qt_tr.load(f"qtbase_{settings.language}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(qt_tr)

    history = History()
    if not settings.setup_done:          # first start: ask for name and department
        from tda.ui.dialogs import FirstRunDialog
        dlg = FirstRunDialog(settings, [c.get("group", "") for c in history.contacts()])
        if not dlg.exec():
            return 0

    core = NetworkCore(settings)
    errors = []
    core.error.connect(errors.append)
    win = MainWindow(settings, core, history)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), win.show_normal()))

    if not _start_network(core, settings, key, errors):
        if errors == ["__other_instance__"]:
            return 0
        QMessageBox.critical(None, APP_NAME, tr("start_error", err="\n".join(errors)))
        return 1

    if "--minimized" in sys.argv or settings.start_minimized:
        if not win.tray.isVisible():
            win.showMinimized()
    else:
        win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
