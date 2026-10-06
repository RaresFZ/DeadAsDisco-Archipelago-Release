"""Pinned UE4SS core staging. The game directory only ever receives the single proxy DLL, and only during a session."""
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from . import pins
from .fsutil import SafetyError, read_json, sha256_file, write_json

MOD_NAME = "APBridge"
MOD_FILES = ("main.lua", "authority.lua", "plain-json.lua", "purchase.lua", "proof.lua", "production.lua",
             "deathlink.lua", "skill-locations.lua", "power-removal.lua", "access.lua", "traps.lua",
             "health-effect.lua", "players.lua", "credits.lua", "ue-values.lua", "sync-scopes.lua")
HOOKS_EXPECTED = 14


def customize_settings(template, core_dir):
    """Exactly the verified isolated-core configuration: workspace Mods, no console, EngineTick only."""
    core_dir = Path(core_dir)
    values = {"ModsFolderPath": str(core_dir / "Mods"), "ControllingModsTxt": str(core_dir / "Mods" / "mods.txt"),
              "ConsoleEnabled": "0", "GuiConsoleEnabled": "0", "GuiConsoleVisible": "0",
              "EnableHotReloadSystem": "0", "EnableAutoReloadingLuaMods": "0", "UseCache": "0",
              "bUseUObjectArrayCache": "false", "bForceGUObjectArrayForIteration": "true", "DoEarlyScan": "0",
              "LoadAllAssetsBeforeDumpingObjects": "0", "LoadAllAssetsBeforeGeneratingCXXHeaders": "0",
              "RenderMode": "ExternalThread", "EnableDumping": "1", "FullMemoryDump": "0"}
    text = template
    for key, value in values.items():
        pattern = re.compile(r"(?m)^" + re.escape(key) + r"\s*=.*$")
        if len(pattern.findall(text)) != 1:
            raise SafetyError(f"Ambiguous/missing UE4SS setting: {key}")
        text = pattern.sub(lambda _m, k=key, v=value: f"{k} = {v}", text)
    hooks = re.findall(r"(?m)^(Hook\w+)\s*=.*$", text)
    if len(hooks) != HOOKS_EXPECTED:
        raise SafetyError("Unexpected UE4SS hook setting schema")
    for key in hooks:
        text = re.sub(r"(?m)^" + key + r"\s*=.*$", lambda _m, k=key: f"{k} = {'1' if k == 'HookEngineTick' else '0'}", text)
    if "[General]" not in text:
        raise SafetyError("UE4SS settings lack [General]")
    return text.replace("[General]", "[General]\nEnableDebugKeyBindings = 0", 1)


def install_core(layout, archive):
    """Extract only the verified files from the pinned UE4SS archive into the private state directory."""
    archive = Path(archive)
    if sha256_file(archive) != pins.UE4SS_ARCHIVE_SHA256:
        raise SafetyError(f"UE4SS archive pin mismatch; download {pins.UE4SS_ARCHIVE_NAME} from {pins.UE4SS_ARCHIVE_URL}")
    core = layout.core_dir
    if core.exists():
        raise SafetyError("Core already installed; uninstall first")
    with tempfile.TemporaryDirectory() as temporary, zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        for required in ("dwmapi.dll", "ue4ss/UE4SS.dll", "ue4ss/UE4SS-settings.ini"):
            if required not in names:
                raise SafetyError(f"Archive lacks {required}")
        for required in ("dwmapi.dll", "ue4ss/UE4SS.dll", "ue4ss/UE4SS-settings.ini"):
            bundle.extract(required, temporary)
        temporary = Path(temporary)
        if sha256_file(temporary / "dwmapi.dll") != pins.PROXY_SHA256:
            raise SafetyError("Proxy DLL pin mismatch")
        if sha256_file(temporary / "ue4ss" / "UE4SS.dll") != pins.UE4SS_DLL_SHA256:
            raise SafetyError("UE4SS DLL pin mismatch")
        core.mkdir(parents=True)
        shutil.copyfile(temporary / "dwmapi.dll", core / "dwmapi.dll")
        shutil.copyfile(temporary / "ue4ss" / "UE4SS.dll", core / "UE4SS.dll")
        shutil.copyfile(temporary / "ue4ss" / "UE4SS-settings.ini", core / "UE4SS-settings.template.ini")
    write_json(core / "core.json", {"archive_sha256": pins.UE4SS_ARCHIVE_SHA256, "build": pins.BUILD,
                                    "files": ["dwmapi.dll", "UE4SS.dll", "UE4SS-settings.template.ini"]})


def assemble_session_core(layout, sid, mod_sources, config_lua, selection_lua):
    """Per-session copy: single-use log, absolute paths and the session's private binding config."""
    session_core = layout.session_dir(sid) / "core"
    if session_core.exists():
        raise SafetyError("Session core already assembled")
    template = (layout.core_dir / "UE4SS-settings.template.ini").read_text(encoding="utf-8")
    scripts = session_core / "Mods" / MOD_NAME / "Scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(layout.core_dir / "UE4SS.dll", session_core / "UE4SS.dll")
    (session_core / "UE4SS-settings.ini").write_text(customize_settings(template, session_core), encoding="utf-8", newline="\n")
    (session_core / "Mods" / "mods.txt").write_text(f"{MOD_NAME} : 1\n", encoding="utf-8", newline="\n")
    for name in MOD_FILES:
        found = [Path(d) / name for d in mod_sources if (Path(d) / name).is_file()]
        if not found:
            raise SafetyError(f"Mod file not found in any source directory: {name}")  # first directory wins
        shutil.copyfile(found[0], scripts / name)
    (scripts / "ap-config.lua").write_text(config_lua, encoding="utf-8", newline="\n")
    (scripts / "sync-selection.lua").write_text(selection_lua, encoding="utf-8", newline="\n")
    return session_core
