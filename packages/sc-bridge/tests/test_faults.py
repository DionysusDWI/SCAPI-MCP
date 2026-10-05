"""Opt-in fault acceptance with mutation guards in a registered lab."""
import os
import time
import unittest
import uuid
import zipfile
import json
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json

@unittest.skipUnless(os.environ.get('SC_FAULT_TEST_CONFIG'),'Explicit lab configuration required')
class FaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b=Bridge(Config.load(os.environ['SC_FAULT_TEST_CONFIG']))
        assert cls.b.config.target.get('test_only') and cls.b.config.target['name'].startswith('SC MCP LAB')
        cls.b.isolate_local();cls.evidence=[]
    @classmethod
    def tearDownClass(cls):atomic_json(cls.b.config.artifacts_dir/'fault-live.json',cls.evidence)
    def wait(self,result,states=('completed','restored')):
        end=time.monotonic()+120
        while result['state'] not in states:
            self.assertNotIn(result['state'],('paused',),str(result));self.assertLess(time.monotonic(),end)
            time.sleep(.05);result=self.b.job_status(result['job_id'])
        return result
    def run_plan(self,plan):return self.wait(self.b.submit(self.wait(plan,('ready',))['plan_id']))
    def test_01_cancel_resume_restore(self):
        b=self.b;lo=[-180,90,-120];hi=[-131,129,-71]
        ready=self.wait(b.fill(lo,hi,3),('ready',));result=b.submit(ready['plan_id'])
        while result['processed']==0:time.sleep(.05);result=b.job_status(result['job_id'])
        b.cancel_job(result['job_id']);cancelled=self.wait(result,('cancelled',))
        self.assertGreater(cancelled['processed'],0);self.assertLess(cancelled['processed'],100000)
        renewed=self.wait(b.resume_job(result['job_id']),('ready',))
        self.assertEqual(renewed['preflight']['estimated_modifications'],100000-cancelled['processed'])
        resumed=self.wait(b.submit(renewed['plan_id']))
        for offset in range(0,100000,4096):self.assertTrue(all(c['value']==3 for c in b.read_region_page(lo,hi,offset,4096)['cells']))
        restored=self.wait(b.restore_job(result['job_id']))
        for offset in range(0,100000,4096):self.assertTrue(all(c['value']==0 for c in b.read_region_page(lo,hi,offset,4096)['cells']))
        self.evidence.append({'test':'cancel_resume_restore','cancelled':cancelled,'resumed':resumed,'restored':restored})
    def test_02_restore_conflict(self):
        b=self.b;pos=[-150,80,-98]
        first=self.run_plan(b.fill(pos,pos,3));second=self.run_plan(b.fill(pos,pos,15))
        result=b.restore_job(first['job_id'])
        while result['state'] not in ('paused','restored'):time.sleep(.05);result=b.job_status(result['job_id'])
        self.assertEqual(result['state'],'paused');self.assertIn('CONFLICT',result['error'])
        self.assertEqual(b.resource_query(pos)['value'],15)
        self.wait(b.restore_job(second['job_id']));self.wait(b.restore_job(first['job_id']))
        self.evidence.append({'test':'restore_conflict','rejected':result})
    def test_03_template_dependency_checksum(self):
        b=self.b;export=self.wait(b.template_export([-150,80,-98],[-150,80,-98]))
        original=b.config.artifacts_dir/'templates'/(export['job_id']+'.scblueprint')
        with zipfile.ZipFile(original) as archive:manifest=json.loads(archive.read('manifest.json'));cells=archive.read('cells.json')
        template_id=uuid.uuid4().hex;manifest['dependencies'].append({'package':'missing.lab.fixture','version':'1'})
        with zipfile.ZipFile(original.with_name(template_id+'.scblueprint'),'w') as archive:
            archive.writestr('manifest.json',json.dumps(manifest));archive.writestr('cells.json',cells)
        result=b.template_import(template_id,[-150,80,-98])
        while result['state'] not in ('paused','ready'):time.sleep(.05);result=b.job_status(result['job_id'])
        self.assertEqual(result['state'],'paused');self.assertIn('MISSING_DEPENDENCY',result['error'])
        manifest['cells_sha256']='0'*64
        with zipfile.ZipFile(original.with_name(template_id+'.scblueprint'),'w') as archive:
            archive.writestr('manifest.json',json.dumps(manifest));archive.writestr('cells.json',cells)
        with self.assertRaises(BridgeError):b.template_import(template_id,[-150,80,-98])
        self.evidence.append({'test':'template_dependency_checksum','rejected':result})
    def test_04_protocol_boot_expiry(self):
        b=self.b;host=b.heartbeat()
        for override,code in [({'boot':'old-fixture'},'STALE_BOOT'),({'expires':0},'EXPIRED_REQUEST'),({'protocol':2},'INCOMPATIBLE_VERSION')]:
            identity=uuid.uuid4().hex;request={'id':identity,'boot':host['boot'],'protocol':3,'expires':int(time.time()*1000+10000),'op':'status','args':{},'identity':None,**override}
            atomic_json(b.config.runtime_dir/'inbox'/(identity+'.json'),request);path=b.config.runtime_dir/'outbox'/(identity+'.json');deadline=time.monotonic()+5
            while not path.exists():self.assertLess(time.monotonic(),deadline);time.sleep(.025)
            response=json.loads(path.read_text());self.assertEqual(response['error']['code'],code)
        self.evidence.append({'test':'protocol_boot_expiry','rejected':['STALE_BOOT','EXPIRED_REQUEST','INCOMPATIBLE_VERSION']})
    def test_05_resource_capacity(self):
        from lifecycle_acceptance import design
        b=self.b;identity=b.identity();reserved=b.call('lab_fill_design_capacity',{},identity)
        try:
            self.assertEqual(reserved['free'],0)
            result=b.resource_write([-150,80,-98],227,{'kind':'furniture','designs':[design('Capacity rejection fixture')]})
            while result['state'] not in ('paused','ready'):time.sleep(.05);result=b.job_status(result['job_id'])
            self.assertEqual(result['state'],'paused');self.assertIn('RESOURCE_CAPACITY',result['error'])
            self.assertEqual(b.resource_query([-150,80,-98])['value'],0)
            self.evidence.append({'test':'resource_capacity','reserved':reserved,'rejected':result})
        finally:b.call('lab_release_design_capacity',{},identity)
    def test_06_menu_refusal(self):
        b=self.b;previous=b.identity();b.call('lab_save_unload',{},previous)
        try:
            self.assertFalse(b.world_info()['loaded'])
            with self.assertRaises(BridgeError) as caught:b.read_region([-150,80,-98],[-150,80,-98])
            self.assertEqual(caught.exception.code,'NO_WORLD')
            self.evidence.append({'test':'menu_read_refusal','world':b.world_info()})
        finally:
            b.call('lab_load_target');deadline=time.monotonic()+15
            while not b.players() or b.players()[0]['position'] is None:
                self.assertLess(time.monotonic(),deadline);time.sleep(.1)
            b.isolate_local()

    def test_07_region_timeout_and_physics_refusal(self):
        b=self.b;position=[900000,80,900000]
        started=time.monotonic();prepared=b.prepare_region(position,position,timeout_seconds=.2)
        self.assertFalse(prepared['ready']);self.assertTrue(prepared['timed_out']);self.assertFalse(prepared['generation_requested'])
        result=b.fill(position,position,3)
        while result['state']!='paused':
            self.assertLess(time.monotonic()-started,20);time.sleep(.1);result=b.job_status(result['job_id'])
        self.assertIn('REGION_TIMEOUT',result['error']);self.assertEqual(result['processed'],0)
        with self.assertRaises(BridgeError) as error:b.fill([-150,80,-98],[-150,80,-98],18)
        self.assertEqual(error.exception.code,'UNREGISTERED_PHYSICS')
        self.evidence.append({'test':'region_timeout_physics','preparation':prepared,'paused':result})

    def test_08_host_lease_template_structure_and_preflight(self):
        b=self.b
        with self.assertRaises(PermissionError):
            with (b.config.runtime_dir/'host.lock').open('rb'):pass
        plan=self.wait(b.fill([-150,80,-98],[-148,80,-98],3),('ready',))
        self.assertEqual(plan['preflight']['estimated_modifications'],3)
        self.assertEqual(plan['preflight']['affected_minimum'],[-150,80,-98])
        self.assertEqual(plan['preflight']['affected_maximum'],[-148,80,-98])
        b.cancel_job(plan['job_id'])
        import hashlib
        template_id=uuid.uuid4().hex;cells=json.dumps([{'position':[True,0,0],'data':{'value':3}}]).encode()
        manifest={'format':'scblueprint','format_version':1,'protocol':3,'api':'1.9.3.2','dependencies':[],'count':1,'cells_sha256':hashlib.sha256(cells).hexdigest()}
        with zipfile.ZipFile(b.config.artifacts_dir/'templates'/(template_id+'.scblueprint'),'w') as archive:
            archive.writestr('manifest.json',json.dumps(manifest));archive.writestr('cells.json',cells)
        result=b.call('template_import',{'template_id':template_id,'destination':[-150,80,-98]},b.identity())
        while result['state'] not in ('paused','ready'):time.sleep(.05);result=b.job_status(result['job_id'])
        self.assertEqual(result['state'],'paused');self.assertIn('INVALID_TEMPLATE',result['error'])
        self.evidence.append({'test':'lease_template_preflight','host_lease_exclusive':True,'preflight':plan['preflight'],'template_rejected':result})
        bad=b.resource_write([-150,80,-98],188+(16<<14),{'kind':'truth_table','data':'0'*17})
        while bad['state'] not in ('paused','ready'):time.sleep(.05);bad=b.job_status(bad['job_id'])
        self.assertEqual(bad['state'],'paused');self.assertIn('INVALID_RESOURCE',bad['error'])
        self.assertEqual(b.resource_query([-150,80,-98])['value'],0)

    def test_09_shared_heartbeat_does_not_stop_jobs(self):
        b=self.b;plan=self.wait(b.fill([-180,90,-120],[-171,99,-111],3),('ready',))
        before=b.heartbeat();job=b.submit(plan['plan_id'])
        with (b.config.runtime_dir/'heartbeat.json').open('rb') as held_reader:
            held_reader.read();time.sleep(1.2)
            result=self.wait(job)
            self.assertEqual(result['state'],'completed')
        time.sleep(1.2);self.assertGreater(b.heartbeat()['time'],before['time'])
        self.wait(b.restore_job(job['job_id']))
        self.evidence.append({'test':'heartbeat_sharing','scheduler_completed_while_reader_held':True,'job':result})
