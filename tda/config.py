"""User settings stored as JSON in the per-user application data folder."""
from __future__ import annotations

import getpass
import json
import os
import socket
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_UDP_PORT = 47100
DEFAULT_TCP_PORT = 47101


def config_dir() -> Path:
    override = os.environ.get("TDA_CONFIG_DIR")
    if override:
        p = Path(override)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home())) / "TDA"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "TDA"
    else:
        p = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tda"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _default_name() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return socket.gethostname()


def _default_downloads() -> str:
    d = Path.home() / "Downloads" / "TDA"
    return str(d)


@dataclass
class Settings:
    user_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = field(default_factory=_default_name)
    group: str = "General"
    status: str = "available"
    language: str = "ar"
    download_dir: str = field(default_factory=_default_downloads)
    password: str = ""                      # shared network key (empty = no encryption)
    extra_hosts: list = field(default_factory=list)  # "ip" or "ip:udpport" for other subnets
    udp_port: int = DEFAULT_UDP_PORT
    tcp_port: int = DEFAULT_TCP_PORT
    auto_away_minutes: int = 10
    notify: bool = True
    sound: bool = True
    start_minimized: bool = False
    autostart: bool = False
    app_title: str = ""                     # custom name shown in the title bar (branding)
    admin_hash: str = ""                    # PBKDF2 hash of the branding/admin password
    admin_salt: str = ""
    setup_done: bool = False                # first-run name/department asked
    chat_bg: str = "pattern"                # "pattern" | "image" | "none"
    chat_bg_image: str = ""
    chat_bg_opacity: int = 80               # 0..100
    auto_images: bool = True                # accept incoming pictures automatically (like WhatsApp)
    bubble_me: str = "#D9FDD3"              # colour of my message bubbles
    bubble_them: str = "#FFFFFF"            # colour of the other person's bubbles
    bubble_border: bool = True              # thin outline around the bubbles
    font_pt: float = 10.5                   # chat text size
    theme_version: int = 0                  # version of the administrator's published appearance
    theme_lock: bool = False                # the administrator locked the appearance
    theme_pin: str = ""                     # public key of the administrator (trusted on first use)
    favorites: list = field(default_factory=list)      # chat keys pinned at the top of the list
    muted: dict = field(default_factory=dict)          # chat key -> muted until (epoch s, -1 = always)
    blocked: list = field(default_factory=list)        # user ids whose messages/files/calls are refused
    disappear: dict = field(default_factory=dict)      # chat key -> seconds after which messages vanish
    update_auto: bool = True                # tell me when a colleague has a newer TDA

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        except FileNotFoundError:
            s.save()
        except Exception:
            pass
        return s

    def save(self) -> None:
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path())
