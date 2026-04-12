# Clawd Buddy

A tiny animated terminal pet that sits on your Windows taskbar and reacts to [Claude Code](https://claude.ai/code) events.

<!-- TODO: add a gif/screenshot here -->
<!-- ![Clawd Buddy demo](docs/demo.gif) -->

## What it does

Clawd Buddy is a small always-on-top character that lives on your taskbar while you work with Claude Code:

| State | What happens |
| --- | --- |
| **Idle** | Gently bobs, blinks, breathes — your quiet companion |
| **Assistant finishes** (`Stop` hook) | Celebrates with confetti, happy eyes, and waving arms |
| **Assistant needs permission** (`PermissionRequest` hook) | Waves at you with a floating **!** so you know to check back |

## Install

```bash
# With uv (recommended — installs as an isolated tool)
uv tool install clawd-buddy

# With pipx
pipx install clawd-buddy

# With pip (into current environment)
pip install clawd-buddy
```

### From source

```bash
git clone https://github.com/ramymagdy-rm/clawd-buddy.git
cd clawd-buddy
uv tool install --from . clawd-buddy
```

## Quick start

### 1. Launch the buddy

```bash
clawd-buddy
```

The buddy appears on your taskbar, centered at the bottom of the screen. It runs until you close it.

### 2. Run at startup (optional)

```bash
# Enable — buddy starts automatically when you log into Windows
clawd-buddy --startup

# Disable — remove from startup
clawd-buddy --no-startup
```

This places a lightweight launcher in your Windows Startup folder (`shell:startup`). No console window appears — the buddy runs silently in the background.

### 3. Wire up Claude Code hooks

Add to your **global** Claude Code settings (`~/.claude/settings.json`) so every session triggers the buddy:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "clawd-buddy --send done",
            "timeout": 5000
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "clawd-buddy --wave",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
```

> **Note:** If you already have other hooks in your `settings.json`, merge the `Stop` and `PermissionRequest` entries into the existing `hooks` object.

### 4. Done

Start a Claude Code session anywhere. When the assistant finishes or needs your attention, the buddy reacts.

## CLI reference

```text
clawd-buddy                  Start buddy on taskbar
clawd-buddy --test           Start with a celebration animation
clawd-buddy --send MSG       Signal a running buddy to celebrate
clawd-buddy --wave           Signal a running buddy to wave (needs attention)
clawd-buddy --startup        Enable run at Windows startup
clawd-buddy --no-startup     Disable run at Windows startup
clawd-buddy --port PORT      Use a custom TCP port (default: 44556)
clawd-buddy --no-topmost     Don't keep the window always-on-top
clawd-buddy --help           Show help
```

## Controls

| Input | Action |
| --- | --- |
| **Drag** | Click anywhere on the buddy and drag to reposition |
| **Space** | Trigger a test celebration |
| **Escape** | Quit the buddy |
| **Tray icon** | Right-click the system tray icon for a menu |

## How it works

### Architecture

```text
Claude Code                            Clawd Buddy
-----------                            -----------
 hooks/Stop ──> clawd-buddy --send ──> TCP:44556 ──> celebrate animation
 hooks/PermissionRequest ──> clawd-buddy --wave ──> TCP:44556 ──> wave animation
```

1. **Claude Code hooks** fire shell commands when events happen (response done, permission needed).
2. The `clawd-buddy --send` / `--wave` CLI connects to `127.0.0.1:44556` and sends a JSON action.
3. The running buddy process receives the signal and plays the animation.

### Signal protocol

The buddy listens on a TCP socket (default port `44556`). Send a JSON payload to trigger actions:

```json
{"action": "celebrate"}
```

```json
{"action": "wave"}
```

You can send signals from any language:

```python
import socket, json
s = socket.socket()
s.connect(("127.0.0.1", 44556))
s.sendall(json.dumps({"action": "celebrate"}).encode())
s.close()
```

```bash
echo '{"action": "wave"}' | nc localhost 44556
```

### Single instance

Only one buddy can run at a time. If you launch `clawd-buddy` while one is already running, it sends a signal to the existing instance and exits.

### System tray

The buddy adds a system tray icon with a right-click menu:

- **Test Celebration** — trigger the celebrate animation
- **Quit** — close the buddy

### Windows startup

`clawd-buddy --startup` places a small VBS launcher in your Windows Startup folder:

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\clawd-buddy-startup.vbs
```

This script starts the buddy with a hidden console window. To remove it, run `clawd-buddy --no-startup` or delete the file manually.

## Animations

### Idle

- Gentle vertical bobbing (sine wave)
- Periodic blinking (every ~3.5 seconds)
- Pupils wander slowly
- Small mouth line with subtle movement
- Arms sway gently at sides

### Celebrate (on `Stop`)

- Fast bouncing
- Happy arc eyes (^ ^)
- Wide smile
- Both arms waving up
- Legs kicking
- Confetti burst (40 particles with gravity and drag)
- Duration: 3.5 seconds

### Wave (on `PermissionRequest`)

- Medium bobbing
- Wide alert eyes (large pupils, staring)
- Surprised "o" mouth
- Right arm waving high
- Pulsing floating **!** indicator above head
- Duration: 5 seconds

## Configuration

### Custom port

If port `44556` is taken, use a different one:

```bash
clawd-buddy --port 55000
```

Update your hooks to match:

```json
"command": "clawd-buddy --send done --port 55000"
```

### Disable always-on-top

```bash
clawd-buddy --no-topmost
```

## Troubleshooting

### Buddy doesn't appear

- **Windows only**: Clawd Buddy uses Windows-specific APIs (`user32`, `shell32`) for transparency and taskbar detection. It does not work on macOS or Linux.
- Make sure no other process is using port `44556`: `netstat -ano | findstr 44556`

### Hook doesn't trigger the buddy

- Make sure the buddy is running (`clawd-buddy` in a terminal or via `--startup`).
- Test manually: `clawd-buddy --send test` — if this says "No buddy on port 44556", the buddy isn't running.
- Check that `clawd-buddy` is on your PATH: `where clawd-buddy`

### Multiple buddies / port conflict

- The buddy uses a lock socket on port `44557` (main port + 1) to prevent duplicates.
- If a stale lock is stuck, kill the process and restart: `taskkill /F /IM clawd-buddy.exe`

### Startup not working

- Verify the VBS file exists: `dir "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\clawd-buddy*"`
- Re-run `clawd-buddy --startup` to regenerate it.
- Make sure `clawd-buddy.exe` is on your PATH: `where clawd-buddy`

## Disclaimer

Clawd Buddy is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by Anthropic. "Claude" and "Claude Code" are trademarks of Anthropic, PBC.

## License

[MIT](LICENSE)
