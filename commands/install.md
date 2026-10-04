---
description: Install the continuum LaunchAgent (macOS only)
allowed-tools: Bash(bash:*)
---

Install continuum. This sets up a LaunchAgent that ticks every 10 minutes and
continues rate-limited Claude Code sessions. It works on macOS only.

Run exactly this one command, with no `cd` and no other changes:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/install.sh"
```

Then report the output briefly. If the command fails, show the error message.
