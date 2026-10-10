"""The whole player experience: type Server / Slot / Password, click Play."""
import json
import logging
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import doctor, play, session, ui_kit
from .fsutil import SafetyError
from .layout import Layout, is_game_dir, remember_game_dir
from .ui_kit import ACCENT, BLACK, ERR, FIELD, LINE, LINE_STRONG, MOON, MUTED, OK, PANEL, TEXT, TINT, WARN

TITLE = "Dead as Disco - Archipelago"
PLAQUES = (("01", "SERVER AND SLOT", "Type them below (ask whoever hosts)."),
           ("02", "PLAY", "Press the big button. The app sets everything up."),
           ("03", "FIRST TIME ONLY", "Finish ONLY the tutorial, stay in the hub, quit the game and close Steam."),
           ("04", "YOUR SAVES", "Moved aside, put back automatically, backed up."))
CHIPS = {"run": (" RUN ", ACCENT, BLACK), "ok": ("  OK ", OK, BLACK), "warn": ("WARN ", WARN, BLACK), "err": (" ERR ", ERR, BLACK),
         "net": (" NET ", "#8fd8ff", BLACK), "you": (" YOU ", TINT, BLACK), "info": ("     ", None, None)}


class _QueueHandler(logging.Handler):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        self.sink(self.format(record))


def classify(message):
    """(chip kind, text without its prefix) for one log message."""
    head = message.lstrip()
    lowered = head.lower()
    if head.startswith("--- "):
        text = head.strip("- ").strip()
        return ("ok" if text.endswith(": done") else "run"), text
    for prefix, kind in (("[OK] ", "ok"), ("[WARN] ", "warn"), ("[FAIL] ", "err"), ("> ", "you")):
        if head.startswith(prefix):
            return kind, head[len(prefix):]
    if head.startswith(("STOPPED", "ERROR", "NOT restored")):
        return "err", head
    if "connected as" in lowered or "has joined" in lowered or "received" in lowered:
        return "net", head
    return "info", head


class Hero(tk.Canvas):
    """Title block with the rotating pixel disco ball (stepped animation, like the other pixel assets)."""

    HEIGHT = 150

    def __init__(self, parent, fonts, version):
        super().__init__(parent, height=self.HEIGHT, bg=BLACK, highlightthickness=0)
        self.fonts, self.version = fonts, version
        self.frames = ui_kit.disco_frames()
        self.step = 0
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()
        self.after(140, self._spin)

    def _draw(self):
        width = max(self.winfo_width(), 900)
        self.delete("all")
        self.create_text(28, 38, text="■", fill=TINT, font=self.fonts.small, anchor="w")
        label = self.create_text(46, 38, text="ARCHIPELAGO RANDOMIZER", fill=MUTED, font=self.fonts.label, anchor="w")
        self.create_text(28, 82, text="DEAD AS DISCO", fill=TEXT, font=self.fonts.title, anchor="w")
        self.create_text(28, 118, text="Your saves stay safe. The disco never stops.", fill=MUTED, font=self.fonts.note, anchor="w")
        if self.version:  # a tint-outlined tag right after the label (the ball sprite owns the right-hand side)
            x = self.bbox(label)[2] + 16
            chip_w = 24 + 12 * len(self.version)
            self.create_rectangle(x, 26, x + chip_w, 50, outline=TINT, width=2)
            self.create_text(x + chip_w / 2, 38, text="V" + self.version, fill=TINT, font=self.fonts.label_b)
        self.sprite = self.create_image(width - 28 - 224, self.HEIGHT / 2 + 2, image=self.frames[self.step], anchor="w", tags="ball")
        self.create_line(28, self.HEIGHT - 2, width - 28, self.HEIGHT - 2, fill=LINE_STRONG, dash=(6, 6))

    def _spin(self):
        try:
            if not self.winfo_exists():
                return
            self.step = (self.step + 1) % len(self.frames)
            self.itemconfigure("ball", image=self.frames[self.step])
            self.after(140, self._spin)
        except tk.TclError:
            pass


class App:
    def __init__(self, root, layout=None, install_root=None):
        self.root = root
        self.layout = layout or Layout.default()
        self.install_root = Path(install_root or play.default_root())
        self.messages = queue.Queue()
        self.buttons = []
        self.client_process = None
        self.failed = False
        self.settings_path = self.layout.state_dir / "gui-settings.json"
        root.title(TITLE + self._version())
        root.geometry(f"980x{min(860, max(680, root.winfo_screenheight() - 90))}")  # fits small laptop screens too
        root.minsize(860, 660)
        root.configure(bg=BLACK)
        ui_kit.load_fonts([self.install_root / "archipelago/dadap/assets/fonts"])
        self.fonts = ui_kit.Fonts(root)
        self._style()
        self._icon()
        ui_kit.dark_titlebar(root)
        Hero(root, self.fonts, self._version().strip()).pack(fill="x")
        saved = self._load()
        self.server = tk.StringVar(value=saved.get("server", ""))
        self.slot = tk.StringVar(value=saved.get("slot", ""))
        self.password = tk.StringVar()
        self.cloud = tk.BooleanVar(value=bool(saved.get("cloud_off", False)))
        body = tk.Frame(root, bg=BLACK)
        body.pack(fill="both", expand=True, padx=28, pady=(14, 14))
        top = tk.Frame(body, bg=BLACK)
        top.pack(fill="x")
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=2, uniform="side")
        left = tk.Frame(top, bg=BLACK)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self._form(left)
        self._commands(left)
        right = tk.Frame(top, bg=BLACK)
        right.grid(row=0, column=1, sticky="nsew")
        for number, head, detail in PLAQUES:
            self._plaque(right, number, head, detail)
        self._journal(body)
        self._chat(body)
        handler = _QueueHandler(self.log)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        root.after(100, self._pump)
        self.log("Ready.")

    # ---- look -------------------------------------------------------------------------------------------
    def _style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Pixel.Vertical.TScrollbar", background="#2b2b30", troughcolor=BLACK, bordercolor=BLACK, arrowcolor=MUTED,
                        lightcolor="#2b2b30", darkcolor="#2b2b30", relief="flat", arrowsize=12)
        style.map("Pixel.Vertical.TScrollbar", background=[("active", TINT)])

    def _icon(self):
        try:
            image = ui_kit.disco_frames(count=1, width=32, height=32, radius=13, zoom=1, scene=False)[0]
            self.root.iconphoto(True, image)
            self._icon_image = image
        except tk.TclError:
            pass

    def _plaque(self, parent, number, head, detail):
        plaque = tk.Frame(parent, bg=LINE, padx=1, pady=1)
        plaque.pack(fill="x", pady=(0, 8))
        row = tk.Frame(plaque, bg=PANEL)
        row.pack(fill="x")
        tk.Frame(row, bg=TINT, width=4).pack(side="left", fill="y")
        tk.Label(row, text=number, bg=FIELD, fg=MUTED, font=self.fonts.label, width=3).pack(side="left", fill="y")
        text = tk.Frame(row, bg=PANEL)
        text.pack(side="left", fill="both", expand=True, padx=10, pady=7)
        tk.Label(text, text=head, bg=PANEL, fg=MUTED, font=self.fonts.small, anchor="w").pack(fill="x")
        tk.Label(text, text=detail, bg=PANEL, fg=TEXT, font=self.fonts.note, anchor="w", justify="left", wraplength=250).pack(fill="x")

    def _form(self, parent):
        panel = ui_kit.Panel(parent, fit=True)
        panel.pack(fill="x")
        form = panel.inner
        form.columnconfigure(1, weight=1)
        for row, (label, variable, secret) in enumerate((("SERVER HOST:PORT", self.server, False), ("SLOT NAME", self.slot, False),
                                                          ("PASSWORD IF ANY", self.password, True))):
            tk.Label(form, text=label, bg=PANEL, fg=MUTED, font=self.fonts.small, anchor="w", width=17).grid(row=row, column=0, sticky="w", pady=5)
            box, _ = ui_kit.field(form, variable, self.fonts.body, secret)
            box.grid(row=row, column=1, sticky="ew", pady=5)
        check = tk.Frame(form, bg=PANEL)
        check.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        ui_kit.PixelCheck(check, self.cloud).pack(side="left", anchor="n", pady=2)
        label = tk.Label(check, bg=PANEL, fg=TEXT, font=self.fonts.note, justify="left", anchor="w", wraplength=520, cursor="hand2",
                         text="Steam Cloud is OFF for Dead as Disco (Steam > Library > right-click the game > Properties > General). "
                              "Turn it back on after playing.")
        label.pack(side="left", padx=(10, 0), fill="x", expand=True)
        label.bind("<Button-1>", lambda _e: self.cloud.set(not self.cloud.get()))

    def _commands(self, parent):
        bar = tk.Frame(parent, bg=BLACK)
        bar.pack(fill="x", pady=(14, 0))
        specs = (("PLAY", self.on_play, True, 190, 52, self.fonts.heading), ("RECOVER SAVES", self.on_recover, False, 158, 52, self.fonts.label_b),
                 ("CHECK INSTALL", self.on_doctor, False, 158, 52, self.fonts.label_b))
        for text, action, primary, width, height, font in specs:
            button = ui_kit.PixelButton(bar, text, action, font, primary=primary, width=width, height=height)
            button.pack(side="left", padx=(0, 12))
            self.buttons.append(button)
        self.segments = ui_kit.Segments(parent)
        self.segments.pack(anchor="w", pady=(10, 0))

    def _journal(self, parent):
        panel = ui_kit.Panel(parent, fit=False, pad=8)
        panel.pack(fill="both", expand=True, pady=(14, 0))
        inner = panel.inner
        head = tk.Frame(inner, bg=PANEL)
        head.pack(fill="x", padx=6, pady=(2, 4))
        tk.Label(head, text="■ JOURNAL", bg=PANEL, fg=MUTED, font=self.fonts.small).pack(side="left")
        self.status = tk.Label(head, text="READY", bg=PANEL, fg=OK, font=self.fonts.label_b)
        self.status.pack(side="right")
        tk.Frame(inner, bg=LINE_STRONG, height=1).pack(fill="x", padx=6)
        scroll = ttk.Scrollbar(inner, style="Pixel.Vertical.TScrollbar")
        scroll.pack(side="right", fill="y", pady=(4, 0))
        self.output = tk.Text(inner, height=9, state="disabled", wrap="word", bg=PANEL, fg=TEXT, relief="flat", font=self.fonts.log, padx=10,
                              pady=6, highlightthickness=0, yscrollcommand=scroll.set, selectbackground=TINT, selectforeground=BLACK,
                              insertbackground=ACCENT, spacing1=3, cursor="arrow")
        self.output.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.output.yview)
        self.output.tag_configure("time", foreground=MOON)
        self.output.tag_configure("err_text", foreground=ERR, font=self.fonts.log_b)
        self.output.tag_configure("run_text", foreground=ACCENT, font=self.fonts.log_b)
        self.output.tag_configure("warn_text", foreground=WARN)
        self.output.tag_configure("you_text", foreground=TINT)
        for kind, (_chip, background, foreground) in CHIPS.items():
            if background:
                self.output.tag_configure("chip_" + kind, background=background, foreground=foreground, font=self.fonts.log_b)

    def _chat(self, parent):
        row = tk.Frame(parent, bg=BLACK)
        row.pack(fill="x", pady=(12, 0))
        tk.Label(row, text=">", bg=BLACK, fg=TINT, font=self.fonts.heading).pack(side="left", padx=(0, 10))
        self.chat = tk.StringVar()
        box, entry = ui_kit.field(row, self.chat, self.fonts.body)
        box.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.on_chat())
        send = ui_kit.PixelButton(row, "SEND", self.on_chat, self.fonts.label_b, width=96, height=40)
        send.pack(side="left", padx=(12, 0))
        tk.Label(parent, text="Chat while playing, or !hint <item>, !hint_location <location>, !help", bg=BLACK, fg=MOON,
                 font=self.fonts.note, anchor="w").pack(fill="x", pady=(6, 0))

    def _version(self):
        """' 0.5.6' from the release certificate; empty when running from a source checkout."""
        try:
            certificate = json.loads((self.install_root / "archipelago/capabilities.json").read_text(encoding="utf-8"))
            return " " + certificate["release_version"]
        except (OSError, ValueError, KeyError):
            return ""

    # ---- plumbing ---------------------------------------------------------------------------------------
    def log(self, message):
        self.messages.put(str(message))

    def _set_status(self, text, color, busy):
        self.status.configure(text=text, fg=color)
        (self.segments.start if busy else self.segments.stop)()

    def _write(self, message):
        kind, text = classify(message)
        chip, background, _ = CHIPS[kind]
        self.output.configure(state="normal")
        self.output.insert("end", time.strftime("%H:%M:%S") + " ", "time")
        self.output.insert("end", chip, "chip_" + kind if background else ())
        self.output.insert("end", " " + text + "\n", kind + "_text" if kind in ("err", "run", "warn", "you") else ())
        self.output.see("end")
        self.output.configure(state="disabled")

    def _pump(self):
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            if isinstance(message, tuple):  # ("status", text, colour, busy), posted from the worker thread
                self._set_status(*message[1:])
            else:
                self._write(message)
        self.root.after(100, self._pump)

    def _load(self):
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings = self._load()  # keep what other code stored (the chosen game folder)
            settings.update({"server": self.server.get().strip(), "slot": self.slot.get().strip(), "cloud_off": bool(self.cloud.get())})
            self.settings_path.write_text(json.dumps(settings), encoding="utf-8")
        except OSError:
            pass

    def run(self, label, work):
        """Run `work` off the UI thread; buttons stay disabled until it finishes."""
        for button in self.buttons:
            button.state(["disabled"])
        self._save()
        self.failed = False
        self._set_status("WORKING", TINT, True)

        def target():
            try:
                self.log(f"--- {label} ---")
                work()
                self.log(f"--- {label}: done ---")
            except SafetyError as error:
                self.failed = True
                self.log(f"STOPPED: {error}")
            except Exception as error:  # noqa: BLE001 - show any failure to the player instead of dying silently
                self.failed = True
                self.log(f"ERROR: {error!r}")
            finally:
                self.messages.put(("status", "STOPPED - READ THE JOURNAL" if self.failed else "READY", ERR if self.failed else OK, False))
                self.root.after(0, lambda: [b.state(["!disabled"]) for b in self.buttons])

        threading.Thread(target=target, daemon=True).start()

    # ---- actions ----------------------------------------------------------------------------------------
    def on_play(self):
        server, slot = self.server.get().strip(), self.slot.get().strip()
        if not server or not slot:
            messagebox.showwarning(TITLE, "Fill in Server and Slot name (ask whoever hosts the game).")
            return
        if not self.cloud.get():
            messagebox.showwarning(TITLE, "Please turn Steam Cloud OFF for Dead as Disco first, then tick the box.\n"
                                   "(The game is started offline, but this removes any risk to your cloud saves.)")
            return
        password = self.password.get() or None
        self.run("Play", lambda: play.play(self.layout, None, server, slot, password, install_root=self.install_root, log=self.log,
                                           on_client=lambda process: setattr(self, "client_process", process)))

    def on_doctor(self):
        def work():
            for level, check, detail in doctor.diagnose(self.layout, session.Probe()):
                self.log(f"[{level}] {check}: {detail}")
        self.run("Check install", work)

    def on_chat(self):
        text = self.chat.get().strip()
        process = self.client_process
        if not text:
            return
        if process is None or process.poll() is not None:
            self.log("Chat is available while you are playing (the Archipelago client is not running).")
            return
        try:
            process.stdin.write(text + "\n")
            process.stdin.flush()
            self.log("> " + text)
            self.chat.set("")
        except OSError as error:
            self.log(f"Could not send: {error}")

    def on_recover(self):
        def work():
            state = session.restore(self.layout, session.Probe())
            self.log("Nothing to recover." if state is None else f"Restored session {state['sid']}; your saves are back.")
        self.run("Recover saves", work)


def choose_layout(root, default=Layout.default, ask=filedialog.askdirectory, warn=messagebox.showwarning):
    """The layout for this PC. When the game cannot be found by itself, ask for its folder (and remember it) instead of crashing."""
    try:
        return default()
    except FileNotFoundError:
        pass
    warn(TITLE, "Dead as Disco was not found automatically.\n\nPlease pick the game folder: the one that contains the "
         "folder named Pagoda (Steam > Library > right-click the game > Manage > Browse local files).")
    while True:
        chosen = ask(parent=root, title="Select the Dead as Disco folder")
        if not chosen:
            return None
        if is_game_dir(chosen):
            layout = default(chosen)
            try:
                remember_game_dir(layout.state_dir, chosen)
            except OSError:
                pass
            return layout
        warn(TITLE, "That folder is not the Dead as Disco install (it must contain Pagoda\\Binaries\\Win64).\nTry again.")


def release_version(install_root):
    """"0.5.15" from the release certificate; empty when running from a source checkout."""
    try:
        return json.loads((Path(install_root) / "archipelago/capabilities.json").read_text(encoding="utf-8"))["release_version"]
    except (OSError, ValueError, KeyError):
        return ""


def main():
    layout, root = None, None
    try:
        layout = Layout.default()
    except FileNotFoundError:
        root = tk.Tk()
        root.withdraw()
        layout = choose_layout(root)
        if layout is None:
            return
    # The designed window is a local web page: first in our own frameless WebView2 window, then in an Edge/Chrome app window. The
    # classic tkinter window is the last resort (nothing could be shown, the page never connected, or DAD_CLASSIC_UI=1).
    if os.environ.get("DAD_CLASSIC_UI") != "1":
        if root is not None:
            root.destroy()
            root = None
        install_root = play.default_root()
        try:
            from . import webgui
            native = None if os.environ.get("DAD_NO_NATIVE") == "1" else webgui.native_window
            if webgui.run(layout, install_root, release_version(install_root), native=native):
                return
        except Exception as error:  # noqa: BLE001 - never leave the player without a window
            logging.getLogger("dadap.gui").warning("Web window unavailable (%r); using the classic window", error)
    root = root or tk.Tk()
    root.deiconify()
    App(root, layout)
    root.mainloop()