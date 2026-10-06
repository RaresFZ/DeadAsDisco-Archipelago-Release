import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from archipelago.client.production import OwnershipReconciler
from archipelago.client.reconciliation import Binding, Ledger, ReconciliationError
from archipelago.client.deathlink import DeathLinkState


class DeathLinkTuningTests(unittest.TestCase):
    def test_amnesty_forgives_the_first_n_and_cooldown_spaces_later_ones(self):
        state = DeathLinkState()
        state.configure(amnesty=2, cooldown=60)
        now = state.connected_at + 1
        ping = lambda stamp: {'time': stamp, 'source': 'peer-' + str(stamp)}
        self.assertFalse(state.receive(ping(now), 'me', now))          # forgiven 1
        self.assertFalse(state.receive(ping(now + 1), 'me', now + 1))  # forgiven 2
        self.assertTrue(state.receive(ping(now + 2), 'me', now + 2))   # accepted
        self.assertFalse(state.receive(ping(now + 10), 'me', now + 10))  # inside cooldown
        self.assertTrue(state.receive(ping(now + 70), 'me', now + 70))   # after cooldown


class ProductionTests(unittest.TestCase):
    def test_feature_delivery_separates_suppression_and_ap_entitlement(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root=Path(folder);source=root/'source';source.write_text('fixture')
            cert=root/'cert';cert.write_text(json.dumps(dict(status='verified-protected-passive-grant-cold',
                max_health_delta=10,duplicate_health_delta=0,sources={str(source):hashlib.sha256(source.read_bytes()).hexdigest()})))
            policy=root/'policy'
            protection=SimpleNamespace(data=dict(production_proof_sha256=hashlib.sha256(cert.read_bytes()).hexdigest(),
                production_control=str(root/'control'),launch_token='fixture',reward_suppression_test=True,
                feature_delivery_policy=str(policy),entitlement_file=str(root/'entitlements'),access_file=str(root/'access')))
            catalog=dict(items=[dict(id=42,tag='Skill.One',mechanism='owned-upgrade'),
                dict(id=43,tag='Level.One',mechanism='mission-access')])
            ledger=Ledger(root/'ledger',Binding('seed',0,1,'generation','slot'))
            ledger.receive(0,[[42,99,1,1],[43,100,1,1]])
            reconciler=OwnershipReconciler(ledger,catalog,protection,cert)
            live={'owned':[]};saved={'owned':[],'save_sha256':'fixture'}
            self.assertEqual(reconciler.reconcile(live,saved),0)
            self.assertEqual((root/'entitlements').read_text(),'')
            self.assertFalse((root/'control').exists())
            policy.write_text('Level.One\n')
            self.assertEqual(reconciler.reconcile(live,saved),1)
            self.assertEqual((root/'access').read_text(),'Level.One\n')
            self.assertFalse((root/'control').exists())
            policy.write_text('*\n')
            reconciler.reconcile(live,saved)
            self.assertEqual((root/'entitlements').read_text(),'Skill.One\n')
            self.assertTrue((root/'control.intent-0').exists())
            ledger.close()

    def test_fan_pack_is_reserved_once_and_confirmed_only_by_the_game_acknowledgment(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root=Path(folder);source=root/'source';source.write_text('fixture')
            cert=root/'cert';cert.write_text(json.dumps(dict(status='verified-protected-passive-grant-cold',
                max_health_delta=10,duplicate_health_delta=0,sources={str(source):hashlib.sha256(source.read_bytes()).hexdigest()})))
            protection=SimpleNamespace(data=dict(production_proof_sha256=hashlib.sha256(cert.read_bytes()).hexdigest(),
                production_control=str(root/'control'),launch_token='tok',credits_control=str(root/'credits')))
            catalog=dict(items=[dict(id=7,name='Fan Pack',mechanism='fan-pack',family='filler')])
            ledger=Ledger(root/'ledger',Binding('seed',0,1,'generation','slot'))
            ledger.receive(0,[[7,99,1,0]])
            reconciler=OwnershipReconciler(ledger,catalog,protection,cert)
            live={'owned':[]};saved={'owned':[],'save_sha256':'fixture'}
            reconciler.reconcile(live,saved)
            command=(root/'credits').read_text()
            self.assertTrue(command.startswith('credits\n0\n7\ntok\n'))
            self.assertTrue((root/'credits.intent-0').exists())
            reconciler.reconcile(live,saved)                       # unacknowledged: waits, never re-dispatches
            self.assertEqual((root/'credits').read_text(),command)
            (root/'credits.applied-0').write_text(json.dumps(dict(index=0,item=7,amount=500)))
            self.assertEqual(reconciler.reconcile(live,saved),1)
            self.assertEqual(ledger.db.execute('SELECT status FROM receipts').fetchone()[0],'applied')
            fresh=OwnershipReconciler(ledger,catalog,protection,cert)
            self.assertEqual(fresh.reconcile(live,saved),0)        # a restarted client never grants it again
            ledger.close()

    def test_client_exits_promptly_on_error_even_if_the_console_pipe_stays_open(self):
        import subprocess, sys
        code = ("import asyncio, types\n"
                "from archipelago.client.main import console_input\n"
                "async def run():\n"
                "    ctx = types.SimpleNamespace(exit_event=asyncio.Event(), connected=False)\n"
                "    task = asyncio.create_task(console_input(ctx))\n"
                "    await asyncio.sleep(0.3)\n"
                "    task.cancel()\n"
                "    raise RuntimeError('client failed')\n"
                "try:\n"
                "    asyncio.run(run())\n"
                "except RuntimeError:\n"
                "    pass\n")
        process = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, cwd=Path(__file__).resolve().parents[2])
        try:
            self.assertEqual(process.wait(timeout=20), 0)          # used to hang for 300 seconds
        finally:
            process.kill()
            process.stdin.close()

    def test_reservations_left_by_an_earlier_game_session_never_lock_the_profile(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root=Path(folder);source=root/'source';source.write_text('fixture')
            cert=root/'cert';cert.write_text(json.dumps(dict(status='verified-protected-passive-grant-cold',
                max_health_delta=10,duplicate_health_delta=0,sources={str(source):hashlib.sha256(source.read_bytes()).hexdigest()})))
            digest=hashlib.sha256(cert.read_bytes()).hexdigest()
            catalog=dict(items=[dict(id=7,name='Fan Pack',mechanism='fan-pack',family='filler'),
                                dict(id=42,tag='Tag.One',mechanism='owned-upgrade')])
            ledger=Ledger(root/'ledger',Binding('seed',0,1,'generation','slot'))
            ledger.receive(0,[[7,99,1,0],[42,100,1,0]])
            def session(name):
                (root/name).mkdir()
                return OwnershipReconciler(ledger,catalog,SimpleNamespace(data=dict(production_proof_sha256=digest,
                    production_control=str(root/name/'control'),launch_token='tok-'+name,credits_control=str(root/name/'credits'))),cert)
            live={'owned':[]};saved={'owned':[],'save_sha256':'fixture'}
            session('one').reconcile(live,saved)                    # fan pack reserved, game closed before acknowledging it
            self.assertEqual(ledger.db.execute("SELECT status FROM receipts WHERE idx=0").fetchone()[0],'applying')
            second=session('two')
            second.reconcile(live,saved)                           # next launch: delivered again, no exception
            self.assertTrue((root/'two'/'credits.intent-0').exists())
            (root/'two'/'credits.applied-0').write_text(json.dumps(dict(index=0,item=7,amount=500)))
            second.reconcile(live,saved)                           # acknowledged; the native grant is reserved next
            self.assertEqual([s for _,s in ledger.db.execute("SELECT idx,status FROM receipts ORDER BY idx")],['applied','applying'])
            third=session('three')                                  # closed again before the game applied the skill
            third.reconcile(live,saved)                            # not owned in the fresh game: granted again
            self.assertTrue((root/'three'/'control.intent-1').exists())
            self.assertEqual(third.reconcile({'owned':['Tag.One']},{'owned':['Tag.One'],'save_sha256':'fixture'}),1)
            self.assertEqual(ledger.pending_items(),[])
            ledger.close()

    def test_shared_durable_ownership_and_crash_ambiguity(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
            root = Path(root)
            source = root / 'proof'; source.write_text('fixture, not live proof')
            cert = root / 'capability.json'
            cert.write_text(json.dumps(dict(status='verified-protected-passive-grant-cold',max_health_delta=10,
                duplicate_health_delta=0,sources={str(source):hashlib.sha256(source.read_bytes()).hexdigest()})))
            protection = SimpleNamespace(data=dict(production_proof_sha256=hashlib.sha256(cert.read_bytes()).hexdigest(),
                production_control=str(root/'control'), launch_token='fixture'))
            catalog = dict(items=[dict(id=42,tag='Tag.One',mechanism='owned-upgrade')])
            ledger = Ledger(root/'ledger', Binding('seed',0,1,'generation','slot'))
            ledger.receive(0,[[42,99,1,1],[42,100,1,1]])
            reconciler = OwnershipReconciler(ledger,catalog,protection,cert)
            reconciler.reconcile({'owned':[]},{'owned':[],'save_sha256':'fixture'})
            self.assertTrue((root/'control.intent-0').exists())
            # A fresh client process in the same game session neither replays the published reservation nor fails:
            # it waits for the game, and recovers durable ownership once the game owns the item.
            fresh = OwnershipReconciler(ledger,catalog,protection,cert)
            self.assertEqual(fresh.reconcile({'owned':[]},{'owned':[],'save_sha256':'fixture'}),0)
            self.assertEqual(ledger.db.execute("SELECT status FROM receipts WHERE idx=0").fetchone()[0],'applying')
            self.assertEqual(fresh.reconcile({'owned':['Tag.One']},{'owned':['Tag.One'],'save_sha256':'fixture'}),2)
            self.assertEqual(ledger.pending_items(),[])
            with self.assertRaises(ReconciliationError):
                fresh.reconcile({'owned':[]},{'owned':[],'save_sha256':'fixture'})
            ledger.close()

    def test_deathlink_expiry_echo_and_reconnect(self):
        state = DeathLinkState(); state.reconnect(100)
        self.assertFalse(state.receive({'time':99,'source':'Other'},'Me',101))
        self.assertFalse(state.receive({'time':101,'source':'Me'},'Me',101))
        self.assertTrue(state.receive({'time':101,'source':'Other'},'Me',101))
        self.assertFalse(state.receive({'time':101,'source':'Other'},'Me',101))
        self.assertIsNone(state.poll(None,102))
        self.assertEqual(state.poll({'ready':True,'alive':True,'death_sequence':0},103),'kill')
        self.assertIsNone(state.poll({'ready':True,'alive':False,'death_sequence':1},104))
        state.poll({'ready':True,'alive':True,'death_sequence':1},105)
        self.assertEqual(state.poll({'ready':True,'alive':False,'death_sequence':2},106),'send')
        state.receive({'time':107,'source':'Other'},'Me',107)
        state.reconnect(108)
        self.assertIsNone(state.pending)

    def test_delayed_native_death_does_not_clear_echo_guard(self):
        state=DeathLinkState();state.reconnect(100)
        state.receive({'time':101,'source':'Other'},'Me',101)
        alive={'ready':True,'alive':True,'can_receive':True,'death_sequence':0}
        self.assertEqual(state.poll(alive,102),'kill')
        self.assertIsNone(state.poll(alive,103))  # game-thread command not serviced yet
        self.assertTrue(state.suppress_until_alive)
        self.assertIsNone(state.poll({'ready':True,'alive':False,'death_sequence':1},104))
        self.assertIsNone(state.poll({'ready':True,'alive':True,'death_sequence':1},105))
        self.assertEqual(state.poll({'ready':True,'alive':False,'death_sequence':2},106),'send')

    def test_incoming_waits_for_normal_player_death_listener(self):
        state=DeathLinkState();state.reconnect(100)
        state.receive({'time':101,'source':'Other'},'Me',101)
        self.assertIsNone(state.poll({'ready':True,'alive':True,'can_receive':False,'death_sequence':0},102))
        self.assertIsNotNone(state.pending)
        self.assertEqual(state.poll({'ready':True,'alive':True,'can_receive':True,'death_sequence':0},103),'kill')
