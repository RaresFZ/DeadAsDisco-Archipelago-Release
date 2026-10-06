import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from archipelago.dadap import pins, session
from archipelago.dadap.fsutil import SafetyError, manifest
from archipelago.dadap.layout import Layout


class FakeProbe:
    def __init__(self):
        self.game = False
        self.steam = False

    def game_running(self):
        return self.game

    def steam_running(self):
        return self.steam


def build(root):
    root = Path(root)
    game, local = root / "game", root / "local"
    (game / "Pagoda" / "Binaries" / "Win64").mkdir(parents=True)
    (game / "Pagoda" / "Binaries" / "Win64" / pins.EXE_NAME).write_bytes(b"exe")
    saved = local / "Pagoda" / "Saved"
    (saved / "SaveGames").mkdir(parents=True)
    (saved / "Config" / "Windows").mkdir(parents=True)
    (saved / "SaveGames" / "PagodaPT_M_0.sav").write_bytes(b"REAL PROGRESS")
    (saved / "SaveGames" / "SharedGameSettings.sav").write_bytes(b"settings")
    (saved / "SaveGames" / "FTUE.sav").write_bytes(b"ftue")
    (saved / "Config" / "Windows" / "GameUserSettings.ini").write_text("gfx")
    layout = Layout(game, saved, local / "DeadAsDiscoAP")
    layout.core_dir.mkdir(parents=True)
    (layout.core_dir / "dwmapi.dll").write_bytes(b"proxy")
    return layout


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.layout = build(self.temp.name)
        self.probe = FakeProbe()
        self.original = manifest(self.layout.saved_dir)
        self.proxy_hash = hashlib.sha256(b"proxy").hexdigest()
        self.patch = (pins.PROXY_SHA256, pins.EXE_SHA256)
        pins.PROXY_SHA256 = self.proxy_hash
        pins.EXE_SHA256 = hashlib.sha256(b"exe").hexdigest()

    def tearDown(self):
        pins.PROXY_SHA256, pins.EXE_SHA256 = self.patch
        self.temp.cleanup()

    def test_round_trip_restores_originals_and_keeps_profile(self):
        state = session.begin(self.layout, "p1", self.probe, sid="s1")
        saved = self.layout.saved_dir
        self.assertEqual(state["status"], "isolated")
        self.assertTrue(state["profile_fresh"])
        # A fresh profile receives preferences only, never progression or first-run flags.
        self.assertFalse((saved / "SaveGames" / "PagodaPT_M_0.sav").exists())
        self.assertFalse((saved / "SaveGames" / "FTUE.sav").exists())
        self.assertEqual((saved / "SaveGames" / "SharedGameSettings.sav").read_bytes(), b"settings")
        (saved / "SaveGames" / "PagodaPT_M_0.sav").write_bytes(b"AP PROGRESS")
        closed = session.restore(self.layout, self.probe)
        self.assertEqual(closed["status"], "restored")
        self.assertEqual(manifest(self.layout.saved_dir), self.original)
        self.assertIsNone(session.active_session(self.layout))
        profile = self.layout.profile_dir("p1") / "Saved" / "SaveGames" / "PagodaPT_M_0.sav"
        self.assertEqual(profile.read_bytes(), b"AP PROGRESS")
        # The backup is an independent verified copy.
        self.assertEqual(manifest(self.layout.backup_dir("s1")), self.original)
        # Second session continues the same profile and rotates, never deletes, the previous one.
        again = session.begin(self.layout, "p1", self.probe, sid="s2")
        self.assertFalse(again["profile_fresh"])
        self.assertEqual((self.layout.saved_dir / "SaveGames" / "PagodaPT_M_0.sav").read_bytes(), b"AP PROGRESS")
        (self.layout.saved_dir / "SaveGames" / "PagodaPT_M_0.sav").write_bytes(b"MORE")
        session.restore(self.layout, self.probe)
        self.assertEqual(manifest(self.layout.saved_dir), self.original)
        self.assertTrue((self.layout.profile_dir("p1") / "Saved.prev-s2").is_dir())
        self.assertEqual((self.layout.profile_dir("p1") / "Saved.prev-s2" / "SaveGames" / "PagodaPT_M_0.sav").read_bytes(), b"AP PROGRESS")

    def test_refuses_running_game_steam_and_unfinished_session(self):
        self.probe.game = True
        with self.assertRaises(SafetyError):
            session.begin(self.layout, "p", self.probe, sid="a")
        self.probe.game, self.probe.steam = False, True
        with self.assertRaises(SafetyError):
            session.begin(self.layout, "p", self.probe, sid="a")
        self.probe.steam = False
        self.assertEqual(manifest(self.layout.saved_dir), self.original)
        session.begin(self.layout, "p", self.probe, sid="a")
        with self.assertRaises(SafetyError):
            session.begin(self.layout, "p", self.probe, sid="b")
        self.probe.game = True
        with self.assertRaises(SafetyError):
            session.restore(self.layout, self.probe)
        self.probe.game = False
        session.restore(self.layout, self.probe)
        self.assertEqual(manifest(self.layout.saved_dir), self.original)

    def test_unsupported_build_is_refused_before_any_change(self):
        self.layout.exe.write_bytes(b"patched")
        with self.assertRaises(SafetyError):
            session.begin(self.layout, "p", self.probe, sid="a")
        self.assertEqual(manifest(self.layout.saved_dir), self.original)
        self.assertFalse(self.layout.pointer.exists())

    def test_crash_at_every_step_recovers_originals(self):
        saved = self.layout.saved_dir
        scratch = self.layout.state_dir / "scratch"
        scratch.mkdir(parents=True)
        def pending(sid):
            state = session._load(self.layout, sid)
            state["status"] = "isolation-pending"
            session._save(self.layout, state)
        # Crash after the intent record, before the rename: originals still live.
        session.begin(self.layout, "p", self.probe, sid="c")
        session._rename(saved, scratch / "test-tree-c")
        session._rename(self.layout.parked_dir("c"), saved)
        pending("c")
        session.restore(self.layout, self.probe)
        self.assertEqual(manifest(saved), self.original)
        # Crash after parking, before the profile was placed.
        session.begin(self.layout, "p", self.probe, sid="d")
        session._rename(saved, scratch / "test-tree-d")
        pending("d")
        session.restore(self.layout, self.probe)
        self.assertEqual(manifest(saved), self.original)
        # Crash with both trees present and a half-written profile.
        session.begin(self.layout, "p", self.probe, sid="e")
        pending("e")
        session.restore(self.layout, self.probe)
        self.assertEqual(manifest(saved), self.original)
        self.assertTrue((self.layout.session_dir("e") / "partial-active").is_dir())

    def test_tampered_parked_originals_are_never_restored_over(self):
        session.begin(self.layout, "p", self.probe, sid="t")
        (self.layout.parked_dir("t") / "SaveGames" / "PagodaPT_M_0.sav").write_bytes(b"tampered")
        with self.assertRaises(SafetyError):
            session.restore(self.layout, self.probe)
        # Nothing was moved or deleted: both trees and the pointer survive for inspection.
        self.assertTrue(self.layout.parked_dir("t").is_dir())
        self.assertTrue(self.layout.pointer.exists())

    def test_proxy_install_is_exclusive_and_removed_only_if_unchanged(self):
        session.begin(self.layout, "p", self.probe, sid="x")
        session.install_proxy(self.layout, "x")
        self.assertEqual(self.layout.proxy_target.read_bytes(), b"proxy")
        with self.assertRaises(SafetyError):
            session.install_proxy(self.layout, "x")
        self.layout.proxy_target.write_bytes(b"someone else")
        with self.assertRaises(SafetyError):
            session.restore(self.layout, self.probe)
        self.assertTrue(self.layout.proxy_target.exists())
        self.layout.proxy_target.write_bytes(b"proxy")
        session.restore(self.layout, self.probe)
        self.assertFalse(self.layout.proxy_target.exists())
        self.assertEqual(manifest(self.layout.saved_dir), self.original)

    def test_forbidden_runtime_files_in_game_directory_refuse_proxy(self):
        session.begin(self.layout, "p", self.probe, sid="f")
        (self.layout.bin_dir / "Mods").mkdir()
        with self.assertRaises(SafetyError):
            session.install_proxy(self.layout, "f")
        session.restore(self.layout, self.probe)

    def test_no_pre_existing_saves(self):
        import shutil
        shutil.move(str(self.layout.saved_dir), str(self.layout.state_dir.parent / "elsewhere"))
        state = session.begin(self.layout, "p", self.probe, sid="n")
        self.assertFalse(state["originals_present"])
        (self.layout.saved_dir / "SaveGames").mkdir()
        (self.layout.saved_dir / "SaveGames" / "new.sav").write_bytes(b"x")
        session.restore(self.layout, self.probe)
        self.assertFalse(self.layout.saved_dir.exists())
        self.assertTrue((self.layout.profile_dir("p") / "Saved" / "SaveGames" / "new.sav").is_file())

    def test_launch_command_is_offline_and_names_the_isolated_core(self):
        session.begin(self.layout, "p", self.probe, sid="l")
        seen = {}
        class Fake:
            pid = 4242
        def runner(command, cwd):
            seen.update(command=command, cwd=cwd);return Fake()
        session.launch(self.layout, "l", core=self.layout.state_dir / "core", runner=runner)
        self.assertIn("-nosteam -httpproxy=127.0.0.1:1", seen["command"])
        self.assertIn("--ue4ss-path", seen["command"])
        self.assertEqual(session._load(self.layout, "l")["launch"]["pid"], 4242)
        session.restore(self.layout, self.probe)


class DoctorTests(unittest.TestCase):
    def test_doctor_reports_each_condition_without_touching_anything(self):
        from archipelago.dadap import doctor
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            layout = build(folder)
            before = manifest(layout.saved_dir)
            probe = FakeProbe()
            levels = {check: level for level, check, _ in doctor.diagnose(layout, probe)}
            self.assertEqual(levels["game build"], "FAIL")      # fake exe is not the pinned build
            self.assertEqual(levels["UE4SS core"], "FAIL")      # fake core is not the pinned build
            self.assertEqual(levels["session"], "OK")
            self.assertEqual(levels["game folder"], "OK")
            probe.game = True
            self.assertEqual({c: l for l, c, _ in doctor.diagnose(layout, probe)}["processes"], "WARN")
            layout.proxy_target.write_bytes(b"x")
            self.assertEqual({c: l for l, c, _ in doctor.diagnose(layout, FakeProbe())}["game folder"], "FAIL")
            self.assertEqual(manifest(layout.saved_dir), before)  # strictly read-only


class UninstallTests(unittest.TestCase):
    def test_uninstall_keeps_profiles_and_refuses_with_open_session(self):
        from archipelago.dadap import cli
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            layout = build(folder)
            layout.state_dir = layout.state_dir.parent / "DeadAsDiscoAP"
            (layout.state_dir / "profiles/p/Saved").mkdir(parents=True)
            (layout.state_dir / "sessions/s").mkdir(parents=True)
            args = ["--game-dir", str(layout.game_dir), "--state-dir", str(layout.state_dir), "--saved-dir", str(layout.saved_dir)]
            self.assertEqual(cli.main(args + ["uninstall"]), 0)
            self.assertTrue((layout.state_dir / "profiles/p").is_dir())
            self.assertFalse((layout.state_dir / "core").exists())
            self.assertEqual(cli.main(args + ["uninstall", "--purge-all"]), 2)  # needs --yes
            (layout.state_dir / "current-session.json").write_text('{"sid": "x"}')
            self.assertEqual(cli.main(args + ["uninstall", "--purge-all", "--yes"]), 2)  # open session
            (layout.state_dir / "current-session.json").unlink()
            self.assertEqual(cli.main(args + ["uninstall", "--purge-all", "--yes"]), 0)
            self.assertFalse(layout.state_dir.exists())
            self.assertTrue((layout.saved_dir / "SaveGames/PagodaPT_M_0.sav").is_file())  # real saves never touched


class WaitTests(unittest.TestCase):
    def test_relaunch_handoff_gap_is_not_an_exit(self):
        states = iter([False, False] + [True] * 3 + [False] * 5 + [True] * 4 + [False] * 100)
        class Probe:
            def game_running(self):
                return next(states)
        clock = {"t": 0.0}
        ticks = []
        session.wait_for_game(Probe(), poll=2.0, settle=20, sleep=lambda s: ticks.append(s), log=ticks.append)
        # 2 not-yet-started + 3 up + 5 handoff gap (10 s < settle) + 4 up + 10 settle polls
        self.assertGreaterEqual(len([x for x in ticks if x == 2.0]), 2 + 3 + 5 + 4 + 9)


if __name__ == "__main__":
    unittest.main()


class GuiSmokeTests(unittest.TestCase):
    def test_window_builds_and_check_install_runs_without_touching_anything(self):
        try:
            import tkinter
            root = tkinter.Tk()
        except Exception:
            self.skipTest("no display available")
        root.withdraw()
        try:
            from archipelago.dadap.gui import App
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
                layout = build(folder)
                before = manifest(layout.saved_dir)
                app = App(root, layout=layout, install_root=Path(folder))
                app.on_doctor()
                import time
                deadline = time.monotonic() + 15
                text = ""
                while time.monotonic() < deadline and "Check install: done" not in text:
                    root.update()
                    time.sleep(0.05)
                    text = app.output.get("1.0", "end")
                self.assertIn("game build", text)
                self.assertIn("Check install: done", text)
                self.assertEqual(manifest(layout.saved_dir), before)
        finally:
            root.destroy()
