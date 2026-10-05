"""No clicking: native non-player fields only, explicitly registered LAB."""
import os,time,unittest
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json

class CreatureInputTests(unittest.TestCase):
    def test_closed_fields(self):
        b=Bridge(None);b.identity=lambda player_index=0:{};b.call=lambda op,args,identity:args
        for fields in ({'health':0},{'walk_speed':65},{'attack_power':float('nan')},{'attack_resilience':0},{'ai':'attack'},{'health':True}):
            with self.assertRaises(BridgeError):b.creature_patch('0'*32,fields)
        self.assertEqual(b.creature_patch('0'*32,{'health':.5}),b.command('creature','patch',{'target_id':'0'*32,'fields':{'health':.5}}))

@unittest.skipUnless(os.getenv('SC_CREATURE_TEST_CONFIG'),'Explicit LAB required')
class CreatureLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=Config.load(os.environ['SC_CREATURE_TEST_CONFIG']);assert cls.config.target.get('test_only') and cls.config.target['name'].startswith('SC MCP LAB');cls.evidence=[]
    @classmethod
    def tearDownClass(cls):atomic_json(cls.config.artifacts_dir/'creature-properties-live.json',cls.evidence)
    def setUp(self):
        self.b=Bridge(self.config);self.b.isolate_local();self.fixture=self.b.call('lab_create_observation_fixture',identity=self.b.identity());self.target=self.b.creature_inspect(self.fixture['wolf_id'])
    def tearDown(self):self.b.call('lab_remove_observation_fixture',identity=self.b.identity())
    def finish(self,p,submit=True):
        if submit:p=self.b.operation_submit(p['operation_id'],p['risk'])
        end=time.monotonic()+10
        while p['state'] not in ('completed','failed'):
            self.assertLess(time.monotonic(),end);time.sleep(.025);p=self.b.operation_status(p['operation_id'])
        self.assertEqual(p['state'],'completed',p);self.evidence.append(p);return p
    def test_01_native_fields_dedup_and_restore(self):
        b=self.b;old=self.target['fields'];fields={'walk_speed':5,'attack_power':17,'attack_resilience':42}
        done=self.finish(b.creature_patch(self.target['target_id'],fields));self.assertEqual(done['after']['fields'],fields)
        again=b.operation_submit(done['operation_id'],done['risk']);self.assertEqual(again['operation_id'],done['operation_id']);self.assertEqual(again['after'],done['after'])
        restored=self.finish(b.operation_restore(done['operation_id'],done['risk']),False)
        for k in fields:self.assertAlmostEqual(restored['after']['fields'][k],old[k],places=4)
        health=self.finish(b.creature_patch(self.target['target_id'],{'health':.75}));self.assertAlmostEqual(health['after']['fields']['health'],.75,places=5)
    def test_02_effective_defense_factor(self):
        b=self.b;b.call('lab_creature_factor',identity=b.identity());target=b.creature_inspect(self.fixture['wolf_id']);old=target['fields']['attack_resilience'];done=self.finish(b.creature_patch(target['target_id'],{'attack_resilience':100}))
        self.assertEqual(done['after']['fields']['attack_resilience'],100);self.assertEqual(done['after']['attack_resilience_factor'],2)
        restored=self.finish(b.operation_restore(done['operation_id'],done['risk']),False);self.assertEqual(restored['after']['fields']['attack_resilience'],old)
    def test_03_external_and_restore_conflicts(self):
        b=self.b;p=b.creature_patch(self.target['target_id'],{'walk_speed':5});b.call('lab_creature_external',identity=b.identity())
        with self.assertRaises(BridgeError) as e:b.operation_submit(p['operation_id'],p['risk'])
        self.assertEqual(e.exception.code,'STALE_PLAN')
        done=self.finish(b.creature_patch(self.target['target_id'],{'walk_speed':5}));b.call('lab_creature_external',identity=b.identity())
        with self.assertRaises(BridgeError) as e:b.operation_restore(done['operation_id'],done['risk'])
        self.assertEqual(e.exception.code,'RESTORE_CONFLICT')
    def test_04_client_player_dead_removed(self):
        b=self.b;other=Bridge(self.config)
        with self.assertRaises(BridgeError) as e:other.creature_patch(self.target['target_id'],{'walk_speed':5})
        self.assertEqual(e.exception.code,'IDENTITY_MISMATCH')
        done=b.creature_patch(self.target['target_id'],{'walk_speed':5})
        with self.assertRaises(BridgeError) as e:other.operation_submit(done['operation_id'],done['risk'])
        self.assertEqual(e.exception.code,'IDENTITY_MISMATCH')
        players=b.entity_query([-180,60,-120],[-120,120,-70],kind='player')['records']
        with self.assertRaises(BridgeError) as e:b.creature_inspect(players[0]['native_id'])
        self.assertEqual(e.exception.code,'INVALID_CREATURE')
        b.call('lab_creature_dead',identity=b.identity())
        with self.assertRaises(BridgeError) as e:b.creature_patch(self.target['target_id'],{'health':1})
        self.assertEqual(e.exception.code,'CREATURE_DEAD')
        b.call('lab_remove_observation_fixture',identity=b.identity())
        with self.assertRaises(BridgeError) as e:b.creature_patch(self.target['target_id'],{'walk_speed':5})
        self.assertEqual(e.exception.code,'TARGET_REMOVED')
    def test_05_response_loss_queries_without_replay(self):
        from dataclasses import replace
        b=self.b;b.config=replace(b.config,timeout=1);plan=b.creature_patch(self.target['target_id'],{'attack_power':29});b.call('lab_creature_drop_reply',identity=b.identity())
        with self.assertRaises(BridgeError) as e:b.operation_submit(plan['operation_id'],plan['risk'])
        self.assertEqual(e.exception.code,'TIMEOUT');done=b.operation_status(plan['operation_id']);self.assertEqual(done['state'],'completed');self.assertEqual(done['after']['fields']['attack_power'],29)
        self.assertEqual(b.operation_submit(plan['operation_id'],plan['risk'])['after'],done['after']);self.evidence.append(done)
