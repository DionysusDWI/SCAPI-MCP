import os,time,unittest
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json

@unittest.skipUnless(os.getenv('SC_SURVIVAL_TEST_CONFIG'),'Independent survival LAB required')
class MaintenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=Config.load(os.environ['SC_SURVIVAL_TEST_CONFIG']);assert cls.config.target.get('test_only') and cls.config.target['name']=='SC MCP LAB SURVIVAL';cls.evidence=[]
    @classmethod
    def tearDownClass(cls):atomic_json(cls.config.artifacts_dir/'maintenance-live.json',cls.evidence)
    def setUp(self):self.b=Bridge(self.config);self.b.isolate_local()
    def finish(self,p):
        p=self.b.operation_submit(p['operation_id'],p['risk']);deadline=time.monotonic()+60;states=[]
        while p['state'] not in ('completed','failed'):
            self.assertLess(time.monotonic(),deadline);time.sleep(.03);p=self.b.operation_status(p['operation_id']);states.append(p['state'])
        self.assertEqual(p['state'],'completed',p);self.evidence.append({'result':p,'states':states});return p
    def wait_world(self):
        deadline=time.monotonic()+30
        while True:
            try:
                if self.b.world_info().get('loaded') and self.b.players()[0]['position'] is not None:self.b.isolate_local();return
            except (BridgeError,IndexError):pass
            self.assertLess(time.monotonic(),deadline);time.sleep(.05)
    def test_01_mode_reload_inventory_and_override_release(self):
        b=self.b;old_session=b.world_info()['session'];self.finish(b.player_override('save',{'walk_speed':6,'attack_power':3,'attack_resilience':12}));self.finish(b.player_override('enable'))
        sub=b.event_subscribe(['eat']);done=self.finish(b.environment_patch(game_mode='Creative'))
        self.assertNotEqual(old_session,b.world_info()['session']);self.assertTrue(done['full_backup']['sha256']);self.assertEqual(done['after']['game_mode'],'Creative');self.assertTrue(b.inventory_read()['creative_supply']);self.assertFalse(b.player_override('query')['enabled']);self.assertEqual(b.player_state()['attack_power'],1)
        with self.assertRaises(BridgeError) as e:b.event_poll(sub['subscription_id'])
        self.assertEqual(e.exception.code,'SUBSCRIPTION_EXPIRED')
        duplicate=b.operation_submit(done['operation_id'],done['risk']);self.assertEqual(duplicate['operation_id'],done['operation_id']);self.assertEqual(duplicate['state'],'completed')
        with self.assertRaises(BridgeError) as e:b.player_patch(food=.8)
        self.assertEqual(e.exception.code,'UNSUPPORTED_MODE')
        self.finish(b.environment_patch(game_mode='Challenging'));self.assertFalse(b.inventory_read()['creative_supply'])
    def test_02_season_reload_and_backup(self):
        b=self.b;old=b.environment_info()['season'];done=self.finish(b.environment_patch(season=.375,seasons_changing=False))
        self.assertAlmostEqual(b.environment_info()['season'],.375,places=4);self.assertFalse(b.environment_info()['seasons_changing']);self.assertEqual(done['recovery'],'none');self.assertTrue(done['full_backup']['sha256'])
        self.finish(b.environment_patch(season=old,seasons_changing=False))
    def test_03_session_fields_and_time_never_rewinds_elapsed(self):
        b=self.b;old=b.environment_info();done=self.finish(b.environment_patch(time_of_day_mode='Changing',time_of_day=.4,simulation_factor=.5,day_duration_seconds=2400,sky_color=[30,40,50,255],precipitation_color=[60,70,80,255]))
        current=b.environment_info();self.assertGreaterEqual(current['elapsed_game_seconds'],old['elapsed_game_seconds']);self.assertAlmostEqual(current['time_of_day'],.4,places=2);self.assertEqual(current['simulation_factor'],.5);self.assertEqual(current['day_duration_seconds'],2400);self.assertEqual(current['sky_color'],[30,40,50,255]);self.evidence.append(current)
        b.call('lab_save_unload',identity=b.identity());b.call('lab_load_target');self.wait_world();reloaded=b.environment_info()
        self.assertEqual(reloaded['simulation_factor'],1);self.assertEqual(reloaded['day_duration_seconds'],1200);self.assertEqual(reloaded['sky_color'],[30,40,50,255]);self.evidence.append(reloaded)
        # Restore persistent clock mode explicitly; original direct operation also modified session fields, so its exact comparison correctly conflicts after reload.
        self.finish(b.environment_patch(time_of_day_mode=old['time_of_day_mode'],sky_color=old['sky_color'],precipitation_color=old['precipitation_color']))
