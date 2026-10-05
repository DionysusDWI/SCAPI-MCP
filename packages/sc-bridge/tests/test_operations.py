"""Opt-in LAB acceptance for explicit non-building effects."""
import os,time,unittest
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json

class OperationInputTests(unittest.TestCase):
    def setUp(self):
        self.b=Bridge(None);self.b.identity=lambda player_index=0:{'player_index':player_index}
        self.b.call=lambda op,args,identity:{'op':op,'args':args}
    def test_closed_types_and_ranges(self):
        for call in (lambda:self.b.player_patch(health=0),lambda:self.b.player_patch(food=True),lambda:self.b.player_patch(level=float('nan')),
                     lambda:self.b.player_patch(path='Health'),lambda:self.b.environment_patch(simulation_factor=0),lambda:self.b.environment_patch(day_duration_seconds=1),
                     lambda:self.b.environment_patch(seed='1932'),lambda:self.b.inventory_transfer({'kind':'player'},{'kind':'container','position':[1,2,3]},3,False),
                     lambda:self.b.event_subscribe(['arbitrary']),lambda:self.b.event_subscribe(['creature_click']),lambda:self.b.operation_submit('invalid','dangerous')):
            with self.assertRaises(BridgeError):call()
    def test_dedicated_and_generic_share_preflight(self):
        self.assertEqual(self.b.player_patch(level=5),self.b.command('player','patch',{'level':5}))
        self.assertEqual(self.b.environment_patch(weather_enabled=False),self.b.command('environment','patch',{'weather_enabled':False}))
        with self.assertRaises(BridgeError):self.b.command('inventory','edit',{'target':{'kind':'player'},'mode':'run_script'})

@unittest.skipUnless(os.getenv('SC_OPERATION_TEST_CONFIG'),'Explicit LAB config required')
class OperationLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=Config.load(os.environ['SC_OPERATION_TEST_CONFIG']);assert cls.config.target.get('test_only') and cls.config.target['name'].startswith('SC MCP LAB')
        cls.evidence=[]
    @classmethod
    def tearDownClass(cls):atomic_json(cls.config.artifacts_dir/'operations-live.json',cls.evidence)
    def setUp(self):self.b=Bridge(self.config);self.b.isolate_local()
    def finish(self,plan,submit=True):
        b=self.b;deadline=time.monotonic()+30
        while plan['state']=='scanning':
            self.assertLess(time.monotonic(),deadline);time.sleep(.03);plan=b.operation_status(plan['operation_id'])
        if submit:plan=b.operation_submit(plan['operation_id'],plan['risk'])
        while plan['state'] not in ('completed','failed','cancelled'):
            self.assertLess(time.monotonic(),deadline);time.sleep(.03);plan=b.operation_status(plan['operation_id'])
        self.assertEqual(plan['state'],'completed',plan);self.evidence.append(plan);return plan
    def test_01_risk_dedup_restore_conflict(self):
        b=self.b;before=b.player_state()['level'];plan=b.player_patch(level=7)
        with self.assertRaises(BridgeError) as e:b.operation_submit(plan['operation_id'],'dangerous')
        self.assertEqual(e.exception.code,'RISK_ACK_REQUIRED')
        done=self.finish(plan);duplicate=b.operation_submit(plan['operation_id'],done['risk']);self.assertEqual(done['operation_id'],duplicate['operation_id'])
        changed=self.finish(b.player_patch(level=8))
        with self.assertRaises(BridgeError) as e:b.operation_restore(done['operation_id'],done['risk'])
        self.assertEqual(e.exception.code,'RESTORE_CONFLICT')
        self.finish(b.player_patch(level=before))
    def test_02_stale_plan(self):
        b=self.b;before=b.player_state()['level'];old=b.player_patch(level=6);self.finish(b.player_patch(level=9))
        with self.assertRaises(BridgeError) as e:b.operation_submit(old['operation_id'],old['risk'])
        self.assertEqual(e.exception.code,'STALE_PLAN');self.finish(b.player_patch(level=before))
    def test_03_environment_direct_restore(self):
        b=self.b;old=b.environment_info()['weather_enabled'];done=self.finish(b.environment_patch(weather_enabled=not old))
        self.assertEqual(b.environment_info()['weather_enabled'],not old)
        restored=b.operation_restore(done['operation_id'],done['risk']);self.finish(restored,False)
        self.assertEqual(b.environment_info()['weather_enabled'],old)
    def test_04_creative_inventory_edit_restore(self):
        b=self.b;before=b.inventory_read();self.assertTrue(before['creative_supply'])
        done=self.finish(b.inventory_edit({'kind':'player'},'set',slots=[{'index':0,'value':3,'count':1}],active_slot=0))
        self.assertEqual(b.inventory_read()['slots'][0]['value'],3)
        restored=b.operation_restore(done['operation_id'],done['risk']);self.finish(restored,False)
        self.assertEqual(b.inventory_read()['slots'][0]['value'],before['slots'][0]['value'])
    def test_05_override_save_enable_disable(self):
        b=self.b;self.finish(b.player_override('save',{'walk_speed':6,'attack_power':3,'attack_resilience':12}))
        self.finish(b.player_override('enable'));self.assertTrue(b.player_override('query')['enabled']);self.assertEqual(b.player_state()['walk_speed'],6)
        self.finish(b.player_override('disable'));self.assertFalse(b.player_override('query')['enabled'])
    def test_06_events_native_and_isolation(self):
        b=self.b;other=Bridge(self.config);a=b.event_subscribe(['eat']);c=other.event_subscribe(['eat'])
        try:
            b.call('lab_event_native_attempt',{},b.identity());first=b.event_poll(a['subscription_id']);second=other.event_poll(c['subscription_id'])
            self.assertEqual(first['events'],second['events']);self.assertEqual([e['outcome'] for e in first['events']],['attempt','failed'])
            with self.assertRaises(BridgeError) as e:other.event_poll(a['subscription_id'])
            self.assertEqual(e.exception.code,'CURSOR_MISMATCH')
            time.sleep(.1);history=b.event_history();self.assertTrue(any(e['kind']=='eat' for e in history['events']));self.assertFalse(history['automatic_actions'])
            self.evidence.append({'native_events':first,'history':history})
        finally:b.event_unsubscribe(a['subscription_id']);other.event_unsubscribe(c['subscription_id'])
    def test_07_events_overflow(self):
        b=self.b;sub=b.event_subscribe(['capture'])
        try:
            b.call('lab_event_overflow',{},b.identity());page=b.event_poll(sub['subscription_id']);self.assertTrue(page['gap']);self.assertEqual(len(page['events']),64);self.evidence.append(page)
        finally:b.event_unsubscribe(sub['subscription_id'])

    def test_08_creature_click_closed_in_host(self):
        b=self.b
        with self.assertRaises(BridgeError) as error:
            b.call('event_subscribe',{'client_id':b.client_id,'kinds':['creature_click']},b.identity())
        self.assertEqual(error.exception.code,'UNREGISTERED_COMMAND')
        with self.assertRaises(BridgeError) as error:
            b.call('lab_fixture_creature',identity=b.identity())
        self.assertEqual(error.exception.code,'CAPABILITY_UNAVAILABLE')
        self.evidence.append({'creature_click':'rejected_by_host','creature_input_fixture':'closed','reason':'user decision: explicit API properties instead of clicks'})
