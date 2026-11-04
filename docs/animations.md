# Animations

The buddy is a little terminal with a face on its screen: glowing pill
eyes, blush, small arms and feet. Changing state blends the pose over
about 0.2 seconds instead of snapping, and a status pill slides in above
its head.

With **Reduce motion** on, each state is a still pose; the pill and the
sounds stay. See [Comfort and accessibility](features.md#comfort-and-accessibility).

## Idle

- Slow breathing, blinks every few seconds
- Glances left and right now and then
- A small smile, arms relaxed
- No status pill (unless the workspace badge is showing)

## Greet: the first prompt of a new session

- One hop, then a friendly wave
- Happy arc eyes and a smile
- **Cyan** "New session" pill and a soft cyan glow
- Silent, about 1.8 seconds
- Once per Claude Code session (tracked by `session_id`)

## Thinking: from your prompt until Claude stops

- Hovers gently while both arms tap away, like typing
- Narrowed eyes looking up to the side
- **Purple** "Thinking…" pill with a spinner ("Thinking ×2" when two
  sessions are working)
- Silent
- Lasts until every working session has stopped, and comes back after
  any reaction while one is still working. A session that never stops
  (a crash, a dropped network) is let go after 10 minutes.

## Celebrate: Claude is done (`Stop`)

- Three quick hops with squash and stretch, then a happy sway
- Happy arc eyes (^ ^), an open smile, extra blush
- Both arms up, wiggling
- A confetti burst
- **Green** "Done" pill with a check mark and a green glow
- The sound pack's celebrate sound
- 5 seconds

## Wave: Claude needs your input (`PermissionRequest`)

- A small repeated bounce
- Wide eyes and a surprised "o" mouth
- Right arm raised and waving fast
- **Yellow** "Needs input" pill with a pulsing **!** and a yellow glow
- The sound pack's wave sound
- 5 seconds

## Speech bubble

`clawd-buddy --message "TEXT"` shows a rounded bubble above the buddy's
head (above the status pill, if one is showing).

- Dark on dark themes, white on light ones, like the pill
- Up to two lines; longer text is cut off with "…"
- Disappears after 3 seconds, and a new message replaces the current one
- Works in any state, without interrupting the animation
- Silent

The water reminder and pomodoro use bubbles too. See
[Integrations](integrations.md#speech-bubbles) for using them from
scripts.

## Several reactions at once

Reactions that arrive while another is playing wait their turn: up to
three play back in the order they arrived.
