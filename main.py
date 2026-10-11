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


def main() -> int:
    _install_crash_log()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())

    # --- single instance: a second launch just brings the first window forward
    key = f"TDA-{getpass.getuser()}"
    probe = QLocalSocket()
    probe.connectToServer(key)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(key)
    server = QLocalServer()
    server.listen(key)

    settings = Settings.load()
    set_language(settings.language)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if settings.language == "ar" else Qt.LayoutDirection.LeftToRight)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)

    core = NetworkCore(settings)
    errors = []
    core.error.connect(errors.append)
    history = History()
    win = MainWindow(settings, core, history)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), win.show_normal()))

    if not core.start():
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
