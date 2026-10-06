"""Developer harness: run the test-suite, generate a seed with a real Archipelago checkout, or serve it. Never touches the game.

    DAD_AP_ROOT=<Archipelago 0.6.8 checkout> python tools/ap-slice-dev.py Tests|Generate|Server --run NAME [--yaml FILE]
"""
import argparse
import asyncio
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import unittest
import zipfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
AP_ROOT = Path(os.environ.get("DAD_AP_ROOT") or WORKSPACE / "artifacts/references/Archipelago-0.6.8")
SOURCE = WORKSPACE / "archipelago/apworld/dead_as_disco"
os.environ["SKIP_REQUIREMENTS_UPDATE"] = "1"
# Official AP source test loader: limit headless development to this world and
# AP's standard fixtures. Generation/server still use the actual AP core.
os.environ["AP_TEST_WORLDS"] = "dead_as_disco"
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(AP_ROOT))


def package(root):
    output = root / "dead_as_disco.apworld"
    if not output.exists():
        root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as z:
            z.writestr("archipelago.json", json.dumps({"version": 7, "compatible_version": 7,
                "game": "Dead as Disco", "world_version": json.loads((SOURCE/'catalog.json').read_text())['world_version'], "minimum_ap_version": "0.6.8"}))
            for path in sorted(SOURCE.glob("*")):
                if path.is_file() and path.suffix in (".py", ".json"):
                    z.write(path, "dead_as_disco/" + path.name)
    installed = AP_ROOT / "custom_worlds/dead_as_disco.apworld"
    installed.parent.mkdir(exist_ok=True)
    if not installed.exists() or installed.read_bytes() != output.read_bytes():
        shutil.copyfile(output, installed)  # only our named file in the ignored clone
    return output


def generate(root):
    package(root)
    from Generate import main, mystery_argparse
    from Main import main as generate_world
    output = root / "output"
    if output.exists():
        raise RuntimeError("Preserve generated seed; choose a new run name")
    players = root / "players"; players.mkdir(exist_ok=True)
    shutil.copyfile(Path(args.yaml) if args.yaml else WORKSPACE / "archipelago/Dead as Disco.yaml", players / "DiscoSlice.yaml")
    options = mystery_argparse(["--player_files_path", str(players), "--seed", str(args.seed),
        "--multi", "1", "--spoiler", "1", "--outputpath", str(output)])
    erargs, seed = main(options)
    world = generate_world(erargs, seed)
    instance = world.worlds[1]
    content = instance.content
    locations = [loc for loc in world.get_locations(1) if loc.address is not None]
    if (set(loc.address for loc in locations) != {r["id"] for r in instance.rows}
            or not {loc.item.code for loc in locations} <= {r["id"] for r in content["items"]}
            or len(locations) != len(instance.rows)
            or any(loc.item is None for loc in locations)):
        raise RuntimeError("Generated real-content location/item IDs differ from manifest")
    paths = list(output.glob("*.archipelago")) or list(output.glob("*.zip"))
    if len(paths) != 1:
        raise RuntimeError("Expected one generated multidata")
    result = {"seed_name": world.seed_name, "game": "Dead as Disco", "player": 1,
              "slot": world.player_name[1], "multidata": str(paths[0]), "locations": len(locations), "items": len(locations),
              "location_ids": [loc.address for loc in locations], "item_ids": [loc.item.code for loc in locations],
              "ap_source_commit": subprocess.check_output(["git", "-C", str(AP_ROOT), "rev-parse", "HEAD"], text=True).strip(),
              "package_sha256": hashlib.sha256((root / "dead_as_disco.apworld").read_bytes()).hexdigest(),
              "pool": content["pool"], "event_locations": len(world.get_locations(1)) - len(locations),
              "content_sha256": hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()}
    (root / "generation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (root / 'catalog.json').write_text(json.dumps(content,indent=2),encoding='utf-8')
    (root / 'slot-data.json').write_text(json.dumps(instance.fill_slot_data(),indent=2),encoding='utf-8')
    print(f"PASS: actual AP generation completed: {len(locations)} checks, {len(set(loc.item.code for loc in locations))} item types.")


async def server(root):
    package(root)
    import MultiServer
    metadata = json.loads((root / "generation.json").read_text(encoding="utf-8"))
    sys.argv = ["MultiServer", metadata["multidata"], "--host", "127.0.0.1", "--port", str(args.port),
                "--disable_item_cheat", "--release_mode", "disabled", "--collect_mode", "disabled"]
    await MultiServer.main(MultiServer.parse_args())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["Tests", "Generate", "Server"])
    parser.add_argument("--run", default="ap-slice-20261005")
    parser.add_argument("--port", type=int, default=38281)
    parser.add_argument('--yaml')
    parser.add_argument('--seed',type=int,default=3404260)
    args = parser.parse_args()
    if not args.run.replace("-", "").isalnum() or len(args.run) > 48:
        raise ValueError("Safe run name required")
    root = WORKSPACE / "artifacts/ap-slice" / args.run
    if args.action == "Tests":
        suite = unittest.defaultTestLoader.discover(str(WORKSPACE / "archipelago/tests"))
        if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful(): sys.exit(1)
    elif args.action == "Generate": generate(root)
    else: asyncio.run(server(root))
