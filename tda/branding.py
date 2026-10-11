"""Custom branding (logo, welcome image, app title) protected by an admin password.

Files live in <config_dir>/branding/ :
    logo.png      square 256x256 version of the chosen logo
    logo.ico      Windows icon (used for shortcuts)
    welcome.png   optional picture for the welcome screen
"""
from __future__ import annotations

import hashlib
import hmac
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap

from .config import Settings, config_dir

_ITER = 200_000


# ---------------------------------------------------------------- admin password
def has_admin_password(s: Settings) -> bool:
    return bool(s.admin_hash)


def set_admin_password(s: Settings, password: str) -> None:
    salt = os.urandom(16)
    s.admin_salt = salt.hex()
    s.admin_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITER).hex()
    s.save()


def check_admin_password(s: Settings, password: str) -> bool:
    if not s.admin_hash:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(s.admin_salt), _ITER).hex()
    return hmac.compare_digest(digest, s.admin_hash)


# ---------------------------------------------------------------- files
def branding_dir() -> Path:
    d = config_dir() / "branding"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logo_path() -> Path:
    return branding_dir() / "logo.png"


def ico_path() -> Path:
    return branding_dir() / "logo.ico"


def welcome_path() -> Path:
    return branding_dir() / "welcome.png"


_cache: dict = {}


def custom_logo() -> Optional[QPixmap]:
    """The custom logo as a pixmap, or None when the default logo is used."""
    p = logo_path()
    if not p.exists():
        return None
    key = ("logo", p.stat().st_mtime)
    if key not in _cache:
        _cache.clear()
        pm = QPixmap(str(p))
        _cache[key] = None if pm.isNull() else pm
    return _cache[key]


def custom_welcome() -> Optional[QPixmap]:
    p = welcome_path()
    if not p.exists():
        return None
    pm = QPixmap(str(p))
    return None if pm.isNull() else pm


def _square(img: QImage, size: int) -> QImage:
    """Fit the image into a transparent square without distorting it."""
    scaled = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    out = QImage(size, size, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    p.end()
    return out


def install_logo(src: str) -> bool:
    img = QImage(src)
    if img.isNull():
        return False
    sq = _square(img, 256)
    if not sq.save(str(logo_path()), "PNG"):
        return False
    _write_ico(sq, ico_path())
    _cache.clear()
    return True


def install_welcome(src: str) -> bool:
    img = QImage(src)
    if img.isNull():
        return False
    if img.width() > 900 or img.height() > 600:
        img = img.scaled(900, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return img.save(str(welcome_path()), "PNG")


def remove_logo():
    for p in (logo_path(), ico_path()):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    _cache.clear()


def remove_welcome():
    try:
        welcome_path().unlink()
    except FileNotFoundError:
        pass


def _write_ico(img: QImage, dest: Path):
    """Write a multi-size .ico (PNG-compressed entries, supported since Windows Vista)."""
    import struct
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    sizes = (16, 24, 32, 48, 64, 128, 256)
    blobs = []
    for s in sizes:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(buf, "PNG")
        buf.close()
        blobs.append(bytes(ba))
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, data in zip(sizes, blobs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    dest.write_bytes(header + entries + b"".join(blobs))


# ---------------------------------------------------------------- Windows shortcuts
def installed_exe() -> str:
    """Path of TDA.exe (the launcher embeds Python, so sys.executable is TDA.exe itself)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "tda.exe":
        return str(exe)
    return str(Path(__file__).resolve().parents[2] / "TDA.exe")


def update_shortcut_icons():
    """Point the TDA desktop / Start-menu shortcuts at the custom icon (or back to TDA.exe)."""
    if sys.platform != "win32":
        return
    exe = installed_exe()
    icon = f"{ico_path()},0" if ico_path().exists() else f"{exe},0"
    links = []
    for loc in (QStandardPaths.StandardLocation.DesktopLocation, QStandardPaths.StandardLocation.ApplicationsLocation):
        base = Path(QStandardPaths.writableLocation(loc))
        links += [base / "TDA.lnk", base / "TDA" / "TDA.lnk"]
    public = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop" / "TDA.lnk"
    links.append(public)
    script = []
    for lnk in links:
        if lnk.exists():
            p = str(lnk).replace("'", "''")
            script.append(f"$s=$w.CreateShortcut('{p}'); $s.IconLocation='{icon}'; $s.Save()")
    if not script:
        return
    cmd = "$w=New-Object -ComObject WScript.Shell; " + "; ".join(script) + "; ie4uinit.exe -show"
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", cmd],
                         creationflags=0x08000000)  # CREATE_NO_WINDOW
    except OSError:
        pass
