import os,time,unittest
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json

@unittest.skipUnless(os.getenv('SC_SURVIVAL_TEST_CONFIG'),'Independent survival LAB required')
class SurvivalOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=Config.load(os.environ['SC_SURVIVAL_TEST_CONFIG']);assert cls.config.target.get('test_only') and cls.config.target['name']=='SC MCP LAB SURVIVAL';cls.evidence=[]
    @classmethod
    def tearDownClass(cls):atomic_json(cls.config.artifacts_dir/'survival-operations-live.json',cls.evidence)
    def setUp(self):self.b=Bridge(self.config);self.b.isolate_local()
    def finish(self,p):
        deadline=time.monotonic()+30
        while p['state']=='scanning':
            self.assertLess(time.monotonic(),deadline);time.sleep(.03);p=self.b.operation_status(p['operation_id'])
        p=self.b.operation_submit(p['operation_id'],p['risk'])
        while p['state'] not in ('completed','failed','cancelled'):
            self.assertLess(time.monotonic(),deadline);time.sleep(.03);p=self.b.operation_status(p['operation_id'])
        self.assertEqual(p['state'],'completed',p);self.evidence.append(p);return p
    def building(self,p):
        deadline=time.monotonic()+30
        while p['state']!='ready':
            self.assertNotIn(p['state'],('paused','failed'));self.assertLess(time.monotonic(),deadline);time.sleep(.03);p=self.b.job_status(p['job_id'])
        p=self.b.submit(p['job_id'])
        while p['state'] not in ('completed','paused','failed'):
            self.assertLess(time.monotonic(),deadline);time.sleep(.03);p=self.b.job_status(p['job_id'])
        self.assertEqual(p['state'],'completed',p);return p
    def test_01_physical_edit_capacity_restore(self):
        b=self.b;self.assertFalse(b.inventory_read()['creative_supply'])
        before=b.inventory_read();done=self.finish(b.inventory_edit({'kind':'player'},'set',slots=[{'index':0,'value':3,'count':5}]))
        self.assertEqual(b.inventory_read()['slots'][0]['reported_count'],5)
        with self.assertRaises(BridgeError) as e:b.inventory_edit({'kind':'player'},'set',slots=[{'index':0,'value':3,'count':9999}])
        self.assertEqual(e.exception.code,'RESOURCE_CAPACITY')
        restore=b.operation_restore(done['operation_id'],done['risk']);deadline=time.monotonic()+10
        while restore['state'] not in ('completed','failed'):
            self.assertLess(time.monotonic(),deadline);time.sleep(.03);restore=b.operation_status(restore['operation_id'])
        self.assertEqual(restore['state'],'completed',restore);self.assertEqual(b.inventory_read()['slots'][0],before['slots'][0])
    def test_02_physical_transfer_conservation(self):
        b=self.b;point=[-155,65,-96];old=b.resource_query(point)
        chest=self.building(b.fill(point,point,45));put=self.finish(b.inventory_edit({'kind':'player'},'add',value=3,count=5))
        try:
            before=b.inventory_read();before_total=sum(s['reported_count'] for s in before['slots'] if s['value']==3)
            moved=self.finish(b.inventory_transfer({'kind':'player'},{'kind':'container','position':point},3,5))
            after=b.inventory_read();player_total=sum(s['reported_count'] for s in after['slots'] if s['value']==3)
            content=b.resource_query(point);container_total=sum(s['count'] for s in content['resource']['slots'] if s['value']==3)
            self.assertEqual(player_total+container_total,before_total)
            self.finish(b.inventory_transfer({'kind':'container','position':point},{'kind':'player'},3,5))
            back=b.operation_restore(put['operation_id'],put['risk']);deadline=time.monotonic()+10
            while back['state'] not in ('completed','failed'):
                self.assertLess(time.monotonic(),deadline);time.sleep(.03);back=b.operation_status(back['operation_id'])
            self.assertEqual(back['state'],'completed',back)
        finally:
            restored=b.restore_job(chest['job_id']);deadline=time.monotonic()+30
            while restored['state'] not in ('restored','paused','failed'):
                self.assertLess(time.monotonic(),deadline);time.sleep(.03);restored=b.job_status(restored['job_id'])
            self.assertEqual(restored['state'],'restored',restored)
    def test_03_climate_snapshots_and_readback(self):
        b=self.b;p=b.climate_patch([-160,-100],[-159,-99],temperature=8,humidity=7);done=self.finish(p)
        self.assertEqual(done['processed'],4);self.assertEqual(done['recovery'],'none')
        with self.assertRaises(BridgeError) as e:b.operation_restore(done['operation_id'],'dangerous')
        self.assertEqual(e.exception.code,'NOT_RECOVERABLE')
        from pathlib import Path
        import json
        snapshots=list(Path(done['snapshot_directory']).glob('*.after.json'));self.assertTrue(snapshots)
        for path in snapshots:
            for c in json.loads(path.read_text(encoding='utf-8')):self.assertEqual((c['temperature'],c['humidity']),(8,7))
        self.assertTrue(done['full_backup']['sha256']);self.evidence.append(b.climate_query([[-160,-100],[-159,-99]]))

    def test_04_physiology_same_frame_and_restore_conflict(self):
        b=self.b;plan=b.player_patch(food=.8,sleep=.8,wetness=.05,temperature=12,stamina=.9)
        time.sleep(.25);done=self.finish(plan)
        self.assertEqual(done['after'],{'food':.8,'sleep':.8,'wetness':.05,'temperature':12,'stamina':.9})
        self.assertEqual(done['guards']['game_mode'],'Challenging');self.assertIn('execution frame',done['comparison'])
        time.sleep(.2)
        with self.assertRaises(BridgeError) as e:b.operation_restore(done['operation_id'],done['risk'])
        self.assertEqual(e.exception.code,'RESTORE_CONFLICT')
