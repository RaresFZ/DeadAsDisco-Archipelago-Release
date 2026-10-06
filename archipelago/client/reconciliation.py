"""Durable AP history/check ledger. Never interprets counts as item indices."""
import json
import sqlite3
from dataclasses import dataclass, asdict


class ReconciliationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Binding:
    seed: str
    team: int
    player: int
    generation: str
    game_slot: str
    protocol: int = 1
    content_hash: str = ""


class Ledger:
    def __init__(self, path, binding: Binding):
        if not binding.seed or not binding.generation or not binding.game_slot or binding.protocol != 1:
            raise ReconciliationError("Incomplete playthrough binding")
        self.binding = binding
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY, confirmed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS receipts(idx INTEGER PRIMARY KEY, payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'received', proof TEXT);
        """)
        encoded = json.dumps(asdict(binding), sort_keys=True)
        row = self.db.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()
        if row and row[0] != encoded:
            self.db.close()
            raise ReconciliationError("Refusing different seed/team/player/save generation or reset/rebind")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('binding',?)", (encoded,))

    def close(self):
        self.db.close()

    def observe(self, locations):
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO checks(id) VALUES(?)", ((x,) for x in set(locations)))

    def confirm(self, checked):
        checked = set(checked)
        confirmed = {r[0] for r in self.db.execute("SELECT id FROM checks WHERE confirmed=1")}
        if not confirmed <= checked:
            raise ReconciliationError("Server lost confirmed checks; refuse rollback/rebind")
        with self.db:
            self.db.executemany("INSERT INTO checks(id,confirmed) VALUES(?,1) "
                                "ON CONFLICT(id) DO UPDATE SET confirmed=1", ((x,) for x in checked))

    def pending_checks(self, missing):
        return {r[0] for r in self.db.execute("SELECT id FROM checks WHERE confirmed=0")} & set(missing)

    def receive(self, index, items):
        if type(index) is not int or index < 0:
            raise ReconciliationError("Invalid ReceivedItems index")
        if (not isinstance(items, (list, tuple)) or any(not isinstance(item, (list, tuple)) or len(item) != 4
                or any(type(v) is not int for v in item) or item[0] <= 0 or item[2] < 0 or not 0 <= item[3] <= 7
                for item in items)):
            raise ReconciliationError("Malformed ReceivedItems payload")
        payloads = [json.dumps(list(item), separators=(",", ":")) for item in items]
        known = [r[0] for r in self.db.execute("SELECT payload FROM receipts ORDER BY idx")]
        if index > len(known):
            raise ReconciliationError("ReceivedItems gap; request Sync")
        if index == 0 and len(payloads) < len(known):
            raise ReconciliationError("Server history shortened; refuse reset/rollback")
        for offset, payload in enumerate(payloads):
            pos = index + offset
            if pos < len(known) and known[pos] != payload:
                raise ReconciliationError("Authoritative received history changed")
        with self.db:
            for offset, payload in enumerate(payloads):
                self.db.execute("INSERT OR IGNORE INTO receipts(idx,payload) VALUES(?,?)", (index + offset, payload))

    def pending_items(self):
        return [(i, json.loads(p), s) for i, p, s in self.db.execute(
            "SELECT idx,payload,status FROM receipts WHERE status!='applied' ORDER BY idx")]

    def begin_item(self, index, *, grant_validated=False, satisfied_prefix=()):
        if not grant_validated:
            raise ReconciliationError("Protected Phase 3 grant proof required")
        row = self.db.execute("SELECT status FROM receipts WHERE idx=?", (index,)).fetchone()
        if not row:
            raise ReconciliationError("No authoritative received item")
        if row[0] == "applied":
            return False
        if row[0] == "applying":
            raise ReconciliationError("Ambiguous prior application: reconcile durable ownership before retry")
        if any(i < index and i not in satisfied_prefix for i, _, _ in self.pending_items()):
            raise ReconciliationError("Earlier received item unresolved")
        with self.db:
            self.db.execute("UPDATE receipts SET status='applying' WHERE idx=?", (index,))
        return True

    def release_reservation(self, index):
        """Return an in-flight item to 'received' so it can be dispatched again.

        Only for a reservation whose effect is provably absent: a new game session that does not own the item, or a
        one-shot filler/trap command that the previous game session never acknowledged."""
        with self.db:
            result = self.db.execute("UPDATE receipts SET status='received' WHERE idx=? AND status='applying'", (index,))
            if result.rowcount != 1:
                raise ReconciliationError("No matching in-flight item")

    def mark_durable(self, index, proof):
        # Only a validated game adapter may supply a reopened-save ownership proof.
        if not isinstance(proof, str) or not proof:
            raise ReconciliationError("Durable game effect proof required")
        with self.db:
            result = self.db.execute("UPDATE receipts SET status='applied',proof=? "
                                     "WHERE idx=? AND status='applying'", (proof, index))
            if result.rowcount != 1:
                raise ReconciliationError("No matching in-flight item")
