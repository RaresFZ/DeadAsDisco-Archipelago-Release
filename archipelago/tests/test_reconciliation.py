import json
import tempfile
import time
import unittest
from pathlib import Path
from archipelago.client.reconciliation import Binding, Ledger, ReconciliationError
from archipelago.client.bridge import GameBridge


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.temp.name) / "ledger.sqlite"
        self.binding = Binding("seed", 0, 1, "isolated-generation", "PagodaPT_M_0")
        self.ledger = Ledger(self.path, self.binding)

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def test_offline_checks_survive_relaunch_and_confirmation_prevents_resend(self):
        self.ledger.observe([101, 101])
        self.ledger.close(); self.ledger = Ledger(self.path, self.binding)
        self.assertEqual(self.ledger.pending_checks([101]), {101})
        self.ledger.confirm([101])
        self.ledger.observe([101])
        self.ledger.close(); self.ledger = Ledger(self.path, self.binding)
        self.assertEqual(self.ledger.pending_checks([101]), set())
        with self.assertRaises(ReconciliationError):
            self.ledger.confirm([])

    def test_duplicate_and_full_history_do_not_duplicate_receipts(self):
        self.ledger.receive(0, [[42, 101, 1, 1]])
        self.ledger.receive(0, [[42, 101, 1, 1]])
        self.ledger.receive(1, [[43, 102, 1, 1]])
        self.ledger.receive(0, [[42, 101, 1, 1], [43, 102, 1, 1]])
        self.assertEqual([r[0] for r in self.ledger.pending_items()], [0, 1])
        with self.assertRaises(ReconciliationError):
            self.ledger.receive(0, [[99, 101, 1, 1], [43, 102, 1, 1]])
        with self.assertRaises(ReconciliationError):
            self.ledger.receive(0, [[42, 101, 1, 1]])
        with self.assertRaises(ReconciliationError):
            self.ledger.receive(3, [[42, 101, 1, 1]])

    def test_grants_disabled_and_crash_window_fails_closed(self):
        self.ledger.receive(0, [[42, 101, 1, 1]])
        with self.assertRaises(ReconciliationError):
            self.ledger.begin_item(0)
        self.assertTrue(self.ledger.begin_item(0, grant_validated=True))
        self.ledger.close(); self.ledger = Ledger(self.path, self.binding)
        with self.assertRaises(ReconciliationError):
            self.ledger.begin_item(0, grant_validated=True)
        # Synthetic adapter proof exercises ledger mechanics, not a real game grant.
        self.ledger.mark_durable(0, "test-reopened-ownership-proof")
        self.ledger.close(); self.ledger = Ledger(self.path, self.binding)
        self.assertFalse(self.ledger.begin_item(0, grant_validated=True))
        self.assertEqual(self.ledger.pending_items(), [])

    def test_wrong_seed_player_or_save_generation_refused(self):
        for b in [Binding("other", 0, 1, "isolated-generation", "PagodaPT_M_0"),
                  Binding("seed", 0, 2, "isolated-generation", "PagodaPT_M_0"),
                  Binding("seed", 0, 1, "reset-generation", "PagodaPT_M_0")]:
            with self.assertRaises(ReconciliationError):
                Ledger(self.path, b)
        with self.assertRaises(ReconciliationError):
            Ledger(self.path, Binding("seed", 0, 1, "isolated-generation", "PagodaPT_M_0", content_hash="different-catalog"))

    def test_unready_stale_wrong_generation_or_unknown_checks_cannot_sync(self):
        p = Path(self.temp.name) / "snapshot.json"
        bridge = GameBridge(p, "isolated-generation", "PagodaPT_M_0", [101])
        self.assertIsNone(bridge.read())
        row = dict(protocol=1, generation="isolated-generation", game_slot="PagodaPT_M_0",
                   ready=True, authority_verified=True, contexts_verified=True,
                   observed_at=time.time(), checks=[101])
        def put(**changes):
            p.write_text(json.dumps(row | changes), encoding="utf-8")
        put(); self.assertEqual(bridge.read(), {101})
        put(ready=False); self.assertIsNone(bridge.read())
        put(authority_verified=False); self.assertIsNone(bridge.read())
        put(authority_verified="false"); self.assertIsNone(bridge.read())
        put(ready="false"); self.assertIsNone(bridge.read())
        put(observed_at=time.time()-20); self.assertIsNone(bridge.read())
        put(generation="reset-generation")
        with self.assertRaises(ReconciliationError): bridge.read()
        put(checks=[999])
        with self.assertRaises(ReconciliationError): bridge.read()
