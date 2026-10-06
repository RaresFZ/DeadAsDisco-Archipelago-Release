import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from archipelago.client.reconciliation import Binding, Ledger, ReconciliationError
from archipelago.client.items import ItemReconciler


class ItemRecoveryTests(unittest.TestCase):
    def test_proven_cold_effect_recovers_receipt_crash_window_and_never_reapplies(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            binding = Binding("seed", 0, 1, "generation", "slot", content_hash="catalog")
            path = root / "ledger.sqlite"
            certificate = root / "proof.json"
            source = root / "synthetic-evidence.json"
            source.write_text('"synthetic fixture; not game evidence"')
            sources = {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}
            # Synthetic fixtures exercise recovery, not an actual game certificate.
            row = dict(status="verified-protected-passive-grant-cold", generation="generation", content_hash="catalog",
                       seed="seed", team=0, player=1, game_slot="slot", receipt=[3404260101, 3404260001, 1, 1], sources=sources,
                       item_id=3404260101, item_tag="Progression.Unlockable.Upgrades.Prophet.HealthUp",
                       max_health_delta=10, duplicate_health_delta=0, unrelated_state_unchanged=True,
                       cold_boot="new-process", proof_sha256=hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest())
            certificate.write_text(json.dumps(row))
            ledger = Ledger(path, binding)
            ledger.receive(0, [[3404260101, 3404260001, 1, 1]])
            items = ItemReconciler(ledger, certificate)
            snapshot = dict(owned=[row["item_tag"]], boot="old-process")
            self.assertEqual(items.reconcile(snapshot), 0)
            self.assertEqual(len(ledger.pending_items()), 1)
            ledger.begin_item(0, grant_validated=True)  # crash after effect/before durable acknowledgement
            ledger.close()
            ledger = Ledger(path, binding)
            items = ItemReconciler(ledger, certificate)
            snapshot["boot"] = "new-process"
            self.assertEqual(items.reconcile(snapshot), 1)
            self.assertEqual(items.reconcile(snapshot), 0)
            ledger.receive(0, [[3404260101, 3404260001, 1, 1]])
            self.assertEqual(items.reconcile(snapshot), 0)
            with self.assertRaises(ReconciliationError): items.reconcile(dict(owned=[], boot="new-process"))
            ledger.close()
            row["duplicate_health_delta"] = 10; certificate.write_text(json.dumps(row))
            ledger = Ledger(path, binding)
            with self.assertRaises(ReconciliationError): ItemReconciler(ledger, certificate)
            row["duplicate_health_delta"] = 0
            row["seed"] = "wrong-seed"; certificate.write_text(json.dumps(row))
            with self.assertRaises(ReconciliationError): ItemReconciler(ledger, certificate)
            row["seed"] = "seed"
            row["receipt"] = [3404260101, 999, 1, 1]; certificate.write_text(json.dumps(row))
            with self.assertRaises(ReconciliationError): ItemReconciler(ledger, certificate)
            row["receipt"] = [3404260101, 3404260001, 1, 1]; certificate.write_text(json.dumps(row))
            source.write_text('"tampered fixture"')
            with self.assertRaises(ReconciliationError): ItemReconciler(ledger, certificate)
            ledger.close()
