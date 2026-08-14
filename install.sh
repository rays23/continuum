#!/usr/bin/env bash
# Installiert claude-wecker als LaunchAgent (Tick alle 10 Minuten).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.rainerschuller.claude-wecker"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BIN="$HOME/.local/bin/claude-wecker"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.local/bin" "$HOME/.local/state/claude-wecker"

cat > "$BIN" <<EOF
#!/usr/bin/env bash
# Wrapper: claude-wecker von ueberall aufrufbar.
exec /opt/homebrew/bin/python3 -m wecker.cli "\$@"
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
echo "  Log          $HOME/.local/state/claude-wecker/wecker.log"
echo
echo "Status ansehen:  claude-wecker --status"
echo "Deinstallieren:  launchctl bootout gui/$(id -u)/$LABEL && rm '$PLIST' '$BIN'"
