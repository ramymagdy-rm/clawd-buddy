# Integrations

How Claude Code drives the buddy, and how you can drive it from anything
else: the command line, a socket, or HTTP.

- [Claude Code hooks](#claude-code-hooks)
- [How signals reach the buddy](#how-signals-reach-the-buddy)
- [Command-line reference](#command-line-reference)
- [Speech bubbles](#speech-bubbles)
- [Signal protocol (TCP)](#signal-protocol-tcp)
- [Status](#status)
- [HTTP webhook](#http-webhook)
- [Using another port](#using-another-port)

## Claude Code hooks

Add these to your **global** Claude Code settings,
`~/.claude/settings.json`, so every session drives the buddy. If you
already have hooks there, add these entries to the existing `hooks`
object.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "clawd-buddy --prompt-start", "timeout": 5 }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "clawd-buddy --send done", "timeout": 5 }] }
    ],
    "PermissionRequest": [
      { "hooks": [{ "type": "command", "command": "clawd-buddy --wave", "timeout": 5 }] }
    ]
  }
}
```

| Hook | Command | The buddy… |
| --- | --- | --- |
| `UserPromptSubmit` | `--prompt-start` | greets on a session's first prompt, then thinks |
| `Stop` | `--send done` | celebrates, then keeps thinking if other sessions are still working |
| `PermissionRequest` | `--wave` | waves for your attention |

Each command sends one signal and exits straight away. `timeout` is in
seconds, so 5 is plenty. The commands read the hook's JSON from stdin to
learn the `session_id` (so several sessions are told apart) and the
project folder (for the [workspace badge](features.md#workspace-badge)).

The `UserPromptSubmit` hook is optional. Without it the buddy still
celebrates and waves, just without the greeting and the thinking state.

If nothing happens, see
[the hook doesn't trigger the buddy](troubleshooting.md#the-hook-doesnt-trigger-the-buddy).

## How signals reach the buddy

```text
Claude Code                                             Clawd Buddy
-----------                                             -----------
 UserPromptSubmit ──> clawd-buddy --prompt-start ──> TCP 44556 ──> greet (new session) + think
 Stop ─────────────> clawd-buddy --send done ─────> TCP 44556 ──> celebrate
 PermissionRequest ─> clawd-buddy --wave ─────────> TCP 44556 ──> wave
```

The running buddy listens on `127.0.0.1:44556`. Every `clawd-buddy`
command other than starting it connects there, sends one small JSON
message and exits.

## Command-line reference

**Starting the buddy**

| Command | What it does |
| --- | --- |
| `clawd-buddy` | Start the buddy in the background. If one is already running, open its settings instead |
| `clawd-buddy --test` | Start with a celebration |
| `clawd-buddy --theme NAME` | Start with a theme (and remember it). See [Themes](themes.md) |
| `clawd-buddy --fg` | Run in the foreground and show its log in the terminal |
| `clawd-buddy --no-topmost` | Don't keep the window above other windows |
| `clawd-buddy --port N` | Use another port (default 44556) |
| `clawd-buddy --http-port N` | Also accept signals over [HTTP](#http-webhook) on `127.0.0.1:N` |
| `clawd-buddy --http-token T` | Require `Authorization: Bearer T` on every HTTP request |
| `clawd-buddy --startup` / `--no-startup` | Turn [run at login](platforms.md#run-at-login) on or off |

**Talking to a running buddy**

| Command | What it does |
| --- | --- |
| `clawd-buddy --prompt-start` | Greet if it's a new session, then think (the `UserPromptSubmit` hook) |
| `clawd-buddy --send TEXT` | Celebrate (the `Stop` hook) |
| `clawd-buddy --wave` | Wave for attention (the `PermissionRequest` hook) |
| `clawd-buddy --message TEXT` | Show a [speech bubble](#speech-bubbles); `""` dismisses it |
| `clawd-buddy --status` | Print the buddy's [state](#status) as JSON |
| `clawd-buddy --settings [PAGE]` | Open the settings window, optionally on `buddy`, `sound`, `reminders`, `focus` or `about` |
| `clawd-buddy --drank` | Confirm the [water reminder](features.md#water-reminder) |
| `clawd-buddy --pomodoro 25/5` | Start a [pomodoro](features.md#pomodoro) (minutes of focus/break, 1–180 each) |
| `clawd-buddy --pomodoro-stop` | Stop the pomodoro |
| `clawd-buddy --top` | Put the buddy back on top of other windows |
| `clawd-buddy --quit` | Close the buddy |

**Options for those commands**

| Option | What it does |
| --- | --- |
| `--session-id ID` | The session this signal belongs to (normally read from the hook's stdin) |
| `--workspace LABEL` | The [workspace badge](features.md#workspace-badge) label (normally the project folder's name) |
| `--port N` | Talk to a buddy on another port |

`clawd-buddy --version` and `clawd-buddy --help` work as usual. Commands
that talk to the buddy print a message and exit with code 1 if no buddy
is running.

## Speech bubbles

Any script or tool can show you a short message above the buddy, without
building its own notifications:

```bash
clawd-buddy --message "tests green"
clawd-buddy --message "deploy starting…"
clawd-buddy --message ""        # dismiss the current bubble
```

A bubble shows for 3 seconds, holds up to two lines, and doesn't
interrupt whatever the buddy is doing. See
[Animations](animations.md#speech-bubble).

## Signal protocol (TCP)

Send one JSON object to `127.0.0.1:44556`, then close the connection:

```json
{"action": "celebrate"}
{"action": "wave"}
{"action": "prompt_start", "session_id": "abc-123"}
{"action": "message", "text": "CI green"}
{"action": "settings", "page": "focus"}
```

| Action | Extra fields | Effect |
| --- | --- | --- |
| `prompt_start` | `session_id` | Greet if the session is new (or, without an id, if the buddy has been quiet a while), then think |
| `celebrate` | `session_id` | Celebrate. With an id, only that session stops thinking; without one, all do |
| `wave` | `session_id` | Wave for attention |
| `thinking_start` / `thinking_end` | `session_id` | Start or stop thinking without a reaction |
| `greet` | `session_id` | Just the greeting |
| `message` | `text` | Show a speech bubble (`""` dismisses it) |
| `drank` | | Confirm the water reminder |
| `pomodoro_start` / `pomodoro_stop` | `work_seconds`, `break_seconds` | Start or stop a pomodoro |
| `settings` | `page` | Open the settings window |
| `raise` | | Put the buddy back on top |
| `quit` | | Close the buddy |
| `status` | | Reply with the [status](#status) JSON |

Any action can also carry `"workspace": "LABEL"` for the
[workspace badge](features.md#workspace-badge). A session that never
sends its `celebrate` is let go after 10 minutes without a signal.

From any language:

```python
import json, socket

with socket.create_connection(("127.0.0.1", 44556)) as s:
    s.sendall(json.dumps({"action": "celebrate"}).encode())
```

```bash
echo '{"action": "wave"}' | nc localhost 44556
```

## Status

`clawd-buddy --status` (or the `status` action) returns a snapshot of
the running buddy. It's also the easiest "is the buddy running?" check:
exit code 0 with JSON when it is, 1 when it isn't.

```json
{
  "version": "0.1.26",
  "pid": 12345,
  "port": 44556,
  "mode": "thinking",
  "queue_depth": 0,
  "working_sessions": 1,
  "last_session_id": "abc-123",
  "last_action": "prompt_start",
  "last_action_ts": 1716595200.0,
  "theme": "dark",
  "sound_pack": "fanfare",
  "topmost": true,
  "bubble_text": "",
  "reduce_motion": false,
  "volume": 1.0,
  "quiet_hours": {"start": "23:00", "end": "08:00"},
  "reminder": {
    "enabled": true,
    "interval_seconds": 3600,
    "anchor": "08:00",
    "sound": "water",
    "quiet_hours": {"start": "23:00", "end": "08:00"},
    "active": false,
    "seconds_until_next": 1742,
    "cups_today": 3,
    "today_date": "2026-05-25",
    "recent_days": [{"date": "2026-05-24", "count": 6}]
  },
  "pomodoro": {
    "active": true,
    "phase": "work",
    "remaining_seconds": 912,
    "cycles": 2,
    "work_seconds": 1500,
    "break_seconds": 300
  },
  "http": {"enabled": true, "port": 8787},
  "workspace": {"label": "api", "ts": 1717680000.0, "seen_count": 2, "badge_enabled": true}
}
```

- `quiet_hours` start and end are `null` when that pause is off.
- `reminder.seconds_until_next` is `null` when the reminder is off and
  `0` while a reminder is waiting.
- `pomodoro.remaining_seconds` is `null` when no pomodoro is running.
- `workspace.label` and `ts` are `null` until a signal with a workspace
  arrives.
- Older buddies leave out the fields that came after them.

## HTTP webhook

Let anything that can make an HTTP request drive the buddy: GitHub
Actions, n8n, IFTTT, a shell one-liner.

```bash
clawd-buddy --http-port 8787             # start with the webhook on
curl -X POST localhost:8787/signal -d '{"action": "wave"}'
curl -X POST localhost:8787/signal -d '{"action": "message", "text": "CI green"}'
curl localhost:8787/status               # same JSON as --status
```

`POST /signal` takes exactly the same JSON as the
[TCP protocol](#signal-protocol-tcp), so every action works.

- **Off unless you ask for it.** No `--http-port`, no listener.
- **Local only.** It always binds `127.0.0.1`.
- **Optional token.** With `--http-token TOKEN`, every request needs
  `Authorization: Bearer TOKEN`.
- **Safe without a token.** `quit` and `settings` are refused (403)
  unless a token is set, so a web page in your browser can't close the
  buddy or pop up its window.

## Using another port

If port 44556 is taken, start the buddy on another one and give the
same `--port` to every command, hooks included:

```bash
clawd-buddy --port 55000
clawd-buddy --send done --port 55000
```

The buddy also uses the next port up (44557 by default) to make sure
only one copy runs.
