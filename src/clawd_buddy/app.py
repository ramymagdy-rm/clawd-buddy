"""
Clawd Buddy — A tiny animated terminal pet that sits on your taskbar.

Always visible. When your coding assistant finishes a response, it celebrates!

Usage:
  clawd-buddy [OPTIONS]

Options:
  --port PORT      TCP port to listen on (default: 44556)
  --no-topmost     Don't keep the window always-on-top
  --test           Trigger a test celebration on startup
  --send MESSAGE   Signal a running buddy (celebrate) and exit
  --wave           Signal buddy to wave (attention needed) and exit
  --help           Show this help and exit

Controls:
  Drag             Click and drag to reposition
  Space            Test celebration
  Escape           Quit
  Right-click      Context menu (tray)
"""

import sys
import os
import math
import time
import json
import random
import threading
import socket
import ctypes
import argparse
import shutil

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame

# ── Platform: Windows transparency & positioning ──────────────────────
if sys.platform == "win32":
    import ctypes.wintypes

    user32 = ctypes.windll.user32

    GWL_EXSTYLE    = -20
    WS_EX_LAYERED  = 0x00080000
    WS_EX_TOOLWINDOW = 0x00000080
    LWA_COLORKEY   = 0x00000001
    SWP_NOMOVE     = 0x0002
    SWP_NOSIZE     = 0x0001
    HWND_TOPMOST   = -1
    HWND_NOTOPMOST = -2
    SW_HIDE        = 0
    SW_SHOW        = 5

    # For taskbar detection
    class APPBARDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.wintypes.DWORD),
            ("hWnd", ctypes.wintypes.HWND),
            ("uCallbackMessage", ctypes.c_uint),
            ("uEdge", ctypes.c_uint),
            ("rc", ctypes.wintypes.RECT),
            ("lParam", ctypes.wintypes.LPARAM),
        ]

    ABM_GETTASKBARPOS = 0x00000005


def _get_hwnd():
    info = pygame.display.get_wm_info()
    return info.get("window", 0)


def _make_transparent(hwnd, color_key):
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                          style | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
    r, g, b = color_key
    user32.SetLayeredWindowAttributes(hwnd, r | (g << 8) | (b << 16), 0, LWA_COLORKEY)


def _set_topmost(hwnd, topmost=True):
    flag = HWND_TOPMOST if topmost else HWND_NOTOPMOST
    user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)


def _get_window_rect(hwnd):
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _move_window(hwnd, x, y):
    _, _, w, h = _get_window_rect(hwnd)
    user32.MoveWindow(hwnd, x, y, w, h, True)


def _get_taskbar_rect():
    """Return (x, y, w, h) of the Windows taskbar."""
    abd = APPBARDATA()
    abd.cbSize = ctypes.sizeof(APPBARDATA)
    ctypes.windll.shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(abd))
    rc = abd.rc
    return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top


def _get_screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


# ── Dimensions ────────────────────────────────────────────────────────
WIN_W, WIN_H = 200, 260  # window size (room for confetti above)
CHAR_W, CHAR_H = 80, 62  # the body rectangle
FPS = 120

# Transparent key — never draw with this exact color
TKEY = (1, 1, 1)

# ── Palette (matching reference: dark body, bright eyes) ─────────────
BODY_OUTER   = (35, 35, 48)     # dark shell
BODY_INNER   = (42, 42, 58)     # slightly lighter fill
TITLE_BAR    = (70, 70, 92)     # light strip at top
SCREEN_BG    = (22, 22, 32)     # screen area
EYE_WHITE    = (230, 235, 255)  # big bright eyes
EYE_GLOW     = (200, 210, 255, 60)
PUPIL_COLOR  = (25, 25, 40)
MOUTH_COLOR  = (120, 130, 160)  # subtle dash
MOUTH_HAPPY  = (255, 220, 80)
LIMB_COLOR   = (35, 35, 48)
SHOE_COLOR   = (50, 50, 68)
CONFETTI = [
    (255, 107, 107), (78, 205, 196), (69, 183, 209),
    (255, 230, 109), (199, 128, 232), (255, 159, 67),
]

SOCK_HOST = "127.0.0.1"
SOCK_PORT = 44556


# ── State ─────────────────────────────────────────────────────────────
# Modes: "idle", "celebrating", "waving"
class BuddyState:
    def __init__(self):
        self.mode = "idle"
        self.mode_start = 0.0
        self.cel_dur = 5.0
        self.wave_dur = 5.0
        self.confetti = []
        self.should_quit = False

    @property
    def celebrating(self):
        return self.mode == "celebrating"

    @property
    def waving(self):
        return self.mode == "waving"

    def trigger(self, _msg=""):
        self.mode = "celebrating"
        self.mode_start = time.time()
        self.confetti = _spawn_confetti(40)

    def wave(self):
        # Only wave if not already celebrating (celebrate takes priority)
        if self.mode != "celebrating":
            self.mode = "waving"
            self.mode_start = time.time()

    def update(self):
        elapsed = time.time() - self.mode_start
        if self.mode == "celebrating" and elapsed > self.cel_dur:
            self.mode = "idle"
        elif self.mode == "waving" and elapsed > self.wave_dur:
            self.mode = "idle"


def _spawn_confetti(n):
    cx = WIN_W // 2
    return [
        [cx + random.randint(-30, 30), WIN_H // 2 - 40,
         random.uniform(-3, 3), random.uniform(-7, -2),
         random.choice(CONFETTI), random.randint(3, 6)]
        for _ in range(n)
    ]


# ── Drawing ───────────────────────────────────────────────────────────
def rounded_rect(surf, color, rect, r):
    x, y, w, h = rect
    r = min(r, w // 2, h // 2)
    pygame.draw.rect(surf, color, (x + r, y, w - 2 * r, h))
    pygame.draw.rect(surf, color, (x, y + r, w, h - 2 * r))
    for cx, cy in [(x+r,y+r),(x+w-r,y+r),(x+r,y+h-r),(x+w-r,y+h-r)]:
        pygame.draw.circle(surf, color, (cx, cy), r)


def draw_buddy(surf, t, state, blink):
    cel = state.celebrating
    wav = state.waving
    cx = WIN_W // 2
    # Character vertical center — sits near bottom of window
    base_y = WIN_H - 70
    bob = math.sin(t * 2.2) * 1.5
    if cel:
        bob = math.sin(t * 10) * 6
    elif wav:
        bob = math.sin(t * 4) * 3

    by = int(base_y - CHAR_H + bob)  # body top

    # ── Legs (behind body) ────────────────────────────────────────
    leg_top = int(by + CHAR_H - 2)
    leg_len = 18
    if cel:
        l_swing = math.sin(t * 7) * 8
        r_swing = math.sin(t * 7 + math.pi) * 8
    elif wav:
        l_swing = math.sin(t * 3) * 3
        r_swing = math.sin(t * 3 + math.pi) * 3
    else:
        l_swing = math.sin(t * 1.8) * 1.5
        r_swing = math.sin(t * 1.8 + math.pi) * 1.5
    for sx, sw in [(-14, l_swing), (14, r_swing)]:
        fx = int(cx + sx + sw)
        fy = leg_top + leg_len
        pygame.draw.line(surf, LIMB_COLOR, (cx + sx, leg_top), (fx, fy), 5)
        rounded_rect(surf, SHOE_COLOR, (fx - 7, fy - 2, 14, 8), 3)

    # ── Arms ──────────────────────────────────────────────────────
    arm_y = int(by + CHAR_H // 2 + bob)
    arm_len = 22
    if cel:
        la = math.sin(t * 8) * 0.5 - 1.3    # both arms up celebrating
        ra = math.sin(t * 8 + math.pi) * 0.5 + 0.3
    elif wav:
        la = math.sin(t * 1.2) * 0.1 - 0.2  # left arm idle
        ra = math.sin(t * 6) * 0.4 - 1.0     # right arm waving high
    else:
        la = math.sin(t * 1.2) * 0.1 - 0.2  # gentle idle
        ra = math.sin(t * 1.2 + 1) * 0.1 + 0.2

    # left
    lx1 = cx - CHAR_W // 2 - 2
    lx2 = int(lx1 + math.cos(math.pi + la) * arm_len)
    ly2 = int(arm_y + math.sin(math.pi + la) * arm_len)
    pygame.draw.line(surf, LIMB_COLOR, (lx1, arm_y), (lx2, ly2), 5)
    pygame.draw.circle(surf, LIMB_COLOR, (lx2, ly2), 4)
    # right
    rx1 = cx + CHAR_W // 2 + 2
    rx2 = int(rx1 + math.cos(ra) * arm_len)
    ry2 = int(arm_y + math.sin(ra) * arm_len)
    pygame.draw.line(surf, LIMB_COLOR, (rx1, arm_y), (rx2, ry2), 5)
    pygame.draw.circle(surf, LIMB_COLOR, (rx2, ry2), 4)

    # ── Body (main terminal box) ──────────────────────────────────
    bx = cx - CHAR_W // 2
    rounded_rect(surf, BODY_OUTER, (bx, by, CHAR_W, CHAR_H), 8)
    rounded_rect(surf, BODY_INNER, (bx + 2, by + 2, CHAR_W - 4, CHAR_H - 4), 7)

    # Title bar strip
    rounded_rect(surf, TITLE_BAR, (bx + 2, by + 2, CHAR_W - 4, 10), 6)
    # Three little dots on title bar
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        pygame.draw.circle(surf, c, (bx + 10 + i * 9, by + 7), 2)

    # Screen area
    scr = (bx + 6, by + 14, CHAR_W - 12, CHAR_H - 22)
    rounded_rect(surf, SCREEN_BG, scr, 4)

    # ── Eyes ──────────────────────────────────────────────────────
    sx, sy, sw, sh = scr
    ey = sy + sh // 2 - 2
    lex = sx + sw // 3
    rex = sx + 2 * sw // 3
    er = 8  # eye radius

    WAVE_EYE = (255, 190, 80)  # amber attention color

    if blink and not wav:
        # Blink — horizontal line
        for ex in (lex, rex):
            pygame.draw.line(surf, EYE_WHITE, (ex - 6, ey), (ex + 6, ey), 2)
    elif cel:
        # Happy — upward arcs (^ ^)
        for ex in (lex, rex):
            pygame.draw.arc(surf, MOUTH_HAPPY, (ex - 7, ey - 5, 14, 10),
                            math.radians(0), math.radians(180), 3)
    elif wav:
        # Wide alert eyes — big and looking at user
        for ex in (lex, rex):
            pygame.draw.circle(surf, EYE_WHITE, (ex, ey), er + 1)
            pygame.draw.circle(surf, PUPIL_COLOR, (ex, ey), 5)
            pygame.draw.circle(surf, (255, 255, 255), (ex - 2, ey - 3), 2)
    else:
        for ex in (lex, rex):
            # White of eye
            pygame.draw.circle(surf, EYE_WHITE, (ex, ey), er)
            # Pupil — slight wander
            px = ex + math.sin(t * 0.6 + ex * 0.01) * 2
            py = ey + math.cos(t * 0.8) * 1.5
            pygame.draw.circle(surf, PUPIL_COLOR, (int(px), int(py)), 4)
            # Highlight
            pygame.draw.circle(surf, (255, 255, 255), (ex - 2, ey - 3), 2)

    # ── Mouth ─────────────────────────────────────────────────────
    my = sy + sh - 6
    if cel:
        # Happy open smile
        pygame.draw.arc(surf, MOUTH_HAPPY, (cx - 10, my - 7, 20, 12),
                        math.radians(200), math.radians(340), 2)
    elif wav:
        # Small "o" mouth — surprised/calling
        pygame.draw.circle(surf, WAVE_EYE, (cx, my - 2), 4, 2)
    else:
        # Small dash
        w_m = 10 + math.sin(t * 1.5) * 1
        pygame.draw.line(surf, MOUTH_COLOR,
                         (int(cx - w_m / 2), my), (int(cx + w_m / 2), my), 2)

    # ── Attention indicator (floating "!" above head when waving) ─
    if wav:
        pulse = (math.sin(t * 5) + 1) / 2  # 0..1 pulsing
        alpha_val = int(180 + 75 * pulse)
        ix = cx + 30
        iy = int(by - 18 + math.sin(t * 3) * 4)
        # "!" exclamation
        bang_surf = pygame.Surface((20, 28), pygame.SRCALPHA)
        bang_color = (*WAVE_EYE, alpha_val)
        pygame.draw.rect(bang_surf, bang_color, (7, 2, 6, 14), border_radius=3)
        pygame.draw.circle(bang_surf, bang_color, (10, 22), 3)
        surf.blit(bang_surf, (ix - 10, iy - 14))

    # ── Confetti ──────────────────────────────────────────────────
    alive = []
    for p in state.confetti:
        p[0] += p[2]; p[1] += p[3]; p[3] += 0.18; p[2] *= 0.99
        if p[1] < WIN_H + 10:
            alive.append(p)
            pygame.draw.rect(surf, p[4], (int(p[0]), int(p[1]), p[5], p[5]))
    state.confetti = alive


# ── Socket listener ───────────────────────────────────────────────────
def socket_listener(state, port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((SOCK_HOST, port))
    except OSError as e:
        print(f"[buddy] Cannot bind {SOCK_HOST}:{port}: {e}")
        return
    srv.listen(5)
    srv.settimeout(1.0)
    print(f"[buddy] Listening on {SOCK_HOST}:{port}")

    while True:
        try:
            conn, _ = srv.accept()
            data = conn.recv(4096).decode("utf-8", errors="replace").strip()
            conn.close()
            if data:
                action = "celebrate"
                try:
                    msg = json.loads(data)
                    action = msg.get("action", "celebrate")
                except (json.JSONDecodeError, AttributeError):
                    pass
                print(f"[buddy] Signal: {action}")
                if action == "wave":
                    state.wave()
                else:
                    state.trigger()
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[buddy] Socket error: {e}")


# ── System tray ───────────────────────────────────────────────────────
def create_tray(state):
    import pystray
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

    def on_celebrate(_icon, _item):
        state.trigger()

    def on_quit(icon, _item):
        state.should_quit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Test Celebration", on_celebrate),
        pystray.MenuItem("Quit", on_quit),
    )
    pystray.Icon("clawd-buddy", img, "Clawd Buddy", menu).run()


# ── Startup management ────────────────────────────────────────────────
_STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""), "Microsoft", "Windows",
    "Start Menu", "Programs", "Startup",
)
_VBS_NAME = "clawd-buddy-startup.vbs"


def _get_startup_path():
    return os.path.join(_STARTUP_DIR, _VBS_NAME)


def _find_exe():
    """Find the clawd-buddy executable path."""
    exe = shutil.which("clawd-buddy")
    if exe:
        return exe
    # Fallback: same dir as current python
    candidate = os.path.join(os.path.dirname(sys.executable), "clawd-buddy.exe")
    if os.path.exists(candidate):
        return candidate
    return "clawd-buddy"


def _enable_startup():
    exe = _find_exe()
    vbs_content = (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run """{exe}""", 0, False\n'
    )
    path = _get_startup_path()
    os.makedirs(_STARTUP_DIR, exist_ok=True)
    with open(path, "w") as f:
        f.write(vbs_content)
    print(f"[buddy] Enabled run at startup")
    print(f"        {path}")


def _disable_startup():
    path = _get_startup_path()
    if os.path.exists(path):
        os.remove(path)
        print(f"[buddy] Disabled run at startup")
        print(f"        Removed {path}")
    else:
        print(f"[buddy] Not in startup (nothing to remove)")


# ── CLI ───────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(
        prog="clawd-buddy",
        description="Clawd Buddy — tiny terminal pet on your taskbar",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  clawd-buddy               Start buddy on taskbar\n"
            "  clawd-buddy --test         Start with a celebration\n"
            "  clawd-buddy --send Done!   Signal a running buddy\n"
            "  clawd-buddy --wave         Wave for attention\n"
            "  clawd-buddy --startup      Run at Windows startup\n"
            "  clawd-buddy --no-startup   Remove from Windows startup\n"
        ),
    )
    p.add_argument("--port", type=int, default=SOCK_PORT,
                   help=f"TCP port (default: {SOCK_PORT})")
    p.add_argument("--no-topmost", action="store_true",
                   help="Don't stay always-on-top")
    p.add_argument("--test", action="store_true",
                   help="Celebrate on startup")
    p.add_argument("--send", metavar="MSG", type=str,
                   help="Send celebrate signal to running buddy and exit")
    p.add_argument("--wave", action="store_true",
                   help="Send wave/attention signal to running buddy and exit")
    p.add_argument("--startup", action="store_true",
                   help="Enable run at Windows startup and exit")
    p.add_argument("--no-startup", action="store_true",
                   help="Disable run at Windows startup and exit")
    p.add_argument("--fg", action="store_true",
                   help="Run in foreground (default auto-detaches)")
    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    port = args.port

    # --startup / --no-startup mode
    if args.startup:
        _enable_startup()
        sys.exit(0)
    if args.no_startup:
        _disable_startup()
        sys.exit(0)

    # --send / --wave mode
    if args.send is not None or args.wave:
        action = "wave" if args.wave else "celebrate"
        payload = json.dumps({"action": action}).encode()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((SOCK_HOST, port))
            s.sendall(payload)
            s.close()
            print(f"[buddy] Sent: {action}")
        except ConnectionRefusedError:
            print(f"[buddy] No buddy on port {port}")
            sys.exit(1)
        sys.exit(0)

    # Auto-detach: spawn via pythonw (no console at all) and exit
    if not args.fg and sys.platform == "win32":
        import subprocess
        # Use pythonw.exe from the same env as current python — no console window
        py_dir = os.path.dirname(sys.executable)
        pythonw = os.path.join(py_dir, "pythonw.exe")
        if not os.path.exists(pythonw):
            # Some envs put it in Scripts/
            pythonw = os.path.join(py_dir, "Scripts", "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable  # fallback
        cmd = [pythonw, "-m", "clawd_buddy.app", "--fg"]
        if args.port != SOCK_PORT:
            cmd += ["--port", str(args.port)]
        if args.no_topmost:
            cmd.append("--no-topmost")
        if args.test:
            cmd.append("--test")
        subprocess.Popen(
            cmd,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
        sys.exit(0)

    # Single instance lock
    lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_sock.bind(("127.0.0.1", port + 1))
    except OSError:
        print("[buddy] Already running — sending signal.")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((SOCK_HOST, port))
            s.sendall(b'{"message": "hello"}')
            s.close()
        except Exception:
            pass
        sys.exit(0)

    # Position window centered on taskbar, just above it
    scr_w, scr_h = _get_screen_size()
    tb_x, tb_y, tb_w, tb_h = _get_taskbar_rect()
    win_x = scr_w // 2 - WIN_W // 2
    win_y = tb_y - WIN_H + 28  # overlap slightly so feet "stand" on taskbar

    os.environ["SDL_VIDEO_WINDOW_POS"] = f"{win_x},{win_y}"
    pygame.init()

    screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.NOFRAME)
    pygame.display.set_caption("Clawd Buddy")
    clock = pygame.time.Clock()

    hwnd = _get_hwnd()
    _make_transparent(hwnd, TKEY)
    if not args.no_topmost:
        _set_topmost(hwnd, True)

    state = BuddyState()
    if args.test:
        state.trigger()

    # Background threads
    threading.Thread(target=socket_listener, args=(state, port), daemon=True).start()
    threading.Thread(target=create_tray, args=(state,), daemon=True).start()

    # Drag
    dragging = False
    drag_off = (0, 0)

    # Blink
    blink_timer = 0.0
    blink_interval = 3.5
    blink_dur = 0.12

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        t = time.time()

        if state.should_quit:
            break

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_SPACE:
                    state.trigger()
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                dragging = True
                drag_off = ev.pos
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                dragging = False
            elif ev.type == pygame.MOUSEMOTION and dragging:
                mx, my = ev.pos
                wx, wy, _, _ = _get_window_rect(hwnd)
                _move_window(hwnd, wx + mx - drag_off[0],
                             wy + my - drag_off[1])

        state.update()

        # Blink
        blink_timer += dt
        phase = blink_timer % blink_interval
        is_blink = phase > blink_interval - blink_dur

        # Draw
        screen.fill(TKEY)
        draw_buddy(screen, t, state, is_blink)
        pygame.display.flip()

    pygame.quit()
    lock_sock.close()
    sys.exit()


if __name__ == "__main__":
    main()
