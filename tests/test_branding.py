"""Branding test: admin password, custom logo/welcome image/title, screenshots.

Run:  python -m tests.test_branding [outdir]
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["TDA_CONFIG_DIR"] = tempfile.mkdtemp()
from PySide6.QtCore import QEventLoop, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tda import branding  # noqa: E402
from tda.config import Settings  # noqa: E402
from tda.history import History  # noqa: E402
from tda.i18n import set_language  # noqa: E402
from tda.network import NetworkCore  # noqa: E402
from tda.ui.dialogs import BrandingDialog  # noqa: E402
from tda.ui.main_window import MainWindow  # noqa: E402
from tda.ui.theme import STYLE  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
app = QApplication(sys.argv)
set_language("ar")
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
app.setStyle("Fusion")
app.setStyleSheet(STYLE)
tmp = Path(tempfile.mkdtemp())

# sample images
logo = QImage(400, 300, QImage.Format.Format_ARGB32)   # not square on purpose
logo.fill(Qt.GlobalColor.transparent)
p = QPainter(logo)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setBrush(QColor("#EA580C"))
p.setPen(Qt.PenStyle.NoPen)
p.drawEllipse(QRectF(60, 10, 280, 280))
f = QFont("DejaVu Sans", 70)
f.setBold(True)
p.setFont(f)
p.setPen(QColor("white"))
p.drawText(QRectF(60, 10, 280, 280), Qt.AlignmentFlag.AlignCenter, "ME")
p.end()
logo.save(str(tmp / "logo.png"))
wel = QImage(900, 400, QImage.Format.Format_ARGB32)
p = QPainter(wel)
g = QLinearGradient(QPointF(0, 0), QPointF(900, 400))
g.setColorAt(0, QColor("#1E3A8A"))
g.setColorAt(1, QColor("#0EA5E9"))
p.fillRect(wel.rect(), g)
f = QFont("DejaVu Sans", 46)
f.setBold(True)
p.setFont(f)
p.setPen(QColor("white"))
p.drawText(QRectF(0, 0, 900, 400), Qt.AlignmentFlag.AlignCenter, "فريق المتابعة والتقييم")
p.end()
wel.save(str(tmp / "welcome.jpg"))

s = Settings(name="عمار", group="IT", udp_port=48500, tcp_port=48501, language="ar")
# admin password
assert not branding.has_admin_password(s)
branding.set_admin_password(s, "1234abcd")
assert branding.check_admin_password(s, "1234abcd")
assert not branding.check_admin_password(s, "wrong")
assert "1234abcd" not in Settings.path().read_text(encoding="utf-8")
print("admin password ok (stored hashed)")

core = NetworkCore(s)
assert core.start()
w = MainWindow(s, core, History(tmp / "h.db"))
w.resize(1100, 680)
w.show()

dlg = BrandingDialog(s, w)
dlg._set_logo(str(tmp / "logo.png"))
dlg._set_welcome(str(tmp / "welcome.jpg"))
dlg.title.setText("مراسل فريق MEAL")
dlg.show()
app.processEvents()
dlg.grab().save(str(out / "branding_dialog.png"))
dlg._save()
w.apply_branding()
assert branding.logo_path().exists() and branding.ico_path().exists() and branding.welcome_path().exists()
assert QImage(str(branding.logo_path())).size().width() == 256
assert branding.ico_path().read_bytes()[:4] == b"\x00\x00\x01\x00"
end = time.time() + 0.5
while time.time() < end:
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
w.grab().save(str(out / "branded_main.png"))
assert w.windowTitle() == "مراسل فريق MEAL", w.windowTitle()
print("custom branding ok")

# restore defaults
dlg2 = BrandingDialog(s, w)
dlg2._set_logo("")
dlg2._set_welcome("")
dlg2.title.setText("")
dlg2._save()
w.apply_branding()
assert not branding.logo_path().exists() and not branding.welcome_path().exists()
print("restore default ok")
w.quit()
print("BRANDING TESTS PASSED")
