# Clawd Buddy commands

Clawd Buddy — manage the animated taskbar companion.

Usage: /buddy [action] [args...]

Actions:
  start         — Launch the buddy on the taskbar (if not already running)
  stop          — Ask the running buddy to exit cleanly (preferred over kill)
  kill          — Force-kill the buddy process if `stop` doesn't work
  status        — Check if the buddy is running (port 44556)
  test          — Send a test celebration to the running buddy
  wave          — Send a wave/attention signal to the running buddy
  top           — Bring the buddy to the front (re-assert always-on-top)
  theme `<name>`  — Switch theme: dark, light, dracula, monokai, nord, gruvbox, solarized, sunset
  version       — Print the installed clawd-buddy version
  startup       — Register the buddy to run at Windows login
  no-startup    — Remove the buddy from Windows login
  prompt-start  — Greet (if new session) + start thinking animation (UserPromptSubmit hook)

If no action is given, default to "start".

Implementation:

- `clawd-buddy` is installed globally via `uv tool install` — call it by name, not by path.
- For "start": run `clawd-buddy` in the background (detached). It auto-daemonizes; no extra flags needed.
- For "stop": run `clawd-buddy --quit` — this asks the running buddy to exit via its socket. Falls back to "kill" if the port isn't responding.
- For "kill": find the buddy PID via `netstat -ano | findstr 44556`, then `taskkill /F /PID <pid>`.
- For "status": check if port 44556 is in use via `netstat -ano | findstr 44556`.
- For "test": run `clawd-buddy --send "Test!"`.
- For "wave": run `clawd-buddy --wave`.
- For "top": run `clawd-buddy --top`.
- For "theme `<name>`": run `clawd-buddy --theme <name>`. Theme persists across launches.
- For "version": run `clawd-buddy --version`.
- For "startup" / "no-startup": run `clawd-buddy --startup` or `clawd-buddy --no-startup`.
- For "prompt-start": run `clawd-buddy --prompt-start`. Pass `--session-id ID` only for testing; the Claude Code hook reads the id from piped JSON on stdin automatically.

Notes:

- Prefer `clawd-buddy --quit` over `taskkill` so the buddy can clean up its socket and tray icon.
- All actions are no-ops if no buddy is running, except `start`.
- The socket protocol uses port 44556 by default; override with `--port` if needed.
