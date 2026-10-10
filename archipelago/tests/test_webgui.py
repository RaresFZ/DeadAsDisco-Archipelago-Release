import http.client
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from archipelago.dadap import webgui
from archipelago.dadap.fsutil import SafetyError

ROOT = Path(__file__).resolve().parents[2]


def wait_idle(controller, seconds=5):
    deadline = time.monotonic() + seconds
    while controller.busy and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not controller.busy


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.controller = webgui.Controller(SimpleNamespace(state_dir=Path(self.temp.name)), ROOT, "9.9.9")

    def tearDown(self):
        self.controller.close()
        self.temp.cleanup()

    def play(self, **data):
        self.controller.play({"server": "host:1234", "slot": "Me", "cloud_off": True, **data})

    def test_journal_lines_get_the_design_tags(self):
        c = webgui.classify
        self.assertEqual(c("--- Play ---"), ("RUN", "Starting Play"))
        self.assertEqual(c("--- Play: done ---"), ("OK", "Play: done"))
        self.assertEqual(c("[OK] game build: x"), ("OK", "game build: x"))
        self.assertEqual(c("[FAIL] disk space: 1 MB"), ("ERR", "disk space: 1 MB"))
        self.assertEqual(c("STOPPED: nope")[0], "ERR")
        self.assertEqual(c("Bob sent Progressive Item to Me (Hemlock Star 1)")[0], "ITEM")
        self.assertEqual(c("Bob: hello there")[0], "CHAT")
        self.assertEqual(c("Me (Team #1) has joined the game")[0], "SYS")

    def test_play_refuses_a_bad_server_slot_or_steam_cloud_before_doing_anything(self):
        with mock.patch.object(webgui.play, "play", side_effect=AssertionError("must not run")):
            self.play(server="archipelago.gg")
            self.assertEqual((self.controller.cs[3], self.controller.focus), ("err", "host"))
            self.play(slot=" ")
            self.assertEqual(self.controller.cs[4], "err")
            self.play(cloud_off=False)
            self.assertEqual(self.controller.cs[0], "err")
        self.assertFalse(self.controller.busy)
        self.assertEqual(self.controller.status, "ready")
        self.assertGreaterEqual(sum(1 for l in self.controller.logs if l["tg"] == "ERR"), 3)

    def test_a_good_session_moves_the_steps_and_returns_to_ready_when_the_game_closes(self):
        def fake_play(layout, profile, server, slot, password, install_root, log, on_client):
            self.assertEqual((server, slot, password), ("host:1234", "Me", "pw"))
            log("Session abc: saves parked, profile 'p' active, mod staged (3 contexts bound). Launching offline...")
            self.assertEqual(self.controller.state()["steps"][2]["st"], "on")
            self.assertEqual(self.controller.status, "running")
            log("Restored session abc; your original saves are back, byte-for-byte verified.")
        with mock.patch.object(webgui.play, "play", fake_play):
            self.play(password="pw")
            wait_idle(self.controller)
        state = self.controller.state()
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["steps"][2]["sub"], "Put back · checked")
        self.assertEqual(state["settings"], {"server": "host:1234", "slot": "Me", "cloud_off": True})
        saved = json.loads((Path(self.temp.name) / "gui-settings.json").read_text())
        self.assertNotIn("password", saved)  # the password is never written down

    def test_a_failed_session_marks_the_right_step_and_keeps_the_message(self):
        with mock.patch.object(webgui.play, "play", side_effect=SafetyError("No answer from the Archipelago server")):
            self.play()
            wait_idle(self.controller)
        state = self.controller.state()
        self.assertEqual(state["status"], "error")
        self.assertEqual(state["steps"][3], {"n": "Server", "st": "err", "sub": "host:1234", "m": "No answer"})
        self.assertIn("The server did not answer", state["bubble"]["t"])  # plain words in the bubble ...
        self.assertIn("@the_twelvez", state["bubble"]["t"])
        self.assertTrue(state["bubble"]["help"])
        self.assertTrue(any(l["tg"] == "ERR" and l["x"] == "STOPPED: No answer from the Archipelago server" for l in state["log"]))  # ... raw text kept
        self.assertTrue(any(l["tg"] == "TIP" and "E-SERVER-NO-ANSWER" in l["x"] for l in state["log"]))
        self.assertTrue(state["banner"].startswith("Stopped"))
        self.assertTrue(any(l["tg"] == "ERR" and "STOPPED" in l["x"] for l in state["log"]))

    def test_details_text_keeps_the_raw_error_and_the_log_file_keeps_every_line(self):
        with mock.patch.object(webgui.play, "play", side_effect=SafetyError("Connection refused: InvalidSlot")):
            self.play()
            wait_idle(self.controller)
        details = self.controller.details()
        self.assertIn("Last error code: E-SLOT", details)
        self.assertIn("Last error (raw): Connection refused: InvalidSlot", details)
        self.assertIn("9.9.9", details)
        written = (Path(self.temp.name) / "launcher-log.txt").read_text(encoding="utf-8")
        self.assertIn("STOPPED: Connection refused: InvalidSlot", written)

    def test_window_buttons_act_on_the_window_but_a_running_session_only_minimizes(self):
        calls = []
        self.controller.window_ops = SimpleNamespace(maximized=False, minimize=lambda: calls.append("min"), close=lambda: calls.append("close"),
                                                     toggle_maximize=lambda: calls.append("max"))
        for action in ("min", "max", "bogus"):
            self.controller.window(action)
        self.controller.window("close")
        self.assertEqual(calls, ["min", "max", "close"])
        self.controller.busy = True
        self.controller.window("close")
        self.controller.busy = False
        self.assertEqual(calls[-1], "min")
        self.assertTrue(self.controller.logs[-1]["x"].startswith("The launcher stays open"))
        self.controller.window_ops = None
        self.controller.window("close")  # no window yet: nothing happens
        self.assertFalse(self.controller.state()["frameless"])

    def test_chat_needs_a_running_client_and_counts_hint_commands(self):
        self.controller.chat("hello")
        self.assertEqual(self.controller.logs[-1]["x"], "Not connected, hit Play first")
        written = []
        self.controller.client = SimpleNamespace(poll=lambda: None, stdin=SimpleNamespace(write=written.append, flush=lambda: None))
        self.controller.status, self.controller.slot = "connected", "Me"
        self.controller.chat("!hint Heavy Kick")
        self.assertEqual((written, self.controller.hints, self.controller.logs[-1]["tg"]), (["!hint Heavy Kick\n"], 1, "CHAT"))

    def test_status_file_drives_the_connected_state_and_counters(self):
        status = Path(self.temp.name) / "status.json"
        status.write_text(json.dumps({"authenticated": True, "received": 4, "confirmed_checks": 9, "locations_total": 34}))
        process = SimpleNamespace(args=["x", "--status", str(status)], poll=lambda: None if time.monotonic() < deadline else 0)
        deadline = time.monotonic() + 1.5
        self.controller.busy, self.controller.status, self.controller.slot = True, "running", "Me"
        self.controller._on_client(process)
        time.sleep(1.2)
        state = self.controller.state()
        self.assertEqual((state["status"], state["nums"]), ("connected", {"items": 4, "checks": 9, "total": 34, "hints": 0}))
        self.assertEqual(state["steps"][4]["st"], "live")
        self.controller.busy = False


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.controller = webgui.Controller(SimpleNamespace(state_dir=Path(self.temp.name)), ROOT, "9.9.9")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.port = self.server.server_address[1]
        self.token = "secret-token"
        self.server.RequestHandlerClass = webgui.make_handler(self.controller, self.token, webgui.assets_dir(ROOT), self.port)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.controller.close()
        self.temp.cleanup()

    def request(self, method, path, body=None, token=True, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host or f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token:
            headers["X-DAD-Token"] = self.token
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data

    def test_page_is_served_with_the_token_and_without_external_resources(self):
        status, data = self.request("GET", "/", token=False)
        page = data.decode()
        self.assertEqual(status, 200)
        self.assertIn(self.token, page)
        self.assertNotIn("__TOKEN__", page)
        self.assertNotIn("googleapis", page)
        self.assertEqual(self.request("GET", "/static/fonts.css", token=False)[0], 200)

    def test_actions_and_state_need_the_token_and_the_local_host_name(self):
        self.assertEqual(self.request("GET", "/api/state", token=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/play", {"server": "a:1", "slot": "b", "cloud_off": True}, token=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/recover", {}, token=False)[0], 403)
        self.assertEqual(self.request("GET", "/api/state", host="evil.example:80")[0], 400)  # DNS rebinding
        self.assertFalse(self.controller.busy)
        status, data = self.request("GET", "/api/state?after=0")
        self.assertEqual((status, json.loads(data)["version"]), (200, "9.9.9"))

    def test_static_files_cannot_escape_the_page_folder(self):
        for path in ("/static/../webgui.py", "/static/%2e%2e/webgui.py", "/static/fonts/../../webgui.py", "/static/../../../README.md"):
            self.assertEqual(self.request("GET", path, token=False)[0], 404, path)

    def test_settings_round_trip_and_the_page_gets_only_new_log_lines(self):
        status, data = self.request("POST", "/api/settings", {"server": "h:1", "slot": "S", "cloud_off": True, "after": 0})
        state = json.loads(data)
        self.assertEqual((status, state["settings"]), (200, {"server": "h:1", "slot": "S", "cloud_off": True}))
        again = json.loads(self.request("GET", f"/api/state?after={state['last']}")[1])
        self.assertEqual(again["log"], [])

    def test_details_and_window_endpoints_need_the_token(self):
        self.assertEqual(self.request("GET", "/api/details", token=False)[0], 403)
        status, data = self.request("GET", "/api/details")
        self.assertEqual((status, "launcher 9.9.9" in json.loads(data)["text"]), (200, True))
        self.assertEqual(self.request("POST", "/api/window", {"action": "close"}, token=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/window", {"action": "close"})[0], 200)  # no window: harmless

    def test_closing_the_page_marks_the_controller_closed(self):
        self.assertEqual(self.request("POST", f"/api/bye?t={self.token}", token=False)[0], 200)
        self.assertTrue(self.controller.closed)
        self.controller.closed = False
        self.assertEqual(self.request("POST", "/api/bye?t=wrong", token=False)[0], 403)
        self.assertFalse(self.controller.closed)


class RunTests(unittest.TestCase):
    def test_no_browser_means_the_classic_window(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            layout = SimpleNamespace(state_dir=Path(folder))
            self.assertFalse(webgui.run(layout, ROOT, launcher=lambda url, profile: None))

    def test_a_page_that_never_connects_falls_back_after_the_timeout(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            layout = SimpleNamespace(state_dir=Path(folder))
            self.assertFalse(webgui.run(layout, ROOT, launcher=lambda url, profile: object(), first_poll_timeout=0.5))


if __name__ == "__main__":
    unittest.main()
