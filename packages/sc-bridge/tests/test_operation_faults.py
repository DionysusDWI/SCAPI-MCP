import os,time,unittest,uuid
from pathlib import Path
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json

@unittest.skipUnless(os.getenv('SC_SURVIVAL_TEST_CONFIG'),'Independent survival LAB required')
class OperationFaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=Config.load(os.environ['SC_SURVIVAL_TEST_CONFIG']);assert cls.config.target.get('test_only') and cls.config.target['name']=='SC MCP LAB SURVIVAL';cls.evidence=[]
    @classmethod
    def tearDownClass(cls):atomic_json(cls.config.artifacts_dir/'operation-faults-live.json',cls.evidence)
    def setUp(self):
        self.b=Bridge(self.config);self.b.isolate_local()
        # Prepare a living survival player using the same audited public path; no resurrection or health bypass.
        self.assertGreater(self.b.player_state()['health'],0,'Native respawn is required before this suite')
        self.finish(self.b.player_patch(food=.8,sleep=.9,wetness=0,temperature=12,stamina=1))
    def finish(self,p,expected='completed',submit=True):
        deadline=time.monotonic()+30
        while p['state']=='scanning':
            self.assertLess(time.monotonic(),deadline);time.sleep(.025);p=self.b.operation_status(p['operation_id'])
        if submit:p=self.b.operation_submit(p['operation_id'],p['risk'])
        while p['state'] not in ('completed','failed','cancelled','paused'):
            self.assertLess(time.monotonic(),deadline);time.sleep(.025);p=self.b.operation_status(p['operation_id'])
        self.assertEqual(p['state'],expected,p);self.evidence.append(p);return p
    def test_01_inventory_partial_failure_compensation(self):
        b=self.b;before=b.inventory_read();b.call('lab_inventory_fail_second',identity=b.identity())
        try:
            done=self.finish(b.inventory_edit({'kind':'player'},'set',slots=[{'index':0,'value':3,'count':5},{'index':1,'value':3,'count':5}]),'failed')
            self.assertEqual(done['error']['code'],'LAB_INJECTED_FAILURE');self.assertEqual(b.inventory_read()['slots'],before['slots'])
            self.assertEqual([s['state'] for s in done['steps'][-2:]],['compensated','compensated'])
            duplicate=b.operation_submit(done['operation_id'],done['risk']);self.assertEqual(duplicate['state'],'failed');self.assertEqual(b.inventory_read()['slots'],before['slots'])
        finally:b.call('lab_inventory_failure_release',identity=b.identity())
    def test_02_inventory_external_change_and_two_clients(self):
        b=self.b;other=Bridge(self.config);old=b.inventory_edit({'kind':'player'},'set',slots=[{'index':0,'value':3,'count':5}])
        done=self.finish(other.inventory_edit({'kind':'player'},'set',slots=[{'index':0,'value':3,'count':2}]))
        with self.assertRaises(BridgeError) as e:b.operation_submit(old['operation_id'],old['risk'])
        self.assertEqual(e.exception.code,'STALE_PLAN');self.assertEqual(b.inventory_read()['slots'][0]['reported_count'],2)
        self.finish(b.operation_restore(done['operation_id'],done['risk']),submit=False)
    def test_03_override_external_change(self):
        b=self.b;self.finish(b.player_override('save',{'walk_speed':6}));self.finish(b.player_override('enable'))
        changed=b.call('lab_override_external_change',identity=b.identity());time.sleep(.1);state=b.player_override('query')
        self.assertFalse(state['enabled']);self.assertIn('OVERRIDE_CONFLICT',state['error']);self.assertEqual(b.player_state()['walk_speed'],changed['walk_speed']);self.evidence.append(state)
    def test_04_journal_failure_no_effect(self):
        b=self.b;level=b.player_state()['level'];b.call('lab_journal_fail_next',identity=b.identity());done=self.finish(b.player_patch(level=7),'failed')
        self.assertTrue(done['audit_error']);self.assertIn(done['audit_state'],('failed','writing','durable'));self.assertEqual(done['state'],'failed');self.assertAlmostEqual(b.player_state()['level'],level,places=2)
    def test_05_bad_identity_and_split_screen(self):
        b=self.b;identity=b.identity();identity['session']=uuid.uuid4().hex
        with self.assertRaises(BridgeError) as e:b.call('operation_preflight',{'action':'player_patch','parameters':{'level':7}},identity)
        self.assertEqual(e.exception.code,'IDENTITY_MISMATCH')
        b.call('lab_add_player',identity=b.identity())
        try:
            with self.assertRaises(BridgeError) as e:b.player_patch(level=7)
            self.assertEqual(e.exception.code,'MULTIPLAYER_DISABLED')
        finally:b.call('lab_remove_player',identity=b.identity());b.isolate_local()
    def test_06_backup_required(self):
        b=self.b;backup=Path(self.config.host_settings()['target']['backup_path']).resolve();backup.relative_to(self.config.backups_dir);moved=backup.with_suffix('.scworld.acceptance-held')
        self.assertFalse(moved.exists());plan=b.environment_patch(game_mode='Creative');before=b.environment_info()['game_mode']
        backup.rename(moved)
        try:
            with self.assertRaises(BridgeError) as e:b.operation_submit(plan['operation_id'],plan['risk'])
            self.assertEqual(e.exception.code,'BACKUP_UNAVAILABLE');self.assertEqual(b.environment_info()['game_mode'],before)
        finally:moved.rename(backup)
    def test_07_unloaded_climate_and_bounds(self):
        b=self.b;p=b.climate_patch([900000,900000],[900001,900001],temperature=9);deadline=time.monotonic()+5
        while p['state']=='scanning':
            self.assertLess(time.monotonic(),deadline);time.sleep(.025);p=b.operation_status(p['operation_id'])
        self.assertEqual(p['state'],'failed');self.assertEqual(p['error']['code'],'REGION_NOT_LOADED');self.assertEqual(p['processed'],0);self.evidence.append(p)
        with self.assertRaises(BridgeError) as e:b.climate_patch([0,0],[1000,1000],temperature=9)
        self.assertEqual(e.exception.code,'LIMIT_EXCEEDED')
    def test_08_event_audit_failure_reported(self):
        b=self.b;sub=b.event_subscribe(['eat'])
        try:
            b.call('lab_event_log_fail_next',identity=b.identity());b.call('lab_event_native_attempt',identity=b.identity());time.sleep(.15);page=b.event_poll(sub['subscription_id'])
            self.assertTrue(page['audit_error']);self.assertEqual(len(page['events']),2);self.evidence.append(page)
        finally:b.event_unsubscribe(sub['subscription_id'])
    def test_09_existing_region_timeout_pauses_without_replay(self):
        b=self.b;p=b.climate_patch([-180,-120],[-131,-71],humidity=5);deadline=time.monotonic()+60
        while p['state']=='scanning':
            self.assertLess(time.monotonic(),deadline);time.sleep(.02);p=b.operation_status(p['operation_id'])
        self.assertEqual(p['state'],'ready',p);p=b.operation_submit(p['operation_id'],p['risk'])
        while p['processed']==0:
            self.assertNotIn(p['state'],('failed','completed'));self.assertLess(time.monotonic(),deadline);time.sleep(.005);p=b.operation_status(p['operation_id'])
        b.call('lab_climate_unavailable',identity=b.identity())
        try:
            while p['state']!='paused':
                self.assertNotIn(p['state'],('completed','failed'));self.assertLess(time.monotonic(),deadline);time.sleep(.03);p=b.operation_status(p['operation_id'])
            self.assertEqual(p['error']['code'],'REGION_LOAD_TIMEOUT');self.assertGreater(p['processed'],0);self.assertLess(p['processed'],2500);self.evidence.append({'explicit_load_fault_fixture':True,'result':p})
        finally:b.call('lab_climate_available',identity=b.identity())
        count=p['processed'];time.sleep(.1);self.assertEqual(b.operation_status(p['operation_id'])['processed'],count);self.assertEqual(b.operation_submit(p['operation_id'],p['risk'])['state'],'paused');self.assertEqual(b.operation_cancel(p['operation_id'])['state'],'cancelled')
