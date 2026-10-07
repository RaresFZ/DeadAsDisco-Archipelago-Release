import hashlib
import tempfile
import unittest
from pathlib import Path

from archipelago.dadap import doctor, pins, session
from archipelago.dadap.fsutil import SafetyError
from archipelago.dadap.layout import Layout


class Probe:
    def game_running(self):
        return False

    def steam_running(self):
        return False


def install(root, contents):
    game = Path(root) / "game"
    (game / "Pagoda" / "Binaries" / "Win64").mkdir(parents=True)
    (game / "Pagoda" / "Binaries" / "Win64" / pins.EXE_NAME).write_bytes(contents)
    return Layout(game, Path(root) / "local" / "Pagoda" / "Saved", Path(root) / "local" / "DeadAsDiscoAP")


class SupportedBuilds(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.saved = (pins.EXE_SHA256, dict(pins.PREVIOUS_BUILDS))

    def tearDown(self):
        pins.EXE_SHA256, pins.PREVIOUS_BUILDS = self.saved
        self.temp.cleanup()

    def pin(self, current, previous):
        pins.EXE_SHA256 = hashlib.sha256(current).hexdigest()
        pins.PREVIOUS_BUILDS = {hashlib.sha256(previous).hexdigest(): "the previous build"}

    def test_current_and_previous_builds_are_accepted(self):
        self.pin(b"new", b"old")
        for contents in (b"new", b"old"):
            layout = install(Path(self.temp.name) / contents.decode(), contents)
            self.assertEqual([r for r in doctor.diagnose(layout, Probe()) if r[1] == "game build"][0][0], "OK")
            state = session.begin(layout, "p", Probe(), sid="s1")
            self.assertEqual(state["status"], "isolated")
            session.restore(layout, Probe())

    def test_any_other_build_is_refused_and_names_what_is_supported(self):
        self.pin(b"new", b"old")
        layout = install(self.temp.name, b"something else")
        with self.assertRaises(SafetyError) as caught:
            session.begin(layout, "p", Probe(), sid="s1")
        self.assertIn(pins.BUILD, str(caught.exception))
        self.assertIn("the previous build", str(caught.exception))
        self.assertEqual([r for r in doctor.diagnose(layout, Probe()) if r[1] == "game build"][0][0], "FAIL")

    def test_pinned_hashes_are_well_formed_and_distinct(self):
        hashes = pins.supported_exe_hashes()
        self.assertEqual(len(hashes), 1 + len(pins.PREVIOUS_BUILDS))
        for value in hashes:
            self.assertRegex(value, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
