import json
import tempfile
import unittest
from pathlib import Path

from archipelago.dadap import gui, pins
from archipelago.dadap.layout import find_game_dir, is_game_dir, remember_game_dir, remembered_game_dir


def install(game):
    binaries = Path(game) / "Pagoda" / "Binaries" / "Win64"
    binaries.mkdir(parents=True)
    (binaries / pins.EXE_NAME).write_bytes(b"exe")
    return Path(game)


def steam(root, libraries=()):
    (root / "steamapps").mkdir(parents=True, exist_ok=True)
    entries = "".join('"%d" { "path" "%s" }\n' % (i, str(p).replace("\\", "\\\\")) for i, p in enumerate(libraries))
    (root / "steamapps" / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n' + entries + "}\n", encoding="utf-8")
    return root


class FindGameDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_steam_installed_outside_the_default_folders(self):
        game = install(steam(self.root / "F" / "Steam").joinpath("steamapps/common/Dead as Disco"))
        self.assertEqual(find_game_dir(roots=[self.root / "C" / "Program Files (x86)" / "Steam", self.root / "F" / "Steam"]), game)

    def test_library_on_another_drive_is_followed(self):
        library = self.root / "F" / "SteamLibrary"
        game = install(library / "steamapps" / "common" / "Dead as Disco")
        client = steam(self.root / "C" / "Steam", [library])
        self.assertEqual(find_game_dir(roots=[client]), game)

    def test_real_install_wins_over_an_empty_leftover_folder(self):
        leftover = self.root / "C" / "Steam" / "steamapps" / "common" / "Dead as Disco"
        leftover.mkdir(parents=True)
        library = self.root / "F" / "Lib"
        game = install(library / "steamapps" / "common" / "Dead as Disco")
        self.assertEqual(find_game_dir(roots=[steam(self.root / "C" / "Steam", [library])]), game)

    def test_remembered_folder_is_used_first(self):
        mine = install(self.root / "manual" / "Dead as Disco")
        self.assertEqual(find_game_dir(mine, roots=[]), mine)

    def test_stale_remembered_folder_is_ignored(self):
        game = install(steam(self.root / "Steam").joinpath("steamapps/common/Dead as Disco"))
        self.assertEqual(find_game_dir(self.root / "gone", roots=[self.root / "Steam"]), game)

    def test_not_found_raises(self):
        with self.assertRaises(FileNotFoundError):
            find_game_dir(roots=[self.root / "nothing-here"])

    def test_remembered_choice_round_trip_keeps_other_settings(self):
        state = self.root / "state"
        state.mkdir()
        (state / "gui-settings.json").write_text(json.dumps({"server": "host:1"}), encoding="utf-8")
        mine = install(self.root / "manual")
        remember_game_dir(state, mine)
        self.assertEqual(remembered_game_dir(state), mine)
        self.assertEqual(json.loads((state / "gui-settings.json").read_text(encoding="utf-8"))["server"], "host:1")
        self.assertTrue(is_game_dir(mine))
        self.assertIsNone(remembered_game_dir(self.root / "no-state"))


class ChooseLayout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.warnings = []

    def tearDown(self):
        self.tmp.cleanup()

    def default(self, game=None):
        if game is None:
            raise FileNotFoundError("not found")
        return type("L", (), {"state_dir": self.root / "state", "game_dir": Path(game)})()

    def warn(self, *args):
        self.warnings.append(args)

    def test_auto_detected_needs_no_prompt(self):
        layout = gui.choose_layout(None, default=lambda game=None: "auto", ask=self.fail, warn=self.fail)
        self.assertEqual(layout, "auto")

    def test_asks_for_the_folder_retries_on_a_wrong_one_and_remembers_it(self):
        good = install(self.root / "F" / "Dead as Disco")
        answers = iter([str(self.root / "wrong"), str(good)])
        layout = gui.choose_layout(None, default=self.default, ask=lambda **_: next(answers), warn=self.warn)
        self.assertEqual(layout.game_dir, good)
        self.assertEqual(len(self.warnings), 2)  # "not found" + "not a game folder"
        self.assertEqual(remembered_game_dir(self.root / "state"), good)

    def test_cancelling_the_picker_exits_cleanly(self):
        self.assertIsNone(gui.choose_layout(None, default=self.default, ask=lambda **_: "", warn=self.warn))


if __name__ == "__main__":
    unittest.main()
