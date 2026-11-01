#!/bin/sh
set -eu

DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
BIN_HOME=${XDG_BIN_HOME:-"$HOME/.local/bin"}
PREFIX="$DATA_HOME/video-upscaler"
MARKER="$PREFIX/.owned-by-universal-linux-video-upscaler"
MANIFEST="$PREFIX/install-manifest.txt"

if [ ! -f "$MARKER" ] || [ ! -f "$MANIFEST" ]; then
    printf 'Managed installation marker or manifest is missing; nothing was removed.\n' >&2
    exit 1
fi

allowed_data="$DATA_HOME/"
allowed_bin="$BIN_HOME/"
while IFS= read -r path; do
    case "$path" in
        "$allowed_data"*|"$allowed_bin"*) ;;
        *) printf 'Unsafe manifest entry; stopped before removing it: %s\n' "$path" >&2; exit 1 ;;
    esac
done < "$MANIFEST"

while IFS= read -r path; do
    [ -e "$path" ] || continue
    if [ -f "$path" ] || [ -L "$path" ]; then
        unlink -- "$path"
    fi
done < "$MANIFEST"

# Python creates these only from application-owned source files after install.
# They are intentionally not present in the install manifest.
if [ -d "$PREFIX/app" ]; then
    find "$PREFIX/app" -type f \( -name '*.pyc' -o -name '*.pyo' \) -exec unlink -- {} \;
    find "$PREFIX/app" -depth -type d -name __pycache__ -empty -exec rmdir -- {} \;
fi

find "$PREFIX" -depth -type d -empty -exec rmdir -- {} \; 2>/dev/null || true
if [ -d "$PREFIX" ]; then
    printf '%s\n' 'Universal Linux Video Upscaler data root; user-supplied files retained' > "$MARKER"
fi
for directory in "$DATA_HOME/kio/servicemenus" "$DATA_HOME/nautilus/scripts" \
                 "$DATA_HOME/nautilus-python/extensions"; do
    [ ! -d "$directory" ] || rmdir --ignore-fail-on-non-empty -- "$directory" 2>/dev/null || true
done
if [ "${VIDEO_UPSCALER_SKIP_DESKTOP_CACHE:-0}" != 1 ] && command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null || true
fi
printf '%s\n' 'Universal Linux Video Upscaler application-owned files removed.'
