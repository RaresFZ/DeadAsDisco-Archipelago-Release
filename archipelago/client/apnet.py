"""Minimal Archipelago network client (websocket + JSON protocol).

Replaces the dependency on an Archipelago source checkout. Implements exactly what the Dead as Disco client needs:
connect/authenticate, received items (ordered, resynchronizing), check submission, scouting with data-package names,
DeathLink bounces, goal status and automatic reconnection. Protocol: https://github.com/ArchipelagoMW/Archipelago/blob/main/docs/network%20protocol.md
"""
import asyncio
import json
import logging
import time
import uuid
from collections import namedtuple

NetworkItem = namedtuple("NetworkItem", "item location player flags")
CLIENT_GOAL = 30
VERSION = {"major": 0, "minor": 6, "build": 8, "class": "Version"}
log = logging.getLogger("apnet")


class _ItemNames:
    def __init__(self, ctx):
        self.ctx = ctx

    def lookup_in_slot(self, code, slot=None):
        game = self.ctx.slot_info.get(slot, {}).get("game")
        reverse = self.ctx.names.get(game, {}).get("items", {})
        return reverse[code]


class NetContext:
    game = "Dead as Disco"
    items_handling = 7  # remote items + own world + starting inventory
    want_slot_data = True

    def __init__(self, password=None):
        self.password = password
        self.auth = None
        self.ws = None
        self.exit_event = asyncio.Event()
        self.server_task = None
        self.server_seed_name = None
        self.team = None
        self.slot = None
        self.slot_data = {}
        self.slot_info = {}        # slot -> {name, game}
        self.player_names = {}     # slot -> alias
        self.checked_locations = set()
        self.missing_locations = set()
        self.items_received = []
        self.locations_info = {}
        self.names = {}            # game -> {"items": {id: name}, "locations": {id: name}}
        self.games = []
        self.uuid = str(uuid.uuid4())
        self.death_link = False
        self.refused = None
        self.item_names = _ItemNames(self)

    # ---- connection state -----------------------------------------------------------------------------
    @property
    def connected(self):
        return self.ws is not None and self.slot is not None

    async def send_msgs(self, messages):
        if self.ws is None:
            raise ConnectionError("Not connected")
        await self.ws.send(json.dumps(messages))

    # ---- overridable hooks ----------------------------------------------------------------------------
    async def server_auth(self, password_requested=False):
        raise NotImplementedError

    def on_package(self, cmd, packet):
        pass

    def on_deathlink(self, data):
        pass

    # ---- client actions -------------------------------------------------------------------------------
    async def send_connect(self):
        tags = ["AP"] + (["DeathLink"] if self.death_link else [])
        await self.send_msgs([{"cmd": "Connect", "password": self.password, "game": self.game, "name": self.auth,
                               "uuid": self.uuid, "version": VERSION, "items_handling": self.items_handling,
                               "tags": tags, "slot_data": self.want_slot_data}])

    async def check_locations(self, locations):
        await self.send_msgs([{"cmd": "LocationChecks", "locations": sorted(locations)}])

    async def update_death_link(self, enabled):
        self.death_link = bool(enabled)
        await self.send_msgs([{"cmd": "ConnectUpdate", "tags": ["AP"] + (["DeathLink"] if enabled else [])}])

    async def send_death(self, cause=""):
        await self.send_msgs([{"cmd": "Bounce", "tags": ["DeathLink"],
                               "data": {"time": time.time(), "source": self.player_names.get(self.slot, str(self.auth)), "cause": cause}}])

    async def shutdown(self):
        self.exit_event.set()
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self.server_task is not None:
            self.server_task.cancel()
            try:
                await self.server_task
            except BaseException:
                pass

    # ---- packet handling ------------------------------------------------------------------------------
    def _text(self, parts):
        out = []
        for part in parts:
            kind, text = part.get("type", "text"), part.get("text", "")
            try:
                if kind == "player_id":
                    text = self.player_names.get(int(text), text)
                elif kind == "item_id":
                    text = self.item_names.lookup_in_slot(int(text), part.get("player"))
                elif kind == "location_id":
                    text = self.names.get(self.slot_info.get(part.get("player"), {}).get("game"), {}).get("locations", {})[int(text)]
            except (KeyError, ValueError):
                pass
            out.append(str(text))
        return "".join(out)

    async def _handle(self, packet):
        cmd = packet.get("cmd")
        if cmd == "RoomInfo":
            self.server_seed_name = packet.get("seed_name")
            self.games = packet.get("games", [])
            await self.server_auth(bool(packet.get("password")))
        elif cmd == "ConnectionRefused":
            self.refused = packet.get("errors", [])
            log.error("Connection refused: %s", ", ".join(self.refused))
        elif cmd == "Connected":
            self.team, self.slot = packet["team"], packet["slot"]
            self.slot_data = packet.get("slot_data", {})
            self.player_names = {p["slot"]: p.get("alias") or p.get("name") for p in packet.get("players", [])
                                 if p.get("team") == self.team}
            self.slot_info = {int(k): v for k, v in packet.get("slot_info", {}).items()}
            self.checked_locations = set(packet.get("checked_locations", []))
            self.missing_locations = set(packet.get("missing_locations", []))
            games = sorted({v.get("game") for v in self.slot_info.values() if v.get("game")} | {self.game})
            await self.send_msgs([{"cmd": "GetDataPackage", "games": games}])
            log.info("Connected as %s (slot %s)", self.player_names.get(self.slot), self.slot)
        elif cmd == "DataPackage":
            for game, data in packet.get("data", {}).get("games", {}).items():
                self.names[game] = {"items": {v: k for k, v in data.get("item_name_to_id", {}).items()},
                                    "locations": {v: k for k, v in data.get("location_name_to_id", {}).items()}}
        elif cmd == "ReceivedItems":
            index = packet["index"]
            items = [NetworkItem(i["item"], i["location"], i["player"], i["flags"]) for i in packet["items"]]
            if index == 0:
                self.items_received = items
            elif index == len(self.items_received):
                self.items_received.extend(items)
            else:
                log.warning("ReceivedItems gap (%s != %s); requesting Sync", index, len(self.items_received))
                await self.send_msgs([{"cmd": "Sync"}])
                return
        elif cmd == "RoomUpdate":
            added = set(packet.get("checked_locations", []))
            self.checked_locations |= added
            self.missing_locations -= added
        elif cmd == "LocationInfo":
            for i in packet.get("locations", []):
                self.locations_info[i["location"]] = NetworkItem(i["item"], i["location"], i["player"], i["flags"])
        elif cmd == "Bounced":
            if "DeathLink" in packet.get("tags", []) and self.death_link:
                self.on_deathlink(packet.get("data", {}))
        elif cmd == "PrintJSON":
            text = self._text(packet.get("data", []))
            if text:
                log.info(text)
        elif cmd == "InvalidPacket":
            log.warning("Server rejected a packet: %s", packet.get("text"))
        self.on_package(cmd, packet)

    def reset_connection_state(self):
        self.ws = None
        self.slot = None
        self.items_received = []   # the server resends everything (index 0) after reconnecting


def _urls(address):
    if "://" in address:
        return [address]
    if ":" not in address.rsplit("]", 1)[-1]:
        address += ":38281"
    return ["ws://" + address, "wss://" + address]


async def server_loop(ctx, address, retry_delay=5.0):
    """Connect, pump packets and reconnect until ctx.exit_event is set."""
    from websockets.asyncio.client import connect
    while not ctx.exit_event.is_set():
        for url in _urls(address):
            if ctx.exit_event.is_set():
                break
            try:
                async with connect(url, max_size=None, open_timeout=10) as ws:
                    ctx.ws = ws
                    async for raw in ws:
                        for packet in json.loads(raw):
                            await ctx._handle(packet)
                break  # clean close: reconnect after the delay
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - any transport/protocol failure means "reconnect"
                log.warning("Connection to %s failed: %s", url, error)
            finally:
                ctx.reset_connection_state()
        try:
            await asyncio.wait_for(ctx.exit_event.wait(), retry_delay)
        except asyncio.TimeoutError:
            pass
