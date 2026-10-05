"""Focused 0.5 inventory, weather and batch cancellation LAB acceptance."""
import os,time,unittest
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json

@unittest.skipUnless(os.getenv('SC_SURVIVAL_TEST_CONFIG'),'Independent LAB required')
class ExtendedOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=Config.load(os.environ['SC_SURVIVAL_TEST_CONFIG']);assert cls.config.target.get('test_only') and cls.config.target['name']=='SC MCP LAB SURVIVAL';cls.evidence=[]
    @classmethod
    def tearDownClass(cls):atomic_json(cls.config.artifacts_dir/'operations-extended-live.json',cls.evidence)
    def setUp(self):self.b=Bridge(self.config);self.b.isolate_local()
    def wait(self,p,submit=True):
        deadline=time.monotonic()+60
        while p['state']=='scanning':
            self.assertLess(time.monotonic(),deadline);time.sleep(.02);p=self.b.operation_status(p['operation_id'])
        if submit:p=self.b.operation_submit(p['operation_id'],p['risk'])
        while p['state'] not in ('completed','failed','cancelled','paused'):
            self.assertLess(time.monotonic(),deadline);time.sleep(.02);p=self.b.operation_status(p['operation_id'])
        self.assertEqual(p['state'],'completed',p);self.evidence.append(p);return p
    def restore(self,p):return self.wait(self.b.operation_restore(p['operation_id'],p['risk']),False)
    def job(self,p,restore=False):
        deadline=time.monotonic()+30
        while p['state'] not in ('ready','restored','completed','paused','failed'):
            self.assertLess(time.monotonic(),deadline);time.sleep(.02);p=self.b.job_status(p['job_id'])
        if p['state']=='ready':p=self.b.submit(p['job_id']);return self.job(p)
        self.assertEqual(p['state'],'restored' if restore else 'completed',p);return p
    def reload(self):
        self.b.call('lab_save_unload',identity=self.b.identity());self.b.call('lab_load_target');deadline=time.monotonic()+30
        while True:
            try:self.b.isolate_local();return
            except BridgeError:
                self.assertLess(time.monotonic(),deadline);time.sleep(.04)
    def test_01_real_edit_modes_selection_and_save(self):
        b=self.b;old=b.inventory_read();endpoint={'kind':'player'};clear=self.wait(b.inventory_edit(endpoint,'clear'))
        self.assertTrue(all(s['reported_count']==0 for s in b.inventory_read()['slots']))
        added=self.wait(b.inventory_edit(endpoint,'add',value=3,count=5));removed=self.wait(b.inventory_edit(endpoint,'remove',value=3,count=2));selected=self.wait(b.inventory_edit(endpoint,'set',slots=[],active_slot=1))
        self.assertEqual(sum(s['reported_count'] for s in b.inventory_read()['slots'] if s['value']==3),3)
        expected=b.inventory_read()['slots'];self.reload();self.assertEqual(b.inventory_read()['slots'],expected)
        # Reload may replace native entity ids. Restore from a fresh explicit plan rather than bypassing identity/CAS.
        slots=[{'index':s['index'],'value':s['value'],'count':s['reported_count']} for s in old['slots']]
        self.wait(b.inventory_edit(endpoint,'set',slots=slots,active_slot=old['active_slot']))
        self.assertEqual(b.inventory_read()['slots'],old['slots'])
    def test_02_container_to_container_conservation(self):
        b=self.b;a=[-155,65,-96];c=[-154,65,-96];jobs=[self.job(b.fill(p,p,45)) for p in (a,c)]
        src={'kind':'container','position':a};dst={'kind':'container','position':c}
        try:
            put=self.wait(b.inventory_edit(src,'set',slots=[{'index':0,'value':3,'count':8}]))
            move=self.wait(b.inventory_transfer(src,dst,3,5));self.assertEqual(b.resource_query(a)['resource']['slots'][0]['count'],3);self.assertEqual(b.resource_query(c)['resource']['slots'][0]['count'],5)
            self.restore(move);self.restore(put)
        finally:
            for j in jobs:self.job(b.restore_job(j['job_id']),True)
    def test_03_environment_and_physiological_fields(self):
        b=self.b;old=b.environment_info();done=self.wait(b.environment_patch(environment_mode='Living',adventure_survival=not old['adventure_survival'],weather_enabled=True,time_of_day_mode='Night'))
        self.assertEqual(done['after']['environment_mode'],'Living');self.restore(done)
        rain=self.wait(b.environment_patch(rain=True,fog=True));self.assertEqual(rain['recovery'],'none');self.assertTrue(rain['after']['rain']);self.assertTrue(rain['after']['fog']);self.wait(b.environment_patch(rain=False,fog=False))
        state=self.wait(b.player_patch(health=.9,level=3));self.assertAlmostEqual(state['after']['health'],.9,places=5);self.assertEqual(state['after']['level'],3)
        with self.assertRaises(BridgeError):b.player_patch(health=0)
    def test_04_climate_batch_cancel(self):
        b=self.b;p=b.climate_patch([-180,-120],[-131,-71],humidity=6);deadline=time.monotonic()+60
        while p['state']=='scanning':
            self.assertLess(time.monotonic(),deadline);time.sleep(.02);p=b.operation_status(p['operation_id'])
        self.assertEqual(p['state'],'ready',p);p=b.operation_submit(p['operation_id'],p['risk'])
        while p['processed']==0:
            self.assertNotIn(p['state'],('failed','completed','paused'));self.assertLess(time.monotonic(),deadline);time.sleep(.005);p=b.operation_status(p['operation_id'])
        b.operation_cancel(p['operation_id'])
        while p['state']!='cancelled':
            self.assertNotIn(p['state'],('failed','completed'));self.assertLess(time.monotonic(),deadline);time.sleep(.02);p=b.operation_status(p['operation_id'])
        self.assertGreater(p['processed'],0);self.assertLess(p['processed'],2500);self.assertTrue(p['full_backup']);self.evidence.append(p)
    def test_05_creative_transfer_generation_and_destruction(self):
        b=self.b;self.wait(b.environment_patch(game_mode='Creative'));point=[-155,65,-96];job=self.job(b.fill(point,point,45));player={'kind':'player'};chest={'kind':'container','position':point}
        try:
            supply=self.wait(b.inventory_edit(player,'set',slots=[{'index':0,'value':3,'count':1}]))
            generate=self.wait(b.inventory_transfer(player,chest,3,5));self.assertEqual(generate['recovery'],'none');self.assertEqual(b.resource_query(point)['resource']['slots'][0]['count'],5)
            destroy=self.wait(b.inventory_transfer(chest,player,3,5));self.assertEqual(destroy['recovery'],'none');self.assertEqual(b.resource_query(point)['resource']['slots'][0]['count'],0)
            with self.assertRaises(BridgeError) as e:b.operation_restore(generate['operation_id'],generate['risk'])
            self.assertEqual(e.exception.code,'NOT_RECOVERABLE');self.restore(supply)
        finally:self.job(b.restore_job(job['job_id']),True);self.wait(b.environment_patch(game_mode='Challenging'))

    def test_06_furniture_inventory_content_and_restore(self):
        from lifecycle_acceptance import design
        b=self.b;point=[-155,65,-96];chest_point=[-154,65,-96]
        jobs=[self.job(b.resource_write(point,227,{'kind':'furniture','designs':[design('Inventory portable linked',3,1),design('Inventory linked child',15,-1)]})),self.job(b.fill(chest_point,chest_point,45))]
        player={'kind':'player'};chest={'kind':'container','position':chest_point}
        try:
            captured=b.resource_query(point);value=captured['value']
            seed=self.wait(b.inventory_edit(player,'set',slots=[{'index':0,'value':value,'count':1}]))
            self.assertEqual(seed['after']['inventories'][0]['slots'][0]['resource']['designs'],captured['resource']['designs'])
            move=self.wait(b.inventory_transfer(player,chest,value,1))
            stored=b.resource_query(chest_point)['resource']['slots'][0]
            self.assertEqual(stored['value'],value);self.assertEqual(stored['count'],1)
            self.assertEqual(stored['resource']['designs'],captured['resource']['designs'])
            self.restore(move);self.restore(seed)
            with self.assertRaises(BridgeError):b.inventory_edit(player,'set',slots=[{'index':0,'value':227+((1023<<2)<<14),'count':1}])
        finally:
            for j in reversed(jobs):self.job(b.restore_job(j['job_id']),True)
