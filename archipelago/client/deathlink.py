"""Connection-local DeathLink queue. Old deaths never survive a reconnect."""
import math
import time


class DeathLinkState:
    def __init__(self):
        self.connected_at = time.time()
        self.pending = None
        self.seen = set()
        self.local_sequence = None
        self.suppress_until_alive = False
        self.remote_death_seen = False
        self.remote_requested_at = None
        self.amnesty = 0          # incoming DeathLinks still to ignore this run
        self.cooldown = 0.0       # seconds after an accepted one during which others are ignored
        self.last_accepted = None

    def configure(self, amnesty=0, cooldown=0):
        """Player tuning from slot data (client side only): per-run amnesty and an accept cooldown."""
        self.amnesty = max(0, int(amnesty))
        self.cooldown = max(0.0, float(cooldown))

    def reconnect(self, now=None):
        self.connected_at = time.time() if now is None else now
        self.pending = None
        self.seen.clear()
        self.local_sequence = None
        self.suppress_until_alive = False
        self.remote_death_seen = False
        self.remote_requested_at = None

    def receive(self, data, source, now=None):
        now = time.time() if now is None else now
        stamp = data.get('time')
        if (type(stamp) not in (int, float) or not math.isfinite(stamp)
                or stamp < self.connected_at or now - stamp > 30 or stamp > now + 5
                or data.get('source') == source):
            return False
        key = (stamp, data.get('source'))
        if key in self.seen:
            return False
        self.seen.add(key)
        if self.amnesty > 0:
            self.amnesty -= 1  # forgiven: counted and ignored
            return False
        if self.cooldown and self.last_accepted is not None and now - self.last_accepted < self.cooldown:
            return False
        self.last_accepted = now
        self.pending = (stamp, now + 30)
        return True

    def poll(self, player, now=None):
        now = time.time() if now is None else now
        if self.pending and now > self.pending[1]:
            self.pending = None
        if not player or not player.get('ready'):
            return None
        sequence = player.get('death_sequence')
        if self.suppress_until_alive and player.get('alive') is False:
            self.remote_death_seen = True
        if self.local_sequence is None:
            self.local_sequence = sequence  # startup cannot replay a historical death
        if sequence != self.local_sequence:
            self.local_sequence = sequence
            if self.suppress_until_alive:
                self.remote_death_seen = True
                return None
            return 'send'
        if player.get('alive') is True:
            if self.remote_death_seen:
                self.suppress_until_alive = False
                self.remote_death_seen = False
                self.remote_requested_at = None
            elif self.suppress_until_alive and now - self.remote_requested_at > 30:
                # Expired native request cannot be replayed; release suppression
                # only after the command's ten-second runtime lease has expired.
                self.suppress_until_alive = False
                self.remote_requested_at = None
            if self.pending and not self.suppress_until_alive and player.get('can_receive', True):
                self.pending = None
                self.suppress_until_alive = True
                self.remote_requested_at = now
                return 'kill'
        return None
