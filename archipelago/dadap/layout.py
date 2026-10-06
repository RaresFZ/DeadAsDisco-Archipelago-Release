"""Where everything lives. Every path is explicit so the same code runs against a sandbox in tests."""
import os
from pathlib import Path

from . import pins


class Layout:
    def __init__(self, game_dir, saved_dir, state_dir):
        self.game_dir = Path(game_dir)
        self.saved_dir = Path(saved_dir)
        self.state_dir = Path(state_dir)

    @classmethod
    def default(cls, game_dir=None):
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return cls(game_dir or find_game_dir(), local / "Pagoda" / "Saved", local / "DeadAsDiscoAP")

    @property
    def bin_dir(self):
        return self.game_dir / "Pagoda" / "Binaries" / "Win64"

    @property
    def exe(self):
        return self.bin_dir / pins.EXE_NAME

    @property
    def proxy_target(self):
        return self.bin_dir / "dwmapi.dll"

    @property
    def core_dir(self):
        return self.state_dir / "core"

    @property
    def pointer(self):
        return self.state_dir / "current-session.json"

    def session_dir(self, sid):
        return self.state_dir / "sessions" / sid

    def backup_dir(self, sid):
        return self.state_dir / "backups" / sid / "Saved"

    def profile_dir(self, name):
        return self.state_dir / "profiles" / name

    def parked_dir(self, sid):
        # Same volume as the live Saved directory so parking is an atomic rename.
        return self.saved_dir.parent / f"Saved.AP-{sid}-original"


def find_game_dir():
    """Best-effort Steam library search; callers may always pass the directory explicitly."""
    candidates = []
    for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if root:
            candidates.append(Path(root) / "Steam")
    for steam in candidates:
        direct = steam / "steamapps" / "common" / "Dead as Disco"
        if direct.is_dir():
            return direct
        library = steam / "steamapps" / "libraryfolders.vdf"
        if library.is_file():
            import re
            for path in re.findall(r'"path"\s+"([^"]+)"', library.read_text(encoding="utf-8", errors="replace")):
                candidate = Path(path.replace("\\\\", "\\")) / "steamapps" / "common" / "Dead as Disco"
                if candidate.is_dir():
                    return candidate
    raise FileNotFoundError("Dead as Disco install not found; pass --game-dir")
