# continuum

Continues Claude Code sessions when their rate limit window opens again.
No tmux, no PTY wrapper, no simulated keystrokes.

The name comes from `continue`. That is the one word missing after a limit.

## Why

Claude Code does not resume a session by itself after a rate limit. It puts the
word `continue` into the empty input box, but you must press Enter. If an
upgrade dialog appears, even that prefilled word disappears again.

The existing tools (`autoclaude`, `herdr-claude-auto-retry`,
`claude-auto-continue`, `claude-nightshift`) all need a terminal multiplexer or
a PTY wrapper, and they send keystrokes. That does not help if you use a
terminal without tmux. It also does not help for a session that already runs.

## How

Claude Code opens one Unix domain socket per process. The socket is at
`$XDG_RUNTIME_DIR/cc-socks/<pid>.sock`, or `/tmp/cc-socks` if that variable is
empty. It reads newline-delimited JSON. This is the same channel that sessions
use to send messages to each other:

```json
{"type":"user","priority":"now","message":{"content":"continue"},"session_id":"..."}
```

Every 10 minutes, continuum does this:

1. Find the config profiles under `~/.claude*/projects/`.
2. Read the sessions of each profile with `CLAUDE_CONFIG_DIR=<profile> claude agents --json`.
   Without that variable you see only your own profile.
3. Detect the limit. The last `assistant` entry in the session JSONL has
   `isApiErrorMessage: true` and matching text.
4. Skip every session that is not `idle` or `waiting`.
5. Write the message to the socket. Send the `session_id` with it, because a
   reused PID must not receive the message.

### The reset time stays unparsed

The error message shows the reset time, for example `resets 7pm (Europe/Berlin)`.
That time is localized and has no date, and the 7 day limits print a different
format. A parser built on two samples fails quietly one day.

A measurement settled this. One early attempt costs exactly one line in the
session log. So continuum polls until the session recovers. It only writes the
reset time to its own log.

## Install

```bash
./install.sh
```

This creates the launch agent `dev.continuum.agent` and the CLI wrapper
`~/.local/bin/continuum`. The agent ticks every 600 seconds. It survives a
closed lid and a closed terminal.

```bash
continuum --status     # state of all sessions in all profiles
continuum --dry-run    # show what would happen
continuum --verbose    # one tick by hand
tail -f ~/.local/state/continuum/continuum.log
```

To remove it:

```bash
launchctl bootout gui/$(id -u)/dev.continuum.agent
rm ~/Library/LaunchAgents/dev.continuum.agent.plist ~/.local/bin/continuum
```

## Limits

- **`crossSessionInbound`**: A session set to `hold` or `refuse` accepts no
  messages from other sessions. continuum cannot reach it. The default setting
  delivers the message.
- **Busy sessions stay untouched.** A message to a session inside a turn waits
  in the queue and then lands in the middle of its work.
- **Reset times differ per profile.** One profile reported `6:50pm` and another
  `7pm`, although both messages appeared 40 seconds apart. So continuum reads
  the state of each profile on its own.
- **Delivery means "written to the socket"**, not "read". If the receive buffer
  were full, continuum would mark the session as poked without it being poked.
  The cost of that error is one missed cycle, so at most 10 minutes.
- **The state file has no lock.** If a manual run and an agent tick overlap, the
  later write wins. The cost is the same: one extra or one missed poke.
- **Claude Code only.** The mechanism needs three Claude Code specifics: the
  socket under `cc-socks`, the JSONL field `isApiErrorMessage`, and
  `claude agents --json`. Codex, Gemini CLI, and Pi open no comparable channel.
  A check on 2026-08-14 found nothing similar in `/tmp`, and Codex keeps its
  state in `~/.codex` as SQLite. For those agents only a PTY or keystrokes
  remain, which is a different design.
- macOS only so far. The socket path respects `XDG_RUNTIME_DIR`, so Linux
  should work, but nobody tested it.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

41 tests, standard library only. The tests deliver to a real Unix domain socket.
The limit detection also runs against real session logs in a past limit state.

### What is verified (2026-08-14)

These are separate statements, so they stay separate:

1. **Protocol and reset behavior**, live against a session in a real limit
   (reset 19:00), through a direct socket write before this tool existed. A
   message at 18:55:30 hit the limit again. A message at 19:00:00 made the
   session resume its work 30 seconds later.
2. **The tool end to end**, at 19:13 and 19:18, against real sessions and real
   sockets. The limit state came from a log snapshot, not from a live limit.
   Both sessions answered. The second tick correctly sent nothing.
3. **The launch agent unattended**, at 20:32 against a session in a real limit
   (reset 12am). It found the session, sent the message, and the session hit the
   limit again. That is the predicted result of an early attempt. `--status`
   also showed its `LIMITED` line against real data for the first time.
4. **Still open**: the same automatic message after the window opens, with
   nobody watching. Every successful wake after a reset so far started by hand.

## License

MIT
