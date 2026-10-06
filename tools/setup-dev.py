"""One-command developer setup (works from a fresh clone, no other workspace needed).

    python tools/setup-dev.py            # .venv + Python packages + Archipelago 0.6.8 source checkout
    python tools/setup-dev.py --release  # additionally download the pinned UE4SS archive needed by make-release.py

Everything lands in git-ignored folders (.venv, artifacts/references, tools/downloads). Requires Python 3.12+ and git.
Node.js 20+ is only needed for `node tools/test-ap-catalog.mjs` and the decoder parity tests.
"""
import argparse
import hashlib
import subprocess
import sys
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from archipelago.dadap import pins  # noqa: E402

AP_URL = "https://github.com/ArchipelagoMW/Archipelago.git"
AP_TAG = "0.6.8"
AP_DIR = ROOT / "artifacts/references/Archipelago-0.6.8"
VENV = ROOT / ".venv"


def venv_python():
    return VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def run(*command):
    print("+", " ".join(str(part) for part in command))
    subprocess.run([str(part) for part in command], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true", help="also download the pinned UE4SS archive (for make-release.py)")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        sys.exit("Python 3.12 or newer is required.")
    if not venv_python().is_file():
        venv.create(VENV, with_pip=True)
    run(venv_python(), "-m", "pip", "install", "--quiet", "-r", ROOT / "archipelago/requirements-headless.txt",
        "-r", ROOT / "requirements-dev.txt")
    if not (AP_DIR / "Generate.py").is_file():
        AP_DIR.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--quiet", "--depth", "1", "--branch", AP_TAG, AP_URL, AP_DIR)
    if args.release:
        target = ROOT / "tools/downloads/ue4ss-dev-1152.zip"
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            print("downloading", pins.UE4SS_ARCHIVE_URL)
            urllib.request.urlretrieve(pins.UE4SS_ARCHIVE_URL, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != pins.UE4SS_ARCHIVE_SHA256:
            target.unlink()
            sys.exit(f"UE4SS archive hash mismatch ({digest}); file removed. Expected {pins.UE4SS_ARCHIVE_SHA256}.")
        print("UE4SS archive verified")
    print("Setup complete. Next:")
    print(f"  {venv_python()} tools/ap-slice-dev.py Tests")
    print(f"  {venv_python()} tools/run-lua-tests.py")


if __name__ == "__main__":
    main()
