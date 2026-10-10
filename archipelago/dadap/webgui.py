"""The launcher window as a local web page (the design in webui/), shown in an Edge/Chrome app window.

Python keeps all the real work (the same play/doctor/recover functions as the classic tkinter window); the page only draws it.
The server listens on 127.0.0.1 only, and every request that does something needs a per-run secret token, so no other web page or
program on the PC can press Play or Recover. If no browser can be opened, the caller falls back to the classic window.
"""
import hmac
import html
import json
import logging
import os
import platform
import re
import secrets
import shutil
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import doctor, friendly, play, session
from .fsutil import SafetyError

STEP_NAMES = ("Steam Cloud", "Game files", "Saves", "Server", "Slot")
HI = 'style="color:#ffe81a"'
TYPES = {".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml", ".png": "image/png", ".js": "text/javascript", ".ico": "image/x-icon"}


def classify(message):
    """(tag, text) of one launcher/client message for the journal."""
    head = message.strip()
    low = head.lower()
    if head.startswith("--- "):
        text = head.strip("- ").strip()
        return ("OK", text) if text.endswith(": done") else ("RUN", "Starting " + text)
    for prefix, tag in (("[OK] ", "OK"), ("[WARN] ", "WARN"), ("[FAIL] ", "ERR")):
        if head.startswith(prefix):
            return tag, head[len(prefix):]
    if head.startswith(("STOPPED", "ERROR", "!!!", "NOT restored")):
        return "ERR", head
    if re.match(r"^.+ sent .+ to .+", head) or low.startswith("received "):
        return "ITEM", head
    if "hint" in low:
        return "HINT", head
    if "has joined" in low or "has left" in low or "connected as" in low:
        return "SYS", head
    if re.match(r"^[^\s:][^:]{0,40}: \S", head):
        return "CHAT", head
    return "SYS", head


class _LogBridge(logging.Handler):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        tag = "ERR" if record.levelno >= logging.ERROR else "WARN" if record.levelno >= logging.WARNING else "SYS"
        self.sink(tag, self.format(record))


class Controller:
    """All launcher state. Thread-safe; the page reads it with `state()` and changes it through the action methods."""

    def __init__(self, layout, install_root, version=""):
        self.layout, self.install_root, self.version = layout, Path(install_root), version
        self.lock = threading.RLock()
        self.logs, self.next_id = [], 1
        self.settings_path = layout.state_dir / "gui-settings.json"
        saved = self._load()
        self.server, self.slot = saved.get("server", ""), saved.get("slot", "")
        self.cloud_off = bool(saved.get("cloud_off", False))
        self.cs = ["on" if self.cloud_off else "wait", "wait", "wait", "wait", "wait"]
        self.subs, self.marks = [None] * 5, [None] * 5
        self.status, self.error = "ready", ""
        self.bubble = {"id": 0, "n": "Launcher", "t": f"Type your server and slot name, then hit <b {HI}>PLAY</b>."}
        self.items = self.checks = self.total = self.hints = 0
        self.busy = False
        self.client, self.status_path, self.focus = None, None, None
        self.last_poll, self.closed = None, False
        self.frameless, self.window_ops, self.last_error = False, None, None
        self.log_path = layout.state_dir / "launcher-log.txt"
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.is_file() and self.log_path.stat().st_size > 1_000_000:
                self.log_path.replace(self.log_path.with_suffix(".old.txt"))
        except OSError:
            pass
        self.handler = _LogBridge(self.push)
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(self.handler)
        logging.getLogger().setLevel(logging.INFO)
        self.push("SYS", f"Launcher ready{', v' + version if version else ''}")

    def close(self):
        logging.getLogger().removeHandler(self.handler)

    # ---- settings ---------------------------------------------------------------------------------------
    def _load(self):
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings = self._load()  # keep what other code stored (the chosen game folder)
            settings.update({"server": self.server.strip(), "slot": self.slot.strip(), "cloud_off": self.cloud_off})
            self.settings_path.write_text(json.dumps(settings), encoding="utf-8")
        except OSError:
            pass

    def set_settings(self, data):
        with self.lock:
            self.server, self.slot = str(data.get("server", self.server)), str(data.get("slot", self.slot))
            self.cloud_off = bool(data.get("cloud_off", self.cloud_off))
            if not self.busy:
                self.cs[0] = "on" if self.cloud_off else ("err" if self.cs[0] == "err" else "wait")
                if self.status == "error":
                    self.status, self.error = "ready", ""
                    self.say(f"Got it. Hit <b {HI}>PLAY</b> when you’re ready.")
                if self.status == "ready":
                    self.cs[3] = self.cs[4] = "wait"
                    self.subs[3] = self.subs[4] = None
            self._save()

    # ---- state shown by the page --------------------------------------------------------------------------
    def push(self, tag, text):
        with self.lock:
            stamp = time.strftime("%H:%M:%S")
            self.logs.append({"id": self.next_id, "t": stamp, "tg": tag, "x": text})
            self.next_id += 1
            del self.logs[:-300]
            try:  # the technical lines are kept as they are, so a player can send the file
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"{time.strftime('%Y-%m-%d')} {stamp} {tag:4} {text}\n")
            except OSError:
                pass

    def log(self, message):
        """Launcher/client message: show it, and let it move the five launch steps."""
        message = str(message)
        tag, text = classify(message)
        self.push(tag, text)
        self._infer(message)

    def say(self, html_text, name="Launcher", help=False):
        with self.lock:
            self.bubble = {"id": self.bubble["id"] + 1, "n": name, "t": html_text, "help": help}

    def step(self, index, state, sub=None, mark=None):
        with self.lock:
            self.cs[index], self.subs[index], self.marks[index] = state, sub, mark

    def _default_sub(self, i):
        state = self.cs[i]
        if i == 0:
            return "Off for Dead as Disco" if self.cloud_off else ("Still on — turn it off first" if state == "err" else "Turn it off in Steam first")
        if i == 3:
            return self.server.strip() or "—"
        if i == 4:
            return self.slot.strip() or "—"
        if i == 1:
            return {"wait": "Checked when you press Play", "on": "Mod loader ready", "run": "Working…", "err": "Needs attention", "live": "Running"}[state]
        return {"wait": "Moved aside when you press Play", "on": "Moved aside · backed up", "run": "Working…", "err": "Needs attention", "live": "Moved aside · backed up"}[state]

    def state(self, after=0):
        with self.lock:
            self.last_poll = time.monotonic()
            steps = [{"n": STEP_NAMES[i], "st": self.cs[i], "sub": self.subs[i] or self._default_sub(i),
                      "m": self.marks[i] or ("Fix" if self.cs[i] == "err" and i != 3 else None)} for i in range(5)]
            slot = self.slot.strip()
            banner = {"error": "Stopped" + (" · " + self.error if self.error else ""), "ready": "Ready to dance",
                      "running": "Connecting…", "connected": "Connected as " + slot}[self.status]
            play_label = {"connected": ("Playing", "Quit the game to finish"), "running": ("Starting", "Hang on…")}.get(
                self.status, ("Play", "Start the game"))
            focus, self.focus = self.focus, None
            return {"version": self.version, "status": self.status, "banner": banner, "play": {"t": play_label[0], "h": play_label[1]},
                    "steps": steps, "ready": sum(1 for s in self.cs if s in ("on", "live")), "bubble": dict(self.bubble),
                    "nums": {"items": self.items, "checks": self.checks, "total": self.total, "hints": self.hints},
                    "log": [dict(l) for l in self.logs if l["id"] > after], "last": self.next_id - 1, "busy": self.busy,
                    "settings": {"server": self.server, "slot": self.slot, "cloud_off": self.cloud_off}, "focus": focus,
                    "frameless": self.frameless, "maximized": bool(getattr(self.window_ops, "maximized", False))}

    # ---- reading what the launch is doing ----------------------------------------------------------------
    def _infer(self, m):
        low = m.lower()
        if m.startswith("First run: installing"):
            self.step(1, "run", "Installing the mod loader")
        elif "first time on this multiworld" in low:
            self.say(f"First time on this multiworld: the game opens for the <b {HI}>tutorial</b>. Finish only the tutorial, stay in the hub, "
                     "then quit the game and close Steam.")
        elif m.startswith("Session ") and ("saves parked" in m or "safely moved aside" in m):
            self.step(1, "on", "Mod loader ready")
            self.step(2, "on", "Moved aside · backed up")
            if "saves parked" in m:
                self.step(3, "on", self.server.strip() or None)
                self.say("Launching the game offline…")
        elif m.startswith("Archipelago client running"):
            self.step(3, "run", "Connecting to " + (self.server.strip() or "the server"))
            self.say("Play the game; close it normally when you are done.")
        elif m.startswith("Restored session"):
            self.step(2, "on", "Put back · checked")
        elif m.startswith("!!!"):
            self.explain(m.lstrip("! "))

    def _step_for(self, message):
        low = message.lower()
        for keys, index in ((("world version",), 4), (("slot",), 4), (("steam cloud",), 0), (("server", "password", "refused", "seed"), 3),
                            (("tutorial", "save", "profile", "restore"), 2), (("game", "install", "mod loader", "ue4ss", "build", "proxy"), 1)):
            if any(key in low for key in keys):
                return index
        return next((i for i, s in enumerate(self.cs) if s == "run"), None)

    def explain(self, message):
        """Show the plain-words explanation (bubble + journal tips) for a technical message; the message itself stays in the journal."""
        info = friendly.explain(message)
        with self.lock:
            self.last_error = {"code": info["code"], "raw": message}
            steps = "".join(f"<li>{html.escape(s)}</li>" for s in info["steps"])
            self.say(f"<b {HI}>{html.escape(info['title'])}</b> <span class='code'>{info['code']}</span><br>{html.escape(info['what'])}"
                     f"<ol>{steps}</ol><span class='ask'>{html.escape(friendly.CONTACT)} "
                     "<button class='copy' type='button'>Copy details</button></span>", help=True)
            self.push("TIP", f"[{info['code']}] {info['what']}")
            self.push("TIP", "Try: " + "  \u2022  ".join(info["steps"]))
        return info

    def _fail(self, message):
        short = message.split(".")[0][:90]
        with self.lock:
            index = self._step_for(message)
            if index is not None:
                self.step(index, "err", None, "No answer" if index == 3 and "answer" in message.lower() else None)
            for i, s in enumerate(self.cs):
                if s in ("run", "live"):
                    self.cs[i] = "wait"
            self.status, self.error = "error", short
            self.explain(message)

    def _watch_status(self, process, path):
        """Follow the client's status file while it runs: connection, items received, checks sent."""
        total_seen = False
        while process.poll() is None:
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            if data:
                with self.lock:
                    self.items = int(data.get("received", self.items) or 0)
                    self.checks = int(data.get("confirmed_checks", 0) or 0)
                    if data.get("locations_total"):
                        self.total, total_seen = int(data["locations_total"]), True
                    if data.get("authenticated") and self.status != "connected" and self.busy:
                        self.status = "connected"
                        self.step(3, "live", "Connected to " + (self.server.strip() or "the server"))
                        self.step(4, "live", (self.slot.strip() or "") + (f" · {self.total} checks" if self.total else ""))
                        self.say(f"You’re in, <b {HI}>{html.escape(self.slot.strip())}</b>. Saves go back when you quit the game.")
                    elif data.get("connection") == "blocked":
                        self._fail("The Archipelago client refused this connection (wrong server, seed or password).")
                    elif not data.get("authenticated") and self.status == "connected":
                        self.status = "running"
                        self.step(3, "run", "Reconnecting…")
                        self.step(4, "wait")
            time.sleep(1)

    def _on_client(self, process):
        self.client = process
        args = list(getattr(process, "args", []) or [])
        if "--status" in args and args.index("--status") + 1 < len(args):
            self.status_path = args[args.index("--status") + 1]
            threading.Thread(target=self._watch_status, args=(process, self.status_path), daemon=True).start()

    # ---- actions -------------------------------------------------------------------------------------------
    def _begin(self, label, status=None):
        with self.lock:
            if self.busy:
                return False
            self.busy = True
            if status:
                self.status, self.error = status, ""
            return True

    def _run(self, label, work, playing=False):
        def target():
            failed = False
            try:
                self.log(f"--- {label} ---")
                work()
                self.log(f"--- {label}: done ---")
            except SafetyError as error:
                failed = True
                self.log(f"STOPPED: {error}")
                self._fail(str(error))
            except Exception as error:  # noqa: BLE001 - show any failure to the player instead of dying silently
                failed = True
                self.log(f"ERROR: {error!r}")
                self._fail(repr(error))
            finally:
                with self.lock:
                    self.busy, self.client, self.status_path = False, None, None
                    if playing and not failed:
                        self.status = "ready"
                        self.cs = ["on" if self.cloud_off else "wait", "wait", "on", "wait", "wait"]
                        self.subs = [None, None, "Put back · checked", None, None]
                        self.say("Saves are back where they were. See you next set.")
        threading.Thread(target=target, daemon=True).start()

    def _fail_start(self, message, html_text, step=None, focus=None):
        self.push("ERR", message)
        self.say(html_text)
        if step is not None:
            self.step(step, "err")
        self.focus = focus

    def play(self, data):
        self.set_settings(data)
        server, slot = self.server.strip(), self.slot.strip()
        with self.lock:
            if self.busy:
                return
            if not server or not re.search(r":\d+$", server):
                return self._fail_start("Server is missing a port, expected host:port",
                                        f"That server needs a port. Something like <b {HI}>archipelago.gg:38281</b>.", 3, "host")
            if not slot:
                return self._fail_start("Slot name is empty", f"Who are you playing as? Type your <b {HI}>slot name</b> first.", 4, "slot")
            if not self.cloud_off:
                return self._fail_start("Steam Cloud still on, saves could be overwritten",
                                        'Steam Cloud is still <b style="color:#ff1d8e">ON</b>. Turn it off or it could eat your saves.', 0)
            password = str(data.get("password") or "") or None
            self._begin("Play", "running")
            self.cs = ["on", "wait", "wait", "run", "wait"]
            self.subs, self.marks = [None] * 5, [None] * 5
            self.items = self.checks = self.hints = 0
            self.say("Warming up the floor…")
        self._run("Play", lambda: play.play(self.layout, None, server, slot, password, install_root=self.install_root, log=self.log,
                                            on_client=self._on_client), playing=True)

    def stop(self):
        self.say("Quit the game from its menu and close Steam. The launcher puts your saves back by itself, nothing to press here.")

    def doctor(self):
        with self.lock:
            if self.busy or not self._begin("Check install"):
                return

        def work():
            results = doctor.diagnose(self.layout, session.Probe())
            groups = {1: {"game build", "UE4SS core", "game folder"}, 2: {"session", "disk space", "volume", "saves", "processes"}}
            verdict = {1: "on", 2: "on"}
            for level, check, detail in results:
                self.log(f"[{level}] {check}: {detail}")
                for index, names in groups.items():
                    if check in names and level == "FAIL":
                        verdict[index] = "err"
            for index, state in verdict.items():
                self.step(index, state)
            self.say("Install looks good. Game files and mod loader are in place." if "err" not in verdict.values()
                     else "Something needs attention. Read the red lines in the log.")
        self._run("Check install", work)

    def recover(self):
        with self.lock:
            if self.busy or not self._begin("Recover saves"):
                return
            self.step(2, "run")

        def work():
            state = session.restore(self.layout, session.Probe())
            self.log("Nothing to recover." if state is None else f"Restored session {state['sid']}; your saves are back.")
            self.step(2, "on", "Put back · checked")
            self.say("Nothing to recover. Your saves are where they should be." if state is None else "Your saves are back where they were.")
        self._run("Recover saves", work)

    def details(self):
        """Everything worth pasting into a support message (no passwords are ever stored in the journal)."""
        with self.lock:
            last = self.last_error or {"code": "-", "raw": "-"}
            recent = [f"{l['t']} {l['tg']:4} {l['x']}" for l in self.logs[-30:]]
            lines = [f"Dead as Disco Archipelago launcher {self.version or '(source)'}", f"Windows: {platform.platform()}",
                     f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}", f"Status: {self.status} / steps {' '.join(self.cs)}",
                     f"Last error code: {last['code']}", f"Last error (raw): {last['raw']}", "", "--- last journal lines ---", *recent, "",
                     f"Full log file: {self.log_path}"]
        return "\n".join(lines)

    def window(self, action):
        ops = self.window_ops
        if ops is None or action not in ("min", "max", "close"):
            return
        if action == "close" and self.busy:
            ops.minimize()  # a running session must not lose its window silently
            self.push("SYS", "The launcher stays open while the game runs. Quit the game first, then close this window.")
            return
        {"min": ops.minimize, "max": ops.toggle_maximize, "close": ops.close}[action]()

    def chat(self, text):
        text = str(text).strip()
        if not text:
            return
        process = self.client
        if self.status != "connected" or process is None or process.poll() is not None:
            self.push("SYS", "Not connected, hit Play first")
            return
        try:
            process.stdin.write(text + "\n")
            process.stdin.flush()
        except OSError as error:
            self.push("ERR", f"Could not send: {error}")
            return
        self.push("CHAT", f"{self.slot.strip()}: {text}")
        if re.match(r"^!hint(_location)?\s+\S", text):
            with self.lock:
                self.hints += 1


# ---- the local server -----------------------------------------------------------------------------------------------
def make_handler(controller, token, assets, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    index_text = (assets / "index.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, kind):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                                                        "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code, value):
            self._send(code, json.dumps(value), "application/json")

        def _checked(self, from_query=False):
            if self.headers.get("Host", "") not in allowed_hosts:
                self._json(400, {"error": "bad host"})
                return False
            given = parse_qs(urlparse(self.path).query).get("t", [""])[0] if from_query else self.headers.get("X-DAD-Token", "")
            if not hmac.compare_digest(given.encode(), token.encode()):
                self._json(403, {"error": "forbidden"})
                return False
            return True

        def do_GET(self):
            path = urlparse(self.path).path
            if self.headers.get("Host", "") not in allowed_hosts:
                return self._json(400, {"error": "bad host"})
            if path == "/":
                return self._send(200, index_text.replace("__TOKEN__", token), "text/html; charset=utf-8")
            if path.startswith("/static/"):
                target = (assets / path[len("/static/"):]).resolve()
                if assets.resolve() in target.parents and target.is_file() and target.suffix in TYPES:
                    return self._send(200, target.read_bytes(), TYPES[target.suffix])
                return self._json(404, {"error": "not found"})
            if path == "/api/details":
                if self._checked():
                    self._json(200, {"text": controller.details()})
                return
            if path == "/api/state":
                if not self._checked():
                    return
                after = parse_qs(urlparse(self.path).query).get("after", ["0"])[0]
                return self._json(200, controller.state(int(after) if after.isdigit() else 0))
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(min(length, 65536))  # always read the request first, so an early refusal never resets the connection
            if path == "/api/bye":
                if self._checked(from_query=True):
                    controller.closed = True
                    self._json(200, {})
                return
            if not self._checked():
                return
            try:
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    raise ValueError
            except ValueError:
                return self._json(400, {"error": "bad json"})
            actions = {"/api/settings": lambda: controller.set_settings(data), "/api/play": lambda: controller.play(data),
                       "/api/stop": controller.stop, "/api/window": lambda: controller.window(str(data.get("action", ""))), "/api/doctor": controller.doctor, "/api/recover": controller.recover,
                       "/api/chat": lambda: controller.chat(data.get("text", ""))}
            if path not in actions:
                return self._json(404, {"error": "not found"})
            actions[path]()
            after = data.get("after", 0)
            self._json(200, controller.state(after if isinstance(after, int) and after >= 0 else 0))

    return Handler


def assets_dir(install_root):
    for candidate in (Path(install_root) / "archipelago/dadap/webui", Path(__file__).resolve().parent / "webui"):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def find_browser():
    roots = [os.environ.get(name) for name in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData")]
    for root in filter(None, roots):
        for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
            if (Path(root) / relative).is_file():
                return str(Path(root) / relative)
    return shutil.which("msedge") or shutil.which("chrome")


def open_window(url, profile_dir):
    """An Edge/Chrome app window (own profile folder: it never touches the player's browser). None if there is no such browser."""
    exe = find_browser()
    if not exe:
        return None
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile_dir}", "--window-size=1280,860", "--no-first-run",
                             "--no-default-browser-check", "--disable-sync", "--disable-extensions", "--lang=en-US",
                             "--disable-features=Translate,TranslateUI,msEdgeTranslate"])


class _NativeOps:
    """What the page's own title-bar buttons do to the frameless window."""

    def __init__(self, window):
        self.window, self.maximized = window, False
        window.events.maximized += lambda: setattr(self, "maximized", True)
        window.events.restored += lambda: setattr(self, "maximized", False)

    def minimize(self):
        self.window.minimize()

    def toggle_maximize(self):
        (self.window.restore if self.maximized else self.window.maximize)()

    def close(self):
        self.window.destroy()


def native_window(controller, url, storage, first_poll_timeout=45):
    """Our own frameless window around the page (WebView2 through pywebview), so the title bar can be the designed one.

    True when the page connected and the window was closed normally. False means "show it another way" (pywebview or the WebView2
    runtime missing, or the page never connected).
    """
    try:
        import webview
    except Exception:  # noqa: BLE001 - optional component
        return False
    try:
        screen = webview.screens[0]
        width, height = min(1280, screen.width - 80), min(900, screen.height - 140)
    except Exception:  # noqa: BLE001
        width, height = 1280, 820
    try:
        window = webview.create_window("Dead as Disco \u2013 Archipelago", url, width=width, height=height, min_size=(1000, 680), frameless=True,
                                       easy_drag=False, resizable=True, background_color="#26092f", text_select=True)
        controller.window_ops, controller.frameless = _NativeOps(window), True
        started = time.monotonic()

        def watchdog():
            while controller.last_poll is None:
                if time.monotonic() - started > first_poll_timeout:
                    window.destroy()
                    return
                time.sleep(0.5)
        threading.Thread(target=watchdog, daemon=True).start()
        Path(storage).mkdir(parents=True, exist_ok=True)
        icon = getattr(controller, "icon_path", None)  # the disco ball, for the window and the taskbar
        webview.start(gui="edgechromium", storage_path=str(storage), **({"icon": str(icon)} if icon and Path(icon).is_file() else {}))
    except Exception:  # noqa: BLE001 - never leave the player without a window
        return False
    finally:
        controller.window_ops, controller.frameless = None, False
    return controller.last_poll is not None


def run(layout, install_root, version="", launcher=open_window, first_poll_timeout=45, idle_close=12, controller=None, native=None):
    """Show the launcher page and serve it until the window is closed. False when no window could be shown (use the classic one).

    `native` (see native_window) is tried first; `launcher` (an Edge/Chrome app window) is the second choice.
    """
    assets = assets_dir(install_root)
    if assets is None:
        return False
    controller = controller or Controller(layout, install_root, version)
    controller.icon_path = assets / "icon.ico"
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    server.RequestHandlerClass = make_handler(controller, token, assets, server.server_address[1])
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    started = time.monotonic()
    try:
        if native is not None and native(controller, url, layout.state_dir / "webview-native", first_poll_timeout):
            while controller.busy:  # the game session must finish (and put the saves back) even though the window is gone
                time.sleep(0.5)
            return True
        window = launcher(url, layout.state_dir / "webview")
        if window is None:
            return False
        while True:
            time.sleep(0.4)
            if controller.last_poll is None:
                if time.monotonic() - started > first_poll_timeout:
                    return False
                continue
            if controller.busy:
                continue  # the game session must finish (and put the saves back) even if the window was closed
            if controller.closed or time.monotonic() - controller.last_poll > idle_close:
                return True
    finally:
        server.shutdown()
        server.server_close()
        controller.close()
