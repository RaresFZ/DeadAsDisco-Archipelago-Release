"""Protected launch contract. A surviving sidecar/slot name cannot authorize a save."""
import hashlib
import json
from pathlib import Path
from .reconciliation import ReconciliationError


class ProtectedBinding:
    def __init__(self, path, generation, game_slot):
        self.data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if "contexts_json" in self.data:
            self.data["contexts"] = json.loads(self.data["contexts_json"])
        if (self.data.get("generation"), self.data.get("game_slot")) != (generation, game_slot):
            raise ReconciliationError("Protected provisioning binding mismatch")

    def verify(self, snapshot):
        p = self.data
        session = json.loads(Path(p["session_file"]).read_text(encoding="utf-8-sig"))
        proxy = json.loads(Path(p["proxy_file"]).read_text(encoding="utf-8-sig"))
        if (session.get("status") != "isolated" or proxy.get("status") != "installed"
                or session.get("parked") != p["parked"] or session.get("copySource") != p["source"]):
            raise ReconciliationError("Protected transaction no longer active")
        if Path(p["lease"]).read_text(encoding="utf-8") != p["launch_token"] + "\n":
            return False
        if snapshot.get("protection_token") != p["launch_token"]:
            raise ReconciliationError("Wrong protected process launch token")
        if p.get("original_save_sha256"):
            parked = Path(p["parked"]) / "SaveGames" / (p["game_slot"] + ".sav")
            if hashlib.sha256(parked.read_bytes()).hexdigest() != p["original_save_sha256"]:
                raise ReconciliationError("Parked original changed")
        boundary = snapshot.get("boundary", {})
        if (boundary.get("slot") != p["game_slot"] or not boundary.get("dataOwner")
                or not boundary.get("savesOwner") or not boundary.get("world")):
            raise ReconciliationError("Incomplete authoritative boundary")
        scopes = snapshot.get("scopes", {})
        contexts = scopes.get("contexts", {})
        for key, variables in p["contexts"].items():
            got = contexts.get(key, {}).get("selected", {})
            for tag, leaves in variables.items():
                current = got.get(tag)
                if p.get('production_proof_sha256'):
                    if not isinstance(current, dict) or any(path not in current or
                            int(current[path]['current']) < int(old['current']) for path, old in leaves.items()):
                        raise ReconciliationError('Protected progression anchor reset')
                elif current != leaves:
                    raise ReconciliationError("Protected context reset or binding anchor changed")
        active = scopes.get("active", {}).get(p["check_scope"], {})
        if active.get("context") != p["check_context"]:
            raise ReconciliationError("Wrong authoritative active Playthrough context")
        owned, equipped = snapshot.get("owned"), snapshot.get("equipped")
        if (not isinstance(owned, list) or not isinstance(equipped, list)
                or len(set(owned)) != len(owned) or len(set(equipped)) != len(equipped)
                or not set(p["owned"]) - set(p.get('suppressed_ownership', [])) <= set(owned)
                or set(owned) - set(p["owned"]) - {p["item_tag"]} - set(p.get('allowed_ownership', []))
                or not set(p["equipped"]) - set(p.get('suppressed_ownership', [])) - set(p.get('allowed_ownership', [])) <= set(equipped)
                or set(equipped) - set(p["equipped"]) - ({p["item_tag"]} if p.get("phase3_enabled") is True else set()) - set(p.get('allowed_ownership', []))):
            raise ReconciliationError("Protected ownership reset or unexpected change")
        return True
