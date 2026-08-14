#!/usr/bin/env bash
# Installiert continuum als LaunchAgent (Tick alle 10 Minuten).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.rainerschuller.continuum"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BIN="$HOME/.local/bin/continuum"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.local/bin" "$HOME/.local/state/continuum"

cat > "$BIN" <<EOF
#!/usr/bin/env bash
# Wrapper: continuum von ueberall aufrufbar.
exec /opt/homebrew/bin/python3 -m continuum.cli "\$@"
EOF
chmod +x "$BIN"
# Der Wrapper braucht das Repo im Modulpfad.
sed -i '' "2i\\
export PYTHONPATH=\"$REPO\${PYTHONPATH:+:\$PYTHONPATH}\"
" "$BIN"

cp "$REPO/$LABEL.plist" "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installiert:"
echo "  LaunchAgent  $PLIST  (alle 600 s)"
echo "  CLI          $BIN"
echo "  Log          $HOME/.local/state/continuum/continuum.log"
echo
echo "Status ansehen:  continuum --status"
echo "Deinstallieren:  launchctl bootout gui/$(id -u)/$LABEL && rm '$PLIST' '$BIN'"
