# Features

Everything the buddy does, and how to set it up. For what each reaction
looks like, see [Animations](animations.md). For driving it from scripts
and other tools, see [Integrations](integrations.md).

- [How it reacts](#how-it-reacts)
- [Settings window](#settings-window)
- [Sound packs](#sound-packs)
- [Comfort and accessibility](#comfort-and-accessibility)
- [Water reminder](#water-reminder)
- [Drinking history](#drinking-history)
- [Pomodoro](#pomodoro)
- [Workspace badge](#workspace-badge)
- [Controls and sizes](#controls-and-sizes)
- [Tray menu](#tray-menu)

## How it reacts

| When | What the buddy does |
| --- | --- |
| **Idle** | Breathes, blinks and glances around now and then |
| **A new session starts** (first prompt) | Hops and waves hello; a **cyan** "New session" pill |
| **Claude is working** (prompt → `Stop`) | Hovers and taps away; a **purple** "Thinking…" pill with a spinner |
| **Claude is done** (`Stop`) | Hops with arms up, confetti, a short fanfare; a **green** "Done" pill |
| **Claude needs you** (`PermissionRequest`) | Bounces and waves, a two-note doorbell; a **yellow** "Needs input" pill |

The status pill lets you see what the assistant is doing without
switching windows. With a compositor (Linux) the buddy also gets a soft
ground shadow, a coloured glow while it reacts, and smooth edges.

- **Nothing gets lost.** If signals arrive while an animation is still
  playing, up to three are queued and play in the order they came.
- **Several sessions at once.** Each Claude Code session is tracked from
  its prompt to its own `Stop` (by the hooks' `session_id`). When one
  finishes, the buddy celebrates and goes back to thinking for the
  others; the pill reads "Thinking ×2" while two are working.

## Settings window

**Right-click the buddy**, pick **Settings & About…** in the tray menu,
or run `clawd-buddy --settings`. One window controls everything:

| Page | What's there |
| --- | --- |
| **Buddy** | What the buddy is doing now (a chip per working workspace), Celebrate / Bring to front / Center on screen, size, theme, reduce motion, workspace badges, start at login |
| **Sound** | Sound pack (picking one plays a preview), volume, quiet hours with any start and end time |
| **Reminders** | Today's cups and a chart of recent days, an **I drank water** button, and the reminder schedule |
| **Focus** | A pomodoro timer with a live countdown ring: focus and break lengths, Start / Restart / Stop |
| **About** | Version, source link, the settings folder, keyboard shortcuts |

Changes apply at once and are saved; there's no Save button. Changes
made elsewhere (the tray menu, Ctrl+1…7) show up while the window is
open, and it follows your desktop's light or dark mode.
`clawd-buddy --settings focus` opens it on a given page. The sidebar's
**Quit Clawd Buddy** button asks for a second click before closing the
buddy.

## Sound packs

Pick one in the settings window or the tray menu (**Sound**). Picking a
pack plays its celebrate sound straight away, so you can try them out.

| Pack | Celebrate | Wave |
| --- | --- | --- |
| **Fanfare** (default) | Rising C-major arpeggio that lands on a full chord | Warm two-note doorbell (G4 → D4) |
| **Chime** | Two rising bell tones | A single lower bell |
| **Retro** | 8-bit coin pickup (C5 → E5 → G5 → C6) | Two short low-high blips |
| **Minimal** | One short soft pip | One short low pip |
| **Off** | Silent | Silent |

No audio files are bundled: every sound is synthesized at start-up. If
your machine has no audio device, the buddy runs silently and the status
pill still shows what's happening.

## Comfort and accessibility

- **Reduce motion.** The buddy stops hopping, bobbing, swinging its arms
  and throwing confetti, and holds a still pose for each state. The
  status pill and sounds stay, so you can still tell what's happening.
- **Volume.** From 0% to 100%. Picking a level plays a preview.
- **Quiet hours.** A nightly window (for example 23:00–08:00) in which
  every sound is muted; the animations still play. It can wrap past
  midnight.

All three are in the settings window, and in the tray menu (**Reduce
Motion**, **Sound → Volume**, **Sound → Quiet Hours**). Defaults: motion
on, volume 100%, quiet hours off.

## Water reminder

The buddy can remind you to drink water. It's off by default; turn it on
in the tray menu (**Water Reminder**) or on the settings window's
**Reminders** page, where all its options live:

| Setting | Options |
| --- | --- |
| **How often** | 30 min, 1 h (default), 1.5 h, 2 h, 4 h |
| **Day starts at** | Any time in 30-minute steps (default 08:00). With 09:00 and every hour, reminders come at 09:00, 10:00, 11:00, … |
| **Sound** | Water (a bright bell, default), Chime, Beep, or Off for visual only. Picking one plays it |
| **Pause overnight** | On by default, 23:00–08:00. Turn it off to be reminded around the clock |

When a reminder is due, its sound plays once and the buddy shows a
**"Drink water!"** bubble until you confirm, in any of these ways:

- press **Space** while the buddy has focus,
- click **I drank water** in the tray menu (shown only while a reminder
  is waiting) or in the settings window,
- run `clawd-buddy --drank`, which also suits smart bottles, macros and
  scripts.

Confirming doesn't move the schedule; the next reminder still comes on
time. Reminders that fall in the overnight pause are skipped, not saved
up for the morning.

## Drinking history

Every confirmation adds a cup to today's count. The **Reminders** page
shows today's cups in large type, a chart of the last seven days and
when the next reminder is due. Counting works whether or not the
reminder is on, so you can use the buddy just to keep track.

At midnight the day moves into the history and the count starts again.
Days without any cups aren't kept. The history is a small JSON file in
`~/.clawd-buddy/history.json` (see
[where things are stored](platforms.md#where-settings-and-data-live)),
easy to back up or edit by hand:

```json
{
  "today":  { "date": "2026-05-25", "count": 3 },
  "recent": [
    { "date": "2026-05-24", "count": 6 },
    { "date": "2026-05-23", "count": 5 }
  ]
}
```

## Pomodoro

```bash
clawd-buddy --pomodoro 25/5    # 25 min focus, 5 min break, repeating
clawd-buddy --pomodoro-stop    # end it
```

Or use the settings window's **Focus** page. The buddy keeps time for
you:

- **Break starts:** it celebrates and says **"Break time!"**
- **Break ends:** it waves and says **"Back to work!"**
- It repeats until you stop it (the command, the **Focus** page, the
  tray's **Stop Pomodoro** entry, or quitting the buddy).

Your volume, quiet hours and reduce-motion settings apply. Each length
can be 1–180 minutes. If the computer was asleep when a phase should
have ended, the buddy catches up as soon as it wakes, and the next phase
still ends on schedule. A cycle doesn't survive restarting the buddy.
`clawd-buddy --status` shows the phase, the time left and how many
cycles you've done.

## Workspace badge

Running Claude Code in several projects at once? A small one-letter
badge at the front of the status pill shows **which project last
signalled**, so when the buddy asks for permission you know which window
to switch to.

- The label comes from the project folder automatically (`C:\dev\api`
  → **A**). Scripts can set it with `--workspace LABEL`, and webhook
  callers with `{"action": "wave", "workspace": "ci"}`.
- Each workspace keeps the same colour, even across restarts.
- It only appears once a **second** workspace signals. With one project,
  the buddy looks exactly as before.
- While thinking, the pill shows a chip for **every** project with a
  session still working (up to three).
- It shows while the buddy is thinking and for about 8 seconds after a
  reaction. Turn it off in the tray menu (**Workspace Badge**) or the
  settings window.

## Controls and sizes

| Input | Action |
| --- | --- |
| **Drag** | Move the buddy. It can go right up to the screen's edges. Clicks around it go through to whatever is behind |
| **Right-click** | Open the settings window |
| **Space** | Test celebration (or confirm a water reminder) |
| **Ctrl+1 … Ctrl+7** | Size: S (1×), M (1.25×), L (1.5×), L+ (2×), XL (3×), XXL (4×), XXXL (5×) |
| **Escape** | Quit the buddy |

The same sizes are in the tray's **Size** menu, and your size is
remembered. The buddy keeps its feet in place when it grows or shrinks.
At XXXL its window is taller than a 1080p screen, so the buddy slides up
inside it to stay in view.

## Tray menu

Right-click the buddy's icon in the system tray:

- **Test Celebration**
- **Size**: S to XXXL, same as Ctrl+1…7
- **Bring to Front**: puts the buddy back on top of other windows
- **Center on Screen**: brings back a buddy that was dragged away or
  ended up off-screen
- **Theme**: the 8 classic palettes, then submenus for the characters,
  princesses and animals (see [Themes](themes.md))
- **Sound**: the sound pack, plus **Volume** and **Quiet Hours**
- **Reduce Motion**
- **Water Reminder**, and **I drank water** while a reminder is waiting
- **Stop Pomodoro**, while a cycle is running
- **Workspace Badge**
- **Settings & About…**: the [settings window](#settings-window)
- **Quit**

On Linux your panel draws the menu itself, so it looks like every other
tray menu (see [Platforms](platforms.md#linux)).
