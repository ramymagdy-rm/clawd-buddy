# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""The settings & About window: the pure helpers behind it, and (when
a display and tkinter are available) a real build of the window whose
controls must drive the live BuddyState and save to the config."""

import datetime
import json
import os
import types

import pytest

from clawd_buddy.state import BuddyState
from clawd_buddy.ui import about


def _state(**kw):
    kw.setdefault("theme_name", "dark")
    kw.setdefault("sound_pack", "off")
    return BuddyState(**kw)


# ── Pure helpers ─────────────────────────────────────────────────────
class TestStatusSummary:
    def test_idle(self):
        title, color, detail = about.status_summary(_state())
        assert title == "Idle"
        assert detail == "Waiting for Claude Code"
        assert color.startswith("#") and len(color) == 7

    def test_two_sessions_thinking(self):
        st = _state()
        st.start_thinking("a", "api")
        st.start_thinking("b", "web")
        title, color, detail = about.status_summary(st)
        assert title == "Thinking ×2"
        assert detail == "2 Claude Code sessions working"
        assert color == "#a88cf0"

    def test_sessions_win_over_the_water_reminder(self):
        st = _state()
        st.start_thinking("a")
        st.reminder_active = True
        assert about.status_summary(st)[2] == "1 Claude Code session working"

    def test_pomodoro_countdown_when_nothing_else(self):
        st = _state()
        st.start_pomodoro(25 * 60, 5 * 60)
        assert about.status_summary(st)[2].startswith("Focus · ")

    def test_colors_match_the_buddy_pill(self):
        from clawd_buddy.ui.drawing import ACCENT
        assert about.STATUS_COLORS == ACCENT


class TestWeekBars:
    def test_oldest_first_ending_with_today(self):
        st = _state(cups_today=3, recent_days=[
            {"date": "2026-10-31", "count": 5},
            {"date": "2026-10-30", "count": 7}])
        bars = about.week_bars(st, today=datetime.date(2026, 11, 1))
        assert bars == [("Fr", 7), ("Sa", 5), ("Su", 3)]

    def test_at_most_seven(self):
        days = [{"date": f"2026-10-{d:02d}", "count": 1}
                for d in range(30, 23, -1)]
        bars = about.week_bars(_state(recent_days=days),
                               today=datetime.date(2026, 11, 1))
        assert len(bars) == 7

    def test_garbage_dates_do_not_crash(self):
        st = _state()
        st.recent_days = [{"date": "nope", "count": 2}]
        assert about.week_bars(st)[0] == ("?", 2)


class TestFormatting:
    @pytest.mark.parametrize("secs,text", [
        (0, "00:00"), (59.6, "01:00"), (25 * 60, "25:00"),
        (3600 + 5 * 60, "1:05:00"), (None, "00:00"), (-3, "00:00")])
    def test_clock(self, secs, text):
        assert about._format_clock(secs) == text

    def test_short_path_uses_tilde(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/u")
        assert about._short_path("/home/u/.config/clawd-buddy") == \
            "~/.config/clawd-buddy"

    def test_short_path_cuts_the_middle(self):
        out = about._short_path("/x" * 60, limit=21)
        assert len(out) == 21 and "…" in out

    @pytest.mark.parametrize("s,e,text", [
        (22 * 60, 8 * 60, "Overnight, 10 hours"),
        (13 * 60, 14 * 60 + 30, "1 hour 30 min"),
        (60, 60, "Start and end are the same")])
    def test_span(self, s, e, text):
        assert about._span_text(s, e) == text


def test_reopening_raises_instead_of_spawning(monkeypatch):
    monkeypatch.setattr(about, "_ABOUT_DIALOG_OPEN", True)
    monkeypatch.setattr(about, "_RAISE_REQUEST", None)
    started = []
    monkeypatch.setattr(about.threading, "Thread",
                        lambda *a, **k: started.append(1))
    about.show_about_dialog(object(), page="focus")
    assert started == []
    assert about._RAISE_REQUEST == "focus"


# ── The real window ──────────────────────────────────────────────────
def _tk_root():
    try:
        import tkinter as tk
        return tk.Tk()
    except Exception as e:  # no tkinter, or no display
        pytest.skip(f"Tk unavailable: {e}")


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from clawd_buddy.ui import tkkit
    monkeypatch.setattr(tkkit, "system_prefers_dark", lambda: True)
    # Never touch the real autostart entry.
    import clawd_buddy.platform as plat
    monkeypatch.setattr(plat, "startup_enabled", lambda: False)
    root = _tk_root()
    st = _state(reminder_enabled=True)
    cc = about.ControlCenter(root, st, "buddy")
    root.update_idletasks()

    def saved():
        path = tmp_path / "clawd-buddy" / "config.json"
        return json.loads(path.read_text()) if path.exists() else {}
    yield types.SimpleNamespace(root=root, st=st, cc=cc, saved=saved)
    root.destroy()


def _click_option(seg, value):
    i = [v for v, _l in seg.options].index(value)
    x = seg.kit.px(3) + i * seg.seg + seg.seg // 2
    seg._click(types.SimpleNamespace(x=x, y=5))


class TestWindow:
    def test_all_pages_build(self, window):
        assert list(window.cc.pages) == list(about.PAGES)
        for page in about.PAGES:
            window.cc.show(page)
            window.root.update_idletasks()
        window.cc.kit.refresh_all()

    def test_size_applies_and_saves(self, window):
        _click_option(window.cc.controls["size"], 6)
        assert window.st.scale_preset == 6
        assert window.st._scale_changed
        assert window.saved()["size"] == 6

    def test_theme_applies_and_saves(self, window):
        sw = window.cc.controls["theme"]
        i = [v for v, *_ in sw.items].index("nord")
        sw._click(types.SimpleNamespace(x=i * sw.cell + 2, y=5))
        assert window.st.theme_name == "nord"
        assert window.saved()["theme"] == "nord"

    def test_toggle_applies_and_saves(self, window):
        window.cc.controls["reduce_motion"]._click(None)
        assert window.st.reduce_motion is True
        assert window.saved()["reduce_motion"] is True

    def test_follows_changes_made_elsewhere(self, window):
        # e.g. the tray's Theme / Size menus, or Ctrl+3 on the buddy.
        window.st.set_theme("dracula")
        window.st.set_scale(3)
        window.cc.kit.refresh_all()
        assert window.cc.controls["theme"].value == "dracula"
        assert window.cc.controls["size"].value == 3

    def test_sound_pack_and_volume(self, window):
        _click_option(window.cc.controls["sound_pack"], "chime")
        assert window.st.sound_pack == "chime"
        window.cc.kit.refresh_all()
        assert window.cc.controls["volume"].enabled
        _click_option(window.cc.controls["volume"], 0.5)
        assert window.st.volume == pytest.approx(0.5)
        assert window.saved()["volume"] == pytest.approx(0.5)

    def test_volume_is_greyed_out_while_muted(self, window):
        window.cc.kit.refresh_all()
        assert not window.cc.controls["volume"].enabled

    def test_quiet_hours_toggle_uses_the_shown_times(self, window):
        quiet = window.cc.controls["quiet"]
        assert window.st.quiet_start is None
        assert not quiet.start.enabled
        quiet.toggle._click(None)
        assert (window.st.quiet_start, window.st.quiet_end) == (
            22 * 60, 8 * 60)
        window.cc.kit.refresh_all()
        assert quiet.start.enabled
        quiet.start._step(1)  # 22:00 → 22:30
        assert window.st.quiet_start == 22 * 60 + 30
        assert window.saved()["quiet_hours"] == {"start": 1350, "end": 480}
        quiet.toggle._click(None)
        assert window.st.quiet_start is None
        assert "quiet_hours" not in window.saved()

    def test_reminder_controls_grey_out_when_off(self, window):
        window.cc.controls["reminder"]._click(None)
        assert window.st.reminder_enabled is False
        window.cc.kit.refresh_all()
        assert not window.cc.controls["interval"].enabled
        assert not window.cc.controls["reminder_sound"].enabled

    def test_reminder_interval(self, window):
        _click_option(window.cc.controls["interval"], 2 * 3600)
        assert window.st.reminder_interval == 2 * 3600
        assert window.saved()["reminder"]["interval"] == 2 * 3600

    def test_pomodoro_start_and_stop(self, window):
        c = window.cc.controls
        c["pomodoro_work"]._step(-1)    # 25 → 20 min
        c["pomodoro_break"]._step(1)    # 5 → 10 min
        c["pomodoro_start"].command()
        assert window.st.pomodoro_active
        assert window.st.pomodoro_work_s == 20 * 60
        assert window.st.pomodoro_break_s == 10 * 60
        window.cc.kit.refresh_all()
        assert c["pomodoro_start"].text == "Restart"
        assert c["pomodoro_stop"].enabled
        c["pomodoro_stop"].command()
        assert not window.st.pomodoro_active

    def test_raise_request_switches_page(self, window, monkeypatch):
        monkeypatch.setattr(about, "_RAISE_REQUEST", "focus")
        window.cc._tick()
        assert window.cc.current == "focus"
        assert about._RAISE_REQUEST is None


def test_without_state_only_the_about_page(monkeypatch):
    from clawd_buddy.ui import tkkit
    monkeypatch.setattr(tkkit, "system_prefers_dark", lambda: False)
    root = _tk_root()
    try:
        cc = about.ControlCenter(root, None)
        assert list(cc.pages) == ["about"]
    finally:
        root.destroy()


def test_startup_enabled_reads_the_autostart_entry(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Linux autostart file")
    from clawd_buddy.platform import _linux
    monkeypatch.setattr(_linux, "_LINUX_AUTOSTART_DIR", str(tmp_path))
    assert not _linux._linux_startup_enabled()
    (tmp_path / _linux._DESKTOP_NAME).write_text("[Desktop Entry]\n")
    assert _linux._linux_startup_enabled()
