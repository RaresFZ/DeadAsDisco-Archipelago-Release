import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from archipelago.dadap import saved_state

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "archipelago/apworld/dead_as_disco/catalog.json"
SAVES = [ROOT / "artifacts/private-saves/a/SaveGames/PagodaPT_M_0.sav",
         ROOT / "artifacts/private-saves/b/SaveGames/PagodaPT_M_0.sav"]


class SavedStateTests(unittest.TestCase):
    def test_predicates_reject_receipts_and_aliasing(self):
        self.assertFalse(saved_state.completed({"predicate": "node-interaction", "id": 1}, {"": "4"}))
        self.assertTrue(saved_state.completed({"predicate": "node-interaction", "id": 1}, None, {1}))
        row = {"predicate": "counter-threshold", "path": "/Easy Stats/Completion Count", "threshold": 1}
        self.assertFalse(saved_state.completed(row, {"/Hard Stats/Completion Count": "1"}))
        self.assertFalse(saved_state.completed({"predicate": "highest-stars", "threshold": 5}, {"/Normal Stats/Highest Score": "99999999"}))
        self.assertFalse(saved_state.completed({"predicate": "challenge-completion"}, {"/Highest Star Rating": "5", "/Completion Count": "0"}))
        self.assertTrue(saved_state.completed({"predicate": "purchased"}, {"": "4"}))
        self.assertFalse(saved_state.completed({"predicate": "purchased"}, {"": "3"}))
        self.assertFalse(saved_state.completed({"predicate": "purchased"}, None))

    def test_picked_up_collectible_counts_before_it_is_bought(self):
        row = {"predicate": "purchased", "alt_tag": "Progression.PickupItem.X", "alt_threshold": 1}
        self.assertFalse(saved_state.completed(row, {"": "1"}, alt_states={"": "0"}))      # not picked up yet
        self.assertTrue(saved_state.completed(row, {"": "2"}, alt_states={"": "1"}))       # picked up in the hub or a level
        self.assertTrue(saved_state.completed(row, {"": "2"}, alt_states={"": "2"}))       # turned in
        self.assertTrue(saved_state.completed(row, {"": "4"}, alt_states=None))            # bought without a pickup record
        catalog = json.loads(CATALOG.read_text())
        linked = [r for r in catalog["locations"] if r.get("alt_tag")]
        self.assertGreaterEqual(len(linked), 20)
        self.assertTrue(all(r["name"].endswith(" Collected") for r in linked))

    def test_python_decoder_matches_reference_checks_and_victory(self):
        if not shutil.which("node"):
            self.skipTest("node unavailable")
        catalog = json.loads(CATALOG.read_text())
        checked = 0
        for path in SAVES:
            if not path.is_file():
                continue
            reference = json.loads(subprocess.run(["node", str(ROOT / "tools/dump-completed.mjs"), str(path), str(CATALOG)],
                                                  capture_output=True, text=True, check=True).stdout)
            result = saved_state.decode(str(path), "PagodaPT_M_0", catalog, None)
            self.assertEqual(result["checks"], reference["checks"])
            self.assertEqual(result["victory"], reference["victory"])
            checked += 1
        if not checked:
            self.skipTest("private protected saves absent")

    def test_torn_node_journal_line_never_creates_a_check(self):
        catalog = json.loads(CATALOG.read_text())
        row = next(r for r in catalog["locations"] if r["predicate"] == "node-interaction")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            journal = Path(folder) / "j.jsonl"
            good = json.dumps({"generation": "g", "game_slot": "s", "protection_token": "t", "kind": "node-interaction",
                               "id": row["id"], "tag": row["item_tag"]})
            journal.write_text(good + "\n" + '{"generation":"g","kind":"node-inter', encoding="utf-8")
            self.assertEqual(saved_state.node_interactions(str(journal), "g", "s", "t", catalog), {row["id"]})
            journal.write_text(good.replace('"t"', '"other"') + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                saved_state.node_interactions(str(journal), "g", "s", "t", catalog)


if __name__ == "__main__":
    unittest.main()
