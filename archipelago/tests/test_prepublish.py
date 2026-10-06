import json
import tempfile
import unittest
from pathlib import Path

from archipelago.client.production import publish_from_ledger
from archipelago.client.reconciliation import Binding, Ledger

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "archipelago/apworld/dead_as_disco/catalog.json").read_text())


class PrepublishTests(unittest.TestCase):
    def test_resumed_profile_is_entitled_before_the_game_starts(self):
        skill = next(r for r in CATALOG["items"] if r["mechanism"] == "owned-upgrade")
        access = next(r for r in CATALOG["items"] if r["mechanism"] == "mission-access")
        node = next(r for r in CATALOG["locations"] if r["predicate"] == "node-interaction")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            ledger = Ledger(str(root / "ledger.sqlite"), Binding("seed", 0, 1, "gen", "PagodaPT_M_0", content_hash="h"))
            ledger.receive(0, [[skill["id"], 1, 1, 0], [access["id"], 2, 1, 0]])
            ledger.observe({node["id"]})
            ledger.close()
            protection = {"entitlement_file": str(root / "run/ent.txt"), "access_file": str(root / "run/acc.txt"),
                          "completed_nodes_file": str(root / "run/nodes.txt"), "node_items": [{"id": node["id"], "tag": node["item_tag"]}]}
            summary = publish_from_ledger(str(root / "ledger.sqlite"), CATALOG, protection)
            self.assertEqual(summary, {"entitled": 1, "access": 1, "nodes": 1})
            self.assertEqual((root / "run/ent.txt").read_text(), skill["tag"] + "\n")
            self.assertEqual((root / "run/acc.txt").read_text(), access["tag"] + "\n")
            self.assertEqual((root / "run/nodes.txt").read_text(), str(node["id"]) + "\n")

    def test_first_ever_session_publishes_empty_files(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            protection = {"entitlement_file": str(root / "e.txt"), "access_file": str(root / "a.txt")}
            publish_from_ledger(str(root / "missing.sqlite"), CATALOG, protection)
            self.assertEqual((root / "e.txt").read_text(), "")


if __name__ == "__main__":
    unittest.main()


class NetworkGuardTests(unittest.TestCase):
    def test_brief_startup_connections_pass_but_persistent_ones_are_refused(self):
        from archipelago.dadap import play
        from archipelago.dadap.fsutil import SafetyError

        class Probe:
            def __init__(self, samples):
                self.samples = iter(samples)
            def game_pid(self):
                return 1
            def external_tcp(self, pid):
                return next(self.samples)

        play.network_guard(Probe([["1.2.3.4:443"], [], []]), sleep=lambda s: None, log=lambda m: None)
        with self.assertRaises(SafetyError):
            play.network_guard(Probe([["1.2.3.4:443"]] * 1000), timeout=0, sleep=lambda s: None, log=lambda m: None)


class ScoutingTests(unittest.TestCase):
    def test_node_shop_window_lists_each_node_and_survives_unknown_items(self):
        from types import SimpleNamespace
        from archipelago.client.scouting import format_scouts, node_location_ids, write_scouts
        nodes = node_location_ids(CATALOG, {r["id"] for r in CATALOG["locations"]})
        self.assertGreaterEqual(len(nodes), 40)
        info = {nodes[0]: SimpleNamespace(item=7, player=2), nodes[1]: SimpleNamespace(item=8, player=3)}
        def item_name(code, player):
            if code == 8:
                raise KeyError("unknown game")
            return "Fever Rush"
        lines = format_scouts(CATALOG, info, item_name, lambda slot: "Alice")
        self.assertEqual(len(lines), 2)
        self.assertIn("Fever Rush (for Alice)", "".join(lines))
        self.assertIn("item #8", "".join(lines))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            target = Path(folder) / "sub" / "nodes.txt"
            write_scouts(target, lines)
            self.assertIn("skill-tree node holds", target.read_text())
