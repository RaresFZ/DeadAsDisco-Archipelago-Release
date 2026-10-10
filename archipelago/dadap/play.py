"""One AP play session: bind the profile to the AP slot, stage the mod, launch offline, run the client, always restore."""
import asyncio
import re
import threading
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from . import binding, core, gvas, pins, saved_state, session
from .fsutil import SafetyError, read_json, write_json

GAME_SLOT = "PagodaPT_M_0"
# A profile must be created before any mission is played: progress made outside AP can never be un-reported.
PROGRESS_FAMILIES = ("story", "rank", "difficulty", "challenge", "quest", "song")


def default_root():
    if getattr(sys, "frozen", False):  # packaged app: data files sit next to the executable
        return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parents[2]


def mod_sources(root):
    return [root / "archipelago/game-mod", root / "tools/runtime/Common", root / "tools/runtime/SyncProof/Scripts"]


def catalog_path(root):
    return root / "archipelago/apworld/dead_as_disco/catalog.json"


def content_hash(catalog):
    return hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()


async def preflight(server, slot, password, ap_root=None, timeout=20):
    """Authenticate once to learn the seed identity and slot data. Items/locations are never requested."""
    from ..client.apnet import NetContext as CommonContext, server_loop
    info, done = {}, asyncio.Event()

    class Peer(CommonContext):
        game = "Dead as Disco"
        items_handling = 0
        want_slot_data = True

        async def server_auth(self, password_requested=False):
            if password_requested and not self.password:
                info["error"] = "Server requires a password"
                done.set()
                return
            self.auth = slot
            await self.send_connect()

        def on_package(self, cmd, packet):
            if cmd == "Connected":
                info.update(seed=self.server_seed_name, team=self.team, player=self.slot, slot_data=packet.get("slot_data", {}))
                done.set()
            elif cmd == "ConnectionRefused":
                info["error"] = "Connection refused: " + ",".join(packet.get("errors", []))
                done.set()

    ctx = Peer(password)
    ctx.server_task = asyncio.create_task(server_loop(ctx, server))
    try:
        await asyncio.wait_for(done.wait(), timeout)
    except asyncio.TimeoutError:
        info["error"] = "No answer from the Archipelago server"
    finally:
        ctx.exit_event.set()
        await ctx.shutdown()
    if "error" in info:
        raise SafetyError(info["error"])
    return info


def _has_tutorial_saves(saved_dir):
    base = Path(saved_dir) / "SaveGames"
    return (base / "PagodaPT_M_0.sav").is_file() and (base / "PagodaGP_Main.sav").is_file()


def _profile_saves(saved_dir):
    base = Path(saved_dir) / "SaveGames"
    pt, gp = base / "PagodaPT_M_0.sav", base / "PagodaGP_Main.sav"
    if not pt.is_file() or not gp.is_file():
        raise SafetyError("The tutorial of this multiworld was not saved completely (the game has not written both of its save files). "
                          "Nothing was changed and your real saves are untouched. Press PLAY again, finish ONLY the tutorial, stay in the "
                          "hub, quit the game from its menu (do not close it with Alt+F4 or Task Manager) and close Steam.")
    return (gvas.read_tagged_save(pt.read_bytes(), pt.name), gvas.read_tagged_save(gp.read_bytes(), gp.name))


def ensure_binding(layout, profile, info, catalog, parsed_pt):
    """Create the profile<->slot binding once; afterwards the profile may only ever play this exact AP slot."""
    path = layout.profile_dir(profile) / "binding.json"
    identity = {"seed": info["seed"], "team": info["team"], "player": info["player"],
                "generation": hashlib.sha256(f"{info['seed']}:{info['team']}:{info['player']}".encode()).hexdigest()[:24],
                "game_slot": GAME_SLOT, "content_sha256": content_hash(catalog)}
    if path.is_file():
        existing = read_json(path)
        if {k: existing.get(k) for k in identity} != identity:
            raise SafetyError("This profile is bound to a different Archipelago slot/seed. Use a new profile for a new game.")
        return identity
    _, variables = saved_state.playthrough_variables(parsed_pt)
    progressed = [r["name"] for r in catalog["locations"] if r["family"] in PROGRESS_FAMILIES
                  and r["predicate"] != "node-interaction" and saved_state.completed(r, variables.get(r["tag"]))]
    if progressed:
        raise SafetyError("This profile already has game progress (" + ", ".join(progressed[:3]) +
                          "...). Create a fresh profile before binding it to an Archipelago slot.")
    write_json(path, {**identity, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return identity


def network_guard(probe, timeout=120, poll=5.0, sleep=time.sleep, log=print):
    """The offline launch must stay offline: require two consecutive clean samples of the game process.

    Startup can briefly touch local services; a connection that persists for the whole window is refused.
    """
    deadline = time.monotonic() + timeout
    clean, last = 0, []
    while clean < 2:
        pid = probe.game_pid()
        last = list(probe.external_tcp(pid)) if pid is not None else []
        clean = 0 if last else clean + 1
        if clean >= 2:
            return
        if time.monotonic() > deadline:
            raise SafetyError("The game kept external network connections open (" + ", ".join(last) + "); refusing to enable the AP bridge.")
        sleep(poll)


def wait_for_mod(core_dir, probe, timeout=300, sleep=time.sleep, marker="[APBridge] LOADED"):
    """Return once the game mod announced itself in the isolated UE4SS log."""
    log = Path(core_dir) / "UE4SS.log"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.is_file():
            text = log.read_text(encoding="utf-8", errors="replace")
            if marker in text:
                return
            if "Fatal error" in text:
                raise SafetyError("UE4SS reported a fatal error during startup")
        sleep(2)
    raise SafetyError("The game mod did not start in time")


def _client_runner(log, on_client=None, logfile=None):
    """Start the AP client headless and forward its messages (items received, checks, DeathLink...) to the window."""
    import threading

    def run(command, cwd):
        process = subprocess.Popen(command + ["--console"], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def pump():
            sink = open(logfile, "a", encoding="utf-8", buffering=1) if logfile else None
            for line in process.stdout:
                line = line.strip()
                if sink and line:
                    sink.write(line + "\n")
                if line:
                    log(line.split(":", 2)[-1].strip() if line.startswith(("INFO:", "WARNING:", "ERROR:")) else line)
        threading.Thread(target=pump, daemon=True).start()
        if on_client:
            on_client(process)
        return process
    return run


def _watch_bridge(path, stop, log):
    """Tell the player when the in-game bridge stopped itself, instead of silently doing nothing."""
    while not stop.wait(5):
        if Path(path).is_file():
            lines = [line.strip() for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
            reason = " | ".join(lines)[-400:] if lines else "unknown reason"
            log(f"!!! The game bridge stopped itself ({reason}). Checks and items are paused. Your saves are safe: quit the game and "
                f"click Play again. If it keeps happening, send the file {path}.")
            return


def derive_profile(slot, seed):
    """One profile per multiworld and slot, named from the seed so a regenerated game never collides."""
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{slot}-{str(seed)[:8]}").strip("-")
    return clean or "profile"


def play(layout, profile, server, slot, password=None, *, ap_root=None, features=None, certificate=None,
         install_root=None, probe=None, launch_runner=subprocess.Popen, client_runner=None,
         preflight_fn=None, wait_game=session.wait_for_game, mod_wait=wait_for_mod, guard=None, log=print, on_client=None):
    probe = probe or session.Probe()
    root = Path(install_root or default_root())
    catalog = json.loads(catalog_path(root).read_text(encoding="utf-8"))
    certificate = Path(certificate or root / "archipelago/capabilities.json")
    if not certificate.is_file():
        raise SafetyError("Missing capabilities certificate; this build cannot grant items")
    if not (layout.core_dir / "UE4SS.dll").is_file():
        archive = root / "vendor" / pins.UE4SS_ARCHIVE_NAME  # bundled with the app: first run installs it by itself
        if not archive.is_file():
            raise SafetyError("The mod loader is not installed and its archive is not bundled; run 'setup --ue4ss-archive <zip>'.")
        log("First run: installing the mod loader (private folder, the game folder is not touched)...")
        core.install_core(layout, archive)
    from . import capabilities
    if features is None and os.environ.get("DAD_TEST_FEATURES"):  # protected-test switch for unvalidated mechanisms
        raw = os.environ["DAD_TEST_FEATURES"].strip()
        features = "all" if raw == "all" else [name for name in raw.split(",") if name]
    caps = capabilities.resolve(features)
    info = (preflight_fn or (lambda: asyncio.run(preflight(server, slot, password, ap_root))))()
    slot_data = info["slot_data"]
    if slot_data.get("content_sha256") != content_hash(catalog):
        raise SafetyError("The multiworld was generated with a different Dead as Disco world version.")
    missing = [c for c in slot_data.get("required_capabilities", []) if not caps.get(capabilities.REQUIRED_KEYS.get(c, c))]
    if missing:
        raise SafetyError("This build has not validated: " + ", ".join(missing) + ". Generate with those options disabled.")
    session.wait_closed(probe, log)  # Steam/game still open? wait instead of failing
    profile = profile or derive_profile(slot, info["seed"])
    saved_profile = layout.profile_dir(profile) / "Saved"
    if not _has_tutorial_saves(saved_profile):
        # First time on this multiworld (or a tutorial that was closed before the game saved it completely): a vanilla tutorial run
        # creates/resumes the profile, then we continue straight into AP.
        from .cli import run_vanilla
        log("First time on this multiworld: the game opens for the TUTORIAL. Finish only the tutorial, stay in the hub, "
            "quit the game from its menu and close Steam. The Archipelago game then starts by itself.")
        run_vanilla(layout, profile, log)
    parsed_pt, _ = _profile_saves(saved_profile)
    identity = ensure_binding(layout, profile, info, catalog, parsed_pt)
    try:
        binding.pick_check_row(catalog, saved_state.playthrough_variables(parsed_pt)[1])  # fail before any save is moved
    except binding.BindingError as error:
        raise SafetyError(str(error))
    state = session.begin(layout, profile, probe, copy_source=str(saved_profile))
    sid = state["sid"]
    client = None
    stop_watch = threading.Event()
    try:
        sdir = layout.session_dir(sid)
        runtime = sdir / "runtime"
        runtime.mkdir(parents=True)
        sentinel = sdir / "parked-sentinel.txt"
        sentinel.write_text("originals are parked; see session.json\n", encoding="utf-8")
        proxy_file = sdir / "proxy-install.json"
        write_json(proxy_file, {"status": "pending"})
        pt, gp = _profile_saves(layout.saved_dir)
        token = secrets.token_hex(32)
        paths = {"session_file": str(sdir / "session.json"), "parked_sentinel": str(sentinel), "lease": str(sdir / "ap-launch.lease"),
                 "runtime_dir": str(runtime), "proxy_file": str(proxy_file), "parked": state["parked"], "source": str(saved_profile)}
        config_lua, selection_lua, protection, summary = binding.build_session(
            catalog=catalog, slot_data=slot_data, generation=identity["generation"], game_slot=GAME_SLOT, token=token,
            paths=paths, parsed_pt=pt, parsed_gp=gp, caps=caps,
            certificate_sha256=hashlib.sha256(certificate.read_bytes()).hexdigest())
        protection["saved_dir"] = str(layout.saved_dir)
        core_dir = core.assemble_session_core(layout, sid, mod_sources(root), config_lua, selection_lua)
        protection_file = sdir / "ap-protection.json"
        write_json(protection_file, protection)
        from ..client.production import publish_from_ledger
        publish_from_ledger(layout.profile_dir(profile) / "ledger.sqlite", catalog, protection)
        session.install_proxy(layout, sid)
        write_json(proxy_file, {"status": "installed"})
        log(f"Session {sid}: saves parked, profile '{profile}' active, mod staged ({summary['contexts']} contexts bound). Launching offline...")
        launch_runner_result = session.launch(layout, sid, core=core_dir, runner=launch_runner)
        mod_wait(core_dir, probe)
        (guard or network_guard)(probe, log=log)
        (sdir / "ap-launch.lease").write_text(token + "\n", encoding="utf-8", newline="\n")
        launcher = [sys.executable, "--client"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "archipelago.client.main"]
        command = launcher + ["--server", server, "--slot", slot, "--seed", identity["seed"],
                   "--team", str(identity["team"]), "--player", str(identity["player"]), "--generation", identity["generation"],
                   "--game-slot", GAME_SLOT, "--ledger", str(layout.profile_dir(profile) / "ledger.sqlite"),
                   "--snapshot", str(runtime / "ap-snapshot"), "--protection", str(protection_file),
                   "--catalog", str(catalog_path(root)), "--production-certificate", str(certificate),
                   "--install-root", str(root), "--status", str(runtime / "status.json"),
                   "--scout-file", str(layout.profile_dir(profile) / "node-contents.txt")]
        if password:
            command += ["--password", password]
        client = (client_runner or _client_runner(log, on_client, str(runtime / "client.log")))(command, cwd=str(root))
        watcher = threading.Thread(target=_watch_bridge, args=(runtime / "ap-refusal.txt", stop_watch, log), daemon=True)
        watcher.start()
        log("Archipelago client running. Play the game; close it normally when you are done.")
        wait_game(probe, log=log)
    except BaseException as error:
        log(f"ERROR during play session: {error!r}")
        raise
    finally:
        stop_watch.set()
        if client is not None and client.poll() is None:
            client.terminate()
            try:
                client.wait(timeout=10)
            except Exception:
                client.kill()
        try:
            session.wait_closed(probe, log)
            closed = session.restore(layout, probe)
            if closed:
                log(f"Restored session {closed['sid']}; your original saves are back, byte-for-byte verified.")
        except SafetyError as error:
            log(f"NOT restored yet ({error}). Close the game and Steam, then run: recover")
            raise
    return sid
