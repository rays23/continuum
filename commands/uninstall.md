---
description: Remove the continuum LaunchAgent, CLI wrapper and installed package
allowed-tools: Bash(bash:*)
---

Uninstall continuum. This removes the LaunchAgent, the CLI wrapper and the
installed package. The log and state folder stays.

Run exactly this one command, with no `cd` and no other changes:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/uninstall.sh"
```

Then report the output briefly. Tell the user that this does not remove the
plugin itself. The user removes the plugin separately with `/plugin`.
