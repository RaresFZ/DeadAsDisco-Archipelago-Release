"""Shared ownership reconciliation, crash-safe dispatch and durable saved effects."""
import hashlib
import json
import os
import time
from pathlib import Path
from .reconciliation import ReconciliationError


class OwnershipReconciler:
    def __init__(self, ledger, catalog, protection, certificate, root=None):
        self.ledger = ledger
        self.items = {row['id']: row for row in catalog['items']}
        self.protection = protection.data
        proof = json.loads(Path(certificate).read_text())
        if (proof.get('status') != 'verified-protected-passive-grant-cold'
                or proof.get('max_health_delta') != 10 or proof.get('duplicate_health_delta') != 0
                or not proof.get('sources')):
            raise ReconciliationError('Verified shared native ownership/cold capability required')
        for path, expected in proof['sources'].items():
            location = Path(path) if Path(path).is_absolute() or root is None else Path(root) / path
            if hashlib.sha256(location.read_bytes()).hexdigest() != expected:
                raise ReconciliationError('Native ownership capability source changed')
        self.proof_hash = hashlib.sha256(Path(certificate).read_bytes()).hexdigest()
        if self.protection.get('production_proof_sha256') != self.proof_hash:
            raise ReconciliationError('Protected runtime not provisioned for this capability')
        self.command = Path(self.protection['production_control'])
        self.inflight = None
        self.hints = []
        self.published = {}

    def publish(self, path, text):
        if not path or self.published.get(path) == text:
            return
        target = Path(path)
        tmp = target.with_suffix('.tmp')
        with tmp.open('w', encoding='utf-8', newline='\n') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        tmp.replace(target)
        self.published[path] = text

    def reconcile(self, live, saved):
        if live is None or saved is None:
            return 0
        owned, durable = set(live.get('owned', [])), set(saved.get('owned', []))
        policy_path = self.protection.get('feature_delivery_policy')
        if policy_path and not self.protection.get('reward_suppression_test'):
            raise ReconciliationError('Delivery staging is protected-test only')
        policy = set(Path(policy_path).read_text().splitlines()) if policy_path and Path(policy_path).exists() else set()
        def released(row):
            return not policy_path or '*' in policy or row.get('tag', row.get('effect')) in policy
        history = [self.items[json.loads(payload)[0]] for payload, in self.ledger.db.execute('SELECT payload FROM receipts ORDER BY idx')]
        for key, mechanism in (('entitlement_file', 'owned-upgrade'), ('access_file', 'mission-access')):
            self.publish(self.protection.get(key), ''.join(tag+'\n' for tag in sorted({r['tag'] for r in history if r['mechanism']==mechanism and released(r)})))
        nodes = {r['id'] for r in self.protection.get('node_items', [])}
        # Locally observed interactions are durable truth even before the server confirms them.
        checked = {ident for ident, in self.ledger.db.execute('SELECT id FROM checks')}
        self.publish(self.protection.get('completed_nodes_file'), ''.join(str(i)+'\n' for i in sorted(nodes & checked)))
        for payload, in self.ledger.db.execute("SELECT payload FROM receipts WHERE status='applied'"):
            row = self.items.get(json.loads(payload)[0])
            if row is None:
                raise ReconciliationError('Applied unknown item')
            if row['mechanism'] == 'owned-upgrade' and (row['tag'] not in owned or row['tag'] not in durable):
                raise ReconciliationError('Applied ownership lost; refuse save rollback')
        applied = 0
        satisfied_prefix = set()
        for index, payload, status in self.ledger.pending_items():
            row = self.items.get(payload[0])
            if row is None:
                raise ReconciliationError('Unknown received item; no mutation authorized')
            if not released(row):
                if status != 'received':
                    raise ReconciliationError('Cannot withdraw a previously released receipt')
                satisfied_prefix.add(index)
                continue
            if row['mechanism'] == 'client-hint':
                if status == 'received': self.ledger.begin_item(index, grant_validated=True, satisfied_prefix=satisfied_prefix)
                self.ledger.mark_durable(index, 'client-hint:' + str(index))
                self.hints.append(index)
                applied += 1
                continue
            if row['mechanism'] == 'mission-access':
                if status == 'received': self.ledger.begin_item(index, grant_validated=True, satisfied_prefix=satisfied_prefix)
                self.ledger.mark_durable(index, 'ap-mission-access:' + row['tag'])
                applied += 1
                continue
            if row['mechanism'] in ('temporary-trap', 'fan-pack'):
                # One-shot, at-most-once effects: durable reservation, game-side acknowledgment file, never replayed.
                label, key, verb = ('trap', 'trap_control', 'trap') if row['mechanism'] == 'temporary-trap' else ('fan pack', 'credits_control', 'credits')
                control = self.protection.get(key)
                if not control:
                    raise ReconciliationError(label.capitalize() + ' received without runtime capability')
                ack = Path(control + f'.applied-{index}')
                if ack.exists():
                    result = json.loads(ack.read_text())
                    if result.get('index') != index or result.get('item') != row['id']:
                        raise ReconciliationError(label.capitalize() + ' acknowledgment mismatch')
                    if status != 'applying':
                        raise ReconciliationError('Unreserved ' + label + ' acknowledgment')
                    self.ledger.mark_durable(index, row['mechanism'] + ':' + hashlib.sha256(ack.read_bytes()).hexdigest())
                    self.inflight = None; applied += 1
                    continue
                if status == 'applying':
                    if self.inflight == index or Path(control + f'.intent-{index}').exists():
                        return applied  # published in this game session: wait for the game's acknowledgment
                    # Reserved by an earlier game session that never acknowledged it (usually the game was closed
                    # first). Deliver it again rather than lock the whole profile; in the very rare case the game
                    # applied it without the acknowledgment surviving, a filler/trap is simply repeated once.
                    self.ledger.release_reservation(index)
                self.dispatch(index, row['id'], control, verb, satisfied_prefix)
                return applied
            if row['mechanism'] != 'owned-upgrade':
                raise ReconciliationError('Unsupported mutation family')
            if row['tag'] in owned and row['tag'] in durable:
                if status == 'received': self.ledger.begin_item(index, grant_validated=True, satisfied_prefix=satisfied_prefix)
                self.ledger.mark_durable(index, 'saved-ownership:' + saved['save_sha256'])
                self.inflight = None
                applied += 1
                continue
            if row['tag'] in owned:
                # Effects are satisfied in this live owner. Drain further native
                # ownership receipts, then confirm the batch after one natural save.
                satisfied_prefix.add(index)
                continue
            if status == 'applying':
                if self.inflight == index or Path(str(self.command) + f'.intent-{index}').exists():
                    return applied  # published in this game session: wait for the game to apply it
                # An earlier game session reserved this grant, but the freshly loaded game does not own the item
                # (checked above against the live and saved ownership), so it was never applied: grant it again.
                self.ledger.release_reservation(index)
                status = 'received'
            if status == 'received' and 'loadable_ownership' in live and row['tag'] not in live['loadable_ownership']:
                # Do not reserve an unloaded definition. Independent ownership,
                # access and traps can drain; this receipt remains retryable.
                satisfied_prefix.add(index)
                continue
            # Commit reservation before publication; ownership is idempotent, so a repeat after a crash is safe.
            self.dispatch(index, row['id'], str(self.command), 'grant', satisfied_prefix)
            return applied
        return applied

    def dispatch(self, index, item, control, verb, satisfied_prefix):
            self.ledger.begin_item(index, grant_validated=True, satisfied_prefix=satisfied_prefix)
            command = f"{verb}\n{index}\n{item}\n{self.protection['launch_token']}\n{int(time.time())}\n"
            marker = Path(control + f'.intent-{index}')
            with marker.open('xb') as f:
                f.write(command.encode()); f.flush(); os.fsync(f.fileno())
            target = Path(control)
            tmp = target.with_suffix('.tmp')
            with tmp.open('wb') as f:
                f.write(command.encode()); f.flush(); os.fsync(f.fileno())
            tmp.replace(target)
            self.inflight = index


def publish_from_ledger(ledger_path, catalog, protection):
    """Write entitlement/access/completed-node files from the durable ledger BEFORE the game starts.

    The mod withholds anything not entitled the moment it is ready. Without this the first service tick of a
    resumed profile would remove an already-received skill before the client had even connected.
    """
    import sqlite3
    items = {row['id']: row for row in catalog['items']}
    entitled, access, nodes = set(), set(), set()
    if Path(ledger_path).exists():
        db = sqlite3.connect(ledger_path)
        try:
            for payload, in db.execute('SELECT payload FROM receipts ORDER BY idx'):
                row = items.get(json.loads(payload)[0])
                if row is None:
                    raise ReconciliationError('Ledger holds an unknown item')
                if row['mechanism'] == 'owned-upgrade':
                    entitled.add(row['tag'])
                elif row['mechanism'] == 'mission-access':
                    access.add(row['tag'])
            wanted = {r['id'] for r in protection.get('node_items', [])}
            nodes = {ident for ident, in db.execute('SELECT id FROM checks')} & wanted
        finally:
            db.close()
    for key, values in (('entitlement_file', sorted(entitled)), ('access_file', sorted(access)),
                        ('completed_nodes_file', sorted(nodes))):
        target = protection.get(key)
        if not target:
            continue
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        with tmp.open('w', encoding='utf-8', newline='\n') as handle:
            handle.write(''.join(f'{v}\n' for v in values))
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    return {'entitled': len(entitled), 'access': len(access), 'nodes': len(nodes)}
