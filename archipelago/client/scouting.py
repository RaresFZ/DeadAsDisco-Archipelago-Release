"""Skill-tree 'shop window': which item sits behind each skill/power/upgrade node (client-side text only)."""
from pathlib import Path


def node_location_ids(catalog, allowed):
    return sorted(r["id"] for r in catalog["locations"] if r["predicate"] == "node-interaction" and r["id"] in allowed)


def format_scouts(catalog, locations_info, item_name, player_name):
    """Human readable lines, sorted by node name. item_name(code, player)/player_name(slot) may raise; fall back safely."""
    names = {r["id"]: r["name"] for r in catalog["locations"]}
    lines = []
    for location, item in sorted(locations_info.items(), key=lambda kv: names.get(kv[0], "")):
        try:
            what = item_name(item.item, item.player)
        except Exception:
            what = f"item #{item.item}"
        try:
            who = player_name(item.player)
        except Exception:
            who = f"player {item.player}"
        lines.append(f"{names.get(location, location)}: {what} (for {who})")
    return lines


def write_scouts(path, lines):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text("What each skill-tree node holds (from the Archipelago server):\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(target)
