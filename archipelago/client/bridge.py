"""Read-only file interface. Missing/unready/mismatched snapshots never authorize reconciliation."""
import json
import time
import math
from pathlib import Path
from .reconciliation import ReconciliationError


class GameBridge:
    def __init__(self, path, generation, game_slot, allowed_locations, protection=None):
        self.path = Path(path)
        self.generation, self.game_slot = generation, game_slot
        self.allowed_locations = set(allowed_locations)
        self.protection = protection
        self.boot = None
        self.sequence = 0
        self.last_snapshot = None

    def read(self):
        self.last_snapshot = None
        candidates = [self.path] if self.protection is None else [Path(str(self.path) + f".{i}.json") for i in (0, 1)]
        rows = []
        for path in candidates:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, PermissionError):
                continue  # normal alternating-slot replacement (Windows: sharing violation while the mod swaps the file)
            except (json.JSONDecodeError, UnicodeError):
                raise ReconciliationError("Malformed game bridge snapshot")
            if not isinstance(data, dict):
                raise ReconciliationError("Game bridge envelope must be an object")
            rows.append(data)
        if not rows:
            return None
        if self.protection:
            if any(type(r.get("sequence")) is not int or r["sequence"] < 1 for r in rows):
                raise ReconciliationError("Invalid bridge sequence")
            data = max(rows, key=lambda r: r["sequence"])
            if data.get("boot") != self.boot:
                self.boot, self.sequence = data.get("boot"), 0
            if not self.boot or data["sequence"] < self.sequence:
                raise ReconciliationError("Bridge process snapshot rolled back")
            self.sequence = data["sequence"]
        else:
            data = rows[0]
        if data.get("protocol") != 1 or data.get("generation") != self.generation or data.get("game_slot") != self.game_slot:
            raise ReconciliationError("Game playthrough binding mismatch")
        if type(data.get("observed_at")) not in (int, float) or not math.isfinite(data["observed_at"]):
            raise ReconciliationError("Invalid bridge timestamp")
        age = time.time() - data["observed_at"]
        if age < -2 or age > 10 or data.get("ready") is not True:
            return None
        if data.get("authority_verified") is not True or data.get("contexts_verified") is not True:
            return None
        if self.protection and not self.protection.verify(data):
            return None
        values = data.get("checks", [])
        if not isinstance(values, list) or any(type(v) is not int for v in values):
            raise ReconciliationError("Invalid game location IDs")
        checks = set(values)
        if not checks <= self.allowed_locations:
            raise ReconciliationError("Unknown game location ID")
        self.last_snapshot = data
        return checks
