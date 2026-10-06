"""Local AP server for a generated run with an operator command channel (protected test instrumentation).

Operator writes console lines (e.g. '/send Slot "Fever Rush"') into <run>/live/commands/NAME.txt; each file is
piped once to the server console and renamed *.done. Create <run>/live/stop.request to shut the server down.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--port", type=int, default=38281)
    args = parser.parse_args()
    live = ROOT / "artifacts/ap-slice" / args.run / "live"
    commands = live / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    stop = live / "stop.request"
    env = os.environ.copy()
    env["AP_TEST_WORLDS"] = "dead_as_disco"
    env["SKIP_REQUIREMENTS_UPDATE"] = "1"
    log = (live / f"server-{int(time.time())}.log").open("wb")
    server = subprocess.Popen([sys.executable, str(ROOT / "tools/ap-slice-dev.py"), "Server", "--run", args.run,
                               "--port", str(args.port)], cwd=ROOT, env=env, stdin=subprocess.PIPE,
                              stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print(f"AP server pid {server.pid} on ws://127.0.0.1:{args.port} (run {args.run})", flush=True)
    try:
        while server.poll() is None and not stop.exists():
            for command in sorted(commands.glob("*.txt")):
                for line in command.read_text(encoding="utf-8").splitlines():
                    server.stdin.write((line + "\n").encode())
                server.stdin.flush()
                command.rename(command.with_suffix(".done"))
                print("sent", command.name, flush=True)
            time.sleep(0.5)
    finally:
        if server.poll() is None:
            try:
                server.communicate(b"/exit\n", timeout=15)
            except Exception:
                server.kill()


if __name__ == "__main__":
    main()
