"""Group roles and permissions (WhatsApp / Telegram style).

group = {
  "gid", "name", "desc", "owner", "version",
  "admins":   [user ids],                       # the owner is always an admin
  "members":  {user id: name},
  "settings": {"send": "all" | "admins",        # who may send messages and media
               "edit": "all" | "admins",        # who may change name / description
               "add":  "all" | "admins"},       # who may add members
  "restricted": {user id: {"write": bool, "media": bool, "call": bool}},   # True = blocked
}

Every computer enforces the rules itself: messages, files and calls from a member who is not
allowed are dropped by the receivers, and updates from someone who may not make them are ignored.
"""
from __future__ import annotations

import copy
from typing import Optional

DEFAULT_SETTINGS = {"send": "all", "edit": "admins", "add": "admins"}
RESTRICTIONS = ("write", "media", "call")


def normalize(g: dict) -> dict:
    """Fill in fields missing from groups created by older versions and sanitize types."""
    g = copy.deepcopy(g)
    members = {str(k)[:64]: str(v)[:64] for k, v in list((g.get("members") or {}).items())[:5000]}
    owner = str(g.get("owner", ""))[:64]
    if owner not in members and members:
        owner = sorted(members)[0]
    admins = [str(a)[:64] for a in (g.get("admins") or []) if str(a) in members]
    if owner and owner not in admins:
        admins.insert(0, owner)
    settings = dict(DEFAULT_SETTINGS)
    for k, v in (g.get("settings") or {}).items():
        if k in DEFAULT_SETTINGS and v in ("all", "admins"):
            settings[k] = v
    restricted = {}
    for uid, flags in (g.get("restricted") or {}).items():
        if uid in members and isinstance(flags, dict):
            f = {r: bool(flags.get(r)) for r in RESTRICTIONS}
            if any(f.values()):
                restricted[uid] = f
    return {"gid": str(g.get("gid", ""))[:64], "name": str(g.get("name", "?"))[:80],
            "desc": str(g.get("desc", ""))[:500], "owner": owner, "version": int(g.get("version", 0) or 0),
            "author": str(g.get("author", ""))[:64],
            "admins": admins, "members": members, "settings": settings, "restricted": restricted}


def role(g: dict, uid: str) -> str:
    if uid == g.get("owner"):
        return "owner"
    if uid in g.get("admins", []):
        return "admin"
    return "member" if uid in g.get("members", {}) else "none"


def is_admin(g: dict, uid: str) -> bool:
    return role(g, uid) in ("owner", "admin")


def can(g: dict, uid: str, action: str) -> bool:
    """action: write | media | call | edit | add | manage"""
    if uid not in g.get("members", {}):
        return False
    if is_admin(g, uid):
        return True
    st = g.get("settings", DEFAULT_SETTINGS)
    blocked = g.get("restricted", {}).get(uid, {})
    if action in ("write", "media"):
        return st.get("send") == "all" and not blocked.get(action)
    if action == "call":
        return not blocked.get("call")
    if action == "edit":
        return st.get("edit") == "all"
    if action == "add":
        return st.get("add") == "all"
    return False      # manage: admins only


def update_allowed(cur: Optional[dict], new: dict, sender: str) -> bool:
    """May `sender` turn group `cur` into `new`?"""
    if cur is None:
        return True                       # first time we hear about the group
    # (version, author) is a total order: when two admins edit at the same moment every computer
    # keeps the same winner, so all copies of the group converge
    if (new["version"], new.get("author", "")) <= (cur["version"], cur.get("author", "")):
        return False
    if is_admin(cur, sender):
        # only the owner may demote other admins or change ownership
        if new["owner"] != cur["owner"] and sender != cur["owner"]:
            return False
        removed_admins = set(cur["admins"]) - set(new["admins"]) - {sender}
        if removed_admins and sender != cur["owner"]:
            return False
        if cur["owner"] not in new["members"] and sender != cur["owner"]:
            return False                  # nobody can remove the owner
        return True
    if sender not in cur["members"]:
        return False
    # a normal member: may only change what the group settings allow, nothing else
    same = lambda k: new.get(k) == cur.get(k)
    if not (same("owner") and same("admins") and same("settings") and same("restricted")):
        return False
    added = set(new["members"]) - set(cur["members"])
    removed = set(cur["members"]) - set(new["members"])
    if removed:
        return False
    if added and not can(cur, sender, "add"):
        return False
    if (not same("name") or not same("desc")) and not can(cur, sender, "edit"):
        return False
    return True


def after_leave(g: dict, uid: str) -> dict:
    """Remove a member; if the owner leaves, the longest-standing admin (or member) takes over."""
    g = copy.deepcopy(g)
    g["members"].pop(uid, None)
    g["restricted"].pop(uid, None)
    if uid in g["admins"]:
        g["admins"].remove(uid)
    if g["owner"] == uid:
        nxt = [a for a in g["admins"] if a in g["members"]] or sorted(g["members"])
        g["owner"] = nxt[0] if nxt else ""
        if g["owner"] and g["owner"] not in g["admins"]:
            g["admins"].insert(0, g["owner"])
    g["version"] += 1
    g["author"] = ""          # applied identically by every remaining member
    return g
