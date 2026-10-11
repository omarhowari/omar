"""Visual smoke test: two full windows chatting over localhost; saves screenshots.

Run:  python -m tests.ui_smoke [ar|en] [outdir]
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["TDA_CONFIG_DIR"] = tempfile.mkdtemp()
from PySide6.QtCore import QEventLoop, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tda.config import Settings  # noqa: E402
from tda.history import History  # noqa: E402
from tda.i18n import set_language  # noqa: E402
from tda.network import NetworkCore  # noqa: E402
from tda.ui.main_window import MainWindow  # noqa: E402
from tda.ui.theme import STYLE  # noqa: E402

lang = sys.argv[1] if len(sys.argv) > 1 else "ar"
out = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
app = QApplication(sys.argv)
set_language(lang)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if lang == "ar" else Qt.LayoutDirection.LeftToRight)
app.setStyle("Fusion")
app.setStyleSheet(STYLE)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.01)


tmp = Path(tempfile.mkdtemp())
wins = []
specs = [("عمار" if lang == "ar" else "Ammar", "IT", 48300, 48310, "available"),
         ("سارة" if lang == "ar" else "Sara", "MEAL", 48310, 48300, "available"),
         ("خالد" if lang == "ar" else "Khaled", "MEAL", 48320, 48300, "busy"),
         ("ليلى" if lang == "ar" else "Layla", "IT", 48330, 48300, "away")]
for name, group, port, peer, st in specs:
    s = Settings(name=name, group=group, udp_port=port, tcp_port=port + 1, password="k",
                 extra_hosts=[f"127.0.0.1:{peer}", "127.0.0.1:48300", "127.0.0.1:48310"], download_dir=str(tmp / name),
                 status=st, language=lang)
    core = NetworkCore(s)
    assert core.start()
    w = MainWindow(s, core, History(tmp / f"{port}.db"))
    wins.append(w)

pump(3)
a, b = wins[0], wins[1]
bid = b.s.user_id
assert bid in a.core.peers
chat = a.open_chat(bid)
msgs_a = ["السلام عليكم، هل وصلك تقرير المتابعة الشهري؟", "أرسلت لك الملف الآن 👇"] if lang == "ar" else \
         ["Hi Sara, did you get the monthly monitoring report?", "Sending the file now 👇"]
msgs_b = ["وعليكم السلام، نعم وصلني. شكراً!\nسأراجعه اليوم وأرد عليك."] if lang == "ar" else \
         ["Yes, got it, thanks!\nI'll review it today."]
a.send_text(bid, msgs_a[0])
pump(1)
b.send_text(a.s.user_id, msgs_b[0])
pump(1)
a.send_text(bid, msgs_a[1])

# --- drag & drop two files (a spreadsheet and an image) onto A's chat with B
from PySide6.QtCore import QMimeData, QPointF, QUrl
from PySide6.QtGui import QColor, QDropEvent, QImage, QPainter
f = tmp / ("تقرير_المتابعة.xlsx" if lang == "ar" else "monitoring_report.xlsx")
f.write_bytes(os.urandom(2_400_000))
img = QImage(640, 400, QImage.Format.Format_RGB32)
img.fill(QColor("#0E4D3C"))
p = QPainter(img); p.fillRect(80, 80, 480, 240, QColor("#B8A068")); p.end()
pic = tmp / "photo.png"
img.save(str(pic))
for path in (f, pic):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    ev = QDropEvent(QPointF(200, 200), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    chat.dropEvent(ev)
pump(1.5)
assert len(b.core.transfers) == 2, b.core.transfers
# B accepts from the links inside the chat card
for tid in list(b.core.transfers):
    b.transfer_action("accept", tid)
pump(3)
assert all(t.state == "done" for t in b.core.transfers.values()), [t.state for t in b.core.transfers.values()]
print("drag&drop + inline accept ok")

# --- a voice call with a fake audio device, logged in both chats
from tda.calls import AudioBackend
class Silent(AudioBackend):
    input_ok = output_ok = True
    def start(self, on_frame):
        import threading
        self.run = True
        def loop():
            while self.run:
                on_frame(bytes(640)); time.sleep(0.02)
        threading.Thread(target=loop, daemon=True).start()
    def play(self, fr): pass
    def stop(self): self.run = False
a.calls.backend_factory = b.calls.backend_factory = Silent
a.start_call(bid)
pump(1)
assert b.calls.state == "incoming"
b.call_win.grab().save(str(out / f"screen_{lang}_call_incoming.png"))
b.calls.accept()
pump(2.2)
a.call_win.grab().save(str(out / f"screen_{lang}_call_active.png"))
a.calls.hangup()
pump(1)
assert a.calls.state == b.calls.state == "idle"
print("call ok")
# a broadcast from Khaled so B shows a broadcast bubble
wins[2].send_text(bid, "اجتماع الفريق الساعة 11" if lang == "ar" else "Team meeting at 11", multi=True)
pump(1)

for w in wins[:2]:
    w.resize(1100, 700)
    w.show()
b.open_chat(a.s.user_id)
pump(0.5)
a.grab().save(str(out / f"screen_{lang}_main.png"))

b.grab().save(str(out / f"screen_{lang}_peer.png"))
print("UI SMOKE OK", [p.name for p in a.core.peers.values()])
for w in wins:
    w.quit()
