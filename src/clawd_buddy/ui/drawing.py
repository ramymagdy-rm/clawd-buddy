# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Procedural drawing of the buddy character.

Pure pygame surface mutation — no platform code, no state ownership.
`draw_buddy(surf, t, state, blink)` is called once per frame from the
main loop with whichever pygame surface should receive the paint.
"""

import math

import pygame

from ..constants import CHAR_H, CHAR_W, WIN_H, WIN_W


# Lazy-initialised font for the speech bubble. We can't build it at
# module import (pygame.font isn't init'd yet); cache after first use so
# the per-frame cost is one Font.render call instead of a font lookup.
_BUBBLE_FONT = None
_BUBBLE_FONT_SIZE = 13


def _bubble_font():
    """Return (and cache) the speech-bubble font. pygame.font init is
    idempotent — calling it more than once is cheap."""
    global _BUBBLE_FONT
    if _BUBBLE_FONT is None:
        if not pygame.font.get_init():
            pygame.font.init()
        _BUBBLE_FONT = pygame.font.SysFont(None, _BUBBLE_FONT_SIZE + 4)
    return _BUBBLE_FONT


def _wrap_bubble_text(font, text, max_px, max_lines=2):
    """Word-wrap `text` to fit within `max_px` pixels per line, capped at
    `max_lines`. Long final line is truncated with an ellipsis.

    Word wrapping is good enough for the bubble's status-ping use case
    — we don't try to hyphenate single words longer than the line; they
    overflow and then get truncated by the ellipsis pass.
    """
    words = text.split()
    if not words:
        return []
    lines = []
    current = ""
    for w in words:
        candidate = w if not current else f"{current} {w}"
        if font.size(candidate)[0] <= max_px:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = w
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)

    if not lines:
        return []

    # If the final line still overflows (single mega-word, or the cap
    # cut us short), trim with an ellipsis until it fits.
    last = lines[-1]
    if font.size(last)[0] > max_px or len(lines) == max_lines and len(words) > sum(len(l.split()) for l in lines):
        # Append ellipsis and trim from the right until it fits.
        candidate = last + "…"
        while font.size(candidate)[0] > max_px and len(candidate) > 1:
            candidate = candidate[:-2] + "…"
        lines[-1] = candidate
    return lines


def draw_speech_bubble(surf, text, cx, head_top_y, theme):
    """Draw a rounded speech bubble with a small downward tail above the
    buddy's head. `cx` is the buddy's horizontal centre; `head_top_y` is
    the topmost y of the body — the bubble is anchored a few pixels above
    it. `theme` provides the colours.

    No-op when `text` is empty (callers can pass `state.bubble_text`
    unconditionally and rely on this short-circuit).
    """
    if not text:
        return
    font = _bubble_font()
    pad_x, pad_y = 6, 4
    margin = 6  # gap between window edge and bubble
    tail_h = 6
    max_text_px = WIN_W - 2 * margin - 2 * pad_x

    lines = _wrap_bubble_text(font, text, max_text_px, max_lines=2)
    if not lines:
        return

    line_surfs = [font.render(l, True, theme["mouth"]) for l in lines]
    line_w = max(s.get_width() for s in line_surfs)
    line_h = line_surfs[0].get_height()
    bubble_w = line_w + 2 * pad_x
    bubble_h = line_h * len(line_surfs) + 2 * pad_y

    # Position the bubble centred horizontally, clamped inside the window.
    bx = int(cx - bubble_w / 2)
    bx = max(margin, min(bx, WIN_W - margin - bubble_w))
    by = head_top_y - bubble_h - tail_h - 2
    # If the bubble would go off the top of the window, clamp it down
    # — better to overlap the head a little than render off-screen.
    by = max(margin, by)

    rounded_rect(surf, theme["screen_bg"], (bx, by, bubble_w, bubble_h), 6)
    pygame.draw.rect(
        surf, theme["body_outer"], (bx, by, bubble_w, bubble_h),
        width=1, border_radius=6,
    )

    # Tail — a small triangle dropping from the bottom-centre toward the
    # buddy's head. Drawn after the bubble body so the outline overlap is
    # invisible.
    tail_top_y = by + bubble_h - 1
    tail_x = max(bx + 8, min(int(cx), bx + bubble_w - 8))
    pygame.draw.polygon(
        surf, theme["screen_bg"],
        [(tail_x - 5, tail_top_y),
         (tail_x + 5, tail_top_y),
         (tail_x, tail_top_y + tail_h)],
    )
    # Outline the two diagonal edges (skip the top — covered by bubble).
    pygame.draw.line(
        surf, theme["body_outer"],
        (tail_x - 5, tail_top_y), (tail_x, tail_top_y + tail_h), 1,
    )
    pygame.draw.line(
        surf, theme["body_outer"],
        (tail_x + 5, tail_top_y), (tail_x, tail_top_y + tail_h), 1,
    )

    for i, line_surf in enumerate(line_surfs):
        lx = bx + pad_x + (line_w - line_surf.get_width()) // 2
        ly = by + pad_y + i * line_h
        surf.blit(line_surf, (lx, ly))


def rounded_rect(surf, color, rect, r):
    """Draw a filled rounded rectangle.

    pygame.draw.rect supports a border_radius parameter directly but its
    blending is inconsistent with circles — this composes two rectangles
    plus four corner circles which produces a cleaner edge.
    """
    x, y, w, h = rect
    r = min(r, w // 2, h // 2)
    pygame.draw.rect(surf, color, (x + r, y, w - 2 * r, h))
    pygame.draw.rect(surf, color, (x, y + r, w, h - 2 * r))
    for cx, cy in [(x+r, y+r), (x+w-r, y+r), (x+r, y+h-r), (x+w-r, y+h-r)]:
        pygame.draw.circle(surf, color, (cx, cy), r)


def draw_buddy(surf, t, state, blink):
    """Render the buddy for the current frame.

    `t` is the wall-clock time (used as a phase source for all sine-wave
    animations). `state` carries the current mode and theme. `blink` is
    a precomputed boolean — the main loop owns the blink timer because
    it's a window-level concern (paused on inactive windows in the
    future).
    """
    th = state.theme
    cel = state.celebrating
    wav = state.waving
    greet = state.greeting
    think = state.thinking
    cx = WIN_W // 2
    base_y = WIN_H - 70
    bob = math.sin(t * 2.2) * 1.5
    if cel:
        bob = math.sin(t * 10) * 6
    elif wav:
        bob = math.sin(t * 4) * 3
    elif greet:
        bob = math.sin(t * 5) * 4
    elif think:
        # Slower, slightly higher amplitude than idle — a "concentrating
        # sway" that reads as alive but not excited.
        bob = math.sin(t * 1.3) * 1.8

    by = int(base_y - CHAR_H + bob)

    # ── Legs ──────────────────────────────────────────────────────
    leg_top = int(by + CHAR_H - 2)
    leg_len = 18
    if cel:
        l_swing = math.sin(t * 7) * 8
        r_swing = math.sin(t * 7 + math.pi) * 8
    elif wav:
        l_swing = math.sin(t * 3) * 3
        r_swing = math.sin(t * 3 + math.pi) * 3
    elif greet:
        l_swing = math.sin(t * 2.5) * 2
        r_swing = math.sin(t * 2.5 + math.pi) * 2
    else:
        # Shared by idle and thinking — quiet baseline sway.
        l_swing = math.sin(t * 1.8) * 1.5
        r_swing = math.sin(t * 1.8 + math.pi) * 1.5
    for sx, sw in [(-14, l_swing), (14, r_swing)]:
        fx = int(cx + sx + sw)
        fy = leg_top + leg_len
        pygame.draw.line(surf, th["limb"], (cx + sx, leg_top), (fx, fy), 5)
        rounded_rect(surf, th["shoe"], (fx - 7, fy - 2, 14, 8), 3)

    # ── Arms ──────────────────────────────────────────────────────
    arm_y = int(by + CHAR_H // 2 + bob)
    arm_len = 22
    if cel:
        la = math.sin(t * 8) * 0.5 - 1.3
        ra = math.sin(t * 8 + math.pi) * 0.5 + 0.3
    elif wav:
        la = math.sin(t * 1.2) * 0.1 - 0.2
        ra = math.sin(t * 6) * 0.4 - 1.0
    elif greet:
        # Right arm raised in a friendly hello — softer than the "needs
        # attention" wave (lower amplitude, smaller raise).
        la = math.sin(t * 1.2) * 0.1 - 0.2
        ra = math.sin(t * 4) * 0.3 - 0.6
    else:
        # idle / thinking
        la = math.sin(t * 1.2) * 0.1 - 0.2
        ra = math.sin(t * 1.2 + 1) * 0.1 + 0.2

    lx1 = cx - CHAR_W // 2 - 2
    lx2 = int(lx1 + math.cos(math.pi + la) * arm_len)
    ly2 = int(arm_y + math.sin(math.pi + la) * arm_len)
    pygame.draw.line(surf, th["limb"], (lx1, arm_y), (lx2, ly2), 5)
    pygame.draw.circle(surf, th["limb"], (lx2, ly2), 4)

    rx1 = cx + CHAR_W // 2 + 2
    rx2 = int(rx1 + math.cos(ra) * arm_len)
    ry2 = int(arm_y + math.sin(ra) * arm_len)
    pygame.draw.line(surf, th["limb"], (rx1, arm_y), (rx2, ry2), 5)
    pygame.draw.circle(surf, th["limb"], (rx2, ry2), 4)

    # ── Body ──────────────────────────────────────────────────────
    bx = cx - CHAR_W // 2
    rounded_rect(surf, th["body_outer"], (bx, by, CHAR_W, CHAR_H), 8)
    rounded_rect(surf, th["body_inner"],
                 (bx + 2, by + 2, CHAR_W - 4, CHAR_H - 4), 7)

    # Title bar
    rounded_rect(surf, th["title_bar"],
                 (bx + 2, by + 2, CHAR_W - 4, 10), 6)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        pygame.draw.circle(surf, c, (bx + 10 + i * 9, by + 7), 2)

    # Screen area
    scr = (bx + 6, by + 14, CHAR_W - 12, CHAR_H - 22)
    rounded_rect(surf, th["screen_bg"], scr, 4)

    # ── Eyes ──────────────────────────────────────────────────────
    sx, sy, sw, sh = scr
    ey = sy + sh // 2 - 2
    lex = sx + sw // 3
    rex = sx + 2 * sw // 3
    er = 8

    if blink and not wav:
        for ex in (lex, rex):
            pygame.draw.line(surf, th["eye_white"],
                             (ex - 6, ey), (ex + 6, ey), 2)
    elif cel:
        for ex in (lex, rex):
            pygame.draw.arc(surf, th["mouth_happy"],
                            (ex - 7, ey - 5, 14, 10),
                            math.radians(0), math.radians(180), 3)
    elif greet:
        # Smaller happy arc than celebrate — friendly but not exuberant.
        for ex in (lex, rex):
            pygame.draw.arc(surf, th["mouth_happy"],
                            (ex - 6, ey - 4, 12, 8),
                            math.radians(0), math.radians(180), 2)
    elif wav:
        for ex in (lex, rex):
            pygame.draw.circle(surf, th["eye_white"], (ex, ey), er + 1)
            pygame.draw.circle(surf, th["pupil"], (ex, ey), 5)
            pygame.draw.circle(surf, (255, 255, 255), (ex - 2, ey - 3), 2)
    elif think:
        # Pupils lifted slightly + a slow horizontal sweep ⇒ "considering".
        for ex in (lex, rex):
            pygame.draw.circle(surf, th["eye_white"], (ex, ey), er)
            px = ex + math.sin(t * 0.9) * 3
            py = ey - 2 + math.cos(t * 0.5) * 0.5
            pygame.draw.circle(surf, th["pupil"], (int(px), int(py)), 4)
            pygame.draw.circle(surf, (255, 255, 255), (ex - 2, ey - 4), 2)
    else:
        for ex in (lex, rex):
            pygame.draw.circle(surf, th["eye_white"], (ex, ey), er)
            px = ex + math.sin(t * 0.6 + ex * 0.01) * 2
            py = ey + math.cos(t * 0.8) * 1.5
            pygame.draw.circle(surf, th["pupil"], (int(px), int(py)), 4)
            pygame.draw.circle(surf, (255, 255, 255), (ex - 2, ey - 3), 2)

    # ── Mouth ─────────────────────────────────────────────────────
    my = sy + sh - 6
    if cel:
        pygame.draw.arc(surf, th["mouth_happy"],
                        (cx - 10, my - 7, 20, 12),
                        math.radians(200), math.radians(340), 2)
    elif greet:
        # Smaller smile — friendly, lower-key than celebrate.
        pygame.draw.arc(surf, th["mouth_happy"],
                        (cx - 7, my - 5, 14, 9),
                        math.radians(200), math.radians(340), 2)
    elif wav:
        pygame.draw.circle(surf, th["wave_eye"], (cx, my - 2), 4, 2)
    else:
        # Idle and thinking share the calm mouth line.
        w_m = 10 + math.sin(t * 1.5) * 1
        pygame.draw.line(surf, th["mouth"],
                         (int(cx - w_m / 2), my),
                         (int(cx + w_m / 2), my), 2)

    # ── Attention border ──────────────────────────────────────────
    # Pulsing rounded outline framing the body to catch peripheral vision.
    # Fixed colors instead of theme accents so the meaning is consistent
    # across all 8 themes:
    #   green   = celebrating  (done)
    #   yellow  = waving       (attention needed)
    #   cyan    = greeting     (new session)
    #   purple  = thinking     (responding) — gentler pulse, lower max alpha
    if cel or wav or greet or think:
        if cel:
            border_color = (80, 220, 110)   # bright green
            pulse_speed = 6.0
        elif wav:
            border_color = (255, 215, 60)   # warm yellow
            pulse_speed = 4.0
        elif greet:
            border_color = (60, 180, 220)   # soft cyan
            pulse_speed = 5.0
        else:  # think
            border_color = (160, 130, 220)  # soft purple
            pulse_speed = 1.2
        pulse = (math.sin(t * pulse_speed) + 1) / 2  # 0..1
        if think:
            # Thinking is the ambient mode — keep the pulse muted so it
            # blends into the background while a prompt is processing.
            alpha_val = int(40 + 90 * pulse)         # ~40..130
        else:
            alpha_val = int(60 + 195 * pulse)        # ~60..255
        pad = 3
        thick = 3
        bw = CHAR_W + 2 * pad
        bh = CHAR_H + 2 * pad
        border_surf = pygame.Surface((bw + 2 * thick, bh + 2 * thick),
                                     pygame.SRCALPHA)
        pygame.draw.rect(
            border_surf, (*border_color, alpha_val),
            (0, 0, bw + 2 * thick, bh + 2 * thick),
            width=thick, border_radius=11,
        )
        surf.blit(border_surf, (bx - pad - thick, by - pad - thick))

    # ── Attention indicator ───────────────────────────────────────
    if wav:
        pulse = (math.sin(t * 5) + 1) / 2
        alpha_val = int(180 + 75 * pulse)
        ix = cx + 30
        iy = int(by - 18 + math.sin(t * 3) * 4)
        bang_surf = pygame.Surface((20, 28), pygame.SRCALPHA)
        bang_color = (*th["wave_eye"], alpha_val)
        pygame.draw.rect(bang_surf, bang_color, (7, 2, 6, 14),
                         border_radius=3)
        pygame.draw.circle(bang_surf, bang_color, (10, 22), 3)
        surf.blit(bang_surf, (ix - 10, iy - 14))

    # ── Thinking indicator (•••) ──────────────────────────────────
    # Three small purple dots above the head, each pulsing on its own
    # phase so the cluster reads as a "typing" animation rather than a
    # static decoration.
    if think:
        dot_y = by - 12
        for i, dx in enumerate((-10, 0, 10)):
            phase = (math.sin(t * 3.5 + i * 1.4) + 1) / 2
            alpha_val = int(70 + 150 * phase)
            dot_surf = pygame.Surface((8, 8), pygame.SRCALPHA)
            pygame.draw.circle(
                dot_surf, (160, 130, 220, alpha_val), (4, 4), 3,
            )
            surf.blit(dot_surf, (cx + dx - 4, dot_y - 4))

    # ── Speech bubble ─────────────────────────────────────────────
    # Drawn last (other than confetti) so it sits above the thinking
    # dots and the attention border, but confetti still rains in front.
    if state.bubble_text:
        draw_speech_bubble(surf, state.bubble_text, cx, by, th)

    # ── Confetti ──────────────────────────────────────────────────
    alive = []
    for p in state.confetti:
        p[0] += p[2]; p[1] += p[3]; p[3] += 0.18; p[2] *= 0.99
        if p[1] < WIN_H + 10:
            alive.append(p)
            pygame.draw.rect(surf, p[4],
                             (int(p[0]), int(p[1]), p[5], p[5]))
    state.confetti = alive
