"""`dadap doctor`: read-only diagnosis of the install. It never launches, moves or writes anything."""
import shutil
from pathlib import Path

from . import pins
from .fsutil import read_json, sha256_file


def _size(path):
    total = 0
    for item in Path(path).rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def diagnose(layout, probe, ap_root=None):
    """[(level, check, detail)] with level in OK / WARN / FAIL."""
    results = []

    def add(level, check, detail):
        results.append((level, check, detail))

    exe = layout.exe
    if not exe.is_file():
        add("FAIL", "game", f"{pins.EXE_NAME} not found under {layout.game_dir}")
    elif sha256_file(exe) != pins.EXE_SHA256:
        add("FAIL", "game build", f"unsupported build; verified only for {pins.BUILD}")
    else:
        add("OK", "game build", pins.BUILD)
    core = layout.core_dir
    if not (core / "UE4SS.dll").is_file():
        add("FAIL", "UE4SS core", "not installed; run: setup --ue4ss-archive <zip>")
    else:
        good = (sha256_file(core / "UE4SS.dll") == pins.UE4SS_DLL_SHA256 and
                (core / "dwmapi.dll").is_file() and sha256_file(core / "dwmapi.dll") == pins.PROXY_SHA256)
        add("OK" if good else "FAIL", "UE4SS core", "pinned files verified" if good else "files differ from the pinned build; reinstall")
    if layout.proxy_target.exists():
        add("FAIL", "game folder", "dwmapi.dll is present in the game folder; run recover")
    else:
        add("OK", "game folder", "clean (no proxy DLL)")
    pointer = layout.pointer
    if pointer.is_file():
        add("FAIL", "session", f"unfinished session {read_json(pointer).get('sid')}; run recover")
    else:
        add("OK", "session", "no unfinished session")
    if probe.game_running():
        add("WARN", "processes", "the game is running")
    elif probe.steam_running():
        add("WARN", "processes", "Steam is running; exit it before a session")
    else:
        add("OK", "processes", "game and Steam are closed")
    saved = layout.saved_dir
    if not saved.is_dir():
        add("WARN", "saves", f"no save folder at {saved} (fine for a never-played install)")
    else:
        need = _size(saved) * 3 + 500 * 1024 * 1024
        anchor = layout.state_dir if layout.state_dir.exists() else saved.parent
        free = shutil.disk_usage(anchor).free
        add("OK" if free >= need else "FAIL", "disk space", f"{free // (1 << 20)} MB free, {need // (1 << 20)} MB needed (backup + profile)")
        same = saved.stat().st_dev == anchor.stat().st_dev
        add("OK" if same else "FAIL", "volume", "saves and state share a volume (atomic parking)" if same else
            "state folder must be on the same drive as the game saves")
    if ap_root:
        root = Path(ap_root)
        add("OK" if (root / "CommonClient.py").is_file() else "FAIL", "Archipelago",
            f"CommonClient found under {root}" if (root / "CommonClient.py").is_file() else f"{root} is not an Archipelago source checkout")
    profiles = layout.state_dir / "profiles"
    if profiles.is_dir():
        for profile in sorted(p for p in profiles.iterdir() if p.is_dir()):
            binding = profile / "binding.json"
            bound = f"bound to seed {read_json(binding)['seed']}" if binding.is_file() else "not bound yet"
            has_save = (profile / "Saved/SaveGames/PagodaPT_M_0.sav").is_file()
            add("OK", f"profile {profile.name}", f"{'has a save' if has_save else 'no save yet'}, {bound}")
    return results
