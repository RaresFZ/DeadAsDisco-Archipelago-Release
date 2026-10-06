import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from archipelago.dadap import capabilities, core, pins, play, session
from archipelago.dadap.fsutil import SafetyError, manifest, read_json
from archipelago.dadap.layout import Layout

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "archipelago/apworld/dead_as_disco/catalog.json").read_text())
# Private fresh-profile save from the live observation; the test is skipped on machines without it.
FRESH = Path(os.environ.get("DAD_FRESH_SAVE") or ROOT / "artifacts/private-saves/fresh/Saved")

# Minimal stand-in with the keys/hooks customize_settings edits (the real UE4SS template is a downloaded binary archive).
SETTINGS_TEMPLATE = "[General]\n" + "".join(f"{key} = 1\n" for key in (
    "ModsFolderPath", "ControllingModsTxt", "ConsoleEnabled", "GuiConsoleEnabled", "GuiConsoleVisible", "EnableHotReloadSystem",
    "EnableAutoReloadingLuaMods", "UseCache", "bUseUObjectArrayCache", "bForceGUObjectArrayForIteration", "DoEarlyScan",
    "LoadAllAssetsBeforeDumpingObjects", "LoadAllAssetsBeforeGeneratingCXXHeaders", "RenderMode", "EnableDumping",
    "FullMemoryDump")) + "".join(f"{hook} = 1\n" for hook in (
    "HookProcessInternal", "HookProcessLocalScriptFunction", "HookInitGameState", "HookLoadMap",
    "HookCallFunctionByNameWithArguments", "HookBeginPlay", "HookEndPlay", "HookLocalPlayerExec", "HookAActorTick",
    "HookEngineTick", "HookGameViewportClientTick", "HookUObjectProcessEvent", "HookProcessConsoleExec", "HookUStructLink"))


class FakeProbe:
    def __init__(self):
        self.pid = 4321
        self.steam = False

    def game_running(self):
        return False

    def steam_running(self):
        return self.steam

    def game_pid(self):
        return self.pid

    def external_tcp(self, pid):
        return []


def slot_data(**options):
    return {"content_sha256": play.content_hash(CATALOG), "location_ids": [r["id"] for r in CATALOG["locations"]],
            "options": options, "required_capabilities": ["ownership"], "death_link": False}


@unittest.skipUnless(FRESH.is_dir(), "private fresh-profile observation save absent")
class PlayFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp.name)
        game, local = root / "game", root / "local"
        (game / "Pagoda/Binaries/Win64").mkdir(parents=True)
        (game / "Pagoda/Binaries/Win64" / pins.EXE_NAME).write_bytes(b"exe")
        saved = local / "Pagoda/Saved"
        (saved / "SaveGames").mkdir(parents=True)
        (saved / "SaveGames/PagodaPT_M_0.sav").write_bytes(b"REAL PLAYER PROGRESS")
        self.layout = Layout(game, saved, local / "DeadAsDiscoAP")
        self.layout.core_dir.mkdir(parents=True)
        (self.layout.core_dir / "dwmapi.dll").write_bytes(b"proxy")
        (self.layout.core_dir / "UE4SS.dll").write_bytes(b"core")
        (self.layout.core_dir / "UE4SS-settings.template.ini").write_text(SETTINGS_TEMPLATE, encoding="utf-8")
        self.original = manifest(saved)
        self.patch = (pins.PROXY_SHA256, pins.EXE_SHA256)
        pins.PROXY_SHA256, pins.EXE_SHA256 = hashlib.sha256(b"proxy").hexdigest(), hashlib.sha256(b"exe").hexdigest()
        # A pristine-looking profile: only a tutorial-stage save exists.
        profile = self.layout.profile_dir("p") / "Saved/SaveGames"
        profile.mkdir(parents=True)
        for name in ("PagodaPT_M_0.sav", "PagodaGP_Main.sav"):
            shutil.copyfile(FRESH / "SaveGames" / name, profile / name)
        # The observation save already has Hemlock cleared, so bind it explicitly (bind-refusal is tested separately).
        import hashlib as _h
        from archipelago.dadap.fsutil import write_json
        generation = _h.sha256(b"SEED123:0:1").hexdigest()[:24]
        write_json(self.layout.profile_dir("p") / "binding.json", {"seed": "SEED123", "team": 0, "player": 1, "generation": generation,
                   "game_slot": "PagodaPT_M_0", "content_sha256": play.content_hash(CATALOG)})
        self.cert = root / "capabilities.json"
        self.cert.write_text(json.dumps({"status": "verified-protected-passive-grant-cold", "max_health_delta": 10,
                                         "duplicate_health_delta": 0, "sources": {}}))
        self.events = []

    def tearDown(self):
        pins.PROXY_SHA256, pins.EXE_SHA256 = self.patch
        self.temp.cleanup()

    def run_play(self, info=None, features=None, profile="p"):
        layout = self.layout
        events = self.events
        info = info or {"seed": "SEED123", "team": 0, "player": 1, "slot_data": slot_data()}

        class Process:
            pid = 99
            def poll(self):
                return None
            def terminate(self):
                events.append("client-terminated")
            def wait(self, timeout=None):
                pass

        def launch_runner(command, cwd):
            events.append(("launch", command))
            assert layout.proxy_target.read_bytes() == b"proxy"
            core_dir = Path(command.split("--ue4ss-path ")[1].strip('"')).parent
            (core_dir / "UE4SS.log").write_text("[Lua] [APBridge] LOADED grants-disabled\n")
            return Process()

        def client_runner(command, cwd):
            events.append(("client", command))
            return Process()

        def wait_game(probe, log=None):
            events.append("game-ran")
            # The game writes progress into the AP profile while the real saves are parked.
            (layout.saved_dir / "SaveGames/PagodaPT_M_0.sav").write_bytes((layout.saved_dir / "SaveGames/PagodaPT_M_0.sav").read_bytes())
            (layout.saved_dir / "SaveGames/marker.txt").write_text("ap progress")

        return play.play(layout, profile, "localhost:38281", "Slot", None, features=features, certificate=self.cert,
                         install_root=ROOT, probe=FakeProbe(), launch_runner=launch_runner, client_runner=client_runner,
                         preflight_fn=lambda: info, wait_game=wait_game, mod_wait=lambda *a, **k: None, guard=lambda *a, **k: None, log=lambda m: None, )

    def test_full_session_stages_binds_launches_and_restores(self):
        sid = self.run_play()
        self.assertEqual(manifest(self.layout.saved_dir), self.original)
        self.assertFalse(self.layout.proxy_target.exists())
        self.assertIsNone(session.active_session(self.layout))
        sdir = self.layout.session_dir(sid)
        protection = read_json(sdir / "ap-protection.json")
        self.assertEqual(protection["game_slot"], "PagodaPT_M_0")
        self.assertTrue(protection["inprocess_decoder"])
        self.assertTrue((sdir / "ap-launch.lease").read_text().strip() == protection["launch_token"])
        self.assertTrue((self.layout.profile_dir("p") / "Saved/SaveGames/marker.txt").is_file())
        binding = read_json(self.layout.profile_dir("p") / "binding.json")
        self.assertEqual(binding["seed"], "SEED123")
        launched = [e for e in self.events if isinstance(e, tuple) and e[0] == "launch"][0][1]
        self.assertIn("-nosteam", launched)
        client = [e for e in self.events if isinstance(e, tuple) and e[0] == "client"][0][1]
        self.assertIn("--protection", client)
        self.assertIn("client-terminated", self.events)
        config = (sdir / "core/Mods/APBridge/Scripts/ap-config.lua").read_text()
        self.assertIn("[\"productionEnabled\"]=true", config)
        self.assertIn("[\"nodeLocationsValidated\"]=true", config)  # validated mechanisms are production, not test
        self.assertIn("[\"nodeLocationsTest\"]=false", config)
        try:
            from lupa.lua54 import LuaRuntime
        except ImportError:
            return  # the generated config is also syntax-checked by the Lua fixtures when lupa is installed
        LuaRuntime().execute(f"local c=dofile([[{sdir / 'core/Mods/APBridge/Scripts/ap-config.lua'}]]);"
                             "assert(c.generation and c.launchToken and c.contexts and c.boundContextCount==3)")

    def test_profile_is_bound_to_one_slot_forever(self):
        self.run_play()
        other = {"seed": "OTHER", "team": 0, "player": 1, "slot_data": slot_data()}
        with self.assertRaises(SafetyError):
            self.run_play(info=other)
        self.assertEqual(manifest(self.layout.saved_dir), self.original)
        self.assertIsNone(session.active_session(self.layout))

    def test_wrong_world_and_unvalidated_capability_are_refused_before_touching_saves(self):
        bad = slot_data()
        bad["content_sha256"] = "0" * 64
        with self.assertRaises(SafetyError):
            self.run_play(info={"seed": "SEED123", "team": 0, "player": 1, "slot_data": bad})
        need = slot_data()
        need["required_capabilities"] = ["ownership", "node-interaction"]
        saved = dict(capabilities.VALIDATED)
        capabilities.VALIDATED["node-interaction"] = False
        try:
            with self.assertRaises(SafetyError):
                self.run_play(info={"seed": "SEED123", "team": 0, "player": 1, "slot_data": need})
            self.assertEqual(manifest(self.layout.saved_dir), self.original)
            self.assertIsNone(session.active_session(self.layout))
            # Protected test mode enables the unvalidated family explicitly.
            sid = self.run_play(info={"seed": "SEED123", "team": 0, "player": 1, "slot_data": need}, features=["node-interaction"])
            config = (self.layout.session_dir(sid) / "core/Mods/APBridge/Scripts/ap-config.lua").read_text()
            self.assertIn("[\"nodeLocationsTest\"]=true", config)
        finally:
            capabilities.VALIDATED.update(saved)

    def test_one_click_flow_creates_the_profile_via_the_tutorial_then_continues_into_ap(self):
        from unittest import mock
        name = play.derive_profile("Slot", "SEED123")
        self.assertEqual(name, "Slot-SEED123")
        # Pre-bind the derived profile (the observation save has progress; binding rules are tested separately).
        import hashlib as _h
        from archipelago.dadap.fsutil import write_json
        generation = _h.sha256(b"SEED123:0:1").hexdigest()[:24]
        write_json(self.layout.profile_dir(name) / "binding.json", {"seed": "SEED123", "team": 0, "player": 1,
                   "generation": generation, "game_slot": "PagodaPT_M_0", "content_sha256": play.content_hash(CATALOG)})
        calls = []

        def fake_tutorial(layout, profile, log=print):
            calls.append(profile)
            target = layout.profile_dir(profile) / "Saved/SaveGames"
            target.mkdir(parents=True)
            for save in ("PagodaPT_M_0.sav", "PagodaGP_Main.sav"):
                shutil.copyfile(FRESH / "SaveGames" / save, target / save)

        info = {"seed": "SEED123", "team": 0, "player": 1, "slot_data": slot_data()}
        with mock.patch("archipelago.dadap.cli.run_vanilla", fake_tutorial):
            sid = self.run_play(info=info, profile=None)
        self.assertEqual(calls, [name])          # the tutorial ran exactly once, for the derived profile
        self.assertTrue((self.layout.session_dir(sid) / "ap-launch.lease").is_file())  # and AP continued without a second click
        with mock.patch("archipelago.dadap.cli.run_vanilla", fake_tutorial):
            self.run_play(info=info, profile=None)
        self.assertEqual(calls, [name])          # second run resumes: no tutorial
        self.assertEqual(manifest(self.layout.saved_dir), self.original)

    def test_profile_with_game_progress_cannot_be_bound(self):
        profile = self.layout.profile_dir("q") / "Saved/SaveGames"
        profile.mkdir(parents=True)
        # The observation profile completed Hemlock, so it is not pristine.
        # Use a profile whose binding does not exist yet.
        src = Path(self.temp.name) / "src"
        shutil.copytree(FRESH, src)
        shutil.copytree(src / "SaveGames", profile, dirs_exist_ok=True)
        # The fixture save has Hemlock complete, so binding must refuse.
        # (The 'p' profile in setUp is the same save; bind refusal is therefore the expected outcome.)
        with self.assertRaises(SafetyError):
            self.run_play(profile="q")
        self.assertEqual(manifest(self.layout.saved_dir), self.original)

    def test_crash_during_play_still_restores_and_removes_the_proxy(self):
        layout = self.layout

        def boom(*a, **k):
            raise RuntimeError("client crashed")

        with self.assertRaises(RuntimeError):
            play.play(layout, "p", "localhost:1", "Slot", None, certificate=self.cert, install_root=ROOT, probe=FakeProbe(),
                      launch_runner=lambda command, cwd: boom(), client_runner=boom,
                      preflight_fn=lambda: {"seed": "SEED123", "team": 0, "player": 1, "slot_data": slot_data()},
                      wait_game=lambda *a, **k: None, mod_wait=lambda *a, **k: None, guard=lambda *a, **k: None, log=lambda m: None, )
        self.assertEqual(manifest(layout.saved_dir), self.original)
        self.assertFalse(layout.proxy_target.exists())
        self.assertIsNone(session.active_session(layout))


if __name__ == "__main__":
    unittest.main()
