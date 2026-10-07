import json
import shutil
import struct
import subprocess
import unittest
from pathlib import Path

from archipelago.dadap import gvas

ROOT = Path(__file__).resolve().parents[2]
SAVES = [
    ROOT / "artifacts/private-saves/a/SaveGames",
    ROOT / "artifacts/private-saves/b/SaveGames",
    ROOT / "artifacts/private-saves/c/SaveGames",  # written by game build 25772865 (engine changelist 33836)
    ROOT / "artifacts/private-saves/d/SaveGames",
]


def python_summary(path):
    save = gvas.read_tagged_save(path.read_bytes(), path.name)
    scopes = [{"scope": s["scope"], "context": s["context"],
               "variables": {gvas.tag(v["key"]): gvas.leaves(v["value"]) for v in s["variables"]}}
              for s in gvas.saved_scopes(save)]
    out = {"scopes": scopes}
    if "PT" in path.name:
        data = gvas.field(save["properties"], "PlayerData")
        out["owned"] = sorted(gvas.tag(x) for x in gvas.field(data, "OwnedUpgrades"))
        out["equipped"] = sorted(gvas.tag(x) for x in gvas.field(data, "EquippedUpgrades"))
    return out


def minimal_save(changelist, save_class="/Script/Pagoda.PagodaPlaythroughSaveGame"):
    """An empty but well-formed GVAS save stamped with the given engine changelist (no game data)."""
    def fstring(text):
        raw = text.encode() + b"\0"
        return struct.pack("<i", len(raw)) + raw
    return (b"GVAS" + struct.pack("<iii", 3, 522, 1018) + struct.pack("<HHH", 5, 7, 4) + struct.pack("<I", changelist)
            + fstring("++brainjar+release") + struct.pack("<ii", 3, 0) + fstring(save_class)
            + b"\0" + fstring("None") + struct.pack("<I", 0))


class SaveHeaderTests(unittest.TestCase):
    def test_saves_from_both_game_builds_are_readable(self):
        # 33649 = Steam build 25647873, 33836 = build 25772865 (the game rewrote every save with the new stamp).
        for changelist in (33649, 33836):
            self.assertEqual(gvas.read_tagged_save(minimal_save(changelist), "PagodaPT_M_0.sav")["properties"], [], changelist)

    def test_an_unknown_engine_build_is_refused(self):
        with self.assertRaises(gvas.SaveError):
            gvas.read_tagged_save(minimal_save(99999), "PagodaPT_M_0.sav")


class GvasParityTests(unittest.TestCase):
    def test_python_decoder_matches_reference_on_real_saves(self):
        if not shutil.which("node"):
            self.skipTest("node unavailable")
        checked = 0
        for folder in SAVES:
            for name in ("PagodaGP_Main.sav", "PagodaPT_M_0.sav"):
                path = folder / name
                if not path.is_file():
                    continue
                reference = json.loads(subprocess.run(["node", str(ROOT / "tools/dump-save-summary.mjs"), str(path)],
                                                      capture_output=True, text=True, check=True).stdout)
                self.assertEqual(python_summary(path), reference, str(path))
                checked += 1
        if not checked:
            self.skipTest("private protected saves absent")

    def test_rejects_wrong_or_truncated_saves(self):
        with self.assertRaises(gvas.SaveError):
            gvas.read_tagged_save(b"not a save", "PagodaPT_M_0.sav")
        for folder in SAVES:
            path = folder / "PagodaPT_M_0.sav"
            if path.is_file():
                data = path.read_bytes()
                with self.assertRaises(gvas.SaveError):
                    gvas.read_tagged_save(data[:-9], path.name)
                with self.assertRaises(gvas.SaveError):
                    gvas.read_tagged_save(data, "PagodaGP_Main.sav")
                return
        self.skipTest("private protected saves absent")


if __name__ == "__main__":
    unittest.main()
