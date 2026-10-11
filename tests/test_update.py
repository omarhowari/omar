"""In-place update over the LAN + administrator appearance published to everyone.

Run:  python -m tests.test_update
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["TDA_CONFIG_DIR"] = tempfile.mkdtemp()

from tests.test_network import app, make, wait  # noqa: E402
from tda import theme_share, updates  # noqa: E402


def main():
    tmp = tempfile.mkdtemp()
    a = make("Admin", 48300, 48310, "net", tmp)
    b = make("User", 48310, 48300, "net", tmp)

    # --- A runs a newer version and has its installer
    setup = Path(tmp) / "TDA-Setup.exe"
    setup.write_bytes(b"MZ" + b"\0" * 1000 + b"Nullsoft Install System" + os.urandom(300_000))
    a.version = "9.1.0"
    a.update_package = lambda: setup
    a.announce("hello")
    seen, ready, failed = [], [], []
    b.update_available.connect(lambda v, pid: seen.append((v, pid)))
    b.update_ready.connect(lambda p, v: ready.append((p, v)))
    b.update_failed.connect(failed.append)
    shown = []
    b.transfer_added.connect(shown.append)
    assert wait(lambda: seen), "update not announced"
    assert seen[0] == ("9.1.0", a.settings.user_id)
    assert b.best_update_source().id == a.settings.user_id
    assert a.best_update_source() is None                       # the newer one does not update backwards
    print("update announced ok:", seen[0][0])
    assert b.request_update()
    assert wait(lambda: ready or failed, 20), "update download timed out"
    assert not failed, failed
    path, ver = ready[0]
    assert ver == "9.1.0" and Path(path).read_bytes() == setup.read_bytes()
    assert updates.looks_like_installer(path)
    assert not shown, "update transfer must not appear in chats"
    print("update downloaded ok:", path)

    # an installer nobody asked for is ignored
    before = len(b.transfers)
    a.offer_files(b.settings.user_id, [str(setup)], purpose="update")
    for _ in range(30):
        app.processEvents()
        import time
        time.sleep(0.03)
    assert len(b.transfers) == before, "unrequested installer accepted"
    print("unrequested installer ignored ok")

    # --- appearance published by the administrator
    a.settings.bubble_me, a.settings.font_pt, a.settings.app_title = "#123456", 13.0, "شركتنا"
    pkg = a.publish_theme("adminpw", lock=True)
    assert pkg and a.settings.theme_version == 1
    got = []
    b.theme_applied.connect(got.append)
    assert wait(lambda: got, 15), "theme not received"
    assert b.settings.bubble_me == "#123456" and b.settings.font_pt == 13.0 and b.settings.app_title == "شركتنا"
    assert b.settings.theme_lock and b.settings.theme_pin == pkg["pub"]
    print("appearance published + applied ok, lock:", b.settings.theme_lock)

    # forged theme (other password) is refused; a tampered one too
    forged = theme_share.sign(dict(pkg["theme"], v=50, bubble_me="#FF0000"), "hacker")
    assert not b.receive_theme(forged)
    tampered = {"theme": dict(pkg["theme"], v=51), "pub": pkg["pub"], "sig": pkg["sig"]}
    assert not b.receive_theme(tampered)
    assert b.settings.bubble_me == "#123456"
    print("forged / tampered appearance refused ok")

    # the admin publishes again from the same password: version 2 arrives
    a.settings.bubble_me = "#654321"
    assert a.publish_theme("adminpw", lock=False)
    assert wait(lambda: b.settings.theme_version == 2, 15)
    assert b.settings.bubble_me == "#654321" and not b.settings.theme_lock
    # another password cannot publish over it from a pinned machine
    assert b.publish_theme("other", lock=False) is None
    print("re-publish ok, other password refused ok")

    for x in (a, b):
        x.stop()
    print("\nALL UPDATE TESTS PASSED")


if __name__ == "__main__":
    main()
