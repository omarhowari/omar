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
from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, Signal  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
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
                 status=st, language=lang, setup_done=True)
    core = NetworkCore(s, data_dir=tmp / f"data{port}")
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
import tda.ui.dialogs as _dlg
def _auto_send(self):           # the picture preview appears; screenshot it and press send
    self.cap.setText("صورة من الزيارة الميدانية" if lang == "ar" else "Photo from the field visit")
    self.show(); app.processEvents()
    if any(x.endswith(".png") for x in self.paths()):
        self.grab().save(str(out / f"screen_{lang}_image_preview.png"))
    return 1
_dlg.ImageSendDialog.exec = _auto_send
tall = QImage(600, 1000, QImage.Format.Format_RGB32)
tall.fill(QColor("#B8A068"))
p = QPainter(tall); p.fillRect(100, 150, 400, 700, QColor("#0E4D3C")); p.end()
tall_pic = tmp / "portrait.png"
tall.save(str(tall_pic))
for path in (f, pic, tall_pic):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    ev = QDropEvent(QPointF(200, 200), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    chat.dropEvent(ev)
pump(1.5)
assert len(b.core.transfers) == 3, b.core.transfers
# B accepts the spreadsheet from the card; the picture downloads by itself
pump(0.5)
for tid, t in list(b.core.transfers.items()):
    if t.state == "offered":
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


class FakeVideo(QObject):
    image = Signal(object)

    def __init__(self, parent=None, kind="screen"):
        super().__init__(parent)
        self.kind = kind
        self.t = QTimer(self, interval=150)
        self.t.timeout.connect(self._f)

    def start(self):
        self.t.start()
        return True

    def stop(self):
        self.t.stop()

    def _f(self):
        if self.kind == "screen":       # a fake "shared screen": the other user's main window
            img = a.grab().toImage()
        else:
            img = QImage(640, 480, QImage.Format.Format_RGB32)
            img.fill(QColor("#0E4D3C"))
            p = QPainter(img)
            p.setBrush(QColor("#B8A068"))
            p.drawEllipse(220, 120, 200, 240)
            p.end()
        self.image.emit(img)


a.calls.screen_factory = lambda parent, target=None: FakeVideo(parent, "screen")
b.calls.camera_factory = lambda parent: FakeVideo(parent, "camera")
import tda.video as _v
_v.CameraSource.available = staticmethod(lambda: True)
a.start_call(bid)
pump(1)
assert b.calls.state == "incoming"
b.call_win.grab().save(str(out / f"screen_{lang}_call_incoming.png"))
b.calls.accept()
pump(2.2)
a.call_win.grab().save(str(out / f"screen_{lang}_call_active.png"))
a.calls.toggle_video("screen")
b.calls.toggle_video("camera")
pump(2.5)
assert b.call_win.video.isVisible() and b.call_win.video.main.img is not None, "video window did not show frames"
b.call_win.video.resize(1000, 620)
pump(0.5)
b.call_win.video.grab().save(str(out / f"screen_{lang}_video.png"))
print("video window ok")
a.calls.hangup()
pump(1)
assert a.calls.state == b.calls.state == "idle"
print("call ok")
# --- groups: A creates a group with B and Khaled, sends a message; B sees the group chat
gid = a.core.create_group("فريق المتابعة والتقييم" if lang == "ar" else "MEAL team",
                          {bid: b.s.name, wins[2].s.user_id: wins[2].s.name})
pump(1.5)
assert gid in b.core.groups
a.send_text("g:" + gid, "صباح الخير للجميع، الاجتماع الساعة 10" if lang == "ar" else "Good morning all, meeting at 10")
pump(1)
wins[2].send_text("g:" + gid, "تمام 👍" if lang == "ar" else "OK 👍")
pump(1.5)
assert "g:" + gid in b.chats and sum(1 for it in b.chats["g:" + gid].items if it.get("kind") == "msg") == 2
print("group chat ok")

# --- offline: Layla closes TDA; A writes to her anyway -> queued
lid = wins[3].s.user_id
wins[3].core.stop()
pump(1)
assert lid not in a.core.peers
a.open_chat(lid)
a.send_text(lid, "سأرسل لك التقرير عند عودتك" if lang == "ar" else "I'll send you the report when you're back")
pump(0.5)
assert a.chats[lid].items[-1]["status"] == "queued", a.chats[lid].items[-1]
a.chats[lid].grab().save(str(out / f"screen_{lang}_offline.png"))
print("offline queue ok")

# a broadcast from Khaled so B shows a broadcast bubble
wins[2].send_text(bid, "اجتماع الفريق الساعة 11" if lang == "ar" else "Team meeting at 11", multi=True)
pump(1)

for w in wins[:2]:
    w.resize(1100, 700)
    w.show()
b.open_chat(a.s.user_id)
pump(0.5)
b.open_chat("g:" + gid)
pump(0.3)
b.grab().save(str(out / f"screen_{lang}_group.png"))
b.open_chat(a.s.user_id)
pump(0.3)
a.grab().save(str(out / f"screen_{lang}_main.png"))

b.grab().save(str(out / f"screen_{lang}_peer.png"))

# --- group administration: B made admin, Khaled frozen from writing
kid = wins[2].s.user_id
a.core.update_group(gid, admins_add=[bid])
a.core.update_group(gid, restrict={kid: {"write": True, "media": True, "call": False}})
pump(1.5)
assert not wins[2].core.can(gid, "write")
from tda.ui.group_info import GroupInfoDialog
gi = GroupInfoDialog(a.core, gid, a._people(), parent=a)
gi.show(); pump(0.4)
gi.grab().save(str(out / f"screen_{lang}_group_admin.png"))
gi.close()
kw = wins[2]
kw.resize(900, 600); kw.show()
kw.open_chat("g:" + gid)
pump(0.6)
kw.grab().save(str(out / f"screen_{lang}_group_frozen.png"))
print("group admin ui ok")

# --- what to share during a call
from tda.ui.share_picker import SharePickerDialog
sp = SharePickerDialog(a)
sp.show(); pump(0.4)
sp.grab().save(str(out / f"screen_{lang}_share_picker.png"))
sp.close()

# --- appearance published by the administrator reaches B, then settings / branding / share windows
a.s.bubble_me, a.s.bubble_them, a.s.font_pt = "#CDE8FF", "#FFF7E0", 11.5
pkg = a.core.publish_theme("admin-pass", lock=True)
assert pkg
pump(4)
assert b.s.bubble_me == "#CDE8FF" and b.s.theme_lock, (b.s.bubble_me, b.s.theme_lock)
b.open_chat(a.s.user_id)
pump(0.5)
b.grab().save(str(out / f"screen_{lang}_theme_applied.png"))
from tda.ui.dialogs import BrandingDialog, SettingsDialog
sd = SettingsDialog(b.s, b, core=b.core)
sd.adv_btn.click()
sd.resize(600, 1500); sd.show(); pump(0.4)
sd.grab().save(str(out / f"screen_{lang}_settings_locked.png"))
sd.close()
sd = SettingsDialog(a.s, a, core=a.core)
sd.adv_btn.click()
sd.resize(600, 1500); sd.show(); pump(0.4)
sd.grab().save(str(out / f"screen_{lang}_settings.png"))
bd = BrandingDialog(a.s, sd, core=a.core)
bd.show(); pump(0.3)
bd.grab().save(str(out / f"screen_{lang}_branding_publish.png"))
bd.close(); sd.close()
import tda.ui.share_app as _sa
from PySide6.QtWidgets import QMessageBox
QMessageBox.information = staticmethod(lambda *x, **k: 0)
fake_setup = tmp / "TDA-Setup.exe"
fake_setup.write_bytes(b"MZ" + bytes(5_000_000))
_sa.updates.update_package = lambda: fake_setup
sh = _sa.ShareAppDialog(a.core, a)
sh.show(); pump(0.3)
sh.grab().save(str(out / f"screen_{lang}_share_app.png"))
sh.close()
# --- a colleague with a newer version -> update bar
a.on_update_available("1.6.0", bid)
pump(0.3)
a.grab().save(str(out / f"screen_{lang}_update_bar.png"))
print("appearance / settings / share / update ui ok")
print("UI SMOKE OK", [p.name for p in a.core.peers.values()])
for w in wins:
    w.quit()
