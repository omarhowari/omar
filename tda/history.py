"""Local chat history (SQLite)."""
from __future__ import annotations

import sqlite3
import time
from typing import List

from .config import config_dir


class History:
    def __init__(self, path=None):
        self.db = sqlite3.connect(str(path or (config_dir() / "history.db")))
        self.db.execute("""CREATE TABLE IF NOT EXISTS messages(
            id TEXT PRIMARY KEY, peer_id TEXT NOT NULL, peer_name TEXT, outgoing INTEGER,
            text TEXT, ts REAL, status TEXT, multi INTEGER DEFAULT 0, kind TEXT DEFAULT 'msg')""")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_peer_ts ON messages(peer_id, ts)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS contacts(
            peer_id TEXT PRIMARY KEY, name TEXT, grp TEXT, last_seen REAL)""")
        self.db.commit()

    def add(self, msg_id, peer_id, peer_name, outgoing, text, ts=None, status="", multi=False, kind="msg"):
        self.db.execute("INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?,?,?)",
                        (msg_id, peer_id, peer_name, int(outgoing), text, ts or time.time(), status, int(multi), kind))
        self.db.commit()

    def set_text(self, msg_id, text):
        self.db.execute("UPDATE messages SET text=? WHERE id=?", (text, msg_id))
        self.db.commit()

    def set_status(self, msg_id, status):
        self.db.execute("UPDATE messages SET status=? WHERE id=?", (status, msg_id))
        self.db.commit()

    def load(self, peer_id, limit=300) -> List[dict]:
        rows = self.db.execute(
            "SELECT id, peer_name, outgoing, text, ts, status, multi, kind FROM messages "
            "WHERE peer_id=? ORDER BY ts DESC LIMIT ?", (peer_id, limit)).fetchall()
        keys = ("id", "peer_name", "outgoing", "text", "ts", "status", "multi", "kind")
        return [dict(zip(keys, r)) for r in reversed(rows)]

    def clear(self, peer_id):
        self.db.execute("DELETE FROM messages WHERE peer_id=?", (peer_id,))
        self.db.commit()

    def remember_contact(self, peer_id, name, group):
        self.db.execute("INSERT OR REPLACE INTO contacts VALUES(?,?,?,?)", (peer_id, name, group, time.time()))
        self.db.commit()

    def contacts(self) -> List[dict]:
        rows = self.db.execute("SELECT peer_id, name, grp, last_seen FROM contacts").fetchall()
        return [dict(zip(("id", "name", "group", "last_seen"), r)) for r in rows]

    def search(self, query, limit=200) -> List[dict]:
        rows = self.db.execute(
            "SELECT peer_id, peer_name, outgoing, text, ts FROM messages WHERE kind='msg' AND text LIKE ? "
            "ORDER BY ts DESC LIMIT ?", (f"%{query}%", limit)).fetchall()
        return [dict(zip(("peer_id", "peer_name", "outgoing", "text", "ts"), r)) for r in rows]
