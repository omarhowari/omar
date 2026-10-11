"""End-to-end test: two TDA instances in one process talk over localhost.

Run:  python -m tests.test_network
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from tda.config import Settings  # noqa: E402
from tda.network import NetworkCore  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication(sys.argv)


def wait(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.01)
    return cond()


def make(name, base, peer_base, password="", tmp=None):
    s = Settings(name=name, group="QA", udp_port=base, tcp_port=base + 1, password=password,
                 extra_hosts=[f"127.0.0.1:{peer_base}"], download_dir=str(Path(tmp) / name))
    c = NetworkCore(s)
    assert c.start(), "start failed"
    return c


def run(port_a, port_b, password_a="", password_b=""):
    tmp = tempfile.mkdtemp()
    a = make("Ali", port_a, port_b, password_a, tmp)
    b = make("Bana", port_b, port_a, password_b, tmp)
    return a, b, tmp


def main():
    # 1) discovery + chat, encrypted
    a, b, tmp = run(48100, 48110, "secret", "secret")
    assert wait(lambda: b.settings.user_id in a.peers and a.settings.user_id in b.peers), "discovery failed"
    print("discovery ok:", a.peers[b.settings.user_id].name, "<->", b.peers[a.settings.user_id].name)

    got, status = [], {}
    b.message_received.connect(got.append)
    a.message_status.connect(lambda mid, ok, err: status.__setitem__(mid, ok))
    mid = a.send_message(b.settings.user_id, "مرحبا يا بنى 👋\nسطر ثاني")
    assert wait(lambda: got and status.get(mid)), "message failed"
    assert got[0]["text"] == "مرحبا يا بنى 👋\nسطر ثاني" and got[0]["from_name"] == "Ali"
    print("chat ok:", repr(got[0]["text"]))

    # 2) file + folder transfer (with an empty file and a nested folder)
    src = Path(tmp) / "src"
    (src / "folder" / "sub").mkdir(parents=True)
    big = os.urandom(3 * 1024 * 1024 + 123)
    (src / "big.bin").write_bytes(big)
    (src / "folder" / "a.txt").write_text("hello", encoding="utf-8")
    (src / "folder" / "sub" / "empty.txt").write_bytes(b"")
    (src / "folder" / "sub" / "تقرير.txt").write_text("نص عربي", encoding="utf-8")

    offers = []
    b.transfer_added.connect(offers.append)
    tid = a.offer_files(b.settings.user_id, [str(src / "big.bin"), str(src / "folder")])
    assert wait(lambda: tid in offers), "offer not received"
    tr_in = b.transfers[tid]
    print("offer ok:", len(tr_in.files), "files,", tr_in.total, "bytes")
    b.accept_transfer(tid)
    assert wait(lambda: a.transfers[tid].state == "done" and b.transfers[tid].state == "done", 20), \
        (a.transfers[tid].state, a.transfers[tid].error, b.transfers[tid].state, b.transfers[tid].error)
    dl = Path(b.settings.download_dir)
    assert (dl / "big.bin").read_bytes() == big
    assert (dl / "folder" / "a.txt").read_text(encoding="utf-8") == "hello"
    assert (dl / "folder" / "sub" / "empty.txt").stat().st_size == 0
    assert (dl / "folder" / "sub" / "تقرير.txt").read_text(encoding="utf-8") == "نص عربي"
    print("file transfer ok")

    # 3) same file again -> renamed, not overwritten
    tid2 = a.offer_files(b.settings.user_id, [str(src / "big.bin")])
    assert wait(lambda: tid2 in offers)
    b.accept_transfer(tid2)
    assert wait(lambda: b.transfers[tid2].state == "done", 20)
    assert (dl / "big (1).bin").read_bytes() == big
    print("rename-on-conflict ok")

    # 4) decline
    tid3 = a.offer_files(b.settings.user_id, [str(src / "folder")])
    assert wait(lambda: tid3 in offers)
    b.reject_transfer(tid3)
    assert wait(lambda: a.transfers[tid3].state == "declined")
    print("decline ok")

    # 5) bye -> removed
    removed = []
    a.peer_removed.connect(removed.append)
    b.stop()
    assert wait(lambda: b.settings.user_id in removed), "bye not processed"
    print("offline detection ok")
    a.stop()

    # 6) different passwords -> invisible to each other
    c, d, _ = run(48120, 48130, "one", "two")
    wait(lambda: False, 2.5)
    assert not c.peers and not d.peers, "peers with different passwords must not see each other"
    c.stop(); d.stop()
    print("password isolation ok")

    # 7) no password on both sides
    e, f, _ = run(48140, 48150)
    assert wait(lambda: f.settings.user_id in e.peers)
    e.stop(); f.stop()
    print("plain mode ok")
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
