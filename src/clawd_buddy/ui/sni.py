# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Linux tray icon with a working right-click menu, via D-Bus.

Why this exists: on Linux, pystray picks its backend at import time.
Its menu-capable backends (AppIndicator, GTK) need PyGObject (`gi`),
which a `uv tool` / `pipx` / pip venv doesn't have and can't easily
build. pystray then falls back to its `xorg` backend, which shows an
icon but has `HAS_MENU = False`: right-clicking it does nothing.

Modern Linux panels (GNOME with the AppIndicator extension, which Ubuntu
ships enabled; KDE Plasma; Xfce, Cinnamon and others) host tray icons
through the freedesktop **StatusNotifierItem** (SNI) protocol and draw
the menu themselves from a **com.canonical.dbusmenu** description. Both
are plain D-Bus. This module speaks them with `jeepney` (pure Python, no
compiled code, no `gi`), so the panel shows a native menu built from the
same `pystray.Menu` that `tray.py` already defines.

`SniIcon` mirrors the part of `pystray.Icon` that `tray.py` uses
(`run`, `stop`, `update_menu`, and being passed to menu actions), so
the menu definition stays backend-agnostic. `MenuModel` and
`icon_pixmaps` are pure helpers, unit-tested without a bus.

jeepney is imported lazily so this module imports on any OS.
"""

import os
import threading
import time

from PIL import Image

WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_IFACE = "org.kde.StatusNotifierItem"
ITEM_PATH = "/StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"
MENU_PATH = "/MenuBar"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
INTROSPECT_IFACE = "org.freedesktop.DBus.Introspectable"

ERR_UNKNOWN_METHOD = "org.freedesktop.DBus.Error.UnknownMethod"
ERR_UNKNOWN_PROPERTY = "org.freedesktop.DBus.Error.UnknownProperty"
ERR_READ_ONLY = "org.freedesktop.DBus.Error.PropertyReadOnly"
ERR_INVALID_ARGS = "org.freedesktop.DBus.Error.InvalidArgs"

LAYOUT_SIG = "(ia{sv}av)"

# How often the loop wakes without traffic to re-check the menu for
# changes made outside it (water reminder firing, About-dialog toggles).
_POLL_SECONDS = 0.5
_REFRESH_SECONDS = 1.0


class DBusError(Exception):
    """Raised by a handler to send a D-Bus error reply."""

    def __init__(self, name, text=""):
        super().__init__(text)
        self.name = name
        self.text = text


def watcher_available():
    """True when a StatusNotifierWatcher (a panel that can host SNI
    icons) is on the session bus. False if jeepney is missing, there is
    no session bus, or nobody hosts SNI icons (e.g. stock GNOME without
    the AppIndicator extension)."""
    try:
        from jeepney.bus_messages import message_bus
        from jeepney.io.blocking import Proxy, open_dbus_connection
    except ImportError:
        return False
    try:
        with open_dbus_connection(bus="SESSION") as conn:
            reply = Proxy(message_bus, conn, timeout=2).NameHasOwner(
                WATCHER_NAME)
            return bool(reply[0])
    except Exception:
        return False


def icon_pixmaps(image, sizes=(16, 22, 24, 32, 48, 64)):
    """Convert a PIL image into the SNI `IconPixmap` value, a(iiay).

    The spec wants ARGB32 in network byte order, i.e. bytes A, R, G, B
    per pixel. Several sizes are offered so the panel can pick a crisp
    one instead of scaling a single bitmap."""
    src = image.convert("RGBA")
    out = []
    for size in sizes:
        img = src if src.size == (size, size) else src.resize(
            (size, size), Image.Resampling.LANCZOS)
        r, g, b, a = img.split()
        out.append((size, size, Image.merge("RGBA", (a, r, g, b)).tobytes()))
    return out


def item_properties(item, separator):
    """DBusMenu properties (a{sv}) for one pystray MenuItem."""
    if item is separator:
        return {"type": ("s", "separator")}
    # DBusMenu treats "_" as a mnemonic marker; "__" is a literal "_".
    props = {
        "label": ("s", item.text.replace("_", "__")),
        "enabled": ("b", bool(item.enabled)),
        "visible": ("b", True),  # hidden items are left out entirely
    }
    checked = item.checked
    if checked is not None:
        props["toggle-type"] = ("s", "radio" if item.radio else "checkmark")
        props["toggle-state"] = ("i", 1 if checked else 0)
    if item.submenu is not None:
        props["children-display"] = ("s", "submenu")
    return props


def _filter_props(props, names):
    if not names:
        return props
    return {k: v for k, v in props.items() if k in names}


class MenuModel:
    """Maps a pystray.Menu onto DBusMenu layouts.

    Item ids must stay stable between the layout the panel cached and a
    later "clicked" event, even when items appear or disappear (e.g.
    "I drank water"). So ids are keyed by the MenuItem object, not by
    position. `pystray.Menu.SEPARATOR` is one shared object, so
    separators are keyed by (parent menu, occurrence) instead.
    """

    ROOT_ID = 0

    def __init__(self, menu, separator):
        self.menu = menu
        self.separator = separator
        self._ids = {}
        self._items = {}
        self._next_id = 1

    def _id_for(self, key, item):
        node_id = self._ids.get(key)
        if node_id is None:
            node_id = self._next_id
            self._next_id += 1
            self._ids[key] = node_id
        self._items[node_id] = item
        return node_id

    def layout(self):
        """The whole menu as a DBusMenu (ia{sv}av) tree. Evaluated fresh
        each call, so checkmarks and visibility reflect current state."""
        return (self.ROOT_ID, {"children-display": ("s", "submenu")},
                self._children(self.menu))

    def _children(self, menu):
        children = []
        seps = 0
        for item in menu:  # pystray yields visible items only
            if item is self.separator:
                key = ("separator", id(menu), seps)
                seps += 1
            else:
                key = id(item)
            node_id = self._id_for(key, item)
            sub = item.submenu
            node = (node_id, item_properties(item, self.separator),
                    self._children(sub) if sub is not None else [])
            children.append((LAYOUT_SIG, node))
        return children

    def item(self, node_id):
        """The MenuItem behind `node_id`, or None (root/unknown id)."""
        return self._items.get(node_id)

    def properties(self, node_id):
        if node_id == self.ROOT_ID:
            return {"children-display": ("s", "submenu")}
        item = self._items.get(node_id)
        if item is None:
            raise DBusError(ERR_INVALID_ARGS, f"unknown menu id {node_id}")
        return item_properties(item, self.separator)


def find_node(node, node_id):
    """Depth-first search of a layout tree for `node_id`."""
    if node[0] == node_id:
        return node
    for _sig, child in node[2]:
        found = find_node(child, node_id)
        if found is not None:
            return found
    return None


def prune(node, depth, names):
    """Apply GetLayout's recursionDepth (-1 = all) and propertyNames."""
    node_id, props, children = node
    if depth == 0:
        kids = []
    else:
        kids = [(sig, prune(child, depth - 1, names))
                for sig, child in children]
    return (node_id, _filter_props(props, names), kids)


_INTROSPECT_XML = """<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
{body}
</node>"""

_ITEM_XML = """  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
    <signal name="NewToolTip"/>
    <signal name="NewMenu"/>
  </interface>"""

_MENU_XML = """  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg type="i" name="id"/>
      <arg type="u" name="timestamp"/>
    </signal>
  </interface>"""


class SniIcon:
    """A StatusNotifierItem tray icon driven by a pystray.Menu.

    Drop-in for the subset of `pystray.Icon` that `tray.py` uses:
    construct with (name, image, title, menu), then `run()` blocks the
    calling thread until `stop()` is called. Menu actions receive this
    object as their `icon` argument, just as they would from pystray.

    All D-Bus traffic happens on the thread that called `run()`.
    `stop()` and `update_menu()` only set flags, so they're safe to call
    from any thread (the quit action, the main loop...).
    """

    HAS_MENU = True

    def __init__(self, name, icon, title, menu):
        import pystray  # only for the SEPARATOR sentinel

        self.name = name
        self.title = title or ""
        self.menu = menu
        self._pixmaps = icon_pixmaps(icon)
        self._model = MenuModel(menu, pystray.Menu.SEPARATOR)
        self._layout = None
        self._revision = 1
        self._stop_event = threading.Event()
        self._dirty = threading.Event()
        self._conn = None
        self._service = None
        self._register_serial = None
        self.registration_error = None

    # ── pystray.Icon-compatible surface ───────────────────────────────
    def run(self):
        from jeepney.bus_messages import MatchRule, message_bus
        from jeepney.io.blocking import Proxy, open_dbus_connection

        conn = self._conn = open_dbus_connection(bus="SESSION")
        try:
            bus = Proxy(message_bus, conn, timeout=5)
            # Spec convention: org.kde.StatusNotifierItem-<pid>-<n>.
            # Nothing calls us yet, so blocking calls are safe here.
            wanted = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
            got = bus.RequestName(wanted, 4)[0]  # 4 = DO_NOT_QUEUE
            self._service = wanted if got in (1, 4) else conn.unique_name
            # Re-register if the panel restarts (GNOME Shell reload,
            # extension toggled): a new watcher owner shows up.
            rule = MatchRule(type="signal", sender="org.freedesktop.DBus",
                             interface="org.freedesktop.DBus",
                             member="NameOwnerChanged")
            rule.add_arg_condition(0, WATCHER_NAME)
            bus.AddMatch(rule)

            self._layout = self._model.layout()
            self._register()

            next_refresh = time.monotonic() + _REFRESH_SECONDS
            while not self._stop_event.is_set():
                try:
                    msg = conn.receive(timeout=_POLL_SECONDS)
                except TimeoutError:
                    msg = None
                if msg is not None:
                    self._dispatch(msg)
                now = time.monotonic()
                if self._dirty.is_set() or now >= next_refresh:
                    self._dirty.clear()
                    self._refresh_layout(announce=True)
                    next_refresh = now + _REFRESH_SECONDS
        finally:
            conn.close()
            self._conn = None

    def stop(self):
        self._stop_event.set()

    def update_menu(self):
        self._dirty.set()

    # ── D-Bus plumbing ────────────────────────────────────────────────
    def _send(self, msg):
        self._conn.send(msg)

    def _register(self):
        # Fire-and-forget: the watcher may call back into us (GetAll,
        # GetLayout) before it replies, and a blocking wait would drop
        # those calls. The reply is picked up in _dispatch.
        from jeepney import DBusAddress, new_method_call

        watcher = DBusAddress(WATCHER_PATH, bus_name=WATCHER_NAME,
                              interface=WATCHER_NAME)
        msg = new_method_call(watcher, "RegisterStatusNotifierItem", "s",
                              (self._service,))
        self._register_serial = next(self._conn.outgoing_serial)
        self._conn.send(msg, serial=self._register_serial)

    def _emit(self, path, iface, member, signature=None, body=()):
        from jeepney import DBusAddress, new_signal

        self._send(new_signal(DBusAddress(path, interface=iface), member,
                              signature, body))

    def _refresh_layout(self, announce):
        """Rebuild the layout; if it changed, bump the revision and
        (when `announce`) tell the panel to re-fetch it."""
        layout = self._model.layout()
        if layout == self._layout:
            return False
        self._layout = layout
        self._revision += 1
        if announce:
            self._emit(MENU_PATH, MENU_IFACE, "LayoutUpdated", "ui",
                       (self._revision, 0))
        return True

    def _dispatch(self, msg):
        from jeepney import (HeaderFields, MessageFlag, MessageType,
                             new_error, new_method_return)

        hdr = msg.header
        fields = hdr.fields
        if hdr.message_type == MessageType.signal:
            # NameOwnerChanged(name, old_owner, new_owner) for the watcher.
            if (fields.get(HeaderFields.member) == "NameOwnerChanged"
                    and msg.body and msg.body[0] == WATCHER_NAME
                    and msg.body[2]):
                self._register()
            return
        if hdr.message_type == MessageType.error:
            if fields.get(HeaderFields.reply_serial) == self._register_serial:
                self.registration_error = msg.body
            return
        if hdr.message_type != MessageType.method_call:
            return

        try:
            signature, body = self._handle_call(
                fields.get(HeaderFields.path),
                fields.get(HeaderFields.interface),
                fields.get(HeaderFields.member),
                msg.body,
            )
            reply = new_method_return(msg, signature, body)
        except DBusError as e:
            reply = new_error(msg, e.name, "s", (e.text,))
        except Exception as e:  # never let one bad call kill the tray
            reply = new_error(msg, "org.freedesktop.DBus.Error.Failed",
                              "s", (repr(e),))
        if not hdr.flags & MessageFlag.no_reply_expected:
            self._send(reply)

    # ── Method handlers ───────────────────────────────────────────────
    def _handle_call(self, path, iface, member, args):
        """Return (signature, body) for the reply, or raise DBusError."""
        if iface == INTROSPECT_IFACE and member == "Introspect":
            return "s", (self._introspect(path),)
        if iface == PROPS_IFACE:
            return self._handle_properties(path, member, args)
        if path == ITEM_PATH and iface in (ITEM_IFACE, None):
            # ItemIsMenu=True: panels open the menu on any click, so
            # these are only called by unusual hosts. Nothing to do.
            if member in ("Activate", "SecondaryActivate", "ContextMenu",
                          "Scroll"):
                return None, ()
        if path == MENU_PATH and iface in (MENU_IFACE, None):
            handler = getattr(self, f"_menu_{member}", None)
            if handler is not None:
                return handler(*args)
        raise DBusError(ERR_UNKNOWN_METHOD,
                        f"No method {iface}.{member} on {path}")

    def _item_properties(self):
        return {
            "Category": ("s", "ApplicationStatus"),
            "Id": ("s", self.name),
            "Title": ("s", self.title),
            "Status": ("s", "Active"),
            "IconName": ("s", ""),
            "IconPixmap": ("a(iiay)", self._pixmaps),
            "IconThemePath": ("s", ""),
            "OverlayIconName": ("s", ""),
            "OverlayIconPixmap": ("a(iiay)", []),
            "AttentionIconName": ("s", ""),
            "AttentionIconPixmap": ("a(iiay)", []),
            "AttentionMovieName": ("s", ""),
            "ToolTip": ("(sa(iiay)ss)", ("", [], self.title, "")),
            "ItemIsMenu": ("b", True),
            "Menu": ("o", MENU_PATH),
        }

    def _menu_properties(self):
        return {
            "Version": ("u", 3),
            "TextDirection": ("s", "ltr"),
            "Status": ("s", "normal"),
            "IconThemePath": ("as", []),
        }

    def _handle_properties(self, path, member, args):
        props_by_iface = {
            (ITEM_PATH, ITEM_IFACE): self._item_properties,
            (MENU_PATH, MENU_IFACE): self._menu_properties,
        }
        iface = args[0] if args else ""
        getter = props_by_iface.get((path, iface))
        if getter is None:
            raise DBusError(ERR_UNKNOWN_PROPERTY,
                            f"No interface {iface} on {path}")
        if member == "GetAll":
            return "a{sv}", (getter(),)
        if member == "Get":
            props = getter()
            if args[1] not in props:
                raise DBusError(ERR_UNKNOWN_PROPERTY, args[1])
            return "v", (props[args[1]],)
        if member == "Set":
            raise DBusError(ERR_READ_ONLY, "properties are read-only")
        raise DBusError(ERR_UNKNOWN_METHOD, member)

    def _menu_GetLayout(self, parent_id, depth, names):
        # Fresh snapshot without a LayoutUpdated signal: the caller is
        # receiving the new layout right now.
        self._refresh_layout(announce=False)
        node = find_node(self._layout, parent_id)
        if node is None:
            raise DBusError(ERR_INVALID_ARGS, f"unknown menu id {parent_id}")
        return f"u{LAYOUT_SIG}", (self._revision, prune(node, depth, names))

    def _menu_GetGroupProperties(self, ids, names):
        if not ids:
            ids = [self._model.ROOT_ID, *self._model._items]
        out = []
        for node_id in ids:
            try:
                props = self._model.properties(node_id)
            except DBusError:
                continue
            out.append((node_id, _filter_props(props, names)))
        return "a(ia{sv})", (out,)

    def _menu_GetProperty(self, node_id, name):
        props = self._model.properties(node_id)
        if name not in props:
            raise DBusError(ERR_INVALID_ARGS, f"no property {name}")
        return "v", (props[name],)

    def _activate(self, node_id):
        """Run the action behind a clicked item. Returns False for an
        unknown id."""
        item = self._model.item(node_id)
        if item is None:
            return False
        if item.submenu is None and item.enabled:
            try:
                item(self)
            finally:
                # Checkmarks / radio state may have changed.
                self._dirty.set()
        return True

    def _menu_Event(self, node_id, event_id, _data, _timestamp):
        if event_id == "clicked" and not self._activate(node_id):
            raise DBusError(ERR_INVALID_ARGS, f"unknown menu id {node_id}")
        return None, ()

    def _menu_EventGroup(self, events):
        errors = []
        for node_id, event_id, _data, _ts in events:
            if event_id == "clicked" and not self._activate(node_id):
                errors.append(node_id)
        return "ai", (errors,)

    def _menu_AboutToShow(self, _node_id):
        return "b", (self._refresh_layout(announce=False),)

    def _menu_AboutToShowGroup(self, _ids):
        changed = self._refresh_layout(announce=False)
        return "aiai", ([self._model.ROOT_ID] if changed else [], [])

    def _introspect(self, path):
        if path == ITEM_PATH:
            body = _ITEM_XML
        elif path == MENU_PATH:
            body = _MENU_XML
        elif path == "/":
            body = '  <node name="StatusNotifierItem"/>\n  <node name="MenuBar"/>'
        else:
            body = ""
        return _INTROSPECT_XML.format(body=body)
