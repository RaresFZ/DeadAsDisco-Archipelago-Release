"""Where everything lives. Every path is explicit so the same code runs against a sandbox in tests."""
import json
import os
import re
import string
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
        state_dir = local / "DeadAsDiscoAP"
        return cls(game_dir or find_game_dir(remembered_game_dir(state_dir)), local / "Pagoda" / "Saved", state_dir)

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


def is_game_dir(path):
    return (Path(path) / "Pagoda" / "Binaries" / "Win64" / pins.EXE_NAME).is_file()


def settings_file(state_dir):
    return Path(state_dir) / "gui-settings.json"


def remembered_game_dir(state_dir):
    """The folder the player picked by hand last time, if it is still a valid install."""
    try:
        chosen = json.loads(settings_file(state_dir).read_text(encoding="utf-8")).get("game_dir")
    except (OSError, ValueError, AttributeError):
        return None
    return Path(chosen) if chosen and is_game_dir(chosen) else None


def remember_game_dir(state_dir, game_dir):
    path = settings_file(state_dir)
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    settings["game_dir"] = str(game_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings), encoding="utf-8")


def _drive_roots():
    """Mounted drive letters only (never probes disconnected network drives)."""
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except (AttributeError, OSError):
        return []
    return [f"{letter}:/" for index, letter in enumerate(string.ascii_uppercase) if mask >> index & 1]


def steam_roots():
    """Every place a Steam installation may live: the registry, the default folders, and common folders on every drive."""
    roots = []
    try:
        import winreg
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(variable):
            roots.append(Path(os.environ[variable]) / "Steam")
    for drive in _drive_roots():
        for name in ("Steam", "SteamLibrary", "Program Files (x86)/Steam", "Program Files/Steam", "Games/Steam", "Games/SteamLibrary"):
            roots.append(Path(drive) / name)
    return roots


def find_game_dir(remembered=None, roots=None):
    """Find the Dead as Disco install: a remembered choice, then every Steam installation and every library it lists.

    Callers may always pass the directory explicitly (the window offers a folder picker when nothing is found).
    """
    if remembered and is_game_dir(remembered):
        return Path(remembered)
    candidates, seen = [], set()

    def consider(folder):
        key = os.path.normcase(str(folder))
        if key not in seen:
            seen.add(key)
            candidates.append(Path(folder) / "steamapps" / "common" / "Dead as Disco")

    for steam in (steam_roots() if roots is None else roots):
        steam = Path(steam)
        if not steam.is_dir():
            continue
        consider(steam)
        library = steam / "steamapps" / "libraryfolders.vdf"
        if library.is_file():
            for path in re.findall(r'"path"\s+"([^"]+)"', library.read_text(encoding="utf-8", errors="replace")):
                consider(path.replace("\\\\", "\\"))
    for candidate in candidates:
        if is_game_dir(candidate):
            return candidate
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("Dead as Disco install not found; pass --game-dir")