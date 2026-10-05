"""Opt-in native interaction acceptance; fixtures never enter public MCP tools."""
import os,time,unittest
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json

@unittest.skipUnless(os.getenv('SC_SURVIVAL_TEST_CONFIG'),'Independent survival LAB required')
class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=Config.load(os.environ['SC_SURVIVAL_TEST_CONFIG']);assert cls.config.target.get('test_only') and cls.config.target['name']=='SC MCP LAB SURVIVAL';cls.evidence=[]
    @classmethod
    def tearDownClass(cls):atomic_json(cls.config.artifacts_dir/'interactions-live.json',cls.evidence)
    def setUp(self):self.b=Bridge(self.config);self.b.isolate_local()
    def fixture(self,name):return self.b.call('lab_fixture_'+name,identity=self.b.identity())
    def finish(self,p,submit=True):
        if submit:p=self.b.operation_submit(p['operation_id'],p['risk'])
        deadline=time.monotonic()+15
        while p['state'] not in ('completed','failed','cancelled'):
            self.assertLess(time.monotonic(),deadline);time.sleep(.025);p=self.b.operation_status(p['operation_id'])
        self.assertEqual(p['state'],'completed',p);self.evidence.append(p);return p
    def test_01_door_direct_restore_and_agent_events(self):
        b=self.b;f=self.fixture('door');sub=b.event_subscribe(['block_click'])
        try:
            done=self.finish(b.interact_block(f['target']));self.assertNotEqual(done['before']['target'],done['after']['target'])
            rows=b.event_poll(sub['subscription_id'])['events'];self.assertEqual([e['outcome'] for e in rows],['attempt','success'])
            self.assertTrue(all(e['source']=='agent' and e['operation_id']==done['operation_id'] for e in rows));self.evidence.append({'events':rows})
            restored=self.finish(b.operation_restore(done['operation_id'],done['risk']),False);self.assertEqual(restored['after'],done['before'])
        finally:b.event_unsubscribe(sub['subscription_id']);self.fixture('remove')
    def test_02_trapdoor(self):
        f=self.fixture('trapdoor')
        try:
            done=self.finish(self.b.interact_block(f['target']));self.assertNotEqual(done['before'],done['after'])
            self.finish(self.b.operation_restore(done['operation_id'],done['risk']),False)
        finally:self.fixture('remove')
    def test_03_switch_external_circuit(self):
        f=self.fixture('switch')
        try:
            done=self.finish(self.b.interact_block(f['target']));time.sleep(.4);state=self.fixture('state')
            self.assertGreater(state['max_brightness'],0,state);self.evidence.append(state)
            self.finish(self.b.operation_restore(done['operation_id'],done['risk']),False)
        finally:self.fixture('remove')
    def test_04_button_pulse_irreversible(self):
        f=self.fixture('button')
        try:
            done=self.finish(self.b.interact_block(f['target']));self.assertEqual(done['recovery'],'none');time.sleep(.3)
            state=self.fixture('state');self.assertGreater(state['max_brightness'],0,state);self.evidence.append(state)
            with self.assertRaises(BridgeError) as e:self.b.operation_restore(done['operation_id'],done['risk'])
            self.assertEqual(e.exception.code,'NOT_RECOVERABLE')
        finally:self.fixture('remove')
    def test_05_container_open_gui_only(self):
        f=self.fixture('container')
        try:
            done=self.finish(self.b.interact_block(f['target']));self.assertEqual(done['recovery'],'none');state=self.fixture('state')
            self.assertEqual(state['modal'],'Game.ChestWidget');self.evidence.append(state)
        finally:self.fixture('remove')
    def test_06_pending_no_replay(self):
        b=self.b;f=self.fixture('door');sub=b.event_subscribe(['block_click'])
        try:
            b.call('lab_pending_enable',identity=b.identity());plan=b.interact_block(f['target']);plan=b.operation_submit(plan['operation_id'],plan['risk']);deadline=time.monotonic()+5
            while plan['state']!='waiting_native':
                self.assertLess(time.monotonic(),deadline);self.assertNotEqual(plan['state'],'failed',plan);time.sleep(.025);plan=b.operation_status(plan['operation_id'])
            duplicate=b.operation_submit(plan['operation_id'],plan['risk']);self.assertEqual(duplicate['state'],'waiting_native')
            self.assertTrue(b.call('lab_pending_complete',identity=b.identity())['accepted']);done=self.finish(plan,False)
            rows=b.event_poll(sub['subscription_id'])['events'];self.assertEqual([e['outcome'] for e in rows],['attempt','unknown','success'])
            self.assertTrue(all(e['operation_id']==done['operation_id'] for e in rows));self.evidence.append({'pending_events':rows})
            self.finish(b.operation_restore(done['operation_id'],done['risk']),False)
        finally:b.event_unsubscribe(sub['subscription_id']);self.fixture('remove')
    def test_07_reach_view_and_occlusion(self):
        b=self.b;f=self.fixture('door');position=b.players()[0]['position']
        try:
            b.camera([-157,66,-97],[-157,66,-101]);b.teleport([-157,65,-90])
            with self.assertRaises(BridgeError) as e:b.interact_block(f['target'])
            self.assertEqual(e.exception.code,'CAMERA_DETACHED')
            b.teleport([-157,65,-97]);b.camera([-157,66,-97],[-153,66,-97])
            with self.assertRaises(BridgeError) as e:b.interact_block(f['target'])
            self.assertEqual(e.exception.code,'TARGET_NOT_VISIBLE')
        finally:self.fixture('remove')
    def test_08_native_event_families(self):
        b=self.b;sub=b.event_subscribe(['item_use','eat','wear','longpress_start','longpress_end','capture'])
        try:
            result=b.call('lab_native_event_suite',identity=b.identity());self.assertFalse(result['native_use']);self.assertTrue(result['native_eat']);self.assertTrue(result['clothing_changed'])
            capture=b.screenshot();page=b.event_poll(sub['subscription_id']);kinds={e['kind'] for e in page['events']}
            self.assertEqual(kinds,{'item_use','eat','wear','longpress_start','longpress_end','capture'})
            self.assertTrue(all(e['source']=='unknown' for e in page['events']));self.evidence.append({'native_suite':result,'events':page,'capture':capture})
        finally:b.event_unsubscribe(sub['subscription_id'])
    def test_09_actual_obstruction_and_reach(self):
        b=self.b;f=self.fixture('switch')
        try:
            self.fixture('blocker')
            with self.assertRaises(BridgeError) as e:b.interact_block(f['target'])
            self.assertEqual(e.exception.code,'TARGET_NOT_VISIBLE')
        finally:self.fixture('remove')
        f=self.fixture('switch')
        try:
            self.fixture('far')
            with self.assertRaises(BridgeError) as e:b.interact_block(f['target'])
            self.assertEqual(e.exception.code,'TARGET_NOT_VISIBLE')
        finally:self.fixture('remove')
