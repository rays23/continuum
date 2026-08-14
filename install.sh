#!/usr/bin/env bash
# Installiert continuum als LaunchAgent (Tick alle 10 Minuten).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="dev.continuum.agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BIN="$HOME/.local/bin/continuum"
PYTHON="${CONTINUUM_PYTHON:-$(command -v python3)}"

if [ -z "$PYTHON" ]; then
    echo "python3 nicht gefunden. Pfad via CONTINUUM_PYTHON setzen." >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.local/bin" "$HOME/.local/state/continuum"

cat > "$BIN" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$REPO\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$PYTHON" -m continuum.cli "\$@"
EOF
chmod +x "$BIN"

sed -e "s|__REPO__|$REPO|g" \
    -e "s|__HOME__|$HOME|g" \
    -e "s|__PYTHON__|$PYTHON|g" \
    "$REPO/dev.continuum.agent.plist" > "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installiert:"
echo "  LaunchAgent  $PLIST  (alle 600 s)"
echo "  CLI          $BIN"
echo "  Log          $HOME/.local/state/continuum/continuum.log"
echo
echo "Status ansehen:  continuum --status"
echo "Deinstallieren:  launchctl bootout gui/$(id -u)/$LABEL && rm '$PLIST' '$BIN'"
