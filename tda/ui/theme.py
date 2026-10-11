"""Icons drawn in code (no binary assets needed) and the application stylesheet."""
from __future__ import annotations

import os
import sys
from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

ACCENT = "#0E4D3C"        # taken from the logo (dark green)
ACCENT_DARK = "#062E24"
ACCENT_SOFT = "#E2EEE8"
GOLD = "#B8A068"           # logo gold

STATUS_COLORS = {
    "available": "#16A34A",
    "away": "#F59E0B",
    "busy": "#DC2626",
    "offline": "#9CA3AF",
}


def resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    return os.path.join(base, rel)


@lru_cache(maxsize=None)
def status_icon(status: str) -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("white"), 3))
    p.setBrush(QBrush(QColor(STATUS_COLORS.get(status, STATUS_COLORS["offline"]))))
    p.drawEllipse(5, 5, 22, 22)
    if status == "busy":
        p.setPen(QPen(QColor("white"), 3.5))
        p.drawLine(11, 16, 21, 16)
    elif status == "away":
        p.setPen(QPen(QColor("white"), 2.5))
        p.drawLine(16, 10, 16, 16)
        p.drawLine(16, 16, 20, 19)
    p.end()
    return QIcon(pm)


def draw_logo(size: int, badge: str | None = None, allow_custom: bool = True) -> QPixmap:
    from ..branding import custom_logo
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    s = size
    custom = custom_logo() if allow_custom else None
    if custom is None:
        custom = default_logo()
    if custom is not None:
        p.drawPixmap(0, 0, custom.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
        _badge(p, s, badge)
        p.end()
        return pm
    # speech bubble
    path = QPainterPath()
    path.addRoundedRect(QRectF(s * 0.04, s * 0.06, s * 0.92, s * 0.70), s * 0.18, s * 0.18)
    tail = QPainterPath()
    tail.moveTo(s * 0.22, s * 0.70)
    tail.lineTo(s * 0.16, s * 0.95)
    tail.lineTo(s * 0.46, s * 0.72)
    tail.closeSubpath()
    path = path.united(tail)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ACCENT))
    p.drawPath(path)
    f = QFont("Segoe UI", max(6, int(s * 0.30)))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, s * 0.06, s, s * 0.70), Qt.AlignmentFlag.AlignCenter, "TDA")
    _badge(p, s, badge)
    p.end()
    return pm


def _badge(p: QPainter, s: int, badge: str | None):
    if badge:
        r = s * 0.36
        p.setPen(QPen(QColor("white"), max(1.0, s * 0.04)))
        p.setBrush(QColor(STATUS_COLORS.get(badge, "#DC2626")))
        p.drawEllipse(QRectF(s - r - 1, s - r - 1, r, r))


@lru_cache(maxsize=1)
def _default_logo_pm():
    path = resource_path(os.path.join("assets", "logo.png"))
    pm = QPixmap(path) if os.path.exists(path) else QPixmap()
    return None if pm.isNull() else pm


def default_logo() -> QPixmap | None:
    """The built-in logo shipped in assets/logo.png (None = draw the generic TDA bubble)."""
    return _default_logo_pm()


def draw_avatar(name: str, size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("white"))
    p.drawEllipse(0, 0, size, size)
    f = QFont("Segoe UI", max(6, int(size * 0.36)))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(ACCENT))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, (name.strip()[:1] or "?").upper())
    p.end()
    return pm


def app_icon(badge: str | None = None) -> QIcon:
    from ..branding import custom_logo
    ico = resource_path(os.path.join("assets", "tda.ico"))
    if badge is None and custom_logo() is None and os.path.exists(ico):
        return QIcon(ico)
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(draw_logo(sz, badge))
    return icon


STYLE = f"""
* {{ font-family: "Segoe UI", "Tahoma", "Noto Sans Arabic", sans-serif; font-size: 10pt; }}
QMainWindow, QDialog {{ background: #F3F4F6; }}
QToolBar {{ background: white; border: none; border-bottom: 1px solid #E5E7EB; padding: 4px; spacing: 4px; }}
QToolBar QToolButton {{ padding: 6px 10px; border-radius: 6px; color: #1F2937; }}
QToolBar QToolButton:hover {{ background: {ACCENT_SOFT}; }}
#SidePanel {{ background: white; }}
#MeCard {{ background: {ACCENT}; border-radius: 10px; border-bottom: 3px solid {GOLD}; }}
#MeCard QLabel {{ color: white; }}
#MeName {{ font-size: 12pt; font-weight: 600; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background: white; border: 1px solid #D1D5DB; border-radius: 6px; padding: 5px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QTreeWidget, QListWidget, QTableWidget {{ background: white; border: none; outline: none; }}
QTreeWidget::item {{ padding: 5px 2px; border-radius: 6px; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: #111827; }}
QTreeWidget::item:hover {{ background: #F0FDFA; }}
QPushButton {{ background: white; border: 1px solid #D1D5DB; border-radius: 6px; padding: 6px 14px; color: #1F2937; }}
QPushButton:hover {{ background: #F9FAFB; border-color: {ACCENT}; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#Primary:disabled {{ background: #CBD5E1; color: #F8FAFC; }}
#ComposeBar {{ background: #F0F2F5; border-top: 1px solid #E5E7EB; }}
#ComposeBox {{ background: white; border: 1px solid #D1D5DB; border-radius: 24px; }}
QPlainTextEdit#Compose {{ background: transparent; border: none; padding: 8px 4px; font-size: 10.5pt; }}
QPushButton#SendRound {{ background: {ACCENT}; border: none; border-radius: 22px; padding: 0; }}
QPushButton#SendRound:hover {{ background: {ACCENT_DARK}; }}
QPushButton#SendRound:disabled {{ background: #CBD5E1; }}
QPushButton#Attach {{ font-size: 16pt; background: transparent; border: none; border-radius: 20px; padding: 0; color: #54656F; }}
QPushButton#Attach:hover {{ background: #F0F2F5; }}
QPushButton#Attach::menu-indicator {{ image: none; width: 0; }}
QPushButton#Attach:disabled {{ color: #CBD5E1; }}
QTextBrowser#ChatView QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QTextBrowser#ChatView QScrollBar::handle:vertical {{ background: rgba(0,0,0,0.25); border-radius: 4px; min-height: 30px; }}
QTextBrowser#ChatView QScrollBar::handle:vertical:hover {{ background: rgba(0,0,0,0.4); }}
QTextBrowser#ChatView QScrollBar::add-line:vertical, QTextBrowser#ChatView QScrollBar::sub-line:vertical {{ height: 0; }}
QTextBrowser#ChatView QScrollBar::add-page:vertical, QTextBrowser#ChatView QScrollBar::sub-page:vertical {{ background: none; }}
QMenu {{ background: white; border: 1px solid #D1D5DB; padding: 4px; }}
QMenu::item {{ padding: 8px 22px; border-radius: 6px; font-size: 10.5pt; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: #111827; }}
QPushButton:disabled {{ color: #9CA3AF; background: #F3F4F6; }}
QTabWidget::pane {{ border: none; background: white; }}
QTabBar::tab {{ background: #E5E7EB; padding: 7px 14px; margin: 2px 2px 0 2px; border-top-left-radius: 6px; border-top-right-radius: 6px; }}
QTabBar::tab:selected {{ background: white; color: {ACCENT}; font-weight: 600; }}
QTextBrowser#ChatView {{ background: transparent; border: none; }}
#ChatHeader {{ background: white; border-bottom: 1px solid #E5E7EB; }}
#ChatTitle {{ font-size: 12pt; font-weight: 600; }}
#Muted {{ color: #6B7280; }}
#WelcomeTitle {{ font-size: 18pt; font-weight: 700; color: #111827; margin-top: 10px; }}
QStatusBar {{ background: white; border-top: 1px solid #E5E7EB; }}
QProgressBar {{ border: 1px solid #D1D5DB; border-radius: 5px; background: #F3F4F6; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QGroupBox {{ font-weight: 600; border: 1px solid #E5E7EB; border-radius: 8px; margin-top: 12px; padding-top: 8px; background: white; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; right: 10px; padding: 0 4px; }}
"""


def glyph_icon(glyph: str, size: int = 64) -> QIcon:
    """An emoji/character drawn on a white tile (used for file thumbnails)."""
    pm = QPixmap(size, size)
    pm.fill(QColor("white"))
    p = QPainter(pm)
    f = QFont()
    f.setPointSize(int(size * 0.42))
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


def send_icon(rtl: bool) -> QIcon:
    """White paper-plane arrow; points left in Arabic like WhatsApp."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    pm = QPixmap(48, 48)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("white"))
    pts = [QPointF(8, 8), QPointF(42, 24), QPointF(8, 40), QPointF(13, 26), QPointF(28, 24), QPointF(13, 22)]
    if rtl:
        pts = [QPointF(48 - q.x(), q.y()) for q in pts]
    p.drawPolygon(QPolygonF(pts))
    p.end()
    return QIcon(pm)


# ------------------------------------------------------------------ chat background
@lru_cache(maxsize=1)
def chat_pattern() -> QPixmap:
    """Built-in Islamic geometric pattern (seamless tile in assets/chat_pattern.png)."""
    path = resource_path(os.path.join("assets", "chat_pattern.png"))
    return QPixmap(path)
