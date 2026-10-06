"""In-process saved-state decoder (port of tools/ap-saved-state.mjs + ap-location-predicates.mjs).

Read-only: it never touches the game. A save changing underneath the read is retried by the caller.
"""
import hashlib
import json
import os

from . import gvas


def completed(row, states, node_interactions=frozenset(), alt_states=None):
    predicate = row["predicate"]
    # A collectible counts as soon as it is picked up (PickupItem variable >= threshold), not only when bought.
    if alt_states and int(alt_states.get("", "0")) >= int(row.get("alt_threshold", 1)):
        return True
    if predicate == "node-interaction":
        return row["id"] in node_interactions
    if not states:
        return False
    if predicate == "purchased":
        return states.get("") == "4"
    if predicate == "unlocked":
        return states.get("") == "1"
    if predicate == "challenge-completion":
        return int(states.get("/Completion Count", "0")) > 0
    if predicate == "story-completion":
        return any(p.endswith("/Completion Count") and int(s) > 0 for p, s in states.items())
    if predicate == "counter-threshold":
        return int(states.get(row["path"], "0")) >= int(row["threshold"])
    if predicate == "highest-stars":
        return any(p.endswith("/Highest Star Rating") and int(s) >= int(row["threshold"]) for p, s in states.items())
    raise ValueError("Unknown terminal predicate: " + predicate)


def victory(goal, catalog, variables, checks):
    if not goal or not goal.get("records"):
        return all(any(p.endswith("/Completion Count") and int(s) > 0 for p, s in variables.get(t, {}).items())
                   for t in catalog["goal"]["tags"])
    by_id = {r["id"]: r for r in catalog["locations"]}

    def row(identifier):
        if identifier not in by_id:
            raise ValueError("Unknown goal record")
        return by_id[identifier]

    def done(identifier):
        r = row(identifier)
        return completed(r, variables.get(r["tag"]))

    story = all(done(i) for i in goal["story_records"])
    if goal["kind"] == 4:
        return all(completed({"predicate": "highest-stars", "threshold": 5}, variables.get(row(i)["tag"]))
                   for i in goal["story_records"])
    enough = sum(1 for i in goal["records"] if done(i) or i in checks) >= goal["count"]
    return (story and enough) if goal["kind"] == 5 else enough


def playthrough_variables(parsed):
    """(context, {tag: {path: state}}) for the single Playthrough scope."""
    scopes = [s for s in gvas.saved_scopes(parsed) if s["scope"] == "Progression.Scope.Playthrough"]
    if len(scopes) != 1:
        raise gvas.SaveError("Expected exactly one Playthrough context")
    scope = scopes[0]
    return scope["context"], {gvas.tag(v["key"]): gvas.leaves(v["value"]) for v in scope["variables"]}


def node_interactions(journal_path, generation, game_slot, token, catalog):
    """Durable skill-node interactions recorded by the game mod; a torn last line is ignored."""
    nodes = set()
    if not journal_path or not os.path.exists(journal_path):
        return nodes
    lines = open(journal_path, encoding="utf-8").read().split("\n")
    if lines and lines[-1] != "":
        lines.pop()
    by_id = {r["id"]: r for r in catalog["locations"]}
    for line in filter(None, lines):
        row = json.loads(line)
        if (row.get("generation"), row.get("game_slot"), row.get("protection_token")) != (generation, game_slot, token):
            raise ValueError("Node journal belongs to another binding")
        if row.get("kind") == "node-interaction":
            location = by_id.get(row.get("id"))
            if not location or location["predicate"] != "node-interaction" or location.get("item_tag") != row.get("tag"):
                raise ValueError("Invalid node journal mapping")
            nodes.add(row["id"])
    return nodes


def decode(save_path, game_slot, catalog, settings, expected_context=None, nodes=frozenset()):
    """Same contract as ap-saved-state.mjs output: {protocol, save_sha256, checks, owned, victory}."""
    before = os.stat(save_path)
    with open(save_path, "rb") as handle:
        data = handle.read()
    after = os.stat(save_path)
    if before.st_mtime_ns != after.st_mtime_ns or before.st_size != len(data):
        raise gvas.SaveError("Save changed during observation")
    parsed = gvas.read_tagged_save(data, game_slot + ".sav")
    context, variables = playthrough_variables(parsed)
    if expected_context is not None and context != expected_context:
        raise gvas.SaveError("Wrong saved playthrough")
    allowed = set((settings or {}).get("location_ids") or [r["id"] for r in catalog["locations"]])
    known = {r["id"] for r in catalog["locations"]}
    if not allowed <= known:
        raise ValueError("Unknown enabled location")
    checks = []
    for row in catalog["locations"]:
        if row["id"] not in allowed:
            continue
        if row["scope"] != "Progression.Scope.Playthrough":
            raise ValueError("Cross-playthrough global checks forbidden")
        if completed(row, variables.get(row["tag"]), nodes, variables.get(row["alt_tag"]) if row.get("alt_tag") else None):
            checks.append(row["id"])
    player = gvas.field(parsed["properties"], "PlayerData")
    return {"protocol": 2, "save_sha256": hashlib.sha256(data).hexdigest(), "checks": checks,
            "owned": sorted(gvas.tag(x) for x in gvas.field(player, "OwnedUpgrades")),
            "victory": victory((settings or {}).get("goal"), catalog, variables, set(checks))}
