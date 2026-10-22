"""Waraq PDF — desktop PDF editor and tools.

Usage:
    python main.py [files...]          open the editor (optionally with files)
    python main.py --tools [files...]  open the batch tools window only
"""
import os
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WaraqPDF")
    app.setOrganizationName("Waraq")
    from waraq import i18n
    from waraq.theme import apply_theme
    settings = QSettings("Waraq", "WaraqPDF")
    i18n.set_language(settings.value("lang", "ar"))
    if i18n.is_rtl():
        app.setLayoutDirection(Qt.RightToLeft)
    apply_theme(app, settings.value("dark", False, type=bool))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--tools" in sys.argv:
        from waraq.tools_app import ToolsWindow
        w = ToolsWindow()
        for f in args:
            if os.path.isfile(f):
                w.files._add(os.path.abspath(f))
        w.show()
    else:
        from waraq.mainwindow import MainWindow
        w = MainWindow()
        w.show()
        if args:
            w.open_files([a for a in args if os.path.exists(a)])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
