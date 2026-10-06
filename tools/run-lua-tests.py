"""Run every Lua fixture (tools/test-ap-*.lua) from the repository root.

    python tools/run-lua-tests.py

Uses the embedded Lua 5.4 from the `lupa` package (installed by tools/setup-dev.py); set DAD_LUA to use a standalone
interpreter instead. Fixtures write scratch files under artifacts/ (git-ignored), which this runner creates.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_one(fixture):
    from lupa.lua54 import LuaRuntime
    os.chdir(ROOT)
    runtime = LuaRuntime()
    runtime.execute("arg = {}")  # the standalone interpreter provides this; fixtures read arg[1]
    runtime.globals().dofile(fixture)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--one":
        run_one(sys.argv[2])
        return 0
    (ROOT / "artifacts/runtime/fixtures").mkdir(parents=True, exist_ok=True)
    external = os.environ.get("DAD_LUA")
    failed = []
    for fixture in sorted((ROOT / "tools").glob("test-ap-*.lua")):
        relative = fixture.relative_to(ROOT).as_posix()
        command = [external, relative] if external else [sys.executable, str(Path(__file__).resolve()), "--one", relative]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        lines = (result.stdout or result.stderr).strip().splitlines()
        print(("PASS " if result.returncode == 0 else "FAIL ") + fixture.name + ("" if result.returncode == 0 else ": " + " | ".join(lines[-3:])))
        if result.returncode:
            failed.append(fixture.name)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
