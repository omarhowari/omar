#!/usr/bin/env bash
# Cross-build the portable Windows x64 TDA folder + installer from Linux (also used by GitHub Actions).
#   needs: python3 + pip, gcc-mingw-w64-x86-64, nsis, zip
#   usage: packaging/windows/build_portable.sh [out dir] [python-3.13 embeddable dir/zip (downloaded if omitted)]
#   (old order "<embed dir> <out dir>" is still accepted)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ $# -ge 2 ] && [ -f "$1/python313.dll" ]; then EMB="$1"; OUT="$2"; else OUT="${1:-$ROOT/dist}"; EMB="${2:-}"; fi
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
APP="$OUT/TDA"

python3 "$ROOT/packaging/windows/assemble.py" "$OUT" "$EMB"

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
