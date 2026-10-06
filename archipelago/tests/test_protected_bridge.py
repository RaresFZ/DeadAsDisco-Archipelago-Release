import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from archipelago.client.protection import ProtectedBinding
from archipelago.client.bridge import GameBridge
from archipelago.client.reconciliation import ReconciliationError


class ProtectedBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.parked = self.root / "parked"
        (self.parked / "SaveGames").mkdir(parents=True)
        (self.parked / "SaveGames/slot.sav").write_bytes(b"original fixture")
        self.session = self.root / "session.json"
        self.proxy = self.root / "proxy.json"
        self.lease = self.root / "launch.lease"
        self.manifest = self.root / "protection.json"
        self.output = self.root / "snapshot"
        self.anchors = {f"scope|{i}": {"anchor": {"": {"current": "4", "viewed": "4"}}} for i in range(6)}
        self.put(self.session, dict(status="isolated", parked=str(self.parked), copySource="frozen"))
        self.put(self.proxy, dict(status="installed"))
        self.lease.write_text("token\n")
        self.put(self.manifest, dict(generation="generation", game_slot="slot", launch_token="token",
                 parked=str(self.parked), source="frozen", session_file=str(self.session), proxy_file=str(self.proxy),
                 lease=str(self.lease), original_save_sha256=hashlib.sha256(b"original fixture").hexdigest(),
                 contexts=self.anchors, check_scope="scope", check_context="0", owned=["old"], equipped=[], item_tag="new"))
        self.protection = ProtectedBinding(self.manifest, "generation", "slot")
        self.bridge = GameBridge(self.output, "generation", "slot", [101], self.protection)
        self.row = dict(protocol=1, generation="generation", game_slot="slot", boot="boot", sequence=1,
                        observed_at=time.time(), ready=True, authority_verified=True, contexts_verified=True,
                        protection_token="token", checks=[101], owned=["old"], equipped=[],
                        boundary=dict(slot="slot", world="world", dataOwner="data", savesOwner="saves"),
                        scopes=dict(contexts={key: {"selected": v} for key, v in self.anchors.items()},
                                    active={"scope": {"context": "0"}}))

    def tearDown(self):
        self.temp.cleanup()

    def put(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def snapshot(self, **changes):
        self.put(Path(str(self.output) + ".1.json"), self.row | changes)

    def test_newer_unready_dominates_ready_during_title_and_alternating_replace(self):
        self.snapshot(); self.assertEqual(self.bridge.read(), {101})
        self.put(Path(str(self.output) + ".0.json"), self.row | dict(sequence=2, ready=False))
        self.assertIsNone(self.bridge.read())
        self.assertIsNone(self.bridge.last_snapshot, "Old ready snapshot must not survive invalidation")
        Path(str(self.output) + ".1.json").unlink()
        self.assertIsNone(self.bridge.read())

    def test_surviving_sidecar_cannot_authorize_original_restored_or_missing_lease(self):
        self.snapshot(); self.assertEqual(self.bridge.read(), {101})
        self.lease.write_text(""); self.assertIsNone(self.bridge.read())
        self.lease.write_text("token\n")
        self.put(self.session, dict(status="restored", parked=str(self.parked), copySource="frozen"))
        with self.assertRaises(ReconciliationError): self.bridge.read()

    def test_context_reset_ownership_reset_wrong_launch_and_original_tamper_refuse(self):
        for changes in [dict(scopes={}), dict(owned=[]), dict(owned=["old", "unrelated"]), dict(protection_token="old-launch")]:
            self.snapshot(**changes)
            with self.assertRaises(ReconciliationError): self.bridge.read()
        self.snapshot()
        (self.parked / "SaveGames/slot.sav").write_bytes(b"modified original")
        with self.assertRaises(ReconciliationError): self.bridge.read()

    def test_corrupt_or_invalid_scalar_types_refuse(self):
        for changes in [dict(sequence=True), dict(observed_at="today"), dict(checks=[True]), dict(checks="101")]:
            self.snapshot(**changes)
            with self.assertRaises(ReconciliationError): self.bridge.read()
        Path(str(self.output) + ".1.json").write_text("{")
        with self.assertRaises(ReconciliationError): self.bridge.read()

    def test_only_phase3_target_equipment_transition_is_allowed(self):
        self.snapshot(owned=["old", "new"], equipped=["new"])
        with self.assertRaises(ReconciliationError): self.bridge.read()
        self.protection.data["phase3_enabled"] = True
        self.assertEqual(self.bridge.read(), {101})
        self.snapshot(owned=["old", "new"], equipped=["new", "unrelated"])
        with self.assertRaises(ReconciliationError): self.bridge.read()
