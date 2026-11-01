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

    def test_a_refusal_the_client_chose_ends_with_a_clean_exit_not_an_unhandled_exception_dialog(self):
        import sys
        from unittest import mock
        from archipelago.client import main as client_main
        argv = ['client', '--server', 'h:1', '--slot', 's', '--seed', '1', '--generation', 'g', '--ledger', 'l', '--snapshot', 'x']
        async def refuse(args):
            raise ReconciliationError('Server seed mismatch')
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(client_main, 'run', refuse), \
                self.assertLogs(level='ERROR') as logged, self.assertRaises(SystemExit) as raised:
            client_main.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn('Archipelago client stopped: Server seed mismatch', logged.output[0])

    def test_any_other_crash_also_ends_with_a_clean_exit_and_the_traceback_in_the_log(self):
        import sys
        from unittest import mock
        from archipelago.client import main as client_main
        argv = ['client', '--server', 'h:1', '--slot', 's', '--seed', '1', '--generation', 'g', '--ledger', 'l', '--snapshot', 'x']
        async def crash(args):
            raise KeyError(3)
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(client_main, 'run', crash), \
                self.assertLogs(level='ERROR') as logged, self.assertRaises(SystemExit) as raised:
            client_main.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn('Archipelago client crashed', logged.output[0])
        self.assertIn('KeyError', logged.output[0])

    def test_the_room_password_is_read_from_the_environment_and_removed_from_it(self):
        import os, sys
        from unittest import mock
        from archipelago.client import main as client_main
        seen = {}
        async def capture(args):
            seen['password'] = args.password
        argv = ['client', '--server', 'h:1', '--slot', 's', '--seed', '1', '--generation', 'g', '--ledger', 'l', '--snapshot', 'x']
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(client_main, 'run', capture), \
                mock.patch.dict(os.environ, {'DAD_AP_PASSWORD': 'hunter2'}):
            client_main.main()
            self.assertNotIn('DAD_AP_PASSWORD', os.environ)
        self.assertEqual(seen['password'], 'hunter2')
        with mock.patch.object(sys, 'argv', argv + ['--password', 'typed']), mock.patch.object(client_main, 'run', capture):
            client_main.main()
        self.assertEqual(seen['password'], 'typed')

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
            # The skill vanishes from the game: nothing fails any more. Receipt 0 was already granted in this game session and the mod
            # refuses to grant one receipt twice in a game process, so it is left for the next launch; receipt 1 was never granted
            # natively (it was satisfied by receipt 0), so it is delivered.
            self.assertEqual(fresh.reconcile({'owned':[]},{'owned':[],'save_sha256':'fixture'}),0)
            self.assertEqual([s for _,s in ledger.db.execute("SELECT idx,status FROM receipts ORDER BY idx")],['applied','applying'])
            self.assertTrue((root/'control.intent-1').exists())
            self.assertEqual(len(fresh.notices),2)
            ledger.close()

    def _reconciler(self, root, tag='tok', name='control'):
        source=root/'proof';source.write_text('fixture, not live proof')
        cert=root/'capability.json'
        cert.write_text(json.dumps(dict(status='verified-protected-passive-grant-cold',max_health_delta=10,
            duplicate_health_delta=0,sources={str(source):hashlib.sha256(source.read_bytes()).hexdigest()})))
        (root/name).mkdir(exist_ok=True)
        protection=SimpleNamespace(data=dict(production_proof_sha256=hashlib.sha256(cert.read_bytes()).hexdigest(),
            production_control=str(root/name/'control'),launch_token=tag))
        return protection,cert

    def test_a_skill_the_game_lost_is_delivered_again_instead_of_stopping_the_client(self):
        # Seen in two players' runs: the ledger holds a skill as applied, the game (live and saved file) no longer owns it, and the old
        # client died with 'Applied ownership lost; refuse save rollback' on every launch. The multiworld still says the player owns
        # the skill, so the next launch delivers it again.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root=Path(folder)
            catalog=dict(items=[dict(id=42,tag='Tag.One',name='Wild Growth',mechanism='owned-upgrade'),
                                dict(id=43,tag='Tag.Two',name='Fever Dream',mechanism='owned-upgrade')])
            ledger=Ledger(root/'ledger',Binding('seed',0,1,'generation','slot'))
            ledger.receive(0,[[42,99,1,1],[43,100,1,1]])
            protection,cert=self._reconciler(root,'tok-1','one')
            first=OwnershipReconciler(ledger,catalog,protection,cert)
            both={'owned':['Tag.One','Tag.Two'],'save_sha256':'old'}
            first.reconcile({'owned':[]},{'owned':[],'save_sha256':'old'})
            first.reconcile({'owned':['Tag.One']},{'owned':['Tag.One'],'save_sha256':'old'})
            first.reconcile(both,both)
            self.assertEqual([s for _,s in ledger.db.execute("SELECT idx,status FROM receipts ORDER BY idx")],['applied','applied'])
            # Next launch (a new runtime folder): the profile's save lost Tag.One.
            protection,cert=self._reconciler(root,'tok-2','two')
            second=OwnershipReconciler(ledger,catalog,protection,cert)
            lost={'owned':['Tag.Two'],'save_sha256':'rolled-back'}
            self.assertEqual(second.reconcile(lost,lost),0)                  # Tag.Two is still confirmed; Tag.One is delivered again
            self.assertEqual([s for _,s in ledger.db.execute("SELECT idx,status FROM receipts ORDER BY idx")],['applying','applied'])
            self.assertTrue((root/'two'/'control.intent-0').exists())
            self.assertTrue((root/'two'/'control').read_text().startswith('grant\n0\n42\ntok-2\n'))
            self.assertEqual(second.notices,['The game no longer had the skill "Wild Growth" the multiworld already sent you: giving it again.'])
            row=json.loads((root/'two'/'ownership-repairs.jsonl').read_text().splitlines()[0])
            self.assertEqual((row['kind'],row['tag'],row['in_saved']),('applied-ownership-lost','Tag.One',False))
            self.assertEqual(row['saved_owned'],['Tag.Two'])
            # The game grants it; once live and saved agree the receipt is applied again.
            self.assertEqual(second.reconcile(both,both),1)
            self.assertEqual(ledger.pending_items(),[])
            ledger.close()

    def test_a_skill_only_one_side_lacks_waits_for_the_game_instead_of_stopping(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root=Path(folder)
            catalog=dict(items=[dict(id=42,tag='Tag.One',mechanism='owned-upgrade')])
            ledger=Ledger(root/'ledger',Binding('seed',0,1,'generation','slot'))
            ledger.receive(0,[[42,99,1,1]])
            protection,cert=self._reconciler(root,'tok-1','one')
            both={'owned':['Tag.One'],'save_sha256':'a'}
            first=OwnershipReconciler(ledger,catalog,protection,cert)
            first.reconcile({'owned':[]},{'owned':[],'save_sha256':'a'});first.reconcile(both,both)
            protection,cert=self._reconciler(root,'tok-2','two')
            second=OwnershipReconciler(ledger,catalog,protection,cert)
            # The live game has not finished loading the save (it lacks the skill the saved file has): no failure, no repair yet.
            self.assertEqual(second.reconcile({'owned':[]},both),0)
            self.assertEqual(ledger.db.execute("SELECT status FROM receipts").fetchone()[0],'applied')
            self.assertFalse((root/'two'/'control').exists())
            # The game finished loading: nothing to repair.
            self.assertEqual(second.reconcile(both,both),0)
            self.assertEqual(second.live_missing_since,{})
            # The saved file lags the live game (an autosave is pending): the live game owns it, so nothing happens either.
            self.assertEqual(second.reconcile(both,{'owned':[],'save_sha256':'b'}),0)
            self.assertEqual(ledger.db.execute("SELECT status FROM receipts").fetchone()[0],'applied')
            # A live game that still lacks the skill after the grace period gets it delivered again.
            third=OwnershipReconciler(ledger,catalog,self._reconciler(root,'tok-3','three')[0],cert)
            self.assertEqual(third.reconcile({'owned':[]},both),0)
            third.live_missing_since[0]-=1000
            third.reconcile({'owned':[]},both)
            self.assertEqual(ledger.db.execute("SELECT status FROM receipts").fetchone()[0],'applying')
            self.assertTrue((root/'three'/'control.intent-0').exists())
            ledger.close()

    def test_a_skill_that_vanishes_again_in_the_same_game_session_is_not_sent_twice(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root=Path(folder)
            catalog=dict(items=[dict(id=42,tag='Tag.One',name='Wild Growth',mechanism='owned-upgrade')])
            ledger=Ledger(root/'ledger',Binding('seed',0,1,'generation','slot'))
            ledger.receive(0,[[42,99,1,1]])
            protection,cert=self._reconciler(root,'tok-1','one')
            both={'owned':['Tag.One'],'save_sha256':'a'};empty={'owned':[],'save_sha256':'b'}
            first=OwnershipReconciler(ledger,catalog,protection,cert)
            first.reconcile(empty,empty);first.reconcile(both,both)            # delivered and applied in this game session
            first.reconcile(empty,empty)                                         # then the game drops it
            self.assertEqual(ledger.db.execute("SELECT status FROM receipts").fetchone()[0],'applied')
            self.assertEqual(len(first.notices),1)
            self.assertIn('comes back the next time you press Play',first.notices[0])
            first.reconcile(empty,empty)                                         # reported once, never re-sent
            self.assertEqual(len(first.notices),1)
            self.assertEqual((root/'one'/'control').read_text().count('grant\n'),1)
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
