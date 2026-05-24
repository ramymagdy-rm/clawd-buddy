# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""The About dialog and the shared buddy-silhouette icon.

The dialog is a tiny tkinter Toplevel that pops up when the user clicks
tray → About. tkinter is imported lazily inside the worker so the buddy
still launches on stripped-down Python installs without `_tkinter` —
the dialog just fails gracefully with a log line.

`_make_buddy_icon_image` is shared by the system-tray and the About
window because the buddy silhouette is the branding everywhere the app
shows itself.
"""

import threading

from .. import __version__ as APP_VERSION


_REPO_URL = "https://github.com/ramymagdy-rm/clawd-buddy"

# Reentrancy guard — the menu callback fires synchronously and a user
# can spam-click the About entry. Without this we'd spin up multiple
# Toplevels.
_ABOUT_DIALOG_OPEN = False


def _make_buddy_icon_image():
    """Procedurally draw a 64x64 RGBA PIL Image of the buddy's face.

    Used as both the system-tray icon and the About-dialog window icon
    so the buddy silhouette is the branding everywhere the app shows
    itself.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([12, 14, 52, 46], radius=5, fill=(42, 42, 58))
    d.rounded_rectangle([12, 14, 52, 22], radius=5, fill=(70, 70, 92))
    d.ellipse([22, 28, 30, 36], fill=(230, 235, 255))
    d.ellipse([34, 28, 42, 36], fill=(230, 235, 255))
    d.line([(28, 40), (36, 40)], fill=(120, 130, 160), width=2)
    d.line([(24, 46), (22, 54)], fill=(35, 35, 48), width=3)
    d.line([(40, 46), (42, 54)], fill=(35, 35, 48), width=3)
    return img


def show_about_dialog():
    """Open the About dialog. Reentrant clicks are debounced — at most
    one dialog at a time. Spawned on its own thread so it doesn't block
    the tray menu (pystray's callbacks are synchronous) or the pygame
    loop.
    """
    global _ABOUT_DIALOG_OPEN
    if _ABOUT_DIALOG_OPEN:
        return
    _ABOUT_DIALOG_OPEN = True
    threading.Thread(target=_run_about_dialog, daemon=True).start()


def _run_about_dialog():
    global _ABOUT_DIALOG_OPEN
    try:
        import tkinter as tk
        import webbrowser

        root = tk.Tk()
        root.title("About Clawd Buddy")
        root.resizable(False, False)

        # Replace the default tk feather icon with the buddy silhouette.
        # PhotoImage must be retained on `root` — tkinter doesn't keep
        # its own reference and the icon vanishes on GC otherwise.
        try:
            from PIL import ImageTk
            icon_photo = ImageTk.PhotoImage(_make_buddy_icon_image())
            root.iconphoto(True, icon_photo)
            root._buddy_icon_ref = icon_photo
        except Exception as ie:
            print(f"[buddy] About dialog icon failed: {ie}")

        frame = tk.Frame(root, padx=24, pady=20)
        frame.pack(expand=True, fill="both")

        tk.Label(frame, text="Clawd Buddy",
                 font=("Segoe UI", 16, "bold")).pack()
        tk.Label(frame, text=f"Version {APP_VERSION}",
                 font=("Segoe UI", 9)).pack(pady=(2, 10))

        tk.Label(frame, text="A tiny animated terminal pet that sits",
                 font=("Segoe UI", 9)).pack()
        tk.Label(frame, text="on your taskbar and reacts to",
                 font=("Segoe UI", 9)).pack()
        tk.Label(frame, text="coding-assistant events.",
                 font=("Segoe UI", 9)).pack(pady=(0, 12))

        tk.Label(frame, text="Author: Ramy Ezzat",
                 font=("Segoe UI", 9)).pack()
        tk.Label(frame, text="License: MIT",
                 font=("Segoe UI", 9)).pack(pady=(0, 8))

        link = tk.Label(frame, text=_REPO_URL,
                        fg="#3a7ad6", cursor="hand2",
                        font=("Segoe UI", 9, "underline"))
        link.pack()
        link.bind("<Button-1>", lambda _e: webbrowser.open(_REPO_URL))

        tk.Button(frame, text="Close", command=root.destroy,
                  padx=18).pack(pady=(14, 0))

        # Center on screen — tk needs a refresh before geometry is known.
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    except Exception as e:
        print(f"[buddy] About dialog failed: {e}")
    finally:
        _ABOUT_DIALOG_OPEN = False
