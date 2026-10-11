"""Assemble the portable Windows x64 TDA folder (works on Windows, Linux and macOS).

    python packaging/windows/assemble.py <out dir> [python-3.13 embeddable folder or .zip]

Result: <out dir>/TDA  = official embeddable Python 3.13 + PySide6/cryptography/sounddevice wheels
(trimmed to what TDA uses) + the TDA source in TDA/app.  TDA.exe (launcher) and the installer are
then made by build_portable.sh (Linux) or build_windows.ps1 (Windows / Visual Studio).
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PY_VER = "3.13.0"
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip"
ROOT = Path(__file__).resolve().parents[2]
KEEP_DLL = re.compile(r"Qt6(Core|Gui|Widgets|Network|Svg)\.dll$")
KEEP_PYD = re.compile(r"Qt(Core|Gui|Widgets|Network)\.pyd$")
DROP_DIRS = ["qml", "include", "typesystems", "glue", "scripts", "examples", "doc", "metatypes", "resources"]
DROP_PLUGINS = ["qmltooling", "designer", "sqldrivers", "multimedia", "position", "sensors", "canvasparts",
                "assetimporters", "renderers", "sceneparsers", "geometryloaders", "virtualkeyboard", "webview",
                "scxmldatamodel", "generic", "platforminputcontexts", "egldeviceintegrations",
                "xcbglintegrations"]


def pip_download(dest: Path, *args):
    subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "--only-binary=:all:",
                           "--platform", "win_amd64", "--python-version", "3.13", "--implementation", "cp",
                           "-d", str(dest), *args])


def rm(p: Path):
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists():
        p.unlink()


def main():
    out = Path(sys.argv[1]).resolve()
    emb = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else ""
    app = out / "TDA"
    rm(app)
    (app / "Lib" / "site-packages").mkdir(parents=True)
    (app / "app").mkdir()
    out.mkdir(parents=True, exist_ok=True)

    # 1) the official embeddable Python
    if not emb:
        emb = str(out / f"python-{PY_VER}-embed-amd64.zip")
        if not os.path.exists(emb):
            print("downloading", EMBED_URL)
            urllib.request.urlretrieve(EMBED_URL, emb)
    if os.path.isdir(emb):
        shutil.copytree(emb, app, dirs_exist_ok=True)
    else:
        zipfile.ZipFile(emb).extractall(app)
    (app / "python313._pth").write_text("python313.zip\n.\nLib\\site-packages\napp\n", encoding="ascii")

    # 2) Windows wheels
    whl = out / "wheels"
    whl.mkdir(exist_ok=True)
    pip_download(whl, "-r", str(ROOT / "requirements.txt"))
    site = app / "Lib" / "site-packages"
    for w in glob.glob(str(whl / "*.whl")):
        zipfile.ZipFile(w).extractall(site)

    # 3) trim Qt to a widgets + network app
    P = site / "PySide6"
    for d in DROP_DIRS:
        rm(P / d)
    for f in list(P.glob("*.exe")) + [P / "opengl32sw.dll"]:
        rm(f)
    for f in P.glob("Qt6*.dll"):
        if not KEEP_DLL.search(f.name):
            rm(f)
    for f in list(P.glob("Qt*.pyd")) + list(P.glob("Qt*.pyi")):
        if not KEEP_PYD.search(f.name):
            rm(f)
    for f in (P / "translations").glob("*") if (P / "translations").exists() else []:
        if f.name not in ("qtbase_ar.qm", "qtbase_en.qm"):
            rm(f)
    for d in DROP_PLUGINS:
        rm(P / "plugins" / d)
    for d in (P / "plugins").glob("wayland*"):
        rm(d)
    for f in site.rglob("*.pyi"):
        rm(f)
    pa = site / "_sounddevice_data" / "portaudio-binaries"
    if pa.exists():
        for f in pa.iterdir():
            if f.name not in ("libportaudio64bit.dll", "README.md"):
                rm(f)
    for d in list(site.rglob("__pycache__")):
        rm(d)

    # 4) camera: only Qt Multimedia + the Windows Media Foundation backend (no FFmpeg)
    ess = glob.glob(str(whl / "pyside6_essentials-*.whl"))[0]
    qtv = re.search(r"essentials-([0-9.]+)-", ess).group(1)
    pip_download(whl / "addons", "--no-deps", f"PySide6-Addons=={qtv}")
    addons = zipfile.ZipFile(glob.glob(str(whl / "addons" / "pyside6_addons-*.whl"))[0])
    for name in ("PySide6/Qt6Multimedia.dll", "PySide6/QtMultimedia.pyd",
                 "PySide6/plugins/multimedia/windowsmediaplugin.dll"):
        addons.extract(name, site)

    # 5) TDA itself
    shutil.copy2(ROOT / "main.py", app / "app" / "main.py")
    for d in ("tda", "assets"):
        shutil.copytree(ROOT / d, app / "app" / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "LICENSE", app / "LICENSE.txt")
    print("assembled", app)


if __name__ == "__main__":
    main()
