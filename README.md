# claude-wecker

Weckt Claude-Code-Sessions, sobald ihr Rate-Limit-Fenster wieder offen ist.
Ohne tmux, ohne PTY-Wrapper, ohne simulierte Tastendrücke.

## Warum

Claude Code führt eine Session nach dem Limit nicht selbst fort. Der eingebaute
Handler `prefillRateLimitAutoQueueContinue` schreibt lediglich das Wort
`continue` in das leere Eingabefeld:

```js
if (Ut.current && Hy.current === "") { Hy.current = "continue"; EOt("continue") }
```

Enter musst du selbst drücken. Kommt ein Upsell-Dialog dazwischen, wird der
Prefill sogar wieder gelöscht (`tengu_rl_checkpoint_auto_continue_cancelled_by_upsell`).

Die vorhandenen Lösungen (`autoclaude`, `herdr-claude-auto-retry`,
`claude-auto-continue`, `claude-nightshift`) setzen alle auf einen
Terminal-Multiplexer oder einen PTY-Wrapper und schicken Tastendrücke. Wer Warp
ohne tmux fährt oder eine bereits laufende Session wecken will, hat damit nichts
gewonnen.

## Wie

Claude Code öffnet je Prozess einen Unix-Domain-Socket unter
`$XDG_RUNTIME_DIR/cc-socks/<pid>.sock` (sonst `/tmp/cc-socks`) und liest dort
zeilenweise JSON. Das ist derselbe Kanal, über den sich Sessions gegenseitig
`SendMessage` schicken:

```json
{"type":"user","priority":"now","message":{"content":"continue"},"session_id":"..."}
```

Ein Tick alle 10 Minuten:

1. Profile über `~/.claude*/projects/` finden, nicht hartkodieren.
2. Sessions je Profil über `CLAUDE_CONFIG_DIR=<profil> claude agents --json` lesen.
   Ohne die Variable sieht man nur das eigene Profil.
3. Limit erkennen: letzter `assistant`-Eintrag im Session-JSONL hat
   `isApiErrorMessage: true` und passenden Text.
4. Nur wecken, wenn die Session auf `idle`/`waiting` steht.
5. Nachricht in den Socket schreiben, mit `session_id` als Schutz gegen
   recycelte PIDs.

### Die Reset-Zeit wird bewusst nicht ausgewertet

Sie steht zwar lesbar in der Fehlermeldung (`resets 7pm (Europe/Berlin)`), ist
aber lokalisiert, ohne Datum, und die 7-Tage-Varianten rendern anders. Ein
Parser auf zwei Stichproben greift irgendwann still daneben.

Gemessen: Ein zu früher Weckversuch kostet exakt eine Zeile im Log. Also pollen
wir stumpf, bis sich die Session erholt. Die Reset-Zeit wird nur ins Log
geschrieben.

## Installation

```bash
./install.sh
```

Legt den LaunchAgent `com.rainerschuller.claude-wecker` an (Tick alle 600 s,
überlebt zugeklappten Deckel und geschlossenes Terminal) und den CLI-Wrapper
`~/.local/bin/claude-wecker`.

```bash
claude-wecker --status     # Zustand aller Sessions aller Profile
claude-wecker --dry-run    # zeigen, was passieren würde
claude-wecker --verbose    # ein Tick von Hand
tail -f ~/.local/state/claude-wecker/wecker.log
```

Deinstallieren:

```bash
launchctl bootout gui/$(id -u)/com.rainerschuller.claude-wecker
rm ~/Library/LaunchAgents/com.rainerschuller.claude-wecker.plist ~/.local/bin/claude-wecker
```

## Grenzen

- **`crossSessionInbound`**: Steht eine Session auf `hold` oder `refuse`, nimmt
  sie keine Fremdnachrichten an und ist nicht weckbar. Default (unset) stellt zu.
- **Beschäftigte Sessions** werden ausgelassen. Eine Nachricht an eine Session
  im Turn wird eingereiht und landet mitten in ihrer laufenden Arbeit.
- **Reset-Zeiten sind pro Profil verschieden.** Beobachtet: `6:50pm` im einen,
  `7pm` im anderen Profil, bei nur 40 Sekunden Abstand der Meldungen. Deshalb
  wird jedes Profil einzeln bewertet.
- **Zustellung heißt „in den Socket geschrieben"**, nicht „gelesen". Wäre der
  Empfangspuffer voll, gälte die Session als gestupst, ohne es zu sein. Kosten
  im Fehlerfall: ein verpasster Weckzyklus, also maximal 10 Minuten.
- **Kein Lock auf der Zustandsdatei.** Überlappen ein Lauf von Hand und ein
  Tick des LaunchAgent, gewinnt der spätere Schreibvorgang. Gleiche Kosten:
  ein doppelter oder ein verpasster Anstoß.
- Getestet auf macOS. Der Socket-Pfad respektiert `XDG_RUNTIME_DIR`, Linux
  sollte laufen, ist aber ungeprüft.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

34 Tests, keine Abhängigkeiten außer der Standardbibliothek. Die Zustellung wird
gegen einen echten Unix-Domain-Socket getestet, die Limit-Erkennung zusätzlich
gegen echte Session-Logs im historischen Limit-Zustand.

### Verifikationsstand (14.08.2026)

Getrennt gehalten, weil es drei verschiedene Aussagen sind:

1. **Protokoll und Reset-Verhalten**, live gegen eine tatsächlich limitierte
   Session (Reset 19:00), per direktem Socket-Schreiben vor Entstehung des
   Tools: Anstoß um 18:55:30 lief erneut ins Limit, Anstoß um 19:00:00 führte
   30 Sekunden später zur Wiederaufnahme der Arbeit.
2. **Das Tool von Ende zu Ende**, um 19:13 und 19:18 gegen echte Sessions und
   echte Sockets, allerdings mit einem Log-Snapshot im historischen
   Limit-Zustand statt einem gerade aktiven Limit. Beide Sessions haben
   geantwortet, der jeweils zweite Tick hat korrekt nicht erneut gestupst.
3. **Noch ausstehend**: ein unbeaufsichtigter Durchlauf des LaunchAgent durch
   einen echten Reset. Ebenso ungesehen ist bisher die `LIMITIERT`-Zeile in
   `--status`, weil seither keine Session limitiert war.
