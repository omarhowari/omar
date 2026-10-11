"""Appearance published by the administrator to every TDA on the network.

The administrator's password (the one protecting "Branding") deterministically derives an Ed25519
signing key, so any admin who knows that password can publish from any computer. Each TDA pins the
public key the first time it accepts a theme (trust on first use) and from then on only applies
themes signed by the same key - ordinary users cannot change everybody's appearance.

theme = {"v": version, "ts": time, "by": name, "lock": bool,
         "app_title": str, "chat_bg": "pattern|image|none", "chat_bg_opacity": int,
         "bubble_me": "#rrggbb", "bubble_them": "#rrggbb", "font_pt": float,
         "logo": base64 PNG | "", "welcome": base64 PNG | "", "bg_image": base64 JPEG | ""}
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .config import Settings, config_dir

MAX_IMAGE = 1_500_000
APPEARANCE_KEYS = ("app_title", "chat_bg", "chat_bg_opacity", "bubble_me", "bubble_them", "font_pt")


def _canonical(theme: dict) -> bytes:
    return json.dumps(theme, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def key_from_password(password: str) -> Ed25519PrivateKey:
    seed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), b"TDA-appearance-key/v1", 200_000, 32)
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def _b64_file(path: str, limit: int = MAX_IMAGE) -> str:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return ""
    return base64.b64encode(data).decode() if len(data) <= limit else ""


def build(s: Settings, version: int, lock: bool) -> dict:
    """The administrator's current appearance, ready to publish."""
    from . import branding
    t = {k: getattr(s, k) for k in APPEARANCE_KEYS}
    t.update({"v": version, "ts": time.time(), "by": s.name, "lock": bool(lock),
              "logo": _b64_file(str(branding.logo_path())) if branding.logo_path().exists() else "",
              "welcome": _b64_file(str(branding.welcome_path())) if branding.welcome_path().exists() else "",
              "bg_image": _b64_file(s.chat_bg_image) if s.chat_bg == "image" and s.chat_bg_image else ""})
    return t


def sign(theme: dict, password: str) -> dict:
    key = key_from_password(password)
    return {"theme": theme, "pub": public_hex(key), "sig": key.sign(_canonical(theme)).hex()}


def verify(package: dict, pinned: str) -> Optional[dict]:
    """Returns the theme if the signature is valid and the key is the pinned one (or nothing is pinned yet)."""
    try:
        theme, pub, sig = package["theme"], str(package["pub"]), str(package["sig"])
        if pinned and pub != pinned:
            return None
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub)).verify(bytes.fromhex(sig), _canonical(theme))
        return theme if isinstance(theme, dict) else None
    except (KeyError, ValueError, TypeError, InvalidSignature):
        return None


def apply(theme: dict, s: Settings) -> None:
    """Write the published appearance into the local settings and branding files."""
    from . import branding
    for k in APPEARANCE_KEYS:
        if k in theme:
            setattr(s, k, type(getattr(s, k))(theme[k]))
    d = config_dir() / "theme"
    d.mkdir(parents=True, exist_ok=True)
    if theme.get("bg_image"):
        p = d / "background.img"
        p.write_bytes(base64.b64decode(theme["bg_image"]))
        s.chat_bg_image = str(p)
    for field, install, remove in (("logo", branding.install_logo, branding.remove_logo),
                                   ("welcome", branding.install_welcome, branding.remove_welcome)):
        if theme.get(field):
            p = d / f"{field}.png"
            p.write_bytes(base64.b64decode(theme[field]))
            install(str(p))
        else:
            remove()
    s.theme_version = int(theme.get("v", 0))
    s.theme_lock = bool(theme.get("lock"))
    s.save()
