#!/usr/bin/env bash
# Installiert continuum als LaunchAgent (Tick alle 10 Minuten).
# Das Paket wird nach ~/.local/share/continuum kopiert. Nach git pull oder
# einem Plugin-Update dieses Skript erneut ausfuehren.
set -euo pipefail

if [ "$(uname)" != "Darwin" ]; then
    echo "continuum installs only on macOS (found: $(uname))." >&2
    exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="dev.continuum.agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BIN="$HOME/.local/bin/continuum"
APP="$HOME/.local/share/continuum"
TMP_APP="$HOME/.local/share/.continuum.tmp.$$"
PYTHON="${CONTINUUM_PYTHON:-$(command -v python3 || true)}"
OLD="$HOME/.local/share/.continuum.old.$$"

sed_escape() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }

if [ -z "$PYTHON" ]; then
    echo "python3 not found. Set the path with CONTINUUM_PYTHON." >&2
    exit 1
fi

# Ein venv-Interpreter verschwindet mit dem venv. Dann den Basis-Interpreter nehmen.
if [ -z "${CONTINUUM_PYTHON:-}" ] && [ -n "${VIRTUAL_ENV:-}" ]; then
    VENV_REAL="$(cd "$VIRTUAL_ENV" 2>/dev/null && pwd -P || echo "$VIRTUAL_ENV")"
    case "$PYTHON" in
        "$VIRTUAL_ENV"/*|"$VENV_REAL"/*)
            # Manche Python-Builds melden den venv-Pfad selbst. Dann ueber base_prefix gehen.
            BASE="$("$PYTHON" -c 'import os, sys
b = sys._base_executable
if os.path.abspath(b).startswith(os.path.realpath(sys.prefix) + os.sep):
    b = os.path.join(sys.base_prefix, "bin", "python%d.%d" % sys.version_info[:2])
print(b)' 2>/dev/null || true)"
            if [ -n "$BASE" ] && [ -x "$BASE" ]; then
                PYTHON="$BASE"
            else
                echo "Warning: $PYTHON lies inside the virtual environment $VIRTUAL_ENV." >&2
                echo "The agent will break when you remove the venv. CONTINUUM_PYTHON overrides it." >&2
            fi
            ;;
    esac
fi

if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    echo "Python at $PYTHON is missing or older than 3.9. Set a valid path with CONTINUUM_PYTHON." >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.local/bin" "$HOME/.local/share" "$HOME/.local/state/continuum"

# Reste abgebrochener Laeufe entfernen.
rm -rf "$HOME"/.local/share/.continuum.tmp.* "$HOME"/.local/share/.continuum.old.*

# Bei Abbruch: Temp-Verzeichnis loeschen. Ist der Austausch halb fertig, das alte Paket zurueckholen.
cleanup() {
    rm -rf "$TMP_APP"
    if [ -d "$OLD" ]; then
        if [ -e "$APP" ]; then rm -rf "$OLD"; else mv "$OLD" "$APP"; fi
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

# Paket zuerst in ein Temp-Verzeichnis kopieren.
mkdir -p "$TMP_APP/continuum"
cp "$REPO"/continuum/*.py "$TMP_APP/continuum/"

# Agent stoppen, dann austauschen. Der Austausch ist nicht atomar,
# der Agent steht waehrend dieser Zeit. Das alte Paket wird erst zur Seite
# verschoben (BSD-mv wuerde sonst in ein bestehendes Ziel hinein verschieben).
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ -e "$APP" ]; then mv "$APP" "$OLD"; fi
mv "$TMP_APP" "$APP"
rm -rf "$OLD"

cat > "$BIN.tmp" <<EOF2
#!/usr/bin/env bash
export PYTHONPATH="$APP\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$PYTHON" -m continuum.cli "\$@"
EOF2
chmod +x "$BIN.tmp"
mv "$BIN.tmp" "$BIN"

sed -e "s|__APP__|$(sed_escape "$APP")|g" \
    -e "s|__HOME__|$(sed_escape "$HOME")|g" \
    -e "s|__PYTHON__|$(sed_escape "$PYTHON")|g" \
    "$REPO/dev.continuum.agent.plist" > "$PLIST.tmp"
mv "$PLIST.tmp" "$PLIST"

launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed:"
echo "  Package      $APP"
echo "  Python       $PYTHON"
echo "  LaunchAgent  $PLIST  (every 600 s)"
echo "  CLI          $BIN"
echo "  Log          $HOME/.local/state/continuum/continuum.log"
echo
echo "Show status:   continuum --status"
echo "Update:        run this installer again after git pull or a plugin update."
echo "Uninstall:     /continuum:uninstall (plugin) or ./uninstall.sh (clone)"
