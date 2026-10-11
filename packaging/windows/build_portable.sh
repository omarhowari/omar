#!/usr/bin/env bash
# Cross-build a portable Windows x64 TDA folder + installer from Linux.
#   needs: gcc-mingw-w64-x86-64, nsis, pip;  inputs: an official Python 3.13 embeddable zip
#   usage: packaging/windows/build_portable.sh <python-3.13-embed-amd64 dir> <out dir>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EMB="$1"; OUT="$2"
APP="$OUT/TDA"
rm -rf "$APP"; mkdir -p "$APP/Lib/site-packages" "$APP/app"

cp -r "$EMB"/* "$APP/"
printf 'python313.zip\n.\nLib\\site-packages\napp\n' > "$APP/python313._pth"

WHL="$OUT/wheels"; mkdir -p "$WHL"
pip download -q --only-binary=:all: --platform win_amd64 --python-version 3.13 --implementation cp \
    -d "$WHL" -r "$ROOT/requirements.txt"
for w in "$WHL"/*.whl; do unzip -q -o "$w" -d "$APP/Lib/site-packages"; done

# --- trim Qt: keep only what a widgets + network app needs
P="$APP/Lib/site-packages/PySide6"
rm -rf "$P"/{qml,include,typesystems,glue,scripts,examples,doc,metatypes,resources} "$P"/*.exe "$P"/opengl32sw.dll
find "$P" -maxdepth 1 -name 'Qt6*.dll' | grep -vE 'Qt6(Core|Gui|Widgets|Network|Svg)\.dll$' | xargs -r rm -f
find "$P" -maxdepth 1 \( -name 'Qt*.pyd' -o -name 'Qt*.pyi' \) | grep -vE '/Qt(Core|Gui|Widgets|Network)\.pyd$' | xargs -r rm -f
find "$P/translations" -type f ! -name 'qtbase_ar.qm' ! -name 'qtbase_en.qm' -delete 2>/dev/null || true
rm -rf "$P/plugins"/{qmltooling,designer,sqldrivers,multimedia,position,sensors,canvasparts,assetimporters,renderers,sceneparsers,geometryloaders,virtualkeyboard,webview,scxmldatamodel,generic,platforminputcontexts,egldeviceintegrations,xcbglintegrations,wayland*}
find "$APP/Lib/site-packages" -name '*.pyi' -delete
PA="$APP/Lib/site-packages/_sounddevice_data/portaudio-binaries"
[ -d "$PA" ] && find "$PA" -type f ! -name 'libportaudio64bit.dll' ! -name 'README.md' -delete
find "$APP/Lib/site-packages" -name '__pycache__' -prune -exec rm -rf {} +

cp -r "$ROOT/main.py" "$ROOT/tda" "$ROOT/assets" "$APP/app/"
find "$APP/app" -name '__pycache__' -prune -exec rm -rf {} +
cp "$ROOT/LICENSE" "$APP/LICENSE.txt"

# --- launcher exe
B="$OUT/build"; mkdir -p "$B"
cp "$ROOT/packaging/windows/"{launcher.c,launcher.rc,app.manifest} "$ROOT/assets/tda.ico" "$B/"
(cd "$B" && x86_64-w64-mingw32-windres launcher.rc -O coff -o res.o \
   && x86_64-w64-mingw32-gcc -O2 -municode -mwindows -static -o "$APP/TDA.exe" launcher.c res.o -lshell32)

# --- portable zip + installer
(cd "$OUT" && rm -f TDA-portable.zip && zip -q -r -9 TDA-portable.zip TDA)
makensis -V2 -DSRC="$APP" -DOUTFILE="$OUT/TDA-Setup.exe" -DICON="$ROOT/assets/tda.ico" \
         -DLICENSE="$ROOT/LICENSE" "$ROOT/packaging/windows/installer.nsi"
ls -la "$OUT"
