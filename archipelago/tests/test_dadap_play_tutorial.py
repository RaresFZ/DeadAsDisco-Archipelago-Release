import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from archipelago.dadap import play
from archipelago.dadap.fsutil import SafetyError
from archipelago.dadap.layout import Layout
from archipelago.tests.test_dadap_play import FakeProbe, slot_data

ROOT = Path(__file__).resolve().parents[2]


class TutorialSavesTests(unittest.TestCase):
    """A profile with only one of the two tutorial save files must replay the tutorial, never abort with a CLI-only hint."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp.name)
        game, local = root / "game", root / "local"
        (game / "Pagoda/Binaries/Win64").mkdir(parents=True)
        saved = local / "Pagoda/Saved"
        (saved / "SaveGames").mkdir(parents=True)
        self.layout = Layout(game, saved, local / "DeadAsDiscoAP")
        self.layout.core_dir.mkdir(parents=True)
        (self.layout.core_dir / "UE4SS.dll").write_bytes(b"core")
        self.cert = root / "capabilities.json"
        self.cert.write_text(json.dumps({"status": "verified-protected-passive-grant-cold"}))
        self.saves = self.layout.profile_dir("p") / "Saved/SaveGames"
        self.saves.mkdir(parents=True)
        (self.saves / "PagodaPT_M_0.sav").write_bytes(b"partial tutorial save")  # the game wrote this one, never PagodaGP_Main.sav

    def tearDown(self):
        self.temp.cleanup()

    def run_play(self, messages):
        catalog = json.loads((ROOT / "archipelago/apworld/dead_as_disco/catalog.json").read_text())
        info = {"seed": "SEED", "team": 0, "player": 1, "slot_data": slot_data()}
        play.play(self.layout, "p", "localhost:38281", "Slot", None, certificate=self.cert, install_root=ROOT, probe=FakeProbe(),
                  preflight_fn=lambda: info, log=messages.append)
        return catalog

    def test_missing_global_save_replays_the_tutorial_and_reports_a_plain_message_if_still_incomplete(self):
        calls, messages = [], []
        with mock.patch("archipelago.dadap.cli.run_vanilla", lambda layout, profile, log=print: calls.append(profile)):
            with self.assertRaises(SafetyError) as caught:
                self.run_play(messages)
        self.assertEqual(calls, ["p"])                         # the tutorial was started again instead of aborting
        self.assertNotIn("newprofile", str(caught.exception))  # the one-click app has no such command
        self.assertIn("Press PLAY again", str(caught.exception))
        self.assertTrue(any("TUTORIAL" in m for m in messages))
        self.assertEqual((self.saves / "PagodaPT_M_0.sav").read_bytes(), b"partial tutorial save")  # nothing was modified


if __name__ == "__main__":
    unittest.main()
