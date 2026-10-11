"""Load test: 1000 simulated users announce themselves to one TDA window.

Run:  python -m tests.test_scale [count]
"""
import json
import os
import socket
import sys
import tempfile
import time
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["TDA_CONFIG_DIR"] = tempfile.mkdtemp()
from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tda.config import Settings  # noqa: E402
from tda.crypto import Cipher  # noqa: E402
from tda.history import History  # noqa: E402
from tda.network import NetworkCore  # noqa: E402
from tda.ui.main_window import MainWindow  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
app = QApplication(sys.argv)
tmp = Path(tempfile.mkdtemp())


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)


s = Settings(name="Admin", group="IT", udp_port=48900, tcp_port=48901, password="k", setup_done=True)
core = NetworkCore(s, data_dir=tmp / "data")
assert core.start()
win = MainWindow(s, core, History(tmp / "h.db"))
win.show()

cipher = Cipher("k")
depts = ["IT", "MEAL", "المالية", "الموارد البشرية", "اللوجستيات", "البرامج", "الحماية", "الصحة"]
sim = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sim.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)   # 1000 replies must fit
sim.bind(("127.0.0.1", 0))
sim.setblocking(False)
ids = [uuid.uuid4().hex for _ in range(N)]
t0 = time.time()
cpu0 = time.process_time()
for i, pid in enumerate(ids):
    hello = {"t": "hello", "id": pid, "name": f"موظف {i + 1}", "group": depts[i % len(depts)],
             "status": "available", "port": 50000 + i % 1000, "host": f"PC-{i}", "os": "Windows 11",
             "v": "1.3.0", "iv": 30}
    sim.sendto(cipher.seal(json.dumps(hello, ensure_ascii=False).encode()), ("127.0.0.1", 48900))
    if i % 100 == 99:
        pump(0.05)          # 1000 users arriving within ~0.5 s
deadline = time.time() + 20
while len(core.peers) < N and time.time() < deadline:
    pump(0.1)
t_disc = time.time() - t0
pump(2.0)                    # let the debounced list rebuild and the delayed replies go out
replies = 0
for _ in range(40):
    pump(0.1)
    try:
        while True:
            sim.recv(65535)
            replies += 1
    except BlockingIOError:
        pass
cpu = time.process_time() - cpu0
t1 = time.perf_counter()
win.refresh_tree()
t_tree = (time.perf_counter() - t1) * 1000
rows = sum(win.tree.topLevelItem(i).childCount() for i in range(win.tree.topLevelItemCount()))

# steady state: every user re-announces (unchanged) -> fast path, no UI work
t2 = time.process_time()
for i, pid in enumerate(ids):
    hello = {"t": "hello", "id": pid, "name": f"موظف {i + 1}", "group": depts[i % len(depts)],
             "status": "available", "port": 50000 + i % 1000, "host": f"PC-{i}", "os": "Windows 11",
             "v": "1.3.0", "iv": 30}
    sim.sendto(cipher.seal(json.dumps(hello, ensure_ascii=False).encode()), ("127.0.0.1", 48900))
pump(1.0)
cpu_steady = (time.process_time() - t2) * 1000

print(f"users discovered: {len(core.peers)}/{N} in {t_disc:.2f}s (CPU {cpu:.2f}s incl. UI)")
print(f"user list rebuild with {rows} rows: {t_tree:.0f} ms")
print(f"direct replies to newcomers: {replies} (spread over ~1.5 s)")
print(f"own announce interval now: {core.announce_interval():.0f}s  (5s on small networks)")
print(f"one full round of {N} unchanged announcements: {cpu_steady:.0f} ms CPU")
assert len(core.peers) == N and rows >= N and core.announce_interval() == 30
win.quit()
print("SCALE TEST PASSED")
