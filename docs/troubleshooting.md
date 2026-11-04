# Troubleshooting

Running the buddy in the foreground shows its log, which usually says
what's wrong:

```bash
clawd-buddy --quit      # close any running buddy
clawd-buddy --fg        # start it with its log in the terminal
```

- [The buddy doesn't appear](#the-buddy-doesnt-appear)
- [The hook doesn't trigger the buddy](#the-hook-doesnt-trigger-the-buddy)
- [Run at login doesn't work](#run-at-login-doesnt-work)
- [Two buddies, or the port is taken](#two-buddies-or-the-port-is-taken)
- [Windows: the sound plays but the buddy is invisible](#windows-the-sound-plays-but-the-buddy-is-invisible)
- [Linux: a black or coloured rectangle around the buddy](#linux-a-black-or-coloured-rectangle-around-the-buddy)
- [Linux: the tray icon has no menu](#linux-the-tray-icon-has-no-menu)

## The buddy doesn't appear

- **It might be off-screen.** Pick **Center on Screen** in the tray
  menu, or the settings window's Buddy page.
- **Is it running?** `clawd-buddy --status` prints its state, or says no
  buddy is listening.
- **Windows:** check nothing else uses port 44556:
  `netstat -ano | findstr 44556`
- **Linux:** an X11 session (or XWayland) is needed; see
  [Platforms](platforms.md#linux).
- **macOS** isn't supported yet.

## The hook doesn't trigger the buddy

1. Make sure the buddy is running: `clawd-buddy --status`.
2. Send a signal by hand: `clawd-buddy --send test`. "No buddy on port
   44556" means the buddy isn't running.
3. Check `clawd-buddy` is on your PATH: `where clawd-buddy` (Windows),
   `which clawd-buddy` (Linux).
4. Check the hooks are in your **global** `~/.claude/settings.json`,
   not just in one project's `.claude/settings.json`. Project hooks only
   fire in that project. See [Claude Code hooks](integrations.md#claude-code-hooks).

## Run at login doesn't work

- Run `clawd-buddy --startup` again; it rewrites the entry.
- **Windows:** check the entry exists:
  `reg query HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v ClawdBuddy`.
  It points at `clawd-buddyw.exe`, which has to still exist (reinstalling
  the buddy elsewhere moves it; run `--startup` again after that).
- **Linux:** check `~/.config/autostart/clawd-buddy.desktop` exists, and
  that `clawd-buddy` is on your PATH (`which clawd-buddy`).

## Two buddies, or the port is taken

Only one buddy runs at a time: it holds port 44557 (its port + 1) to make
sure. To close a buddy, run `clawd-buddy --quit`. If it doesn't respond:

- **Windows:** `taskkill /F /IM Clawd-Buddy.exe` (or `pythonw.exe` before
  0.1.26, which also closes other Python programs)
- **Linux:** `pkill -f clawd_buddy`

If another program uses port 44556, run the buddy on
[another port](integrations.md#using-another-port).

## Windows: the sound plays but the buddy is invisible

Fixed in **0.1.22**. Earlier versions could place the buddy off the
bottom of the screen on displays scaled to 125–200% (the Windows 11
laptop default). Upgrade and restart the buddy:

```bash
uv tool upgrade clawd-buddy
clawd-buddy --quit
clawd-buddy
```

With `--fg` you should see `[buddy] DPI awareness: per-monitor-v2`.

## Linux: a black or coloured rectangle around the buddy

Fixed in **0.1.23**: the window is transparent whenever a compositing
manager is running. Upgrade and restart the buddy. With `--fg` you
should see `[buddy] Transparency: per-pixel alpha (visual 0x…)`.

If that line is missing, the buddy fell back to its themed background:

- **No compositor is running** (a bare i3 or Openbox session, say).
  Start one such as `picom`, or pick a theme that blends with your panel:
  `light`, `solarized` or `sunset` on light panels, `dark`, `dracula`,
  `monokai`, `nord` or `gruvbox` on dark ones.
- **You set `SDL_VIDEODRIVER`** to something other than `x11`, or set
  `SDL_FRAMEBUFFER_ACCELERATION` or `SDL_VIDEO_X11_WINDOW_VISUALID`
  yourself. The buddy respects your values; unset them to get
  transparency back.

## Linux: the tray icon has no menu

Fixed in **0.1.24**: the buddy publishes its tray icon over D-Bus and the
panel draws the menu. Upgrade and restart the buddy. With `--fg` you
should see `[buddy] Tray: StatusNotifierItem (D-Bus menu)`.

If you see `no StatusNotifierItem host found` instead, nothing on your
desktop shows StatusNotifierItem icons:

- **GNOME without Ubuntu's defaults** (Fedora, Arch, Debian…): install
  and enable the *AppIndicator and KStatusNotifierItem Support*
  extension, then restart the buddy.
- **Minimal window managers** (i3, Openbox…): use a bar or tray that
  supports StatusNotifierItem, such as waybar, polybar with an SNI
  module, or `snixembed`.
- **You set `PYSTRAY_BACKEND`:** the buddy then leaves the tray to
  pystray. Unset it to get the D-Bus menu back.

Without a tray menu you can still reach every setting: right-click the
buddy, or run `clawd-buddy --settings`.
