"""Replies, reactions and delete-for-everyone between two TDA instances.

Run:  python -m tests.test_messages
"""
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["TDA_CONFIG_DIR"] = tempfile.mkdtemp()

from tests.test_network import make, wait  # noqa: E402
from tda.history import History  # noqa: E402


def main():
    tmp = tempfile.mkdtemp()
    a = make("Ali", 48400, 48410, "k", tmp)
    b = make("Bana", 48410, 48400, "k", tmp)
    aid, bid = a.settings.user_id, b.settings.user_id
    assert wait(lambda: bid in a.peers and aid in b.peers)
    inbox, reacts, deleted = [], [], []
    b.message_received.connect(inbox.append)
    a.reaction.connect(reacts.append)
    b.message_deleted.connect(lambda s, m: deleted.append((s, m)))

    m1 = a.send_message(bid, "هل وصل التقرير؟")
    assert wait(lambda: inbox)
    # reply quoting m1
    got = []
    a.message_received.connect(got.append)
    b.send_message(aid, "نعم وصل", reply={"id": m1, "name": "Ali", "text": "هل وصل التقرير؟" * 30})
    assert wait(lambda: got)
    assert got[0]["reply"]["id"] == m1 and len(got[0]["reply"]["text"]) <= 200
    print("reply ok:", got[0]["reply"]["name"])
    # reaction, then change it, then remove it
    b.react(aid, m1, "👍")
    assert wait(lambda: reacts)
    assert reacts[-1]["msg_id"] == m1 and reacts[-1]["emoji"] == "👍" and reacts[-1]["from"] == bid
    b.react(aid, m1, "❤️")
    assert wait(lambda: reacts[-1]["emoji"] == "❤️")
    b.react(aid, m1, "")
    assert wait(lambda: reacts[-1]["emoji"] == "")
    print("reactions ok")
    # forwarded flag
    a.send_message(bid, "نص معاد توجيهه", fwd=True)
    assert wait(lambda: len(inbox) == 2 and inbox[1]["fwd"])
    print("forward flag ok")
    # delete for everyone (private)
    a.delete_message(bid, m1)
    assert wait(lambda: deleted == [(aid, m1)])
    print("delete for everyone ok")
    # group: member deletes own message; reactions in a group reach everybody
    gid = a.create_group("فريق", {bid: "Bana"})
    assert wait(lambda: gid in b.groups)
    greacts, gdel = [], []
    b.reaction.connect(greacts.append)
    b.group_message_deleted.connect(lambda g, m, by: gdel.append((g, m, by)))
    gm = a.send_group_message(gid, "مرحبا بالجميع")
    a.react("g:" + gid, gm, "🙏")
    assert wait(lambda: greacts and greacts[-1]["gid"] == gid and greacts[-1]["emoji"] == "🙏")
    b.delete_message("g:" + gid, "xyz", own=True)      # a member asks to delete his own message
    a_del = []
    a.group_message_deleted.connect(lambda g, m, by: a_del.append((g, m, by)))
    assert wait(lambda: a_del == [(gid, "xyz", bid)])  # delivered; the UI checks it is really his
    assert not b.delete_message("g:" + gid, gm, own=False)   # not admin: cannot delete others' messages
    print("group reactions + own delete ok")

    # history: extra column (and migration of an old database)
    import sqlite3
    old = os.path.join(tmp, "old.db")
    db = sqlite3.connect(old)
    db.execute("CREATE TABLE messages(id TEXT PRIMARY KEY, peer_id TEXT NOT NULL, peer_name TEXT, outgoing INTEGER,"
               " text TEXT, ts REAL, status TEXT, multi INTEGER DEFAULT 0, kind TEXT DEFAULT 'msg')")
    db.execute("INSERT INTO messages VALUES('1','p','n',1,'hi',1,'',0,'msg')")
    db.commit()
    db.close()
    h = History(old)
    assert h.load("p")[0]["extra"] == {}
    h.set_extra("1", {"reactions": {"x": {"e": "👍", "n": "X"}}, "star": True})
    assert h.load("p")[0]["extra"]["star"] and h.get("1")["peer_id"] == "p"
    h.add("2", "p", "n", 0, "yo", extra={"reply": {"id": "1", "name": "n", "text": "hi"}})
    assert h.load("p")[1]["extra"]["reply"]["id"] == "1"
    h.delete("1")
    assert len(h.load("p")) == 1
    print("history extra + old database migration ok")
    for x in (a, b):
        x.stop()
    print("\nMESSAGE FEATURES PASSED")


if __name__ == "__main__":
    main()
