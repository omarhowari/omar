"""Unit tests for group permission rules (no network)."""
from tda import groups as G

g = G.normalize({"gid": "g1", "name": "T", "owner": "o", "admins": ["o", "a", "b"], "version": 1,
                 "members": {"o": "Owner", "a": "Admin", "b": "Admin2", "m": "Member", "x": "Other"}})
assert G.role(g, "o") == "owner" and G.role(g, "a") == "admin" and G.role(g, "m") == "member"
assert G.can(g, "m", "write") and not G.can(g, "m", "edit") and not G.can(g, "m", "add")


def upd(**ch):
    n = dict(g, **ch)
    n["version"] = g["version"] + 1
    return G.normalize(n)


assert G.update_allowed(g, upd(name="New"), "a")
assert not G.update_allowed(g, upd(name="New"), "m")
assert not G.update_allowed(g, upd(admins=["o", "a"]), "a")        # admin demoting another admin: owner only
assert G.update_allowed(g, upd(admins=["o", "b"]), "a")            # an admin may step down
assert G.update_allowed(g, upd(admins=["o"]), "o")
assert not G.update_allowed(g, upd(owner="a"), "a")
assert not G.update_allowed(g, upd(members={"a": "A", "b": "B", "m": "M", "x": "X"}), "a")   # removing the owner
stale = dict(upd(name="x"))
stale["version"] = 1
assert not G.update_allowed(g, stale, "o")                         # old versions are ignored
r = upd(restricted={"m": {"write": True}})
assert not G.can(r, "m", "write") and G.can(r, "m", "media") and G.can(r, "m", "call")
s = upd(settings={"send": "admins", "add": "all"})
assert not G.can(s, "m", "write") and G.can(s, "a", "write") and G.can(s, "m", "add")
added = dict(s, members=dict(s["members"], y="New guy"), version=s["version"] + 1)
assert G.update_allowed(s, G.normalize(added), "m")                # members may add when add = all
left = G.after_leave(g, "o")
assert left["owner"] == "a" and "o" not in left["members"]
print("GROUP RULES OK")
