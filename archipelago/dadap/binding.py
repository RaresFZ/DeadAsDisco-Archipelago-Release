"""Bind an AP slot to a profile save and render the game mod's per-session configuration.

Port of the anchor/config logic in tools/prepare-ap-bridge.mjs for the portable release. The anchors prove that
the live game is the same playthrough (and not a reset/rollback) that the AP ledger was created from.
"""
import json
import re

from . import gvas

COUNTER = re.compile(r"^Progression\.(AbilityCounter|Counter)\.")
OBJECT_CAP = 96


class BindingError(RuntimeError):
    pass


def lua(value):
    """Lua literal for plain data. Matches the verified JavaScript serializer (ASCII tags/paths only)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "{" + ",".join(lua(v) for v in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join(f"[{lua(str(k))}]={lua(v)}" for k, v in value.items()) + "}"
    raise TypeError("Unsupported config value")


def _bounds(v, depth=0):
    if depth > 4:
        raise BindingError("Composite depth cap")
    if v["structType"].endswith("ValueSnapshot"):
        return 1
    if not v["structType"].endswith("CompositeSnapshot"):
        raise BindingError("Unsupported selected snapshot")
    children = gvas.field(v["fields"], "InnerVariables")
    if len(children) > 32:
        raise BindingError("Composite child cap")
    return 1 + sum(_bounds(c["value"], depth + 1) for c in children)


def _leaves(v, prefix="", out=None):
    out = {} if out is None else out
    if v["structType"].endswith("ValueSnapshot"):
        out[prefix] = {"current": str(gvas.field(v["fields"], "CurrentState")), "viewed": str(gvas.field(v["fields"], "ViewedState"))}
    else:
        for child in gvas.field(v["fields"], "InnerVariables"):
            _leaves(child["value"], prefix + "/" + child["key"], out)
    return out


def select_anchors(scopes, check_tag):
    """(selected {scope:[tags]}, contexts {'scope|context': {tag: leaves}}, selected_objects)."""
    selected, contexts = {}, {}
    for s in scopes:
        by_tag = {gvas.tag(v["key"]): v for v in s["variables"]}
        if s["scope"].endswith("InfiniteDiscoSong"):
            wanted = list(by_tag)
        else:
            stable = sorted(t for t, v in by_tag.items()
                            if v["value"]["structType"].endswith("ValueSnapshot") and not COUNTER.match(t))
            if not stable:
                raise BindingError("No stable anchor in scope " + s["scope"])
            wanted = [stable[0]]
        if s["scope"] in selected and selected[s["scope"]] != wanted:
            raise BindingError("Selection differs across contexts")
        selected[s["scope"]] = wanted
        contexts[s["scope"] + "|" + s["context"]] = {t: _leaves(by_tag[t]["value"]) for t in wanted}
    playthrough = [s for s in scopes if s["scope"] == "Progression.Scope.Playthrough"]
    if len(playthrough) != 1:
        raise BindingError("Expected exactly one Playthrough context")
    selected["Progression.Scope.Playthrough"] = sorted(set(selected["Progression.Scope.Playthrough"]) | {check_tag})
    objects = 0
    for s in scopes:
        wanted = selected[s["scope"]]
        found = [v for v in s["variables"] if gvas.tag(v["key"]) in wanted]
        if len(found) != len(wanted):
            raise BindingError("Missing selected saved variable")
        objects += sum(_bounds(v["value"]) for v in found)
    if objects > OBJECT_CAP:
        raise BindingError("Selected objects exceed fixed runtime cap")
    return selected, contexts, objects


def pick_check_row(catalog, playthrough_variables):
    """A purchase-style location whose scalar variable exists (state 3/4): the legacy per-tick anchor check."""
    preferred = [r for r in catalog["locations"] if r["predicate"] == "purchased"]
    preferred.sort(key=lambda r: (r["tag"] != "Progression.Memorabilia.Trinkets.Magazine.Rebel", r["id"]))
    for row in preferred:
        states = playthrough_variables.get(row["tag"])
        if states and states.get("") in ("3", "4"):
            return row
    raise BindingError("No scalar anchor check variable exists in this save yet; play past the tutorial first")


def progress_count(catalog, playthrough_variables):
    """How many catalog records the save already completes. A fresh profile must be (nearly) pristine."""
    from .saved_state import completed
    return sum(1 for r in catalog["locations"] if r["predicate"] != "node-interaction"
               and completed(r, playthrough_variables.get(r["tag"])))


STARTERS_KEY = "starter_tags"


def _asset(row):
    return row["asset"] + "." + row["asset"].split("/")[-1]


def build_session(*, catalog, slot_data, generation, game_slot, token, paths, parsed_pt, parsed_gp, caps, check_row=None,
                  certificate_sha256=None):
    """Everything the game mod and the client need for one session, from the profile's current saves.

    paths: dict with session_file, parked_sentinel, lease, runtime_dir (plain directory for control/evidence files).
    caps: {'ownership','node-interaction','reward-suppression','mission-access','temporary-traps','death-link'} -> bool
    Returns (config_lua, selection_lua, protection_dict, summary).
    """
    from . import saved_state
    scopes = gvas.saved_scopes(parsed_pt) + gvas.saved_scopes(parsed_gp)
    context, variables = saved_state.playthrough_variables(parsed_pt)
    check = check_row or pick_check_row(catalog, variables)
    selected, contexts, objects = select_anchors(scopes, check["tag"])
    player = gvas.field(parsed_pt["properties"], "PlayerData")
    owned = sorted(gvas.tag(x) for x in gvas.field(player, "OwnedUpgrades"))
    equipped = sorted(gvas.tag(x) for x in gvas.field(player, "EquippedUpgrades"))
    options = slot_data.get("options", {})
    run = paths["runtime_dir"].replace("\\", "/").rstrip("/")
    starters = set(catalog.get(STARTERS_KEY, []))
    item = next(r for r in catalog["items"] if r["tag"] in starters)
    config = {
        "generation": generation, "launchToken": token, "gameSlot": game_slot,
        "sessionFile": paths["session_file"].replace("\\", "/"), "parkedSave": paths["parked_sentinel"].replace("\\", "/"),
        "lease": paths["lease"].replace("\\", "/"), "control": run + "/ap-control.request",
        "output": run + "/ap-snapshot", "evidence": run + "/ap-evidence.jsonl", "refusal": run + "/ap-refusal.txt",
        "owned": owned, "equipped": "|".join(equipped), "contexts": contexts,
        "checkScope": check["scope"], "checkContext": context, "checkTag": check["tag"],
        "itemTag": item["tag"], "itemAsset": _asset(item), "locationId": check["id"],
        "phase3Enabled": False, "coldRecoveryOnly": False, "proofPermit": run + "/phase3.permit", "proofMarker": run + "/phase3-attempt",
        "boundContextCount": len(scopes),
        "productionEnabled": True, "productionControl": run + "/production-control.request",
    }
    owned_items = [r for r in catalog["items"] if r["mechanism"] == "owned-upgrade"]
    config["allowedOwnership"] = {r["tag"]: True for r in owned_items}
    config["productionItems"] = {str(r["id"]): {"tag": r["tag"], "asset": _asset(r), "family": r["family"]} for r in owned_items}
    enabled = set(slot_data.get("location_ids", []))
    node_rows = [r for r in catalog["locations"] if r["predicate"] == "node-interaction" and (not enabled or r["id"] in enabled)]
    on = lambda name: bool(caps.get(name))
    test = lambda name: caps.get(name) == "test"
    summary = {"objects": objects, "contexts": len(scopes), "node_rows": len(node_rows), "capabilities_required": []}
    if node_rows and on("node-interaction"):
        family_switch = {"skill": "shuffle_skills", "power": "shuffle_powers", "upgrade": "shuffle_upgrades"}
        config.update(nodeLocationsEnabled=True, nodeLocationsValidated=not test("node-interaction"), nodeLocationsTest=test("node-interaction"),
                      nodeJournal=run + "/node-journal.jsonl", entitlementFile=run + "/ownership-entitlements.txt",
                      completedNodesFile=run + "/completed-nodes.txt")
        config["nodeItems"] = {r["item_tag"]: {"id": r["id"], "asset": _asset(next(i for i in catalog["items"] if i["tag"] == r["item_tag"])),
                                              "ownershipFamily": next(i for i in catalog["items"] if i["tag"] == r["item_tag"])["family"]}
                               for r in node_rows}
        suppress = on("reward-suppression")
        config["suppressedNodes"] = {r["tag"]: True for r in owned_items
                                     if suppress and r["tag"] not in starters and options.get(family_switch.get(r["family"], ""))}
        config.update(rewardSuppressionValidated=suppress and not test("reward-suppression"), rewardSuppressionTest=test("reward-suppression"),
                      powerRemovalValidated=suppress and not test("reward-suppression"), powerRemovalTest=test("reward-suppression"))
    if options.get("shuffle_access") and on("mission-access"):
        config.update(accessEnabled=True, accessValidated=not test("mission-access"), accessTest=test("mission-access"), accessFile=run + "/mission-access.txt",
                      accessItems={r["tag"]: True for r in catalog["items"] if r["mechanism"] == "mission-access"})
    if options.get("traps") and on("temporary-traps"):
        config.update(trapsEnabled=True, trapsValidated=not test("temporary-traps"), trapsTest=test("temporary-traps"), trapControl=run + "/trap-control.request",
                      trapDuration=options.get("trap_duration", 10),
                      trapItems={str(r["id"]): r["effect"] for r in catalog["items"] if r["mechanism"] == "temporary-trap"})
    if options.get("fan_pack_percentage") and on("fan-packs"):
        config.update(fanPacksEnabled=True, fanPacksValidated=not test("fan-packs"), fanPacksTest=test("fan-packs"),
                      creditsControl=run + "/credits-control.request",
                      fanPacks={str(r["id"]): max(1, round(int(options.get("fan_pack_amount", 500)) * float(r.get("scale", 1.0))))
                                for r in catalog["items"] if r["mechanism"] == "fan-pack"})
    if slot_data.get("death_link") and on("death-link"):
        config.update(deathLinkEnabled=True, deathLinkValidated=not test("death-link"), deathLinkTest=test("death-link"), deathLinkControl=run + "/deathlink-control.request")
    selection = {scope: {t: True for t in tags} for scope, tags in selected.items()}
    protection = {
        "generation": generation, "game_slot": game_slot, "launch_token": token, "protocol": 1,
        "contexts_json": json.dumps(contexts), "owned": owned, "equipped": equipped,
        "check_scope": check["scope"], "check_context": context, "item_tag": item["tag"],
        "session_file": paths["session_file"], "proxy_file": paths["proxy_file"], "lease": paths["lease"],
        "parked": paths["parked"], "source": paths["source"], "original_save_sha256": None,
        "grants_enabled": True, "phase3_enabled": False,
        "allowed_ownership": sorted(config["allowedOwnership"]),
        "production_control": config["productionControl"],
        "node_locations_validated": bool(config.get("nodeLocationsValidated")), "node_locations_test": bool(config.get("nodeLocationsTest")),
        "reward_suppression_validated": bool(config.get("rewardSuppressionValidated")), "reward_suppression_test": bool(config.get("rewardSuppressionTest")),
        "access_validated": bool(config.get("accessValidated")), "access_test": bool(config.get("accessTest")),
        "traps_validated": bool(config.get("trapsValidated")), "traps_test": bool(config.get("trapsTest")),
        "death_link_validated": bool(config.get("deathLinkValidated")), "death_link_test": bool(config.get("deathLinkTest")),
        "inprocess_decoder": True, "production_proof_sha256": certificate_sha256,
        "node_items": [{"id": r["id"], "tag": r["item_tag"]} for r in node_rows] if config.get("nodeLocationsEnabled") else [],
        "entitlement_file": config.get("entitlementFile"), "completed_nodes_file": config.get("completedNodesFile"),
        "access_file": config.get("accessFile"), "trap_control": config.get("trapControl"),
        "death_link_control": config.get("deathLinkControl"),
        "fan_packs_validated": bool(config.get("fanPacksValidated")), "fan_packs_test": bool(config.get("fanPacksTest")),
        "credits_control": config.get("creditsControl"),
        "suppressed_ownership": sorted(config.get("suppressedNodes", {})),
        "node_journal": config.get("nodeJournal"),
    }
    return "return " + lua(config) + "\n", "return " + lua(selection) + "\n", protection, summary
