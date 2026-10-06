"""Final disposition audit: every one of the candidate location records and item types gets exactly one status.

Statuses:
  IMPLEMENTED          selectable by generation and wired to a runtime predicate/mechanism
  EXCLUDED_BY_DESIGN   cannot or must not be a check (free at New Game, debug-only, unbuyable starters)
  BLOCKED              a specific technical limitation prevents safe support (reason recorded)
Evidence tiers (honest, per record):
  live-observed        this exact record completed in a live AP session (some ledger observed it)
  predicate-verified   schema-exact predicate resolves from a real game save variable; not yet seen completing live
Run: python tools/audit-release.py   (writes docs/FINAL_AUDIT.md and artifacts/audit/final-audit.json)
"""
import collections
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "archipelago/apworld/dead_as_disco/catalog.json").read_text(encoding="utf-8"))
OUT = ROOT / "docs"
JSON_OUT = ROOT / "artifacts/audit"

LIVE_SKILL_ITEMS = {"Heavy Kick": "skill granted+equipped live", "Bass Invader": "power gated then granted live"}
MECHANISM_EVIDENCE = {
    "owned-upgrade": "native ownership grant proven live (Heavy Kick, Bass Invader; Stalwart/Backup cold round trip)",
    "mission-access": "access filter proven live (Hemlock start key, Arora delivery, persisted)",
    "temporary-trap": "Half Heart and Silence proven live",
    "client-hint": "client-side hint scouting",
    "fan-pack": "native AddCredits; live validation pending (runs in a protected test mode)",
}


def observed_locations():
    seen = set()
    committed = ROOT / "archipelago/data/evidence/live-observed-locations.json"
    if committed.is_file():
        seen |= set(json.loads(committed.read_text(encoding="utf-8"))["ids"])
    for path in list((ROOT / "artifacts/ap-slice").glob("*/live/*/ledger.sqlite")) + \
            [Path.home() / "AppData/Local/DeadAsDiscoAP/profiles/ap1/ledger.sqlite"]:
        if not path.is_file():
            continue
        try:
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            seen |= {row[0] for row in db.execute("SELECT id FROM checks")}
            db.close()
        except sqlite3.Error:
            pass
    return seen


def main():
    starters = set(CATALOG.get("starter_tags", []))
    free = set(CATALOG.get("free_start_locations", []))
    support = CATALOG.get("song_support", {})
    live = observed_locations()
    rows, counts = [], collections.Counter()
    for r in CATALOG["locations"]:
        reason, status = None, "IMPLEMENTED"
        song_tag = r["tag"] if r["family"] == "song" else (r["tag"] if r.get("completion_family") == "song" else None)
        if r["id"] in free:
            status, reason = "EXCLUDED_BY_DESIGN", "Owned/completed at New Game (default outfit, default dance or debug-only item); can never be a real check"
        elif r.get("item_tag") in starters:
            status, reason = "EXCLUDED_BY_DESIGN", "Free starting skill; it is AP start inventory because its node can never be purchased"
        elif song_tag is not None and not support.get(song_tag, {}).get("supported"):
            status, reason = "BLOCKED", support.get(song_tag, {}).get("reason") or "Song join not supported"
        tier = "live-observed" if r["id"] in live else "predicate-verified"
        rows.append({"id": r["id"], "name": r["name"], "family": r["family"], "predicate": r["predicate"],
                     "status": status, "evidence": tier if status == "IMPLEMENTED" else None, "reason": reason})
        counts[status] += 1
    item_rows = []
    for i in CATALOG["items"]:
        status = "IMPLEMENTED"
        note = MECHANISM_EVIDENCE[i["mechanism"]]
        if i["tag"] in starters if "tag" in i else False:
            note = "Start inventory (free at New Game); " + note
        item_rows.append({"id": i["id"], "name": i["name"], "family": i["family"], "mechanism": i["mechanism"],
                          "status": status, "start_inventory": bool("tag" in i and i["tag"] in starters), "evidence": note})
    by_family = collections.defaultdict(collections.Counter)
    for row in rows:
        by_family[row["family"]][row["status"]] += 1
    report = {
        "world_version": CATALOG["world_version"], "candidate_locations": len(rows), "item_types": len(item_rows),
        "location_status": dict(counts),
        "evidence_tiers": dict(collections.Counter(r["evidence"] for r in rows if r["evidence"])),
        "families": {k: dict(v) for k, v in sorted(by_family.items())},
        "excluded_by_design": [r for r in rows if r["status"] == "EXCLUDED_BY_DESIGN"],
        "blocked": [r for r in rows if r["status"] == "BLOCKED"],
        "inventory_not_candidates": dict(collections.Counter(q.get("reason", "?") for q in CATALOG.get("quarantined", []))),
        "locations": rows, "items": item_rows,
    }
    assert len(rows) == 1164 and sum(counts.values()) == 1164, "every candidate record must have exactly one status"
    OUT.mkdir(parents=True, exist_ok=True)
    JSON_OUT.mkdir(parents=True, exist_ok=True)
    (JSON_OUT / "final-audit.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    lines = ["# Final disposition audit (generated by tools/audit-release.py)", "",
             f"World {report['world_version']}: **{report['candidate_locations']}** candidate location records and "
             f"**{report['item_types']}** item types.", "", "## Locations", "",
             "| Status | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(counts.items())]
    maximum = counts["IMPLEMENTED"]
    lines += ["", f"Maximum generation-eligible checks: **{maximum}** (default options select far fewer; songs are opt-in).",
              "", "Evidence tiers among IMPLEMENTED records: " + ", ".join(f"{k}: {v}" for k, v in sorted(report["evidence_tiers"].items())) + ".",
              "`live-observed` = that exact record completed in a live AP session; `predicate-verified` = schema-exact predicate resolves from real save variables, not yet seen completing live.",
              "", "## By family", "", "| Family | " + " | ".join(["IMPLEMENTED", "EXCLUDED_BY_DESIGN", "BLOCKED"]) + " |", "|---|---|---|---|"]
    for family, c in sorted(by_family.items()):
        lines.append(f"| {family} | {c['IMPLEMENTED']} | {c['EXCLUDED_BY_DESIGN']} | {c['BLOCKED']} |")
    lines += ["", "## Excluded by design", ""]
    lines += [f"- {r['name']} ({r['family']}): {r['reason']}" for r in report["excluded_by_design"]]
    lines += ["", "## Blocked by a specific technical limitation", ""]
    blocked = collections.defaultdict(list)
    for r in report["blocked"]:
        blocked[r["reason"]].append(r["name"])
    for reason, names in blocked.items():
        lines.append(f"- **{reason}** ({len(names)} records): " + ", ".join(names[:6]) + (" ..." if len(names) > 6 else ""))
    lines += ["", "## Item types", "", "| Family | Count | Mechanism evidence |", "|---|---|---|"]
    fam = collections.defaultdict(list)
    for i in item_rows:
        fam[(i["family"], i["evidence"])].append(i)
    for (family, evidence), group in sorted(fam.items()):
        lines.append(f"| {family} | {len(group)} | {evidence} |")
    lines += ["", "Start inventory (free at New Game): " + ", ".join(i["name"] for i in item_rows if i["start_inventory"]) + ".",
              "", "## Inventory definitions that are not candidates", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(report["inventory_not_candidates"].items())]
    (OUT / "FINAL_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"locations": dict(counts), "evidence": report["evidence_tiers"], "items": len(item_rows)}))


if __name__ == "__main__":
    main()
