# Platforms

Clawd Buddy runs on **Windows 10/11** and **Linux** (X11, or XWayland on
Wayland desktops). macOS isn't supported yet.

| | Windows 10/11 | Linux |
| --- | --- | --- |
| **Transparent background** | Yes (colour key) | Yes with a compositor; a themed background without one |
| **Always on top** | Yes | Yes (`_NET_WM_STATE_ABOVE`) |
| **Tray menu** | Notification-area icon | StatusNotifierItem over D-Bus, drawn by your panel |
| **Run at login** | Registry Run key | `~/.config/autostart/clawd-buddy.desktop` |
| **Named process** | Clawd Buddy (`Clawd-Buddy.exe`) in Task Manager | n/a |
| **App launcher** | n/a | `.desktop` entry with the buddy icon, pinnable to the dock |

- [Windows](#windows)
- [Linux](#linux)
- [Run at login](#run-at-login)
- [One buddy at a time](#one-buddy-at-a-time)
- [Where settings and data live](#where-settings-and-data-live)

## Windows

**Display scaling.** The buddy declares per-monitor DPI awareness, so it
sits in the right place at any scaling (125–200% is the Windows 11
laptop default). At high scaling it draws at its native pixel size,
crisp rather than blurry. Use the tray's **Size** menu (or Ctrl+2…7) if
you'd like it bigger.

### Task Manager name

In Task Manager the buddy shows up as **Clawd Buddy** with its own icon:
**Clawd Buddy** on the Processes tab, `Clawd-Buddy.exe` on the Details
tab. (Versions before 0.1.26 showed up as **Python** / `pythonw.exe`.)

To do that, the first time it starts the buddy makes its own copy of
Python's `pythonw.exe`, named `Clawd-Buddy.exe`, with the buddy's name
and icon:

```text
<the buddy's environment>\clawd-buddy-host-<hash>\Clawd-Buddy.exe
                                                 python3XX.dll, python3.dll, vcruntime140*.dll
```

For a `uv tool` install the environment is
`%APPDATA%\uv\tools\clawd-buddy`. The copy is about 7 MB and runs
exactly the same Python, from the same environment.

- It's rebuilt by itself when you upgrade the buddy or Python, and old
  copies are removed once nothing runs from them. You can delete the
  folder any time; it comes back on the next start.
- A new copy has to start successfully before it's used. If it can't be
  built or doesn't work (a read-only environment, the Microsoft Store
  Python, antivirus holding the file), the buddy runs as `pythonw.exe`
  as before, and `clawd-buddy` says why.
- It needs the buddy to be installed in its own environment, as `uv`,
  `pipx` or a venv do. A plain `pip install` into your system Python
  keeps running as `pythonw.exe`.
- The copy isn't code-signed. If your Python came from python.org, its
  `pythonw.exe` is signed, but changing the name and icon removes the
  signature from the copy.
- Double-clicking `Clawd-Buddy.exe` does nothing: it's the Python
  interpreter, and the buddy tells it what to run. Start the buddy with
  `clawd-buddy` (or `clawd-buddyw`, which opens no console window).

## Linux

**X11 is required.** Wayland doesn't let apps position their own windows
or keep them on top, so on Wayland desktops the buddy runs through
XWayland (it sets `SDL_VIDEODRIVER=x11` itself). Most Wayland desktops
include XWayland.

**Transparency.** With a compositing manager running (GNOME, KDE, Xfce
with compositing, picom…), the window is truly transparent. Without one,
transparent pixels would show as black, so the buddy paints its theme's
background instead. The panel height is detected automatically (48 px
if it can't be).

**Tray menu.** The buddy publishes its tray icon over D-Bus as a
StatusNotifierItem, and your panel (GNOME, KDE, Xfce, Cinnamon…) draws
the menu, so it looks like every other tray menu. Either mouse button
opens it. Stock GNOME needs the **AppIndicator and KStatusNotifierItem
Support** extension, which Ubuntu enables by default.

### Dock icon and app launcher

Each time it starts, the buddy installs a launcher for itself:

- `~/.local/share/applications/clawd-buddy.desktop`
- `~/.local/share/icons/hicolor/256x256/apps/clawd-buddy.png`

So the dock shows **Clawd Buddy** with the buddy icon, and you can find
it in Activities / the app grid.

- Right-click it in the app grid and choose **Pin to Dash** (or **Add to
  Favorites**) to keep it on the dock. Clicking it starts the buddy, or
  opens its settings if it's already running.
- Right-clicking the dock icon also offers **Settings** and **Quit**.
- The launcher runs the copy of the buddy that installed it, so it's
  refreshed whenever you start another install.
- To remove it, delete those two files.

The buddy itself stays off the dock and Alt-Tab while it runs; it's a
pet, not a window.

## Run at login

```bash
clawd-buddy --startup       # start the buddy when you log in
clawd-buddy --no-startup    # stop doing that
```

The settings window's **Buddy** page has the same switch.

- **Windows:** adds `ClawdBuddy` to
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, pointing at
  `clawd-buddyw.exe`, so the buddy starts without a console window.
  (Older versions used a script in the Startup folder; `--startup`
  removes it.)
- **Linux:** creates `~/.config/autostart/clawd-buddy.desktop`, the XDG
  autostart standard that GNOME, KDE, Xfce and others follow.

## One buddy at a time

Only one buddy runs at a time. Starting `clawd-buddy` again (from a
terminal, the dock or the app grid) opens the running buddy's settings
window instead. The buddy holds the port after its own (44557 by
default) to make sure of this.

## Where settings and data live

| What | Windows | Linux |
| --- | --- | --- |
| **Settings** (theme, sound, size, reminders…) | `%APPDATA%\clawd-buddy\config.json` | `$XDG_CONFIG_HOME/clawd-buddy/config.json` (usually `~/.config/clawd-buddy/`) |
| **Drinking history** | `%USERPROFILE%\.clawd-buddy\history.json` | `~/.clawd-buddy/history.json` |

Settings live in the usual config folder for your system. Data the
buddy collects lives in `~/.clawd-buddy/`, where it's easy to back up or
sync with your dotfiles. The settings window's **About** page shows the
settings folder.

`config.json` is written by the buddy whenever you change a setting, and
it's plain JSON if you'd rather edit it with the buddy closed:

| Key | Holds |
| --- | --- |
| `theme` | The theme name, e.g. `"nord"` |
| `sound_pack` | `fanfare`, `chime`, `retro`, `minimal` or `off` |
| `volume` | 0.0 to 1.0 |
| `quiet_hours` | `{"start": …, "end": …}` in minutes after midnight, or absent when off |
| `reduce_motion` | `true` / `false` |
| `size` | 1 to 7, matching Ctrl+1…7 (1 is S) |
| `workspace_badge` | `true` / `false` |
| `reminder` | The water reminder: `enabled`, `interval`, `anchor_minute`, `sound`, `quiet_hours` |
