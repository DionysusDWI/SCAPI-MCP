"""Active object snapshots: no tests may target a production world."""
import os
import time
import unittest
from sc_bridge import Bridge, BridgeError, Config
from sc_bridge.client import atomic_json

LO=[-180,60,-120]
HI=[-120,120,-70]

class ObjectInputTests(unittest.TestCase):
    def setUp(self):
        self.b=Bridge(None);self.b.identity=lambda player_index=0: {'player_index':player_index}
        self.b.call=lambda op,args,identity: {'op':op,'args':args,'identity':identity}
    def test_limits_filters_and_cursor(self):
        cases=[lambda:self.b.entity_query(HI,LO),lambda:self.b.entity_query(LO,HI,kind='npc'),
            lambda:self.b.entity_query(LO,HI,template=''),lambda:self.b.entity_query(LO,HI,limit=True),
            lambda:self.b.entity_query(LO,HI,cursor='bad'),lambda:self.b.pickable_query(LO,HI,value=False),
            lambda:self.b.pickable_query([0,0,0],[500000,0,0]),lambda:self.b.entity_query([0,0,0],[100,255,100])]
        for case in cases:
            with self.subTest(case=case),self.assertRaises(BridgeError):case()
    def test_generic_and_client_identity(self):
        args={'minimum':LO,'maximum':HI,'kind':'player','limit':2}
        self.assertEqual(self.b.command('observe','entity_query',args),self.b.entity_query(**args))
        with self.assertRaises(BridgeError):self.b.command('observe','pickable_query',{'minimum':LO,'maximum':HI,'path':'objects'})
        self.assertNotEqual(self.b.client_id,Bridge(None).client_id)

@unittest.skipUnless(os.environ.get('SC_ENTITY_TEST_CONFIG'),'Explicit lab required')
class ObjectLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=Config.load(os.environ['SC_ENTITY_TEST_CONFIG'])
        assert cls.config.target.get('test_only') and cls.config.target['name'].startswith('SC MCP LAB')
        cls.evidence=[]
    @classmethod
    def tearDownClass(cls):atomic_json(cls.config.artifacts_dir/'entity-observation-live.json',cls.evidence)
    def setUp(self):
        self.b=Bridge(self.config);self.b.isolate_local()
        self.b.call('lab_expire_observation_snapshots',{},self.b.identity())
    def fixture(self):return self.b.call('lab_create_observation_fixture',{},self.b.identity())
    def cleanup(self):
        self.b.call('lab_remove_observation_fixture',{},self.b.identity());time.sleep(.2)
    def test_01_capture_filter_and_pages(self):
        b=self.b;fixture=self.fixture()
        try:
            first=b.entity_query(LO,HI,limit=1);self.assertGreaterEqual(first['total'],2)
            self.assertFalse(first['persistent_identity']);self.assertIsNotNone(first['next_cursor'])
            records=first['records'];page=first
            while page['next_cursor']:
                page=b.entity_query(LO,HI,limit=1,cursor=page['next_cursor'])
                self.assertEqual(page['snapshot_id'],first['snapshot_id']);self.assertEqual(page['observed_at_utc_ms'],first['observed_at_utc_ms'])
                records+=page['records']
            self.assertEqual(len(records),first['total']);self.assertEqual(len({r['observation_id'] for r in records}),len(records))
            self.assertTrue(any(r['kind']=='player' for r in records));self.assertTrue(any(r['template']=='Wolf' for r in records))
            filtered=b.entity_query(LO,HI,template='Wolf');self.assertTrue(filtered['records']);self.assertTrue(all(r['template']=='Wolf' for r in filtered['records']))
            players=b.entity_query(LO,HI,kind='player');self.assertEqual(players['total'],1)
            pickables=b.pickable_query(LO,HI,limit=1);self.assertEqual(pickables['total'],4)
            selected=b.pickable_query(LO,HI,value=3);self.assertEqual(selected['total'],2);self.assertTrue(all(r['value']==3 for r in selected['records']))
            self.evidence.append({'test':'capture_filter_pages','fixture':fixture,'entities':records,'pickables':pickables,'value_filter':selected})
        finally:self.cleanup()
    def test_02_snapshot_survives_object_removal(self):
        b=self.b;fixture=self.fixture()
        try:
            first=b.pickable_query(LO,HI,limit=1);self.assertEqual(first['total'],4)
        finally:self.cleanup()
        current=b.pickable_query(LO,HI);self.assertFalse(current['records'])
        records=first['records'];page=first
        while page['next_cursor']:
            page=b.pickable_query(LO,HI,limit=1,cursor=page['next_cursor']);records+=page['records']
        self.assertEqual(len(records),4);self.assertEqual({r['native_id'] for r in records},set(fixture['pickable_ids']))
        self.evidence.append({'test':'snapshot_after_removal','original':first,'retained_records':records,'current':current})
    def test_03_cursor_owner_query_expiry(self):
        b=self.b;self.fixture()
        try:first=b.pickable_query(LO,HI,limit=1)
        finally:self.cleanup()
        other=Bridge(self.config)
        with self.assertRaises(BridgeError) as error:other.pickable_query(LO,HI,cursor=first['next_cursor'])
        self.assertEqual(error.exception.code,'CURSOR_MISMATCH')
        with self.assertRaises(BridgeError) as error:b.pickable_query(LO,HI,value=3,cursor=first['next_cursor'])
        self.assertEqual(error.exception.code,'CURSOR_MISMATCH')
        with self.assertRaises(BridgeError) as error:b.pickable_query(LO,HI,cursor=first['snapshot_id']+':4096')
        self.assertEqual(error.exception.code,'INVALID_CURSOR')
        b.call('lab_expire_observation_snapshots',{},b.identity())
        with self.assertRaises(BridgeError) as error:b.pickable_query(LO,HI,cursor=first['next_cursor'])
        self.assertEqual(error.exception.code,'SNAPSHOT_EXPIRED')
        self.evidence.append({'test':'cursor_guards','client_isolation':True,'query_binding':True,'expiry':True})
    def test_04_unloaded_wrong_target_multiplayer(self):
        b=self.b
        with self.assertRaises(BridgeError) as error:b.entity_query([99999,60,99999],[100000,65,100000])
        self.assertEqual(error.exception.code,'REGION_NOT_LOADED')
        identity=b.identity();identity['name']='forbidden other world'
        with self.assertRaises(BridgeError) as error:b.call('entity_query',{'minimum':LO,'maximum':HI,'kind':'all','template':None,'limit':64,'client_id':b.client_id},identity)
        self.assertEqual(error.exception.code,'IDENTITY_MISMATCH')
        b.call('lab_add_player',{},b.identity())
        try:
            with self.assertRaises(BridgeError) as error:b.entity_query(LO,HI)
            self.assertEqual(error.exception.code,'MULTIPLAYER_DISABLED')
        finally:b.call('lab_remove_player',{},b.identity());b.isolate_local()
        self.evidence.append({'test':'unloaded_identity_split','verified':True})
    def test_05_menu_reload_invalidates_snapshot(self):
        b=self.b;self.fixture()
        try:first=b.entity_query(LO,HI,limit=1)
        finally:self.cleanup()
        identity=b.identity();b.call('lab_save_unload',{},identity)
        try:
            with self.assertRaises(BridgeError) as error:b.call('entity_query',{'minimum':LO,'maximum':HI,'limit':64,'client_id':b.client_id},identity)
            self.assertEqual(error.exception.code,'NO_WORLD')
        finally:
            b.call('lab_load_target',{});deadline=time.monotonic()+30
            while True:
                try:b.player_state();break
                except BridgeError:self.assertLess(time.monotonic(),deadline);time.sleep(.1)
            b.isolate_local()
        with self.assertRaises(BridgeError) as error:b.entity_query(LO,HI,cursor=first['next_cursor'])
        self.assertEqual(error.exception.code,'SNAPSHOT_EXPIRED')
        deadline=time.monotonic()+30
        while True:
            try:
                current=b.pickable_query(LO,HI);break
            except BridgeError as error:
                if error.code!='REGION_NOT_LOADED':raise
                self.assertLess(time.monotonic(),deadline);time.sleep(.1)
        self.assertFalse(current['records']);self.assertFalse(b.entity_query(LO,HI,template='Wolf')['records'])
        self.evidence.append({'test':'menu_reload_cleanup_and_invalidation','verified':True})
