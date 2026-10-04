#!/usr/bin/env bash
# Entfernt LaunchAgent, CLI-Wrapper und das kopierte Paket.
set -euo pipefail

LABEL="dev.continuum.agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BIN="$HOME/.local/bin/continuum"
APP="$HOME/.local/share/continuum"
STATE="$HOME/.local/state/continuum"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST" "$BIN"
rm -rf "$APP" "$HOME"/.local/share/.continuum.tmp.* "$HOME"/.local/share/.continuum.old.*

echo "Removed LaunchAgent, CLI and package."
echo "Kept log and state in $STATE. Delete that folder by hand if you want."
