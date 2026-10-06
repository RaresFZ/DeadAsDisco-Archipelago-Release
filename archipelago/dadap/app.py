"""Entry point of the packaged application: no arguments opens the window; --client runs the AP client; otherwise the CLI."""
import sys


def _redirect_output():
    """A windowed (no console) executable has no stdout: keep a log file so problems are never silent."""
    if getattr(sys, "frozen", False) and sys.stdout is None:
        import os
        from pathlib import Path
        folder = Path(os.environ.get("LOCALAPPDATA", ".")) / "DeadAsDiscoAP"
        folder.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(folder / "last-run.log", "w", encoding="utf-8", buffering=1)


def main(argv=None):
    _redirect_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--client"]:
        from ..client.main import main as client_main
        sys.argv = [sys.argv[0]] + argv[1:]
        client_main()
        return 0
    if argv:
        from .cli import main as cli_main
        return cli_main(argv)
    from .gui import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
