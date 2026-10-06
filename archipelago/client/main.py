"""Headless CommonClient connection. No game progression writes until targeted Phase 3 passes."""
import argparse
import asyncio
import json
import logging
import hashlib
import sys
import threading
from pathlib import Path
from .reconciliation import Binding, Ledger, ReconciliationError
from .bridge import GameBridge
from .protection import ProtectedBinding
from .items import ItemReconciler
from .saved_state import SavedStateReader
from .production import OwnershipReconciler
from .deathlink import DeathLinkState
from .slot_contract import SlotContract


async def console_input(ctx):
    """Archipelago-style text console: every line from stdin is sent as chat; '!' lines are server commands (!hint ...)."""
    loop = asyncio.get_running_loop()
    lines = asyncio.Queue()

    def read_stdin():
        # A daemon thread, not the default executor: a blocked readline must never keep the process alive after an error.
        try:
            for text in sys.stdin:
                loop.call_soon_threadsafe(lines.put_nowait, text)
            loop.call_soon_threadsafe(lines.put_nowait, "")
        except (RuntimeError, ValueError, OSError):
            pass  # the event loop or the pipe is already closed

    threading.Thread(target=read_stdin, daemon=True).start()
    while not ctx.exit_event.is_set():
        line = await lines.get()
        if not line:
            return
        line = line.strip()
        if line and ctx.connected:
            await ctx.send_msgs([{'cmd': 'Say', 'text': line}])


async def run(args):
    from .apnet import CLIENT_GOAL, NetContext as CommonContext, server_loop  # self-contained AP protocol client
    content_path = Path(getattr(args, "catalog", None) or (Path(__file__).parents[1] / "apworld/dead_as_disco/slice.json"))
    content = json.loads(content_path.read_text(encoding="utf-8"))
    content_hash = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    ledger = Ledger(args.ledger, Binding(args.seed, args.team, args.player, args.generation, args.game_slot, content_hash=content_hash))
    protection_path = getattr(args, "protection", None)
    protection = ProtectedBinding(protection_path, args.generation, args.game_slot) if protection_path else None
    bridge = GameBridge(args.snapshot, args.generation, args.game_slot, [r["id"] for r in content["locations"]], protection)
    item_certificate = getattr(args, "item_certificate", None)
    if protection and content["protocol"] == 2 and protection.data.get("inprocess_decoder"):
        from .inprocess_state import InProcessSavedStateReader
        saved_reader = InProcessSavedStateReader(protection, content_path)
    else:
        saved_reader = SavedStateReader(protection_path, content_path, Path(__file__).resolve().parents[2]) if protection and content["protocol"] == 2 else None
    production_certificate = getattr(args, "production_certificate", None)
    try:
        items = ItemReconciler(ledger, item_certificate) if item_certificate else None
        if production_certificate:
            if protection is None or saved_reader is None:
                raise ReconciliationError("Production grants require expanded protected binding")
            items = OwnershipReconciler(ledger, content, protection, production_certificate, getattr(args, "install_root", None))
        if items is not None and protection is None:
            raise ReconciliationError("Certified recovery requires protected game binding")
    except Exception:
        ledger.close()
        raise
    status = {"connection": "disconnected", "authenticated": False, "game_ready": False,
              "game_seen_ready": False, "confirmed_checks": 0,
              "received": 0, "applied": 0, "authenticated_connections": 0, "checks_submitted": 0}

    last_report = None
    scout_wanted = set()
    deaths = DeathLinkState()
    death_link_enabled = False
    goal_sent = False
    contract = None
    protocol_error = None
    def report():
        nonlocal last_report
        # Public status contains no passwords or private game state.
        if args.status:
            encoded = json.dumps(status, sort_keys=True)
            if encoded == last_report:
                return
            p = Path(args.status); p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(encoded, encoding="utf-8")
            tmp.replace(p)
            last_report = encoded

    class Context(CommonContext):
        game = "Dead as Disco"
        items_handling = 7
        want_slot_data = True

        async def server_auth(self, password_requested=False):
            if self.server_seed_name != args.seed:
                status.update(connection="blocked", authenticated=False, game_ready=False)
                report(); self.exit_event.set()
                raise ReconciliationError("Server seed mismatch")
            if password_requested and not self.password:
                raise ReconciliationError("Server requires configured password")
            self.auth = args.slot
            status.update(connection="authenticating", authenticated=False); report()
            await self.send_connect()

        def on_package(self, cmd, packet):
            nonlocal protocol_error
            try:
                self.handle_packet(cmd, packet)
            except ReconciliationError as error:
                protocol_error = error
                status.update(connection="blocked", authenticated=False, game_ready=False)
                report(); self.exit_event.set()
                raise

        def handle_packet(self, cmd, packet):
            nonlocal contract
            if cmd == "Connected":
                if (self.server_seed_name, self.team, self.slot) != (args.seed, args.team, args.player):
                    raise ReconciliationError("Authenticated AP identity mismatch")
                slot_data = packet.get("slot_data", {})
                if (slot_data.get("protocol") != content["protocol"] or slot_data.get("pool") != content["pool"]
                        or slot_data.get("content_sha256") != content_hash):
                    raise ReconciliationError("Unsupported AP slot data")
                contract = SlotContract(content, slot_data)
                if protection:
                    capability_keys={'ownership':('grants_enabled',),
                        'node-interaction':('node_locations_validated','node_locations_test'),
                        'reward-suppression':('reward_suppression_validated','reward_suppression_test'),
                        'mission-access':('access_validated','access_test'),
                        'temporary-traps':('traps_validated','traps_test'),
                        'fan-packs':('fan_packs_validated','fan_packs_test')}
                    for capability in slot_data.get('required_capabilities', []):
                        keys=capability_keys.get(capability)
                        if keys is None or not any(protection.data.get(key) is True for key in keys):
                            raise ReconciliationError('Runtime capability missing: '+capability)
                encoded_contract = json.dumps(contract.decoder_settings(), sort_keys=True)
                previous = ledger.db.execute("SELECT value FROM metadata WHERE key='slot_contract'").fetchone()
                if previous and previous[0] != encoded_contract:
                    raise ReconciliationError('Authenticated world configuration changed')
                with ledger.db:
                    ledger.db.execute("INSERT OR IGNORE INTO metadata VALUES('slot_contract',?)", (encoded_contract,))
                if saved_reader:
                    saved_reader.configure(contract.decoder_settings())
                if not self.checked_locations <= contract.locations:
                    raise ReconciliationError('Server returned unknown checked locations')
                ledger.confirm(self.checked_locations)
                status["confirmed_checks"] = len(self.checked_locations)
                status["authenticated_connections"] += 1
                status.update(connection="connected", authenticated=True); report()
                deaths.reconnect()
            elif cmd == "ReceivedItems":
                if contract is None:
                    raise ReconciliationError('Items arrived before world authentication')
                known = contract.items
                items = [[i['item'], i['location'], i['player'], i['flags']] for i in packet['items']]
                if any(item[0] not in known for item in items):
                    raise ReconciliationError('Server returned unknown item IDs')
                ledger.receive(packet["index"], items)
                status["received"] = len(self.items_received); report()
            elif cmd == "RoomUpdate":
                if contract is None or not self.checked_locations <= contract.locations:
                    raise ReconciliationError('Server returned disabled/unknown checks')
                ledger.confirm(self.checked_locations)
                status["confirmed_checks"] = len(self.checked_locations)
            elif cmd == "ConnectionRefused":
                status.update(connection="refused", authenticated=False); report()

        def on_deathlink(self, data):
            if death_link_enabled:
                deaths.receive(data, self.player_names[self.slot])

    ctx = Context(args.password)
    console_task = None
    if getattr(args, 'console', False):
        console_task = asyncio.create_task(console_input(ctx))
    # Never put the durable check set in CommonContext.locations_checked: its automatic
    # Connected replay occurs before this subclass can validate the binding.
    sent_this_connection = set()
    connection_serial = 0
    report()
    ctx.server_task = asyncio.create_task(server_loop(ctx, args.server))
    deadline = asyncio.get_running_loop().time() + args.seconds if args.seconds else None
    try:
        while not ctx.exit_event.is_set():
            connected = ctx.connected
            if not connected:
                status.update(connection="disconnected", authenticated=False, game_ready=False)
                sent_this_connection.clear()
                deaths.reconnect()
                death_link_enabled = False
                goal_sent = False
            elif status["authenticated"]:
                if connection_serial != status["authenticated_connections"]:
                    sent_this_connection.clear()
                    connection_serial = status["authenticated_connections"]
                    death_link_enabled = contract.death_link or bool(getattr(args, 'death_link', False) and protection and protection.data.get('death_link_test'))
                    if death_link_enabled and protection and not (protection.data.get('death_link_validated') or protection.data.get('death_link_test')):
                        raise ReconciliationError('Incoming DeathLink runtime capability not validated')
                    await ctx.update_death_link(death_link_enabled)
                    deaths.configure(contract.options.get('death_link_amnesty', 0), contract.options.get('death_link_cooldown', 0))
                    if getattr(args, 'scout_file', None):
                        from .scouting import node_location_ids
                        scout_wanted = set(node_location_ids(content, contract.locations))
                        if scout_wanted:
                            await ctx.send_msgs([{'cmd': 'LocationScouts', 'locations': sorted(scout_wanted), 'create_as_hint': 0}])
                if scout_wanted and scout_wanted <= set(ctx.locations_info) and all(
                        ctx.slot_info.get(i.player, {}).get('game') in ctx.names for i in ctx.locations_info.values()):
                    from .scouting import format_scouts, write_scouts
                    write_scouts(args.scout_file, format_scouts(content, {i: ctx.locations_info[i] for i in scout_wanted},
                                                               ctx.item_names.lookup_in_slot, lambda s: ctx.player_names[s]))
                    scout_wanted = set()
                observed = bridge.read()
                status["game_ready"] = observed is not None
                if observed is not None:
                    if protection is None:
                        raise ReconciliationError("Live game checks require protected launch provisioning")
                    ledger.observe(set(observed) & contract.locations)
                    saved = await saved_reader.read(bridge.last_snapshot) if saved_reader else None
                    if saved is not None:
                        if not set(saved['checks']) <= contract.locations:
                            raise ReconciliationError('Unknown persistent location ID')
                        ledger.observe(saved['checks'])
                    status["game_seen_ready"] = True
                    new = ledger.pending_checks(ctx.missing_locations) - sent_this_connection
                    if new:
                        await ctx.check_locations(new)
                        sent_this_connection.update(new)
                        status["checks_submitted"] += len(new)
                    if items is not None:
                        # Recovery of this exact already-proven saved effect only.
                        # This does not dispatch or authorize a native mutation.
                        if production_certificate:
                            items.reconcile(bridge.last_snapshot, saved)
                            remaining = sorted(set(ctx.missing_locations) - {r[0] for r in ledger.db.execute('SELECT id FROM checks')})
                            if remaining and items.hints:
                                targets = sorted({remaining[index % len(remaining)] for index in items.hints})
                                await ctx.send_msgs([{'cmd':'LocationScouts','locations':targets,'create_as_hint':2}])
                            items.hints.clear()
                        else:
                            items.reconcile(bridge.last_snapshot)
                        status["applied"] = ledger.db.execute("SELECT COUNT(*) FROM receipts WHERE status='applied'").fetchone()[0]
                    if saved and saved.get('victory') and not goal_sent:
                        await ctx.send_msgs([{'cmd':'StatusUpdate','status':CLIENT_GOAL}])
                        goal_sent = True
                        status['victory'] = True
                    if death_link_enabled:
                        action = deaths.poll(bridge.last_snapshot.get('player'))
                        if action == 'send':
                            await ctx.send_death(args.slot + ' died in Dead as Disco')
                            status['deathlink_sent'] = status.get('deathlink_sent', 0) + 1
                        elif action == 'kill':
                            import os, time
                            path = Path(protection.data['death_link_control'])
                            tmp = path.with_suffix('.tmp')
                            with tmp.open('w', encoding='utf-8', newline='\n') as f:
                                f.write(protection.data['launch_token']+'\n'+str(int(time.time()))+'\n')
                                f.flush(); os.fsync(f.fileno())
                            tmp.replace(path)
                            status['deathlink_requested'] = status.get('deathlink_requested', 0) + 1
                # Missing-item/native grant dispatch remains disabled.
            report()
            if deadline and asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(0.5)
        if protocol_error is not None:
            raise protocol_error
    except ReconciliationError:
        status.update(connection="blocked", authenticated=False, game_ready=False)
        report()
        raise
    finally:
        if console_task is not None:
            console_task.cancel()
        ctx.exit_event.set()
        await ctx.shutdown()
        ledger.close()
        status.update(connection="blocked" if status["connection"] == "blocked" else "disconnected", authenticated=False, game_ready=False)
        report()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ap-root", help="ignored (kept for compatibility): no Archipelago install is needed any more")
    for name in ("server", "slot", "seed", "generation", "ledger", "snapshot"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--game-slot", default="PagodaPT_M_0")
    p.add_argument("--team", type=int, default=0)
    p.add_argument("--player", type=int, default=1)
    p.add_argument("--password")
    p.add_argument("--status")
    p.add_argument("--protection", help="Verified protected transaction and context manifest")
    p.add_argument("--item-certificate", help="Validated exact protected cold-effect recovery proof; no native writes")
    p.add_argument("--catalog", help="Exact seed content catalog; omit for the preserved vertical slice")
    p.add_argument("--console", action="store_true", help="read chat/!commands from stdin (used by the window)")
    p.add_argument("--scout-file", help="Write what each skill-tree node holds to this text file")
    p.add_argument("--install-root", help="Base directory for relative certificate source paths")
    p.add_argument("--production-certificate", help="Verified reusable native ownership capability")
    p.add_argument("--death-link", action="store_true")
    p.add_argument("--seconds", type=float, default=0)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
