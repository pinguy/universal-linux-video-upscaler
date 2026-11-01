#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
BIN_HOME=${XDG_BIN_HOME:-"$HOME/.local/bin"}
PREFIX="$DATA_HOME/video-upscaler"
APP_DIR="$PREFIX/app"
LAUNCHER="$BIN_HOME/video-upscaler"
UNINSTALLER="$BIN_HOME/video-upscaler-uninstall"
MARKER="$PREFIX/.owned-by-universal-linux-video-upscaler"
MANIFEST="$PREFIX/install-manifest.txt"
DESKTOP_MODE=auto
NAUTILUS_EXTENSION=0

for arg in "$@"; do
    case "$arg" in
        --desktop=auto|--desktop=all|--desktop=kde|--desktop=gnome|--desktop=none)
            DESKTOP_MODE=${arg#--desktop=} ;;
        --nautilus-extension) NAUTILUS_EXTENSION=1 ;;
        -h|--help)
            printf '%s\n' 'Usage: ./install.sh [--desktop=auto|all|kde|gnome|none] [--nautilus-extension]'
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

if [ -e "$PREFIX" ] && [ ! -f "$MARKER" ]; then
    printf 'Refusing to use unowned path: %s\n' "$PREFIX" >&2
    exit 1
fi
if [ -e "$LAUNCHER" ] && ! grep -q 'Universal Linux Video Upscaler' "$LAUNCHER" 2>/dev/null; then
    printf 'Refusing to replace unrelated launcher: %s\n' "$LAUNCHER" >&2
    exit 1
fi

install -d "$APP_DIR" "$BIN_HOME"
printf '%s\n' 'Universal Linux Video Upscaler managed installation' > "$MARKER"
python3 - "$ROOT" "$APP_DIR" <<'PY'
from pathlib import Path
import shutil
import sys

source, target = map(Path, sys.argv[1:])
ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git", ".pytest_cache")
for name in ("src", "integrations", "docs", "screenshots"):
    shutil.copytree(source / name, target / name, dirs_exist_ok=True, ignore=ignore)
for name in ("pyproject.toml", "README.md", "LICENSE", "THIRD_PARTY.md",
             "requirements-cpu.txt", "uninstall.sh"):
    shutil.copy2(source / name, target / name)
PY

cat > "$LAUNCHER" <<EOF
#!/bin/sh
# Universal Linux Video Upscaler managed launcher
set -eu
APP_DIR=\${XDG_DATA_HOME:-"\$HOME/.local/share"}/video-upscaler/app
PYTHONPATH="\$APP_DIR/src\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m video_upscaler "\$@"
EOF
chmod 0755 "$LAUNCHER"

cat > "$UNINSTALLER" <<EOF
#!/bin/sh
# Universal Linux Video Upscaler managed uninstaller
set -eu
APP_DIR=\${XDG_DATA_HOME:-"\$HOME/.local/share"}/video-upscaler/app
exec "\$APP_DIR/uninstall.sh" "\$@"
EOF
chmod 0755 "$UNINSTALLER"

want_kde=0
want_gnome=0
case "$DESKTOP_MODE" in
    all) want_kde=1; want_gnome=1 ;;
    kde) want_kde=1 ;;
    gnome) want_gnome=1 ;;
    auto)
        command -v dolphin >/dev/null 2>&1 && want_kde=1
        if command -v nautilus >/dev/null 2>&1 || [ -d "$DATA_HOME/nautilus/scripts" ]; then
            want_gnome=1
        fi ;;
esac

desktop_exec=$(python3 - "$LAUNCHER" <<'PY'
import sys
value = sys.argv[1].replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
print('"' + value + '"')
PY
)

KDE_MENU="$DATA_HOME/kio/servicemenus/video-upscaler.desktop"
NAUTILUS_SCRIPT="$DATA_HOME/nautilus/scripts/Upscale Video…"
NAUTILUS_EXT="$DATA_HOME/nautilus-python/extensions/video_upscaler_nautilus.py"
if [ "$want_kde" -eq 1 ]; then
    install -d "$(dirname -- "$KDE_MENU")"
    python3 - "$ROOT/integrations/kde/upscale-video.desktop.in" "$KDE_MENU" "$desktop_exec" <<'PY'
from pathlib import Path
import sys
source, target, executable = sys.argv[1:]
Path(target).write_text(Path(source).read_text().replace('@EXEC@', executable))
PY
    if [ "${VIDEO_UPSCALER_SKIP_DESKTOP_CACHE:-0}" != 1 ] && command -v kbuildsycoca6 >/dev/null 2>&1; then
        kbuildsycoca6 --noincremental >/dev/null
    fi
fi
if [ "$want_gnome" -eq 1 ]; then
    install -d "$(dirname -- "$NAUTILUS_SCRIPT")"
    python3 - "$ROOT/integrations/nautilus/Upscale Video…" "$NAUTILUS_SCRIPT" "$desktop_exec" <<'PY'
from pathlib import Path
import sys
source, target, executable = sys.argv[1:]
Path(target).write_text(Path(source).read_text().replace('@EXEC@', executable))
PY
    chmod 0755 "$NAUTILUS_SCRIPT"
fi
if [ "$NAUTILUS_EXTENSION" -eq 1 ]; then
    if ! python3 -c 'import gi; gi.require_version("Nautilus", "4.0")' 2>/dev/null; then
        printf '%s\n' 'python-nautilus/Nautilus 4 bindings are unavailable; baseline Nautilus Script was retained.' >&2
        NAUTILUS_EXTENSION=0
    else
        install -Dm0644 "$ROOT/integrations/nautilus/video_upscaler_nautilus.py" "$NAUTILUS_EXT"
    fi
fi

{
    find "$APP_DIR" -type f -print
    printf '%s\n' "$LAUNCHER" "$UNINSTALLER" "$MARKER"
    [ "$want_kde" -eq 0 ] || printf '%s\n' "$KDE_MENU"
    [ "$want_gnome" -eq 0 ] || printf '%s\n' "$NAUTILUS_SCRIPT"
    [ "$NAUTILUS_EXTENSION" -eq 0 ] || printf '%s\n' "$NAUTILUS_EXT"
    printf '%s\n' "$MANIFEST"
} > "$MANIFEST"

printf 'Installed launcher: %s\n' "$LAUNCHER"
[ "$want_kde" -eq 0 ] || printf 'Installed KDE action: %s\n' "$KDE_MENU"
[ "$want_gnome" -eq 0 ] || printf 'Installed Nautilus Script: %s\n' "$NAUTILUS_SCRIPT"
printf 'Run: %s doctor\n' "$LAUNCHER"
