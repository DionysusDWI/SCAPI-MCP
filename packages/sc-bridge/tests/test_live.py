"""Opt-in real host tests. Never load or mutate a production world."""
import os
import time
import unittest
from sc_bridge import Bridge, BridgeError, Config
from sc_bridge.client import atomic_json

@unittest.skipUnless(os.environ.get('SC_LIVE_TEST_CONFIG'), 'Explicit lab configuration required')
class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b=Bridge(Config.load(os.environ['SC_LIVE_TEST_CONFIG']))
        target=cls.b.config.target
        assert target.get('test_only') is True and target['name'].startswith('SC MCP LAB')
        assert target.get('world_token')
        info=cls.b.world_info()
        assert info['loaded'] and info['name']==target['name'] and info['directory']==target['directory']
        cls.b.isolate_local()
        cls.evidence=[]

    @classmethod
    def tearDownClass(cls):
        atomic_json(cls.b.config.artifacts_dir/'live-tests.json',cls.evidence)

    def wait(self, result, desired=('completed','restored'), seconds=60):
        deadline=time.monotonic()+seconds
        while result['state'] not in desired:
            if result['state'] in ('paused','cancelled') or time.monotonic()>deadline:
                self.fail(str(result))
            time.sleep(.05);result=self.b.job_status(result['job_id'])
        return result

    def run_plan(self, plan):
        ready=self.wait(plan,('ready',))
        done=self.wait(self.b.submit(ready['plan_id']))
        self.evidence.append(done)
        return done

    def read(self, lo, hi):
        deadline=time.monotonic()+5
        while True:
            try:return self.b.read_region(lo,hi)
            except BridgeError as e:
                if e.code!='REGION_NOT_LOADED' or time.monotonic()>deadline:raise
                time.sleep(.05)

    def test_01_direct_write_read_restore(self):
        pos=[-150,70,-98];before=self.read(pos,pos)
        done=self.b.modify_cells([{'position':pos,'expected':before['cells'][0]['value'],'value':3}])
        self.assertEqual(self.read(pos,pos)['cells'][0]['value'],3)
        restored=self.b.restore_operation(done['operation_id'])
        self.assertEqual(self.read(pos,pos),before)
        self.evidence.append({'test':'direct_write_read_restore','operation':done,'restored':restored})

    def test_02_fill_replace_clear_and_restore(self):
        lo=[-150,70,-98];hi=[-148,72,-96];before=self.read(lo,hi)
        first=self.run_plan(self.b.fill(lo,hi,3))
        self.assertTrue(all(c['value']==3 for c in self.read(lo,hi)['cells']))
        second=self.run_plan(self.b.replace(lo,hi,3,15))
        self.assertTrue(all(c['value']==15 for c in self.read(lo,hi)['cells']))
        third=self.run_plan(self.b.clear(lo,hi))
        self.assertTrue(all(c['value']==0 for c in self.read(lo,hi)['cells']))
        for job in (third,second,first):self.wait(self.b.restore_job(job['job_id']))
        self.assertEqual(self.read(lo,hi),before)

    def test_03_overlap_copy_and_move(self):
        lo=[-150,70,-98];hi=[-147,70,-98];before=self.read(lo,hi)
        first=self.run_plan(self.b.fill(lo,[-149,70,-98],3))
        second=self.run_plan(self.b.copy(lo,[-149,70,-98],[-149,70,-98]))
        self.assertEqual([c['value'] for c in self.read(lo,hi)['cells']],[3,3,3,0])
        third=self.run_plan(self.b.move(lo,[-150,70,-98],[-147,70,-98]))
        self.assertEqual([c['value'] for c in self.read(lo,hi)['cells']],[0,3,3,3])
        for job in (third,second,first):self.wait(self.b.restore_job(job['job_id']))
        self.assertEqual(self.read(lo,hi),before)

    def test_04_geometries(self):
        lo=[-150,70,-98];hi=[-146,74,-94];before=self.read(lo,hi)
        for shape in ('line','cuboid','sphere','cylinder','cone'):
            for hollow in (False,True):
                done=self.run_plan(self.b.geometry(lo,hi,shape,3,hollow))
                values=[c['value'] for c in self.read(lo,hi)['cells']]
                self.assertIn(3,values)
                self.wait(self.b.restore_job(done['job_id']))
                self.assertEqual(self.read(lo,hi),before)

    def test_05_template_roundtrip(self):
        lo=[-150,70,-98];hi=[-148,72,-96]
        first=self.run_plan(self.b.fill(lo,hi,15))
        exported=self.wait(self.b.template_export(lo,hi))
        inspection=self.b.template_inspect(exported['job_id'])
        self.assertEqual(inspection['manifest']['count'],27)
        second=self.run_plan(self.b.template_import(exported['job_id'],[-145,70,-98]))
        self.assertTrue(all(c['value']==15 for c in self.read([-145,70,-98],[-143,72,-96])['cells']))
        self.wait(self.b.restore_job(second['job_id']));self.wait(self.b.restore_job(first['job_id']))
        self.evidence.append({'test':'template_roundtrip','template':inspection})

    def test_06_unloaded_and_wrong_identity(self):
        with self.assertRaises(BridgeError) as error:self.b.read_region([900000,70,900000],[900000,70,900000])
        self.assertEqual(error.exception.code,'REGION_NOT_LOADED')
        identity=self.b.identity();identity['directory']='app:/doc/Worlds/World1'
        with self.assertRaises(BridgeError) as error:self.b.call('read_region',{'minimum':[-150,70,-98],'maximum':[-150,70,-98]},identity)
        self.assertEqual(error.exception.code,'IDENTITY_MISMATCH')

    def test_07_generic_and_dedicated_equivalence(self):
        lo=[-150,70,-98];hi=[-148,72,-96]
        first=self.run_plan(self.b.command('fill','region',{'minimum':lo,'maximum':hi,'value':3}))
        values=self.read(lo,hi);self.wait(self.b.restore_job(first['job_id']))
        second=self.run_plan(self.b.fill(lo,hi,3))
        self.assertEqual(self.read(lo,hi),values);self.wait(self.b.restore_job(second['job_id']))

    def test_08_complex_resources_copy_restore(self):
        import xml.etree.ElementTree as ET
        node=ET.Element('Values')
        for name, kind, value in [('Name','string','SC MCP linked fixture'),('TerrainUseCount','int','0'),('Resolution','int','2'),('InteractionMode','Game.FurnitureInteractionMode','None'),('Values','string','8*3,'),('LinkedDesign','int','-1')]:
            ET.SubElement(node,'Value',Name=name,Type=kind,Value=value)
        fixtures=[(45,{'kind':'container','slots':[{'value':3 if i==0 else 0,'count':7 if i==0 else 0} for i in range(16)]}),
            (97,{'kind':'sign','lines':['SC MCP LAB','中文资源','颜色样式','四行保留'],'colors':[4294901760,4278255360,4278190335,4294967295],'url':'https://docs.scwk.net/'}),
            (186+(16<<14),{'kind':'memory','data':'0123456789ABCDEF'}),
            (188+(16<<14),{'kind':'truth_table','data':'0123456789ABCDEF'}),
            (227,{'kind':'furniture','designs':[ET.tostring(node,encoding='unicode')]})]
        platform=self.run_plan(self.b.fill([-156,69,-94],[-143,69,-90],3))
        try:
            for index,(value,resource) in enumerate(fixtures):
                source=[-154+index*2,70,-93];destination=[source[0],70,-91]
                first=self.run_plan(self.b.resource_write(source,value,resource))
                captured=self.b.resource_query(source)
                second=self.run_plan(self.b.copy(source,source,destination))
                copied=self.b.resource_query(destination)
                self.assertEqual(copied['resource'],captured['resource'])
                self.wait(self.b.restore_job(second['job_id']));self.wait(self.b.restore_job(first['job_id']))
                self.assertEqual(self.b.resource_query(source)['value'],0)
                self.evidence.append({'test':'resource_copy_restore','kind':resource['kind'],'source':captured,'copy':copied})
            for block_id in (27,64,216):
                source=[-154,70,-93];destination=[-154,70,-91]
                empty=self.run_plan(self.b.fill(source,source,block_id));resource=self.b.resource_query(source)['resource']
                resource['slots'][0]={'value':3,'count':7}
                first=self.run_plan(self.b.resource_write(source,block_id,resource));captured=self.b.resource_query(source)
                second=self.run_plan(self.b.copy(source,source,destination))
                self.assertEqual(self.b.resource_query(destination)['resource'],captured['resource'])
                for job in (second,first,empty):self.wait(self.b.restore_job(job['job_id']))
                self.evidence.append({'test':'container_family','block_id':block_id,'source':captured})
            source=[-154,70,-93];destination=[-154,70,-91]
            first=self.run_plan(self.b.command_config(source,[-154,69,-93],3))
            captured=self.b.resource_query(source)
            second=self.run_plan(self.b.copy(source,source,destination))
            self.assertEqual(self.b.resource_query(destination)['resource'],captured['resource'])
            self.wait(self.b.restore_job(second['job_id']));self.wait(self.b.restore_job(first['job_id']))
        finally:self.wait(self.b.restore_job(platform['job_id']))

    def test_09_directional_and_colored_transforms(self):
        materials=self.b.materials()
        stairs=next(m['id'] for m in materials if m['type']=='Game.StoneStairsBlock')
        source=[-150,70,-98];destination=[-148,70,-98]
        value=stairs+(1<<14)
        first=self.b.modify_cells([{'position':source,'expected':0,'value':value}])
        second=self.run_plan(self.b.copy(source,source,destination,rotation=90))
        self.assertEqual(self.b.resource_query(destination)['value'],stairs)
        self.wait(self.b.restore_job(second['job_id']))
        second=self.run_plan(self.b.copy(source,source,destination,mirror='x'))
        self.assertNotEqual(self.b.resource_query(destination)['value'],value)
        self.wait(self.b.restore_job(second['job_id']));self.b.restore_operation(first['operation_id'])
        colored=3+((1|(9<<1))<<14)
        first=self.run_plan(self.b.fill(source,source,colored))
        second=self.run_plan(self.b.copy(source,source,destination,rotation=90,mirror='z'))
        self.assertEqual(self.b.resource_query(destination)['value'],colored)
        self.wait(self.b.restore_job(second['job_id']));self.wait(self.b.restore_job(first['job_id']))

    def test_10_cancel_conflict_and_clients(self):
        import concurrent.futures
        lo=[-150,70,-98];hi=[-148,72,-96]
        plan=self.wait(self.b.fill(lo,hi,3),('ready',))
        changed=self.b.modify_cells([{'position':lo,'expected':0,'value':15}])
        result=self.b.submit(plan['plan_id'])
        deadline=time.monotonic()+5
        while result['state']=='running' and time.monotonic()<deadline:
            time.sleep(.05);result=self.b.job_status(result['job_id'])
        self.assertEqual(result['state'],'paused');self.assertIn('CONFLICT',result['error'])
        self.b.restore_operation(changed['operation_id'])
        plan=self.b.fill([-170,70,-110],[-130,90,-70],3)
        self.b.cancel_job(plan['job_id'])
        result=self.b.job_status(plan['job_id']);self.assertEqual(result['state'],'cancelled')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:Bridge(self.b.config).world_info(),range(2)))
        self.assertEqual(results[0]['session'],results[1]['session'])

    def test_11_split_player_rejected(self):
        identity=self.b.identity();self.b.call('lab_add_player',{},identity)
        try:
            with self.assertRaises(BridgeError) as error:self.b.fill([-150,70,-98],[-150,70,-98],3)
            self.assertEqual(error.exception.code,'MULTIPLAYER_DISABLED')
        finally:self.b.call('lab_remove_player',{},identity)

    def test_12_observation(self):
        self.assertEqual(self.b.measure([-150,70,-98],[-148,72,-96])['volume'],27)
        self.assertTrue(self.b.prepare_region([-150,70,-98],[-148,72,-96])['ready'])
        self.assertFalse(self.b.prepare_region([900000,70,900000],[900000,70,900000])['ready'])
        original=self.b.players()[0]['position'];self.b.teleport([-158,65,-98])
        self.b.camera([-158,70,-98],[-150,70,-98]);shot=self.b.screenshot()
        self.assertTrue(__import__('pathlib').Path(shot['path']).exists())
        self.evidence.append({'test':'observation','screenshot':shot})

    def test_13_structured_resources_conditions_heading(self):
        pos=[-150,80,-98]
        first=self.run_plan(self.b.command('place','default',{'position':pos,'value':3}))
        self.assertTrue(self.b.command('condition','blockexist',{'position':pos,'value':3})['matches'])
        self.wait(self.b.restore_job(first['job_id']))
        self.assertEqual(self.b.command('observe','heading',{'yaw':90,'pitch':15}),{'yaw':90,'pitch':15})
        self.assertEqual(self.b.heading(0,0),{'yaw':0,'pitch':0})
        self.assertEqual(self.b.command('observe','measure',{'minimum':pos,'maximum':pos})['volume'],1)

    def test_14_sign_families_and_furniture_transform(self):
        from lifecycle_acceptance import design
        import xml.etree.ElementTree as ET
        b=self.b;source=[-154,70,-93];middle=[-152,70,-93];target=[-150,70,-93]
        scaffold=self.run_plan(b.fill([-156,69,-94],[-143,72,-90],3))
        try:
            for block in (98,210,211):
                resource={'kind':'sign','lines':['family','中文','styled','four'],'colors':[4294901760,4278255360,4278190335,4294967295],'url':'https://docs.scwk.net/'}
                first=self.run_plan(b.resource_write(source,block,resource));expected=b.resource_query(source)
                second=self.run_plan(b.copy(source,source,middle))
                self.assertEqual(b.resource_query(middle)['resource'],expected['resource'])
                for job in (second,first):self.wait(b.restore_job(job['job_id']))
                self.evidence.append({'test':'sign_family','block_id':block,'resource':expected['resource']})
            root=ET.fromstring(design('Asymmetric root',3,1));child=ET.fromstring(design('Asymmetric child',15,-1))
            root.find("Value[@Name='Values']").set('Value','1*3,1*15,6*0,')
            child.find("Value[@Name='Values']").set('Value','2*15,6*0,')
            first=self.run_plan(b.resource_write(source,227,{'kind':'furniture','designs':[ET.tostring(root,encoding='unicode'),ET.tostring(child,encoding='unicode')]}))
            original=b.resource_query(source)
            rotated=self.run_plan(b.copy(source,source,middle,rotation=90))
            self.assertEqual((b.resource_query(middle)['value']>>14)&3,3)
            self.wait(b.restore_job(rotated['job_id']))
            mirrored=self.run_plan(b.copy(source,source,middle,mirror='x'));mirror_data=b.resource_query(middle)
            self.assertNotEqual(mirror_data['resource'],original['resource'])
            inverse=self.run_plan(b.copy(middle,middle,target,mirror='x'))
            self.assertEqual(b.resource_query(target)['resource'],original['resource'])
            self.evidence.append({'test':'linked_furniture_transform','source':original,'mirrored':mirror_data,'inverse':b.resource_query(target)})
            for job in (inverse,mirrored,first):self.wait(b.restore_job(job['job_id']))
        finally:self.wait(b.restore_job(scaffold['job_id']))
