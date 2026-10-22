"""Light / dark Qt style sheets matching the Waraq PDF design."""
from PySide6.QtGui import QPalette, QColor

LIGHT_RIB = dict(rib="#F3F3F3", ribbar="#E6E6E6", tab_sel="#F3F3F3", hover="#FDE9C4", hover_b="#F1C27D", checked="#F9D9A6",
                 file="#C0392B", title="#E6E6E6", doctabs="#5E5E5E", doctab="#F6EBD3", grp="#6B6B6B", sep="#D4D4D4")
DARK_RIB = dict(rib="#2A2F36", ribbar="#1F2329", tab_sel="#2A2F36", hover="#4A3F2A", hover_b="#B88A3E", checked="#5C4A26",
                file="#B03A2E", title="#1F2329", doctabs="#16191D", doctab="#3A3F47", grp="#9DA7B3", sep="#3D444D")
LIGHT = dict(bg="#EEF1F5", panel="#F8FAFC", surface="#FFFFFF", border="#D1D5DB", text="#1F2937", muted="#4B5563",
             accent="#1D4ED8", accent_soft="#DBEAFE", hover="#EEF2FF", rail="#F1F5F9", title="#1E293B", danger="#B91C1C",
             workspace="#C9D0DA")
DARK = dict(bg="#1B1F24", panel="#22272E", surface="#2B3038", border="#3D444D", text="#E6EDF3", muted="#9DA7B3",
            accent="#4C8DFF", accent_soft="#1F3A66", hover="#2F3A4A", rail="#1F242B", title="#0F1318", danger="#FF7B72",
            workspace="#2B2F36")


def qss(c):
    r = DARK_RIB if c is DARK else LIGHT_RIB
    return ribbon_qss(c, r) + f"""
QWidget {{ font-family: "Segoe UI", "IBM Plex Sans Arabic", "Tahoma", sans-serif; font-size: 13px; color: {c['text']}; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 3px 5px; background: transparent; }}
QToolButton:hover {{ background: {c['hover']}; border-color: {c['accent_soft']}; }}
QToolButton:checked {{ background: {c['accent_soft']}; border-color: {c['accent']}; }}
QFrame#rail {{ background: {c['rail']}; border-right: 1px solid {c['border']}; }}
QStackedWidget#sidepanel, QWidget#props, PropertiesPanel {{ background: {c['panel']}; }}
QLabel#panelTitle {{ font-weight: 600; padding: 4px 0; }}
QLabel#muted {{ color: {c['muted']}; }}
QLabel#h1 {{ font-size: 24px; font-weight: 600; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; }}
QWidget#start {{ background: {c['bg']}; }}
QFrame#drop {{ background: {c['surface']}; border: 2px dashed {c['accent']}; border-radius: 10px; }}
QToolButton#tool {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 10px; }}
QToolButton#tool:hover {{ border-color: {c['accent']}; }}
QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton#primary {{ background: {c['accent']}; color: white; border: 0; font-weight: 500; }}
QPushButton#danger {{ color: {c['danger']}; }}
QLineEdit, QPlainTextEdit, QComboBox {{ background: {c['surface']}; border: 1px solid {c['border']};
    border-radius: 5px; padding: 4px 6px; selection-background-color: {c['accent']}; }}
QAbstractSpinBox QLineEdit, QComboBox QLineEdit {{ border: 0; padding: 0; margin: 0; background: transparent; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QListWidget, QTreeWidget, QTableWidget {{ background: {c['panel']}; border: 0; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; border-radius: 4px; }}
QStatusBar {{ background: {c['surface']}; border-top: 1px solid {c['border']}; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 26px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['accent_soft']}; }}
QSplitter::handle {{ background: {c['border']}; width: 1px; }}
QHeaderView::section {{ background: {c['panel']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 6px; color: {c['muted']}; }}
QProgressBar {{ border: 1px solid {c['border']}; border-radius: 4px; text-align: center; background: {c['surface']}; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
"""


def ribbon_qss(c, r):
    return f"""
QWidget#titlebar {{ background: {r['title']}; }}
QLabel#wintitle {{ color: {c['text']}; font-size: 13px; }}
QToolButton#qa {{ padding: 2px; border-radius: 3px; }}
QFrame#tbsep {{ color: {r['sep']}; margin: 7px 3px; }}
QToolButton#win_min, QToolButton#win_max, QToolButton#win_close {{ border: 0; border-radius: 0; font-size: 13px; background: transparent; }}
QToolButton#win_min:hover, QToolButton#win_max:hover {{ background: {r['sep']}; }}
QToolButton#win_close:hover {{ background: #E81123; color: white; }}
QTabWidget#ribbon::pane {{ border: 0; border-top: 1px solid {r['sep']}; border-bottom: 1px solid {r['sep']}; background: {r['rib']}; }}
QTabWidget#ribbon > QTabBar {{ background: {r['ribbar']}; }}
QTabWidget#ribbon > QTabBar::tab {{ background: transparent; border: 1px solid transparent; border-bottom: 0; padding: 5px 11px 6px 11px;
    margin-top: 3px; color: {c['text']}; font-size: 13px; }}
QTabWidget#ribbon > QTabBar::tab:selected {{ background: {r['tab_sel']}; border-color: {r['sep']}; border-top-left-radius: 2px;
    border-top-right-radius: 2px; color: {c['text']}; font-weight: normal; }}
QTabWidget#ribbon > QTabBar::tab:hover:!selected {{ background: {r['rib']}; }}
QWidget#ribbonpage, QTabWidget#ribbon QScrollArea {{ background: {r['rib']}; }}
QFrame#group {{ border: 0; border-left: 1px solid {r['sep']}; }}
QLabel#grouplabel {{ color: {r['grp']}; font-size: 12px; padding: 0 0 1px 0; }}
QToolButton#filebtn {{ background: {r['file']}; color: white; border: 0; border-radius: 0; padding: 6px 18px; margin: 3px 0 0 0;
    font-size: 13px; font-weight: normal; }}
QToolButton#filebtn::menu-indicator {{ image: none; width: 0; }}
QToolButton#big, QToolButton#small, QToolButton#iconbtn {{ border: 1px solid transparent; border-radius: 2px; padding: 1px 3px;
    background: transparent; font-size: 12px; }}
QToolButton#big:hover, QToolButton#small:hover, QToolButton#iconbtn:hover {{ background: {r['hover']}; border-color: {r['hover_b']}; }}
QToolButton#big:checked, QToolButton#small:checked, QToolButton#iconbtn:checked {{ background: {r['checked']}; border-color: {r['hover_b']}; }}
QToolButton#small {{ text-align: left; padding-left: 2px; }}
QToolButton#big::menu-button, QToolButton#small::menu-button {{ border: 0; width: 12px; }}
QTabWidget#doctabs > QTabBar {{ background: {r['doctabs']}; }}
QTabWidget#doctabs::pane {{ border: 0; }}
QTabWidget#doctabs > QTabBar::tab {{ background: #8A8A8A; color: #FFFFFF; padding: 4px 10px; margin: 3px 1px 0 1px; border: 0;
    border-top-left-radius: 3px; border-top-right-radius: 3px; max-width: 300px; }}
QTabWidget#doctabs > QTabBar::tab:selected {{ background: {r['doctab']}; color: {c['text']}; font-weight: normal; }}
QToolButton#plustab {{ background: transparent; color: white; border: 0; font-size: 18px; padding: 0 8px; }}
QToolButton#plustab:hover {{ background: #777777; }}
"""


def apply_theme(app, dark=False):
    c = DARK if dark else LIGHT
    from . import icons
    icons.set_icon_color("#D6DEE8" if dark else "#1F2937")
    icons.DARK_ICONS = dark
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(c["bg"]))
    pal.setColor(QPalette.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.Base, QColor(c["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(c["panel"]))
    pal.setColor(QPalette.Text, QColor(c["text"]))
    pal.setColor(QPalette.Button, QColor(c["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.Highlight, QColor(c["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, QColor(c["surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(c["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(c["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(qss(c))
