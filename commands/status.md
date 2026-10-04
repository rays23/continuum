---
description: Show the state of all Claude Code sessions that continuum watches
allowed-tools: Bash(~/.local/bin/continuum:*)
---

Show the continuum status. Run exactly this one command:

```bash
~/.local/bin/continuum --status
```

Then report the output briefly. If the file `~/.local/bin/continuum` does not
exist, continuum is not installed. Tell the user to run `/continuum:install`.
