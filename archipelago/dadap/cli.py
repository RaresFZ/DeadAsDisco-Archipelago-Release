"""Command line: python -m archipelago.dadap <command>."""
import argparse
import json
import sys
from pathlib import Path

from . import pins, session
from .fsutil import SafetyError
from .layout import Layout


def _layout(args):
    layout = Layout.default(args.game_dir)
    if args.state_dir:
        layout.state_dir = Path(args.state_dir)
    if args.saved_dir:
        layout.saved_dir = Path(args.saved_dir)
    return layout


def cmd_status(args):
    layout = _layout(args)
    active = session.active_session(layout)
    print(json.dumps({"build": pins.BUILD, "game_dir": str(layout.game_dir), "saved_dir": str(layout.saved_dir),
                      "state_dir": str(layout.state_dir), "core_installed": layout.core_dir.is_dir(),
                      "unfinished_session": active}, indent=2))


def cmd_doctor(args):
    from . import doctor
    results = doctor.diagnose(_layout(args), session.Probe(), args.ap_root)
    for level, check, detail in results:
        print(f"[{level:4}] {check}: {detail}")
    if any(level == "FAIL" for level, _, _ in results):
        raise SafetyError("Doctor found problems (see FAIL lines above).")


def cmd_recover(args):
    layout = _layout(args)
    state = session.restore(layout, session.Probe())
    print("Nothing to recover." if state is None else f"Restored session {state['sid']}; original saves verified byte-for-byte.")


def run_vanilla(layout, profile, log=print):
    """Offline vanilla launch against an AP profile: no UE4SS, no mod. Used to create/observe a fresh profile."""
    probe = session.Probe()
    state = session.begin(layout, profile, probe)
    log(f"Session {state['sid']}: your saves are safely moved aside; profile '{profile}' "
        f"{'created' if state['profile_fresh'] else 'resumed'}. Launching the game offline...")
    try:
        session.launch(layout, state["sid"])
        session.wait_for_game(probe, log=log)
    finally:
        try:
            session.wait_closed(probe, log)
            closed = session.restore(layout, probe)
            log(f"Restored session {closed['sid']}; your original saves are back (verified byte-for-byte).")
        except SafetyError as error:
            log(f"NOT restored yet ({error}). Close the game and Steam, then use Recover.")
            raise


def cmd_vanilla(args):
    run_vanilla(_layout(args), args.profile)


def cmd_setup(args):
    from . import core
    layout = _layout(args)
    core.install_core(layout, args.ue4ss_archive)
    print(f"UE4SS core installed under {layout.core_dir}. The game directory was not touched.")


def cmd_play(args):
    from . import play
    layout = _layout(args)
    features = "all" if args.test_features == "all" else (args.test_features.split(",") if args.test_features else None)
    play.play(layout, args.profile, args.server, args.slot, args.password, ap_root=args.ap_root, features=features,
              certificate=args.certificate)


def cmd_uninstall(args):
    import shutil
    layout = _layout(args)
    if session.active_session(layout):
        raise SafetyError("An unfinished session exists; run recover first.")
    if layout.proxy_target.exists():
        raise SafetyError("The proxy DLL is present in the game folder; run recover first (it is removed with a hash check).")
    state = layout.state_dir
    if state.name != "DeadAsDiscoAP" and not args.force_path:
        raise SafetyError("Refusing to delete an unexpected state directory.")
    targets = [state / "core", state / "sessions"]
    if args.purge_all:
        if not args.yes:
            raise SafetyError("--purge-all also deletes profiles and save backups; add --yes to confirm.")
        targets = [state]
    removed = []
    for target in targets:
        if target.exists():
            shutil.rmtree(target)
            removed.append(str(target))
    print("Removed: " + (", ".join(removed) if removed else "nothing") + ". The game folder and your real save folder were never modified."
          + ("" if args.purge_all else f" Profiles and save backups were kept in {state}."))


def build_parser():
    parser = argparse.ArgumentParser(prog="dadap", description="Dead as Disco Archipelago portable runtime")
    parser.add_argument("--game-dir")
    parser.add_argument("--state-dir")
    parser.add_argument("--saved-dir")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(run=cmd_status)
    sub.add_parser("recover").set_defaults(run=cmd_recover)
    doctor = sub.add_parser("doctor", help="read-only diagnosis of the install")
    doctor.add_argument("--ap-root")
    doctor.set_defaults(run=cmd_doctor)
    vanilla = sub.add_parser("vanilla")
    vanilla.add_argument("--profile", required=True)
    vanilla.set_defaults(run=cmd_vanilla)
    newprofile = sub.add_parser("newprofile", help="create a fresh AP profile: play the tutorial in vanilla, then quit")
    newprofile.add_argument("--profile", required=True)
    newprofile.set_defaults(run=cmd_vanilla)
    setup = sub.add_parser("setup")
    setup.add_argument("--ue4ss-archive", required=True)
    setup.set_defaults(run=cmd_setup)
    play = sub.add_parser("play")
    play.add_argument("--profile", required=True)
    play.add_argument("--server", required=True)
    play.add_argument("--slot", required=True)
    play.add_argument("--password")
    play.add_argument("--ap-root")
    play.add_argument("--certificate")
    play.add_argument("--test-features", help="protected test mode for unvalidated mechanisms: all or comma list")
    play.set_defaults(run=cmd_play)
    uninstall = sub.add_parser("uninstall", help="remove the staged core and session logs (profiles/backups kept)")
    uninstall.add_argument("--purge-all", action="store_true", help="also delete profiles and save backups")
    uninstall.add_argument("--yes", action="store_true")
    uninstall.add_argument("--force-path", action="store_true")
    uninstall.set_defaults(run=cmd_uninstall)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.run(args)
    except SafetyError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
