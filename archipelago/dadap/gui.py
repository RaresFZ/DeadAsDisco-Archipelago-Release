"""The whole player experience: type Server / Slot / Password, click Play."""
import json
import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from . import doctor, play, session
from .fsutil import SafetyError
from .layout import Layout

TITLE = "Dead as Disco - Archipelago"
HELP = ("Type the Server, Slot name and Password (ask whoever hosts), then click Play.\n"
        "First time on a multiworld the game opens for the tutorial: finish ONLY the tutorial, stay in the hub, quit the game and "
        "close Steam - the Archipelago game then starts by itself. Next time just click Play.\n"
        "Your real saves are never touched: they are moved aside and put back automatically (with a backup).")


class _QueueHandler(logging.Handler):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        self.sink(self.format(record))


class App:
    def __init__(self, root, layout=None, install_root=None):
        self.root = root
        self.layout = layout or Layout.default()
        self.install_root = Path(install_root or play.default_root())
        self.messages = queue.Queue()
        self.buttons = []
        self.client_process = None
        self.settings_path = self.layout.state_dir / "gui-settings.json"
        root.title(TITLE)
        root.geometry("820x600")
        ttk.Label(root, text=HELP, justify="left", wraplength=780).pack(padx=12, pady=(10, 4), anchor="w")
        form = ttk.Frame(root)
        form.pack(fill="x", padx=12, pady=6)
        saved = self._load()
        self.server = tk.StringVar(value=saved.get("server", ""))
        self.slot = tk.StringVar(value=saved.get("slot", ""))
        self.password = tk.StringVar()
        self.cloud = tk.BooleanVar(value=bool(saved.get("cloud_off", False)))
        for row, (label, var, secret) in enumerate((("Server (host:port)", self.server, False), ("Slot name", self.slot, False),
                                                    ("Password (if any)", self.password, True))):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(form, textvariable=var, width=46, show="*" if secret else "").grid(row=row, column=1, sticky="w", padx=8)
        ttk.Checkbutton(root, variable=self.cloud, text="Steam Cloud is OFF for Dead as Disco (Steam > Library > right-click the game > "
                        "Properties > General). Turn it back on after playing.").pack(padx=12, anchor="w")
        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=12, pady=8)
        play_button = ttk.Button(bar, text="PLAY", command=self.on_play, width=18)
        play_button.pack(side="left", padx=4, ipady=6)
        self.buttons.append(play_button)
        for text, action in (("Recover saves", self.on_recover), ("Check install", self.on_doctor)):
            button = ttk.Button(bar, text=text, command=action)
            button.pack(side="left", padx=4)
            self.buttons.append(button)
        self.output = scrolledtext.ScrolledText(root, height=22, state="disabled", wrap="word")
        self.output.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        chat = ttk.Frame(root)
        chat.pack(fill="x", padx=12, pady=(0, 12))
        self.chat = tk.StringVar()
        entry = ttk.Entry(chat, textvariable=self.chat)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.on_chat())
        ttk.Button(chat, text="Send", command=self.on_chat).pack(side="left", padx=(6, 0))
        ttk.Label(chat, text="  chat, or !hint <item>, !hint_location <loc>, !help ...").pack(side="left")
        handler = _QueueHandler(self.log)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        root.after(100, self._pump)
        self.log("Ready.")

    # ---- plumbing ---------------------------------------------------------------------------------------
    def log(self, message):
        self.messages.put(str(message))

    def _pump(self):
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            self.output.configure(state="normal")
            self.output.insert("end", message + "\n")
            self.output.see("end")
            self.output.configure(state="disabled")
        self.root.after(100, self._pump)

    def _load(self):
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps({"server": self.server.get().strip(), "slot": self.slot.get().strip(),
                                                      "cloud_off": bool(self.cloud.get())}), encoding="utf-8")
        except OSError:
            pass

    def run(self, label, work):
        """Run `work` off the UI thread; buttons stay disabled until it finishes."""
        for button in self.buttons:
            button.state(["disabled"])
        self._save()

        def target():
            try:
                self.log(f"--- {label} ---")
                work()
                self.log(f"--- {label}: done ---")
            except SafetyError as error:
                self.log(f"STOPPED: {error}")
            except Exception as error:  # noqa: BLE001 - show any failure to the player instead of dying silently
                self.log(f"ERROR: {error!r}")
            finally:
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


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
