"""Reversible play sessions: park the player's real saves, swap in an AP profile, always restore.

Safety contract (mirrors the verified development harness):
  * originals are copied to a hash-verified backup AND parked by atomic same-volume rename; never deleted
  * the live Saved directory is only ever an AP profile while a session is open
  * the single proxy DLL is installed with exclusive create and removed only if its hash is unchanged
  * `restore` is idempotent and handles a crash at every step, so `recover` is always safe to run
"""
import os
import subprocess
import time
from pathlib import Path

from . import pins
from .fsutil import SafetyError, copy_tree, manifest, read_json, sha256_file, verify, write_json

SETTINGS_FILES = ("SaveGames/SharedGameSettings.sav", "SaveGames/EnhancedInputUserSettings.sav",
                  "SaveGames/GameUserSettings.sav", "Config/Windows/GameUserSettings.ini",
                  "Pagoda_PCD3D_SM6.upipelinecache")


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # a windowed app must never flash a console for helper calls


class Probe:
    """Process queries. Replaceable so tests never need a real game."""

    def _images(self):
        output = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, creationflags=NO_WINDOW).stdout
        return [line.split('","')[0].strip('"').lower() for line in output.splitlines() if line.strip()]

    def game_running(self):
        return any(name.startswith("pagoda") for name in self._images())

    def steam_running(self):
        return any(name in ("steam.exe", "steamwebhelper.exe") for name in self._images())

    def game_pid(self):
        output = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {pins.EXE_NAME}"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, creationflags=NO_WINDOW).stdout
        for line in output.splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) > 1 and parts[0].lower() == pins.EXE_NAME.lower():
                return int(parts[1])
        return None

    def external_tcp(self, pid):
        """Remote endpoints of established non-loopback TCP connections owned by pid."""
        output = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", check=True).stdout
        remotes = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[-1] == str(pid) and parts[3] == "ESTABLISHED":
                if not (parts[2].startswith("127.") or parts[2].startswith("[::1]")):
                    remotes.append(parts[2])
        return remotes


def new_session_id():
    import secrets
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def _same_volume(a, b):
    return os.stat(a).st_dev == os.stat(b).st_dev


def _rename(source, destination, attempts=20):
    """Directory rename with short retries: antivirus or a closing game may hold a handle briefly."""
    for attempt in range(attempts):
        try:
            os.rename(source, destination)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)


def assert_closed(probe):
    if probe.game_running():
        raise SafetyError("Close Dead as Disco completely before changing saves.")
    if probe.steam_running():
        raise SafetyError("Exit Steam completely (saves are swapped; Steam Cloud must not observe the swap).")


def wait_closed(probe, log=print, sleep=time.sleep, timeout=1800, poll=5):
    """Block until the game AND Steam are fully closed (the game starts Steam when it launches)."""
    announced = False
    deadline = time.monotonic() + timeout
    while probe.game_running() or probe.steam_running():
        if time.monotonic() > deadline:
            raise SafetyError("Timed out waiting for the game and Steam to close")
        if not announced:
            log("Waiting for the game and Steam to close completely (right-click the Steam tray icon -> Exit)...")
            announced = True
        sleep(poll)


def active_session(layout):
    return read_json(layout.pointer) if layout.pointer.is_file() else None


def begin(layout, profile, probe, check_exe=True, sid=None, copy_source=None):
    if active_session(layout):
        raise SafetyError("An unfinished session exists. Run recover before starting another.")
    assert_closed(probe)
    if check_exe:
        if not layout.exe.is_file() or sha256_file(layout.exe) != pins.EXE_SHA256:
            raise SafetyError(f"Unsupported game build; verified only for {pins.BUILD}.")
    sid = sid or new_session_id()
    session_dir = layout.session_dir(sid)
    if session_dir.exists():
        raise SafetyError("Session id already used")
    saved, parked, backup = layout.saved_dir, layout.parked_dir(sid), layout.backup_dir(sid)
    if parked.exists():
        raise SafetyError("Parked originals already exist; investigate first")
    present = saved.is_dir()
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    if present and not _same_volume(saved, layout.state_dir):
        raise SafetyError("State directory must share a volume with the game saves")
    files = manifest(saved) if present else []
    if present:
        backup.parent.mkdir(parents=True)
        copy_tree(saved, backup)
    state = {"sid": sid, "status": "isolation-pending", "profile": profile, "saved": str(saved), "parked": str(parked),
             "backup": str(backup) if present else None, "originals_present": present, "files": files,
             "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "proxy": None, "mod": False,
             "copySource": copy_source}
    write_json(session_dir / "session.json", state)
    write_json(layout.pointer, {"sid": sid})
    if present:
        _rename(saved, parked)
    profile_saved = layout.profile_dir(profile) / "Saved"
    if profile_saved.is_dir():
        copy_tree(profile_saved, saved)
        state["profile_fresh"] = False
    else:
        saved.mkdir(parents=True)
        for relative in SETTINGS_FILES:  # preferences only; never progression
            source = parked / relative
            if present and source.is_file():
                (saved / relative).parent.mkdir(parents=True, exist_ok=True)
                (saved / relative).write_bytes(source.read_bytes())
        state["profile_fresh"] = True
    state["status"] = "isolated"
    write_json(session_dir / "session.json", state)
    return state


def _load(layout, sid):
    return read_json(layout.session_dir(sid) / "session.json")


def _save(layout, state):
    write_json(layout.session_dir(state["sid"]) / "session.json", state)


def install_proxy(layout, sid):
    state = _load(layout, sid)
    if state["status"] != "isolated":
        raise SafetyError("Isolated save transaction required before proxy installation")
    source = layout.core_dir / "dwmapi.dll"
    if sha256_file(source) != pins.PROXY_SHA256:
        raise SafetyError("Pinned proxy source changed")
    for name in ("override.txt", "UE4SS.dll", "ue4ss", "xinput1_3.dll", "Mods"):
        if (layout.bin_dir / name).exists():
            raise SafetyError(f"Forbidden core/mod/runtime path present in game directory: {name}")
    target = layout.proxy_target
    if target.exists():
        raise SafetyError("Proxy destination exists; refusing replacement")
    state["proxy"] = {"installed": True, "sha256": pins.PROXY_SHA256}
    _save(layout, state)  # intent first: a crash here is repaired by restore
    with open(source, "rb") as src, open(target, "xb") as dst:
        dst.write(src.read())
    if sha256_file(target) != pins.PROXY_SHA256:
        raise SafetyError("Installed proxy hash mismatch")
    return state


def remove_proxy(layout, state):
    proxy = state.get("proxy")
    if not proxy or not proxy.get("installed"):
        return False
    target = layout.proxy_target
    if target.exists():
        if sha256_file(target) != proxy["sha256"]:
            raise SafetyError("Proxy changed; preserved, refusing removal")
        target.unlink()
    state["proxy"] = {"installed": False, "sha256": proxy["sha256"]}
    return True


def launch(layout, sid, core=None, runner=subprocess.Popen):
    """Offline launch. With a core directory the proxy is told exactly which UE4SS.dll to load."""
    state = _load(layout, sid)
    if state["status"] != "isolated":
        raise SafetyError("Isolated save transaction required before launch")
    command = f'"{layout.exe}" {pins.LAUNCH_ARGUMENTS}'
    if core is not None:
        for scope in ("UE4SS_MODS_PATHS",):
            if os.environ.get(scope):
                raise SafetyError("External UE4SS mod environment override present")
        command += f' --ue4ss-path "{Path(core) / "UE4SS.dll"}"'
        state["mod"] = True
    process = runner(command, cwd=str(layout.bin_dir))
    state["launch"] = {"command": command, "pid": getattr(process, "pid", None), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _save(layout, state)
    return process


def wait_for_game(probe, appear_timeout=180, poll=2.0, sleep=time.sleep, settle=20, log=lambda message: None):
    """Block until the game has appeared and then fully exited.

    The first shipping process hands over to a relaunched child with a new pid, so liveness is judged by any
    Pagoda process (launcher included) and an exit must persist for the whole settle period.
    """
    deadline = time.monotonic() + appear_timeout
    while not probe.game_running():
        if time.monotonic() > deadline:
            raise SafetyError("Game never started")
        sleep(poll)
    log("Game process detected.")
    gone = 0.0
    while gone < settle:
        gone = 0.0 if probe.game_running() else gone + poll
        sleep(poll)
    log("Game process has exited.")


def _capture(layout, state, destination_name):
    """Move the live (AP) Saved tree out of the way without deleting anything."""
    saved = Path(state["saved"])
    if not saved.is_dir():
        return None
    profile = layout.profile_dir(state["profile"])
    profile.mkdir(parents=True, exist_ok=True)
    if destination_name == "profile":
        incoming = profile / f"Saved.incoming-{state['sid']}"
        _rename(saved, incoming)
        active = profile / "Saved"
        if active.exists():
            _rename(active, profile / f"Saved.prev-{state['sid']}")
        _rename(incoming, active)
        return active
    partial = layout.session_dir(state["sid"]) / "partial-active"
    _rename(saved, partial)
    return partial


def restore(layout, probe):
    """Idempotent: safe after a clean finish, a crash at any step, or repeatedly."""
    pointer = active_session(layout)
    if not pointer:
        return None
    state = _load(layout, pointer["sid"])
    if state["status"] == "restored":
        layout.pointer.unlink()
        return state
    assert_closed(probe)
    changed = remove_proxy(layout, state)
    if changed:
        _save(layout, state)
    saved, parked = Path(state["saved"]), Path(state["parked"])
    if state["originals_present"]:
        if parked.is_dir():
            verify(parked, state["files"])
            if saved.is_dir():
                _capture(layout, state, "profile" if state["status"] == "isolated" else "partial")
            _rename(parked, saved)
        verify(saved, state["files"])
    elif saved.is_dir():
        _capture(layout, state, "profile" if state["status"] == "isolated" else "partial")
    state["status"] = "restored"
    state["restored_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save(layout, state)
    layout.pointer.unlink()
    return state
