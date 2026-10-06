"""Generate the player YAML template with Archipelago's own template generator (same format as every AP game).

    DAD_AP_ROOT=<Archipelago 0.6.8 checkout> python tools/make-template.py
The option docstrings/groups in archipelago/apworld/dead_as_disco/options.py become the comments and sections.
"""
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AP_ROOT = Path(os.environ.get("DAD_AP_ROOT") or ROOT / "artifacts/references/Archipelago-0.6.8")
os.environ["AP_TEST_WORLDS"] = "dead_as_disco"
os.environ["SKIP_REQUIREMENTS_UPDATE"] = "1"
SOURCE = ROOT / "archipelago/apworld/dead_as_disco"
version = json.loads((SOURCE / "catalog.json").read_text(encoding="utf-8"))["world_version"]
target = AP_ROOT / "custom_worlds/dead_as_disco.apworld"
target.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("archipelago.json", json.dumps({"version": 7, "compatible_version": 7, "game": "Dead as Disco",
                                               "world_version": version, "minimum_ap_version": "0.6.8"}))
    for path in sorted(SOURCE.glob("*")):
        if path.is_file() and path.suffix in (".py", ".json"):
            z.write(path, "dead_as_disco/" + path.name)
sys.path.insert(0, str(AP_ROOT))
os.chdir(AP_ROOT)
import Options  # noqa: E402

NOTES = "\n".join([
    "# ---- Dead as Disco notes -----------------------------------------------------------------------",
    "# * The skill tree is an Archipelago SHOP: buying a node sends a check, the skill arrives from the multiworld.",
    "# * Theme groups work in exclude_locations / priority_locations (bottom of this file): Memorabilia, Challenges,",
    "#   Quests, Cosmetic Purchases, Dance Purchases, Story Completions, Achievements, Song Completions, Skill Nodes,",
    "#   Upgrade Nodes, Charlie Tree Nodes, Story Star Ratings, Song Star Ratings, Story Difficulty Checks,",
    "#   Song Difficulty Checks.  local_items / non_local_items accept: Idol Powers, Active Skills, Passive Upgrades,",
    "#   Mission Access, Traps, Filler.",
    "# * Filler items are Fan Packs (fans for the skill-tree shop) unless you lower fan_pack_percentage.",
    "# -------------------------------------------------------------------------------------------------",
    ""])

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
    Options.generate_yaml_templates(folder, generate_hidden=True)
    text = (Path(folder) / "Dead as Disco.yaml").read_text(encoding="utf-8-sig")
    text = text.replace("description: Default Dead as Disco Template", "description: Dead as Disco randomizer")
    text = text.replace("\ngame: Dead as Disco\n", "\n" + NOTES + "game: Dead as Disco\n", 1)
    (ROOT / "archipelago/Dead as Disco.yaml").write_text(text, encoding="utf-8", newline="\n")
    print("template written:", len(text.splitlines()), "lines")
