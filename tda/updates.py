"""In-place updates over the LAN (no uninstall, no internet).

Every installed TDA keeps a copy of the installer it was installed with in <install dir>\\setup\\TDA-Setup.exe.
It announces its version; when a computer sees a colleague with a newer version it offers the user an
update, downloads that installer from the colleague over the encrypted LAN connection, and runs it silently
(/S): the installer closes TDA, replaces the program files (settings, history and groups are kept in the
user's AppData folder and are not touched) and starts the new version again.
So the administrator only installs the new version on ONE computer, and it spreads to everybody.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

SETUP_NAME = "TDA-Setup.exe"
MAX_SETUP = 400 * 1024 * 1024


def version_tuple(v: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def newer(a: str, b: str) -> bool:
    """True when version a is newer than version b."""
    return version_tuple(a) > version_tuple(b)


def install_dir() -> Path:
    # <install dir>\app\tda\updates.py
    return Path(__file__).resolve().parent.parent.parent


def update_package() -> Optional[Path]:
    """The installer of the running version, if this is an installed copy on Windows."""
    override = os.environ.get("TDA_SETUP_PATH")
    p = Path(override) if override else install_dir() / "setup" / SETUP_NAME
    try:
        return p if p.is_file() and 0 < p.stat().st_size <= MAX_SETUP else None
    except OSError:
        return None


def looks_like_installer(path: str) -> bool:
    """A Windows program built with NSIS (what TDA-Setup.exe is)."""
    try:
        with open(path, "rb") as f:
            head = f.read(2)
            if head != b"MZ":
                return False
            f.seek(0)
            data = f.read(256 * 1024)
        return b"Nullsoft" in data or b"NSIS" in data
    except OSError:
        return False


def run_installer(path: str, silent: bool = True) -> bool:
    """Start the installer. Silent mode keeps all choices and restarts TDA when finished.
    Windows asks once for administrator permission (UAC) because the program is in Program Files."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        args = "/S /UPDATE" if silent else ""
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(path), args, str(Path(path).parent), 1)
        return int(r) > 32
    except Exception:
        try:
            os.startfile(str(path))          # type: ignore[attr-defined]
            return True
        except Exception:
            return False
