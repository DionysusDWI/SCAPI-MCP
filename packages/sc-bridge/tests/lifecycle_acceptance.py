"""Multi-launch lab acceptance. Phase is explicit; no production-world lifecycle."""
import copy
import json
import os
import time
import unittest
import xml.etree.ElementTree as ET
from sc_bridge import Bridge,Config
from sc_bridge.client import atomic_json

def design(name,value=3,linked=-1):
    node=ET.Element('Values')
    for n,t,v in [('Name','string',name),('TerrainUseCount','int','0'),('Resolution','int','2'),('InteractionMode','Game.FurnitureInteractionMode','None'),('Values','string',f'8*{value},'),('LinkedDesign','int',str(linked))]:
        ET.SubElement(node,'Value',Name=n,Type=t,Value=v)
    return ET.tostring(node,encoding='unicode')

def portable(cell):
    result=copy.deepcopy(cell)
    if result.get('resource',{}).get('kind')=='furniture':
        data=result['value']>>14;data&=~((1023<<2)|(7<<15));result['value']=(data<<14)|(result['value']&16383)
    if result.get('resource',{}).get('kind')=='container':
        result['resource']['slots']=[{**portable(s),'count':s['count']} for s in result['resource']['slots']]
    return result

class LifecycleAcceptance(unittest.TestCase):
    def test_phase(self):
        b=Bridge(Config.load(os.environ['SC_LIFECYCLE_CONFIG']))
        self.assertTrue(b.config.target.get('test_only'));self.assertTrue(b.config.target['name'].startswith('SC MCP LAB'))
        b.isolate_local();path=b.config.artifacts_dir/'portable-live.json'
        phase=os.environ['SC_LIFECYCLE_PHASE']
        def wait(result,states=('completed','restored')):
            deadline=time.monotonic()+120
            while result['state'] not in states:
                self.assertNotIn(result['state'],('paused','cancelled'),str(result));self.assertLess(time.monotonic(),deadline)
                time.sleep(.05);result=b.job_status(result['job_id'])
            return result
        def run(plan):return wait(b.submit(wait(plan,('ready',))['plan_id']))
        def circuits():
            def sample(command_voltage):
                deadline=time.monotonic()+10
                while True:
                    outputs=b.call('lab_circuit_outputs',{},b.identity())
                    if all(o['type'] for o in outputs) and [o['voltage'] for o in outputs]==[0,0,command_voltage]:break
                    self.assertLess(time.monotonic(),deadline,str(outputs));time.sleep(.1)
                time.sleep(.25);self.assertEqual(b.call('lab_circuit_outputs',{},b.identity()),outputs)
                return outputs
            initial=sample(1)
            changed=b.modify_cells([{'position':[-154,69,-93],'expected':3,'value':15}])
            try:negative=sample(0)
            finally:b.restore_operation(changed['operation_id'])
            recovered=sample(1)
            return {'positive':initial,'negative':negative,'restored':recovered}
        if phase=='source':
            jobs=[];jobs.append(run(b.fill([-156,69,-94],[-143,69,-90],3)))
            positions=[[-154+i*2,70,-93] for i in range(6)]
            furniture={'kind':'furniture','designs':[design('Portable linked root',3,1),design('Portable linked child',15,-1)]}
            values=[(227,furniture),(45,{'kind':'container','slots':[{'value':227,'count':2,'resource':furniture}]+[{'value':0,'count':0} for _ in range(15)]}),
                (97,{'kind':'sign','lines':['portable','中文','style','four'],'colors':[4294901760,4278255360,4278190335,4294967295],'url':'https://docs.scwk.net/'}),
                (186+(16<<14),{'kind':'memory','data':'0123456789ABCDEF'}),(188+(16<<14),{'kind':'truth_table','data':'0123456789ABCDEF'})]
            for pos,(value,res) in zip(positions,values):jobs.append(run(b.resource_write(pos,value,res)))
            jobs.append(run(b.command_config(positions[-1],[-154,69,-93],3)))
            expected=[b.resource_query(p) for p in positions]
            exported=wait(b.template_export([-156,69,-94],[-143,70,-90]))
            record={'source_world':b.world_info(),'template_id':exported['job_id'],'positions':positions,'expected':expected,'source_jobs':jobs,'source_package':b.template_inspect(exported['job_id'])}
            record['source_circuits']=circuits()
            atomic_json(path,record)
            # Source data remains until save/reload verification; never erase evidence prematurely.
        elif phase=='source-reloaded':
            record=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual([b.resource_query(p) for p in record['positions']],record['expected'])
            record['source_reload_verified']=True
            record['source_reload_circuits']=circuits()
            for job in reversed(record['source_jobs']):wait(b.restore_job(job['job_id']))
            atomic_json(path,record)
        elif phase=='destination':
            record=json.loads(path.read_text(encoding='utf-8'));collision_jobs=[]
            for i in range(16):
                collision_jobs.append(run(b.resource_write([-150,75,-98],227,{'kind':'furniture','designs':[design(f'Collision design {i}',3 if i%2 else 15)]})))
            dest=[-156,69,-94];job=run(b.template_import(record['template_id'],dest))
            actual=[b.resource_query(p) for p in record['positions']]
            self.assertEqual([portable(c) for c in actual],[portable(c) for c in record['expected']])
            self.assertNotEqual(actual[0]['value'],record['expected'][0]['value'])
            record['destination_circuits']=circuits()
            record.update(destination_world=b.world_info(),destination_actual=actual,destination_job=job,collision_jobs=collision_jobs)
            atomic_json(path,record)
        elif phase=='destination-reloaded':
            record=json.loads(path.read_text(encoding='utf-8'));actual=[b.resource_query(p) for p in record['positions']]
            self.assertEqual(actual,record['destination_actual']);record['destination_reload_verified']=True
            record['destination_reload_circuits']=circuits()
            wait(b.restore_job(record['destination_job']['job_id']))
            for job in reversed(record['collision_jobs']):wait(b.restore_job(job['job_id']))
            record['destination_restore_verified']=True;atomic_json(path,record)
        elif phase=='backup-loaded':
            self.assertEqual(b.world_info()['name'],'SC MCP LAB BACKUP VERIFY')
            self.assertIsNotNone(b.players()[0]['position'])
            atomic_json(b.config.artifacts_dir/'backup-import-loaded.json',{'world':b.world_info(),'status':b.status(),'validated':True})
        else:self.fail('Unknown lifecycle phase')

if __name__=='__main__':unittest.main()
