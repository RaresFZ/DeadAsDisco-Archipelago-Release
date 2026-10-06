import json
import shutil
import subprocess
import unittest
from pathlib import Path

from archipelago.dadap import gvas

ROOT = Path(__file__).resolve().parents[2]
SAVES = [
    ROOT / "artifacts/private-saves/a/SaveGames",
    ROOT / "artifacts/private-saves/b/SaveGames",
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
