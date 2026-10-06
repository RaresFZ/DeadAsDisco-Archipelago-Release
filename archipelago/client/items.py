"""Single proven passive-item reconciler. Authoritative history, never callback-only."""
import json
import hashlib
from pathlib import Path
from .reconciliation import ReconciliationError


class ItemReconciler:
    def __init__(self, ledger, certificate_path):
        self.ledger = ledger
        self.path = Path(certificate_path)
        self.certificate = json.loads(self.path.read_text(encoding="utf-8"))
        c = self.certificate
        if (c.get("status") != "verified-protected-passive-grant-cold"
                or (c.get("seed"), c.get("team"), c.get("player"), c.get("game_slot"))
                    != (ledger.binding.seed, ledger.binding.team, ledger.binding.player, ledger.binding.game_slot)
                or c.get("generation") != ledger.binding.generation
                or c.get("content_hash") != ledger.binding.content_hash
                or c.get("item_id") != 3404260101
                or c.get("item_tag") != "Progression.Unlockable.Upgrades.Prophet.HealthUp"
                or c.get("max_health_delta") != 10 or c.get("duplicate_health_delta") != 0
                or c.get("unrelated_state_unchanged") is not True):
            raise ReconciliationError("Validated protected passive grant/cold certificate required")
        sources = c.get("sources")
        if not isinstance(sources, dict) or not sources:
            raise ReconciliationError("Hash-pinned cold effect sources required")
        for path, expected in sources.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
                raise ReconciliationError("Cold effect proof source changed")
        if c.get("proof_sha256") != hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest():
            raise ReconciliationError("Cold effect proof digest mismatch")
        if c.get("receipt") != [3404260101, 3404260001, 1, 1] or not c.get("cold_boot"):
            raise ReconciliationError("Exact representative receipt/cold process required")

    def reconcile(self, snapshot):
        c = self.certificate
        owned = c["item_tag"] in snapshot.get("owned", [])
        # Never trust a sidecar to hide lost durable game progression.
        applied = self.ledger.db.execute("SELECT COUNT(*) FROM receipts WHERE status='applied'").fetchone()[0]
        if applied and not owned:
            raise ReconciliationError("Applied AP ownership disappeared; refuse reset/rollback")
        pending = self.ledger.pending_items()
        if not pending:
            return 0
        index, payload, state = pending[0]
        if index != 0 or payload != c["receipt"]:
            raise ReconciliationError("Only the certified representative receipt is supported")
        # This slice's targeted grant used this exact authoritative receipt. Its
        # closed saved endpoint and independent fresh-process effect proof authorize
        # durable recovery without reapplying the ownership effect.
        if owned and snapshot.get("boot") == c["cold_boot"]:
            if state == "received":
                self.ledger.begin_item(index, grant_validated=True)
            self.ledger.mark_durable(index, "protected-cold:" + c["proof_sha256"])
            return 1
        # A received item remains durable while the game is unready. An unexpected
        # missing target at the certified reopened boundary is a rollback, not an
        # excuse to replay an uncertain grant.
        if snapshot.get("boot") == c["cold_boot"] and not owned:
            raise ReconciliationError("Certified cold ownership missing")
        return 0
