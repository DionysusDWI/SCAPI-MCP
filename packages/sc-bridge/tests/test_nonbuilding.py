"""Finite read-only conditions and selected-player observations."""
import concurrent.futures
import math
import os
import time
import unittest
from sc_bridge import Bridge, BridgeError, Config
from sc_bridge.client import atomic_json


class NonBuildingInputTests(unittest.TestCase):
    def setUp(self):
        self.b=Bridge(None)
        self.b.identity=lambda player_index=0: {'player_index':player_index}
        self.b.call=lambda op,args,identity: {'op':op,'args':args,'identity':identity}

    def test_closed_names_types_and_ranges(self):
        for kwargs in [dict(name='fileexist'),dict(name='blockchange'),dict(name='statsrange',subtype='default'),
            dict(name='statsrange',subtype='health',minimum=True,maximum=100),
            dict(name='levelrange',minimum=math.nan,maximum=100),
            dict(name='levelrange',minimum=10**400,maximum=10**401),
            dict(name='heightrange',minimum=10,maximum=5),
            dict(name='gamemode',mode='0'),dict(name='gamemode',mode='Creative',minimum=0)]:
            with self.subTest(kwargs=kwargs),self.assertRaises(BridgeError):self.b.condition_query(**kwargs)
        for offset,limit in [(False,64),(0,65),(-1,1),(0,0)]:
            with self.assertRaises(BridgeError):self.b.inventory_read(offset,limit)

    def test_generic_has_same_arguments_and_no_extra_paths(self):
        self.assertEqual(self.b.command('statsrange','health',{'range_minimum':0,'range_maximum':100}),
            self.b.condition_query('statsrange','health',minimum=0,maximum=100))
        with self.assertRaises(BridgeError):self.b.command('observe','player_state',{'path':'Health'})
        with self.assertRaises(BridgeError):self.b.command('observe','lighting_query',{})
        self.assertEqual(self.b.command('gamemode','default',{'mode':'Cruel'})['args']['mode'],'Cruel')


@unittest.skipUnless(os.environ.get('SC_NONBUILDING_TEST_CONFIG'),'Explicit lab required')
class NonBuildingLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b=Bridge(Config.load(os.environ['SC_NONBUILDING_TEST_CONFIG']))
        assert cls.b.config.target.get('test_only') and cls.b.config.target['name'].startswith('SC MCP LAB')
        cls.b.isolate_local();cls.evidence=[]
    @classmethod
    def tearDownClass(cls):atomic_json(cls.b.config.artifacts_dir/'nonbuilding-live.json',cls.evidence)

    def test_environment_player_inventory(self):
        b=self.b;world=b.world_info();environment=b.environment_info();player=b.player_state();page=b.inventory_read(limit=2)
        self.assertEqual(environment['world']['directory'],world['directory'])
        self.assertEqual(environment['game_mode'],'Creative')
        self.assertEqual(player['player_name'],world['players'][0]['name'])
        self.assertTrue(all(math.isfinite(player[key]) for key in ('level','health','food','stamina','sleep','temperature','wetness','walk_speed')))
        self.assertLessEqual(len(page['slots']),2);self.assertTrue(page['creative_supply'])
        inventory=[];offset=0
        while True:
            page=b.inventory_read(offset,64);inventory.extend(page['slots'])
            if page['next_offset'] is None:break
            offset=page['next_offset']
        self.assertEqual(len(inventory),page['total'])
        self.assertEqual(len(set(slot['index'] for slot in inventory)),len(inventory))
        self.assertTrue(all(slot['count_kind']=='creative_supply' for slot in inventory if slot['reported_count']>0))
        self.evidence.append({'test':'environment_player_inventory','environment':environment,'player':player,'inventory_pages':math.ceil(len(inventory)/64),'inventory_slots':len(inventory)})

    def test_condition_units_and_generic(self):
        b=self.b;player=b.player_state();records=[]
        for subtype,key,scale in [('health','health',100),('food','food',100),('stamina','stamina',100),('sleep','sleep',100),('wetness','wetness',100),('speed','walk_speed',10),('attack','attack_power',1),('defense','attack_resilience',1),('temperature','temperature',1)]:
            result=b.condition_query('statsrange',subtype,minimum=-100000,maximum=100000)
            self.assertTrue(result['matches']);self.assertAlmostEqual(result['observed'],result['native_value']*scale,places=3)
            self.assertEqual(result['scale'],scale)
            if key not in ('temperature','wetness'):self.assertAlmostEqual(result['native_value'],player[key],places=3)
            records.append(result)
        for name in ('levelrange','heightrange','timerange','modcount'):
            result=b.condition_query(name,minimum=-100000,maximum=100000);self.assertTrue(result['matches']);records.append(result)
        self.assertTrue(b.condition_query('gamemode',mode='Creative')['matches'])
        self.assertFalse(b.condition_query('gamemode',mode='Survival')['matches'])
        self.assertFalse(b.condition_query('heightrange',minimum=1000,maximum=2000)['matches'])
        a=b.command('statsrange','health',{'range_minimum':0,'range_maximum':100});c=b.condition_query('statsrange','health',minimum=0,maximum=100)
        for key in ('observed','unit','matches'):self.assertEqual(a[key],c[key])
        self.evidence.append({'test':'condition_units_and_generic','conditions':records})

    def test_identity_clients_and_rejections(self):
        b=self.b;identity=b.identity();identity['name']='SSGC forbidden target'
        with self.assertRaises(BridgeError) as error:b.call('player_state',{},identity)
        self.assertEqual(error.exception.code,'IDENTITY_MISMATCH')
        for args in [{'name':'fileexist','subtype':'default','minimum':0,'maximum':1},
            {'name':'statsrange','subtype':'arbitrary','minimum':0,'maximum':1}]:
            with self.assertRaises(BridgeError) as error:b.call('condition_query',args,b.identity())
            self.assertEqual(error.exception.code,'UNREGISTERED_COMMAND')
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:Bridge(b.config).player_state(),range(2)))
        self.assertEqual([r['player_name'] for r in results],[b.players()[0]['name']]*2)
        self.evidence.append({'test':'identity_and_clients','wrong_target_rejected':True,'two_clients':True})

    def test_light_requires_loaded_computed_chunk(self):
        b=self.b;pos=[-150,100,-98];light=b.lighting_query(pos)
        self.assertGreaterEqual(light['light'],0);self.assertLessEqual(light['light'],15)
        result=b.condition_query('blocklight',position=pos,minimum=0,maximum=15)
        self.assertTrue(result['matches'])
        generic=b.command('blocklight','default',{'position':pos,'range_minimum':100,'range_maximum':200})
        self.assertFalse(generic['matches'])
        for call in (lambda:b.lighting_query([99999,100,99999]),
            lambda:b.condition_query('blocklight',position=[99999,100,99999],minimum=0,maximum=15)):
            with self.assertRaises(BridgeError) as error:call()
            self.assertEqual(error.exception.code,'REGION_NOT_LOADED')
        self.evidence.append({'test':'light_loaded_and_unloaded','light':light,'condition':result,'generic':generic})

    def test_menu_refuses_observations(self):
        b=self.b;identity=b.identity();b.call('lab_save_unload',{},identity)
        try:
            with self.assertRaises(BridgeError) as error:b.call('environment_info',{},identity)
            self.assertEqual(error.exception.code,'NO_WORLD')
        finally:
            b.call('lab_load_target',{});deadline=time.monotonic()+30
            while True:
                try:b.player_state();break
                except BridgeError:
                    self.assertLess(time.monotonic(),deadline);time.sleep(.1)
            b.isolate_local()
        self.evidence.append({'test':'menu_refusal_reload','verified':True})
