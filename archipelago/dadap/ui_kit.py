"""Pixel look of the app window: palette, bundled fonts, a dithered disco-ball sprite and a few square widgets (tkinter only).

Art direction: black ground, one tint per screen, sharp corners with notches, white corner marks, caps labels in a pixel font, a
terminal journal with state chips. Nothing here touches the game, the saves or the network.
"""
import ctypes
import math
import os
import random
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

BLACK, PANEL, FIELD = "#000000", "#08080b", "#0c0c10"
TEXT, MUTED, MOON = "#F4F4F6", "#B6B6C0", "#777777"
LINE, LINE_STRONG = "#292929", "#575757"
ACCENT, CORE = "#7FB8FF", "#FFEED4"          # active states / focus
TINT, TINT_DIM = "#FF64C8", "#3a1030"        # the disco tint: used on at most a tenth of the surface
OK, WARN, ERR = "#F4F4F6", "#FFBE6E", "#FF4646"

FONT_DIRS = (Path(__file__).resolve().parent / "assets/fonts",)


def load_fonts(extra_dirs=()):
    """Make the bundled TTFs available to this process only (nothing is installed on the PC). Returns the number loaded."""
    if os.name != "nt":
        return 0
    count = 0
    for folder in (*extra_dirs, *FONT_DIRS):
        for path in sorted(Path(folder).glob("*.ttf")):
            try:
                count += bool(ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0))  # FR_PRIVATE
            except (OSError, AttributeError):
                pass
    return count


class Fonts:
    def __init__(self, root):
        families = set(tkfont.families(root))

        def pick(name, fallback):
            return name if name in families else fallback
        title, label, body = pick("Press Start 2P", "Consolas"), pick("Silkscreen", "Consolas"), pick("JetBrains Mono", "Consolas")
        self.pixel = title != "Consolas"
        self.title = tkfont.Font(root, family=title, size=-24)
        self.heading = tkfont.Font(root, family=title, size=-16)
        self.label = tkfont.Font(root, family=label, size=-13)
        self.label_b = tkfont.Font(root, family=label, size=-13, weight="bold" if label == "Silkscreen" else "normal")
        self.small = tkfont.Font(root, family=label, size=-10)
        self.body = tkfont.Font(root, family=body, size=-14)
        self.body_b = tkfont.Font(root, family=body, size=-14, weight="bold")
        self.note = tkfont.Font(root, family=body, size=-12)
        self.log = tkfont.Font(root, family=body, size=-13)
        self.log_b = tkfont.Font(root, family=body, size=-13, weight="bold")


def dark_titlebar(root):
    """Black title bar on Windows 11 / dark caption on Windows 10 (ignored where unsupported)."""
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        for attribute, value in ((20, 1), (35, 0x000000), (36, 0xF6F4F4)):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(ctypes.c_int(value)), 4)
    except (OSError, AttributeError, tk.TclError):
        pass


# ---- sprite ---------------------------------------------------------------------------------------------
_BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
_GRAY = ("#16161b", "#4a4a55", "#b6b6c0", "#f4f4f6")
_PINK = ("#2a0c22", "#8a2f6c", "#ff64c8", "#ffe3f4")


def _threshold(x, y):
    return (_BAYER[y % 4][x % 4] + 0.5) / 16


def _facet(i, j):
    return ((i * 73856093) ^ (j * 19349663)) % 97 / 96


def disco_frames(count=8, width=56, height=36, radius=11, zoom=4, scene=True):
    """A rotating, ordered-dither disco ball with light beams and cross stars; the loop is seamless (one facet period)."""
    cx, cy = width // 2, height // 2 + 1
    rng = random.Random(7)
    stars = [(rng.randrange(2, width - 2), rng.randrange(2, height - 2)) for _ in range(14)] if scene else []
    frames = []
    for frame in range(count):
        phase = frame / count
        rot = phase * (2 * math.pi / 12)
        base = phase * (math.pi / 3) + 0.4
        beams = [(math.cos(base + k * math.pi / 3), math.sin(base + k * math.pi / 3)) for k in range(6)] if scene else []
        grid = [[BLACK] * width for _ in range(height)]
        for y in range(height):
            for x in range(width):
                dx, dy = x - cx, y - cy
                if dx * dx + dy * dy <= radius * radius:
                    nx, ny = dx / radius, dy / radius
                    nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
                    facet = _facet(int(math.floor((math.atan2(nx, nz) + rot) / (2 * math.pi / 12))) % 12,
                                   int(math.floor(math.asin(max(-1.0, min(1.0, ny))) / (math.pi / 9))))
                    light = max(0.0, nx * -0.5 + ny * -0.6 + nz * 0.62)
                    level = max(0.0, min(1.0, 0.15 + 0.5 * light + 0.45 * facet)) * 3.99
                    tone = max(0, min(3, int(level + _threshold(x, y) - 0.5)))
                    grid[y][x] = (_PINK if facet > 0.8 else _GRAY)[tone]
                    if dx * dx + dy * dy > (radius - 1) * (radius - 1) and tone < 3:
                        grid[y][x] = MOON
                elif scene:
                    for ux, uy in beams:
                        along, across = dx * ux + dy * uy, abs(-dx * uy + dy * ux)
                        spread = 0.8 + along * 0.075
                        if along > radius and across < spread:
                            strength = (1 - across / spread) * max(0.0, 1 - (along - radius) / (width * 0.5))
                            if strength > _threshold(x, y):
                                grid[y][x] = TINT if strength > 0.62 else "#7a2a60"
        if scene:
            for y in range(cy - radius):
                grid[y][cx] = MOON  # the string
            for index, (sx, sy) in enumerate(stars):
                if grid[sy][sx] != BLACK or (index + frame) % 3 == 0:
                    continue
                bright = (index + frame) % 3 == 1
                grid[sy][sx] = "#ffffff" if bright else MOON
                for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if 0 <= sx + ox < width and 0 <= sy + oy < height and grid[sy + oy][sx + ox] == BLACK:
                        grid[sy + oy][sx + ox] = "#555555" if bright else "#2a2a2a"
        image = tk.PhotoImage(width=width, height=height)
        for y, row in enumerate(grid):
            image.put("{" + " ".join(row) + "}", to=(0, y))
        frames.append(image.zoom(zoom, zoom) if zoom > 1 else image)
    return frames


# ---- widgets --------------------------------------------------------------------------------------------
class Panel(tk.Canvas):
    """Notched frame with two white corner marks. Put content in `.inner`; `fit` makes the panel as tall as its content."""

    def __init__(self, parent, fit=True, fill=PANEL, border=LINE, notch=4, pad=10):
        super().__init__(parent, bg=BLACK, highlightthickness=0, height=40)
        self.fill, self.border, self.notch, self.pad = fill, border, notch, pad
        self.inner = tk.Frame(self, bg=fill)
        self._window = self.create_window(pad, pad, window=self.inner, anchor="nw")
        self.bind("<Configure>", self._layout)
        self.fit = fit
        if fit:  # the content decides the height (its requested size, not the size this panel forces on it)
            self.inner.bind("<Configure>", lambda _e: self.configure(height=self.inner.winfo_reqheight() + 2 * pad))

    def _layout(self, event):
        w, h, n = event.width, event.height, self.notch
        self.delete("frame")
        self.create_polygon([n, 0, w - n, 0, w - 1, n, w - 1, h - n, w - n, h - 1, n, h - 1, 0, h - n, 0, n], fill=self.fill,
                            outline=self.border, tags="frame")
        self.create_line(8, 1, 34, 1, fill=TEXT, width=2, tags="frame")
        self.create_line(w - 34, h - 1, w - 8, h - 1, fill=TEXT, width=2, tags="frame")
        self.tag_lower("frame")
        self.itemconfigure(self._window, width=max(1, w - 2 * self.pad))
        if not self.fit:
            self.itemconfigure(self._window, height=max(1, h - 2 * self.pad))


class PixelButton(tk.Canvas):
    """Square button with an offset block shadow; same `state([...])` interface as a ttk button."""

    def __init__(self, parent, text, command, font, primary=False, width=150, height=40):
        super().__init__(parent, width=width + 6, height=height + 6, bg=parent["bg"], highlightthickness=0, cursor="hand2", takefocus=1)
        self.text, self.command, self.font, self.primary = text, command, font, primary
        self.w, self.h = width, height
        self.disabled = self.hover = self.down = False
        self.bind("<Enter>", lambda _e: self._set(hover=True))
        self.bind("<Leave>", lambda _e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda _e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<space>", lambda _e: self._fire())
        self.bind("<Return>", lambda _e: self._fire())
        self.bind("<FocusIn>", lambda _e: self._draw())
        self.bind("<FocusOut>", lambda _e: self._draw())
        self._draw()

    def state(self, flags):
        for flag in flags:
            self.disabled = flag == "disabled" or (self.disabled and flag != "!disabled")
        self.configure(cursor="arrow" if self.disabled else "hand2")
        self._draw()

    def _set(self, **values):
        for key, value in values.items():
            setattr(self, key, value)
        self._draw()

    def _release(self, event):
        was_down = self.down
        self._set(down=False)
        if was_down and 0 <= event.x <= self.w + 6 and 0 <= event.y <= self.h + 6:
            self._fire()

    def _fire(self):
        if not self.disabled:
            self.command()

    def _draw(self):
        self.delete("all")
        shift = 4 if self.down and not self.disabled else (2 if self.hover and not self.disabled else 0)
        if not self.disabled:
            self.create_rectangle(4, 4, self.w + 3, self.h + 3, fill=TINT_DIM if not self.primary else "#7a2a60", outline="")
        fill = (BLACK if not self.primary else TINT) if not self.disabled else BLACK
        edge = LINE_STRONG if self.disabled else (ACCENT if self.focus_get() is self else TEXT)
        self.create_rectangle(shift + 1, shift + 1, shift + self.w - 1, shift + self.h - 1, fill=fill, outline=edge, width=2)
        color = MOON if self.disabled else (BLACK if self.primary else TEXT)
        self.create_text(shift + self.w / 2, shift + self.h / 2, text=self.text, fill=color, font=self.font)


class PixelCheck(tk.Canvas):
    def __init__(self, parent, variable, size=22):
        super().__init__(parent, width=size, height=size, bg=parent["bg"], highlightthickness=0, cursor="hand2", takefocus=1)
        self.variable, self.size = variable, size
        self.bind("<Button-1>", lambda _e: self.toggle())
        self.bind("<space>", lambda _e: self.toggle())
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def toggle(self):
        self.variable.set(not self.variable.get())

    def _draw(self):
        self.delete("all")
        s = self.size
        self.create_rectangle(1, 1, s - 1, s - 1, outline=TEXT, width=2, fill=BLACK)
        if self.variable.get():
            self.create_rectangle(6, 6, s - 6, s - 6, fill=TINT, outline="")


class Segments(tk.Canvas):
    """The block strip: dim at rest, a lit run sweeps along while the app works."""

    def __init__(self, parent, count=30, block=10, gap=4, height=10):
        super().__init__(parent, width=count * (block + gap) - gap, height=height, bg=parent["bg"], highlightthickness=0)
        self.count, self.items, self.head, self.running = count, [], 0, False
        for i in range(count):
            self.items.append(self.create_rectangle(i * (block + gap), 0, i * (block + gap) + block, height, fill="#1c1c20", outline=""))

    def start(self):
        if not self.running:
            self.running = True
            self._step()

    def stop(self):
        self.running = False
        for item in self.items:
            self.itemconfigure(item, fill="#1c1c20")

    def _step(self):
        if not self.running:
            return
        try:
            for i, item in enumerate(self.items):
                distance = (self.head - i) % self.count
                self.itemconfigure(item, fill=TINT if distance < 6 else "#1c1c20")
            self.head = (self.head + 1) % self.count
            self.after(70, self._step)
        except tk.TclError:
            self.running = False


def field(parent, variable, font, secret=False):
    """A black input with a 1 px frame that turns to the accent colour on focus. Returns (frame, entry)."""
    box = tk.Frame(parent, bg=LINE, padx=1, pady=1)
    entry = tk.Entry(box, textvariable=variable, show="•" if secret else "", bg=FIELD, fg=TEXT, insertbackground=ACCENT, relief="flat",
                     bd=0, highlightthickness=0, font=font, selectbackground=TINT, selectforeground=BLACK)
    entry.pack(fill="x", ipady=7, ipadx=8)
    entry.bind("<FocusIn>", lambda _e: box.configure(bg=ACCENT))
    entry.bind("<FocusOut>", lambda _e: box.configure(bg=LINE))
    return box, entry
