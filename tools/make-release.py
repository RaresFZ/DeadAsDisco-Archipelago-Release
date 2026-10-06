"""Assemble the player package: a Windows application folder (no Python/Archipelago install needed to PLAY).

    python tools/make-release.py --version 0.5.6

Writes artifacts/ap-release/DeadAsDiscoAP-<version>-windows.zip (refuses to overwrite). --version is the release of the app;
the apworld and the YAML carry the world version from catalog.json (unchanged unless multiworlds become incompatible). Contains no saves, proofs or
credentials. The pinned UE4SS archive (MIT licensed) is bundled from tools/downloads and hash-verified here.
"""
import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from archipelago.dadap import pins  # noqa: E402

LUA = ["authority", "plain-json", "purchase", "proof", "production", "deathlink", "skill-locations", "power-removal",
       "access", "traps", "health-effect", "players", "credits", "main"]
CERT_EVIDENCE = ["archipelago/data/evidence/ap-cold-20261006b-round-trip.json", "archipelago/data/evidence/ap-fresh-profile-20261006-live.json"]
APP = ROOT / "artifacts/ap-app"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_app():
    if (APP / "dist").exists():
        shutil.rmtree(APP / "dist")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed", "--name", "DeadAsDiscoAP",
                    "--paths", str(ROOT), "--hidden-import", "websockets.asyncio.client", "--distpath", str(APP / "dist"),
                    "--workpath", str(APP / "work"), "--specpath", str(APP), str(ROOT / "tools/dadap_app.py")],
                   check=True, cwd=ROOT)
    return APP / "dist/DeadAsDiscoAP"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise SystemExit("semantic version required")
    catalog = json.loads((ROOT / "archipelago/apworld/dead_as_disco/catalog.json").read_text(encoding="utf-8"))
    # The release version names the app package; the world version (catalog.json) only changes when generated multiworlds
    # become incompatible, so a client-only fix can ship as a new release of the same world.
    world_version = catalog["world_version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", world_version):
        raise SystemExit("catalog world_version must be a semantic version")
    ue4ss = ROOT / "tools/downloads/ue4ss-dev-1152.zip"
    if sha(ue4ss) != pins.UE4SS_ARCHIVE_SHA256:
        raise SystemExit("local UE4SS archive does not match the pinned hash")
    output = ROOT / "artifacts/ap-release" / f"DeadAsDiscoAP-{args.version}-windows.zip"
    if output.exists():
        raise SystemExit("Preserve released package; choose a new version")
    subprocess.run([sys.executable, str(ROOT / "tools/audit-release.py")], check=True, cwd=ROOT)
    app = build_app()
    data = {}  # path relative to the data root -> source file
    for name in LUA:
        data[f"archipelago/game-mod/{name}.lua"] = ROOT / f"archipelago/game-mod/{name}.lua"
    data["tools/runtime/Common/ue-values.lua"] = ROOT / "tools/runtime/Common/ue-values.lua"
    data["tools/runtime/SyncProof/Scripts/sync-scopes.lua"] = ROOT / "tools/runtime/SyncProof/Scripts/sync-scopes.lua"
    data["archipelago/apworld/dead_as_disco/catalog.json"] = ROOT / "archipelago/apworld/dead_as_disco/catalog.json"
    for name in CERT_EVIDENCE:
        data[name] = ROOT / name
    pinned = {key: sha(path) for key, path in data.items() if key.startswith(("archipelago/game-mod/", "tools/runtime/")) or key in CERT_EVIDENCE}
    pinned["archipelago/client/production.py"] = sha(ROOT / "archipelago/client/production.py")
    certificate = {"status": "verified-protected-passive-grant-cold", "max_health_delta": 10, "duplicate_health_delta": 0,
                   "release_version": args.version, "world_version": world_version, "evidence": CERT_EVIDENCE, "sources": pinned}
    # The certificate pins the client source too; ship it as data so the pin is checkable on the player machine.
    data["archipelago/client/production.py"] = ROOT / "archipelago/client/production.py"
    top = {"README.md": ROOT / "README.md",
           "FINAL_AUDIT.md": ROOT / "docs/FINAL_AUDIT.md", "LICENSE": ROOT / "LICENSE",
           "THIRD_PARTY_NOTICES.md": ROOT / "THIRD_PARTY_NOTICES.md"}
    manifest = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        def add(name, path):
            archive.write(path, "DeadAsDiscoAP/" + name)
            manifest[name] = sha(path)
        for path in sorted(app.rglob("*")):
            if path.is_file():
                add(path.relative_to(app).as_posix(), path)
        for name, path in sorted(data.items()):
            add("data/" + name, path)
        add("data/vendor/" + pins.UE4SS_ARCHIVE_NAME, ue4ss)
        for name, path in sorted(top.items()):
            add(name, path)
        yaml_text = (ROOT / "archipelago/Dead as Disco.yaml").read_text(encoding="utf-8")
        yaml_text, replaced = re.subn(r"(?m)^(    Dead as Disco: )\S+", lambda m: m.group(1) + world_version, yaml_text)
        if replaced != 1:
            raise SystemExit("YAML requires.game version line not found")
        archive.writestr("DeadAsDiscoAP/Dead as Disco.yaml", yaml_text)
        manifest["Dead as Disco.yaml"] = hashlib.sha256(yaml_text.encode()).hexdigest()
        archive.writestr("DeadAsDiscoAP/dead_as_disco.apworld", _apworld(ROOT / "archipelago/apworld/dead_as_disco", world_version))
        text = json.dumps(certificate, indent=2, sort_keys=True)
        archive.writestr("DeadAsDiscoAP/data/archipelago/capabilities.json", text)
        manifest["data/archipelago/capabilities.json"] = hashlib.sha256(text.encode()).hexdigest()
        archive.writestr("DeadAsDiscoAP/manifest.json", json.dumps(manifest, indent=1, sort_keys=True))
    print(json.dumps({"package": str(output.relative_to(ROOT)), "files": len(manifest) + 2,
                      "megabytes": round(output.stat().st_size / 1e6, 1), "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))


def _apworld(world_dir, version):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("archipelago.json", json.dumps({"version": 7, "compatible_version": 7, "game": "Dead as Disco",
                                                   "world_version": version, "minimum_ap_version": "0.6.8"}))
        for path in sorted(world_dir.glob("*")):
            if path.is_file() and path.suffix in (".py", ".json"):
                z.write(path, "dead_as_disco/" + path.name)
    return buffer.getvalue()


if __name__ == "__main__":
    main()
