# Clawd Buddy commands

Clawd Buddy — manage the animated taskbar companion.

Usage: /buddy [action]

Actions:
  start    — Launch the buddy on the taskbar (if not already running)
  stop     — Kill the running buddy
  test     — Send a test celebration to the running buddy
  wave     — Send a wave/attention signal to the running buddy
  status   — Check if the buddy is running

If no action is given, default to "start".

Implementation:

- `clawd-buddy` is installed globally via `uv tool install`
- For "start": run `clawd-buddy` in the background (detached)
- For "stop": find the buddy process via `netstat -ano | findstr 44556` to get the PID, then `taskkill /F /PID <pid>`
- For "test": run `clawd-buddy --send "Test!"`
- For "wave": run `clawd-buddy --wave`
- For "status": check if port 44556 is in use via `netstat -ano | findstr 44556`
