# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Tests for the Linux StatusNotifierItem tray backend (ui/sni.py).

The D-Bus transport itself needs a session bus and a panel, so it's
verified by hand (see CHANGELOG 0.1.24). What's tested here is everything
the panel actually sees: the icon bytes, the DBusMenu layout built from
the real pystray menu, stable ids, and the method handlers, which are
called directly without a bus.
"""

import pytest
from PIL import Image

try:
    import pystray
except Exception as e:  # its Linux backends open an X display at import
    pytest.skip(f"pystray unavailable here: {e}", allow_module_level=True)

from clawd_buddy.ui import sni, tray

SEP = pystray.Menu.SEPARATOR


def _labels(node):
    return [child[1].get("label", ("s", "-"))[1] for _sig, child in node[2]]


def _find(node, label):
    for _sig, child in node[2]:
        if child[1].get("label", ("s", ""))[1] == label:
            return child
        found = _find(child, label)
        if found is not None:
            return found
    return None


# ── Icon pixmaps ─────────────────────────────────────────────────────
class TestIconPixmaps:
    def test_bytes_are_argb_network_order(self):
        # SNI wants A, R, G, B per pixel — not PIL's R, G, B, A.
        img = Image.new("RGBA", (16, 16), (10, 20, 30, 200))
        (w, h, data), = sni.icon_pixmaps(img, sizes=(16,))
        assert (w, h) == (16, 16)
        assert len(data) == 16 * 16 * 4
        assert data[:4] == bytes((200, 10, 20, 30))

    def test_offers_several_sizes(self):
        img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
        sizes = [(w, h) for w, h, _ in sni.icon_pixmaps(img)]
        assert (22, 22) in sizes and (64, 64) in sizes

    def test_real_buddy_icon_converts(self):
        from clawd_buddy.ui.about import _make_buddy_icon_image
        pixmaps = sni.icon_pixmaps(_make_buddy_icon_image())
        assert all(len(d) == w * h * 4 for w, h, d in pixmaps)


# ── Item properties ──────────────────────────────────────────────────
class TestItemProperties:
    def test_plain_item(self):
        props = sni.item_properties(pystray.MenuItem("Quit", None), SEP)
        assert props["label"] == ("s", "Quit")
        assert props["enabled"] == ("b", True)
        assert "toggle-type" not in props

    def test_separator(self):
        assert sni.item_properties(SEP, SEP) == {"type": ("s", "separator")}

    def test_checkmark_and_radio(self):
        check = pystray.MenuItem("Motion", None, checked=lambda _i: True)
        radio = pystray.MenuItem("Nord", None, checked=lambda _i: False,
                                 radio=True)
        assert sni.item_properties(check, SEP)["toggle-type"] == (
            "s", "checkmark")
        assert sni.item_properties(check, SEP)["toggle-state"] == ("i", 1)
        assert sni.item_properties(radio, SEP)["toggle-type"] == ("s", "radio")
        assert sni.item_properties(radio, SEP)["toggle-state"] == ("i", 0)

    def test_disabled_item(self):
        item = pystray.MenuItem("v1.0", None, enabled=False)
        assert sni.item_properties(item, SEP)["enabled"] == ("b", False)

    def test_underscore_is_not_a_mnemonic(self):
        item = pystray.MenuItem("snake_case", None)
        assert sni.item_properties(item, SEP)["label"] == ("s", "snake__case")

    def test_submenu_parent(self):
        item = pystray.MenuItem("Theme", pystray.Menu(
            pystray.MenuItem("Dark", None)))
        assert sni.item_properties(item, SEP)["children-display"] == (
            "s", "submenu")


# ── Menu model ───────────────────────────────────────────────────────
class TestMenuModel:
    def _menu(self, flags):
        return pystray.Menu(
            pystray.MenuItem("Water", None,
                             visible=lambda _i: flags["water"]),
            pystray.MenuItem("A", None),
            SEP,
            pystray.MenuItem("Sub", pystray.Menu(
                pystray.MenuItem("B", None), SEP,
                pystray.MenuItem("C", None))),
            SEP,
            pystray.MenuItem("Quit", None),
        )

    def test_layout_mirrors_menu(self):
        model = sni.MenuModel(self._menu({"water": False}), SEP)
        root = model.layout()
        assert root[0] == 0
        assert _labels(root) == ["A", "-", "Sub", "-", "Quit"]
        assert _labels(_find(root, "Sub")) == ["B", "-", "C"]

    def test_ids_are_unique(self):
        model = sni.MenuModel(self._menu({"water": True}), SEP)
        ids = []

        def walk(node):
            for _s, child in node[2]:
                ids.append(child[0])
                walk(child)
        walk(model.layout())
        assert len(ids) == len(set(ids))
        assert 0 not in ids  # 0 is the root

    def test_ids_stay_stable_when_items_appear(self):
        # The panel clicks by id from the layout it cached; an item
        # appearing above must not shift the ids below it.
        flags = {"water": False}
        model = sni.MenuModel(self._menu(flags), SEP)
        quit_before = _find(model.layout(), "Quit")[0]
        flags["water"] = True
        root = model.layout()
        assert _labels(root)[0] == "Water"
        assert _find(root, "Quit")[0] == quit_before

    def test_layout_is_comparable_for_change_detection(self):
        flags = {"water": False}
        model = sni.MenuModel(self._menu(flags), SEP)
        first = model.layout()
        assert model.layout() == first
        flags["water"] = True
        assert model.layout() != first

    def test_real_tray_menu_builds(self):
        # The full menu tray.py defines must convert without errors.
        built = {}

        class Capture:
            HAS_MENU = True

            def __init__(self, name, icon, title, menu):
                built["menu"] = menu

            def run(self):
                pass

        from clawd_buddy.state import BuddyState
        state = BuddyState(theme_name="dark", sound_pack="off")
        original = tray._pick_icon_class
        tray._pick_icon_class = lambda _p: Capture
        try:
            tray._create_tray_impl(state)
        finally:
            tray._pick_icon_class = original
        root = sni.MenuModel(built["menu"], SEP).layout()
        assert "Quit" in _labels(root)
        assert _find(root, "Dark")[1]["toggle-state"] == ("i", 1)


class TestFindAndPrune:
    TREE = (0, {"p": ("s", "root")}, [
        ("(ia{sv}av)", (1, {"label": ("s", "a"), "enabled": ("b", True)}, [
            ("(ia{sv}av)", (2, {"label": ("s", "b")}, [])),
        ])),
    ])

    def test_find_node(self):
        assert sni.find_node(self.TREE, 2)[1]["label"] == ("s", "b")
        assert sni.find_node(self.TREE, 99) is None

    def test_prune_depth(self):
        assert sni.prune(self.TREE, 0, [])[2] == []
        one = sni.prune(self.TREE, 1, [])
        assert one[2][0][1][2] == []
        assert sni.prune(self.TREE, -1, []) == self.TREE

    def test_prune_property_names(self):
        pruned = sni.prune(self.TREE, -1, ["label"])
        assert pruned[2][0][1][1] == {"label": ("s", "a")}


# ── D-Bus method handlers (no bus) ───────────────────────────────────
class TestHandlers:
    @pytest.fixture
    def icon(self):
        self.clicks = []
        self.flags = {"check": False}
        menu = pystray.Menu(
            pystray.MenuItem("Celebrate",
                             lambda _icon, _item: self.clicks.append("c")),
            pystray.MenuItem("Toggle",
                             lambda _icon, _item: self.flags.update(
                                 check=not self.flags["check"]),
                             checked=lambda _i: self.flags["check"]),
            pystray.MenuItem("Off", lambda _icon, _item: self.clicks.append(
                "x"), enabled=False),
        )
        icon = sni.SniIcon("clawd-buddy", Image.new("RGBA", (64, 64)),
                           "Clawd Buddy", menu)
        icon._layout = icon._model.layout()
        return icon

    def call(self, icon, path, iface, member, *args):
        return icon._handle_call(path, iface, member, args)

    def test_item_properties(self, icon):
        sig, (props,) = self.call(icon, sni.ITEM_PATH, sni.PROPS_IFACE,
                                  "GetAll", sni.ITEM_IFACE)
        assert sig == "a{sv}"
        assert props["Menu"] == ("o", sni.MENU_PATH)
        assert props["ItemIsMenu"] == ("b", True)
        assert props["Title"] == ("s", "Clawd Buddy")

    def test_get_single_property(self, icon):
        assert self.call(icon, sni.MENU_PATH, sni.PROPS_IFACE, "Get",
                         sni.MENU_IFACE, "Version") == ("v", (("u", 3),))

    def test_unknown_property_errors(self, icon):
        with pytest.raises(sni.DBusError):
            self.call(icon, sni.ITEM_PATH, sni.PROPS_IFACE, "Get",
                      sni.ITEM_IFACE, "Nope")

    def test_get_layout(self, icon):
        sig, (rev, root) = self.call(icon, sni.MENU_PATH, sni.MENU_IFACE,
                                     "GetLayout", 0, -1, [])
        assert sig == "u(ia{sv}av)"
        assert _labels(root) == ["Celebrate", "Toggle", "Off"]

    def test_click_runs_action(self, icon):
        node = _find(icon._layout, "Celebrate")
        self.call(icon, sni.MENU_PATH, sni.MENU_IFACE, "Event",
                  node[0], "clicked", ("i", 0), 0)
        assert self.clicks == ["c"]
        assert icon._dirty.is_set()  # loop will announce the new layout

    def test_hover_does_not_run_action(self, icon):
        node = _find(icon._layout, "Celebrate")
        self.call(icon, sni.MENU_PATH, sni.MENU_IFACE, "Event",
                  node[0], "hovered", ("i", 0), 0)
        assert self.clicks == []

    def test_disabled_item_does_nothing(self, icon):
        node = _find(icon._layout, "Off")
        self.call(icon, sni.MENU_PATH, sni.MENU_IFACE, "Event",
                  node[0], "clicked", ("i", 0), 0)
        assert self.clicks == []

    def test_unknown_id_errors(self, icon):
        with pytest.raises(sni.DBusError):
            self.call(icon, sni.MENU_PATH, sni.MENU_IFACE, "Event",
                      999, "clicked", ("i", 0), 0)

    def test_checkmark_updates_after_click(self, icon):
        node = _find(icon._layout, "Toggle")
        _sig, (rev1, _root) = self.call(icon, sni.MENU_PATH, sni.MENU_IFACE,
                                        "GetLayout", 0, -1, [])
        self.call(icon, sni.MENU_PATH, sni.MENU_IFACE, "Event",
                  node[0], "clicked", ("i", 0), 0)
        _sig, (rev2, root) = self.call(icon, sni.MENU_PATH, sni.MENU_IFACE,
                                       "GetLayout", 0, -1, [])
        assert rev2 > rev1
        assert _find(root, "Toggle")[1]["toggle-state"] == ("i", 1)

    def test_about_to_show_reports_changes(self, icon):
        assert self.call(icon, sni.MENU_PATH, sni.MENU_IFACE,
                         "AboutToShow", 0) == ("b", (False,))
        self.flags["check"] = True
        assert self.call(icon, sni.MENU_PATH, sni.MENU_IFACE,
                         "AboutToShow", 0) == ("b", (True,))

    def test_event_group(self, icon):
        node = _find(icon._layout, "Celebrate")
        sig, (errors,) = self.call(
            icon, sni.MENU_PATH, sni.MENU_IFACE, "EventGroup",
            [(node[0], "clicked", ("i", 0), 0),
             (999, "clicked", ("i", 0), 0)])
        assert self.clicks == ["c"]
        assert errors == [999]

    def test_group_properties(self, icon):
        node = _find(icon._layout, "Toggle")
        sig, (out,) = self.call(icon, sni.MENU_PATH, sni.MENU_IFACE,
                                "GetGroupProperties", [node[0]], ["label"])
        assert out == [(node[0], {"label": ("s", "Toggle")})]

    def test_activate_is_accepted(self, icon):
        assert self.call(icon, sni.ITEM_PATH, sni.ITEM_IFACE,
                         "Activate", 0, 0) == (None, ())

    def test_unknown_method_errors(self, icon):
        with pytest.raises(sni.DBusError) as e:
            self.call(icon, sni.MENU_PATH, sni.MENU_IFACE, "Bogus")
        assert e.value.name == sni.ERR_UNKNOWN_METHOD

    def test_introspect(self, icon):
        sig, (xml,) = self.call(icon, sni.MENU_PATH, sni.INTROSPECT_IFACE,
                                "Introspect")
        assert "com.canonical.dbusmenu" in xml

    def test_stop_and_update_are_flag_only(self, icon):
        # Safe from any thread: they must not touch the connection.
        icon.update_menu()
        icon.stop()
        assert icon._dirty.is_set() and icon._stop_event.is_set()


# ── Backend selection in tray.py ─────────────────────────────────────
class TestPickIconClass:
    class _NoMenu:
        HAS_MENU = False

    class _WithMenu:
        HAS_MENU = True

    def _fake_pystray(self, icon_cls):
        return type("P", (), {"Icon": icon_cls})

    @pytest.fixture(autouse=True)
    def _linux(self, monkeypatch):
        monkeypatch.setattr(tray.sys, "platform", "linux")
        monkeypatch.delenv("PYSTRAY_BACKEND", raising=False)

    def test_uses_sni_when_pystray_has_no_menu(self, monkeypatch):
        monkeypatch.setattr(sni, "watcher_available", lambda: True)
        assert tray._pick_icon_class(
            self._fake_pystray(self._NoMenu)) is sni.SniIcon

    def test_keeps_pystray_without_a_watcher(self, monkeypatch):
        monkeypatch.setattr(sni, "watcher_available", lambda: False)
        assert tray._pick_icon_class(
            self._fake_pystray(self._NoMenu)) is self._NoMenu

    def test_keeps_menu_capable_pystray_backend(self, monkeypatch):
        # e.g. AppIndicator via a system PyGObject — already works.
        monkeypatch.setattr(sni, "watcher_available", lambda: True)
        assert tray._pick_icon_class(
            self._fake_pystray(self._WithMenu)) is self._WithMenu

    def test_explicit_pystray_backend_wins(self, monkeypatch):
        monkeypatch.setenv("PYSTRAY_BACKEND", "xorg")
        monkeypatch.setattr(sni, "watcher_available", lambda: True)
        assert tray._pick_icon_class(
            self._fake_pystray(self._NoMenu)) is self._NoMenu

    def test_windows_untouched(self, monkeypatch):
        monkeypatch.setattr(tray.sys, "platform", "win32")
        monkeypatch.setattr(sni, "watcher_available", lambda: True)
        assert tray._pick_icon_class(
            self._fake_pystray(self._NoMenu)) is self._NoMenu
