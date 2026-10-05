"""Explicit two-launch interruption test. Only a registered test-only lab can stop itself."""
import os
import json
import time
import unittest
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json

class RestartAcceptance(unittest.TestCase):
    def test_phase(self):
        b=Bridge(Config.load(os.environ['SC_RESTART_CONFIG']))
        self.assertTrue(b.config.target.get('test_only'));self.assertTrue(b.config.target['name'].startswith('SC MCP LAB'))
        b.isolate_local();path=b.config.artifacts_dir/'restart-live.json'
        lo=[-180,90,-120];hi=[-131,129,-71]
        def wait(result,states=('completed','restored')):
            deadline=time.monotonic()+120
            while result['state'] not in states:
                self.assertNotIn(result['state'],('paused','cancelled'),str(result));self.assertLess(time.monotonic(),deadline)
                time.sleep(.05);result=b.job_status(result['job_id'])
            return result
        if os.environ['SC_RESTART_PHASE']=='interrupt':
            ready=wait(b.fill(lo,hi,3),('ready',));job=b.submit(ready['plan_id'])
            while not job['processed']:time.sleep(.05);job=b.job_status(job['job_id'])
            atomic_json(path,{'boot_before':b.heartbeat()['boot'],'job_id':job['job_id'],'before_interrupt':job,'minimum':lo,'maximum':hi})
            with self.assertRaises(BridgeError) as caught:b.call('lab_interrupt_process',{},b.identity(writing=True))
            self.assertEqual(caught.exception.code,'TIMEOUT')
        else:
            record=json.loads(path.read_text(encoding='utf-8'))
            self.assertNotEqual(b.heartbeat()['boot'],record['boot_before'])
            self.assertTrue(any(j['job_id']==record['job_id'] for j in b.interrupted_jobs()))
            def count():return sum(c['value']==3 for offset in range(0,100000,4096) for c in b.read_region_page(lo,hi,offset,4096)['cells'])
            first=count();time.sleep(2);second=count()
            self.assertGreater(first,0);self.assertLess(first,100000);self.assertEqual(first,second)
            continued=wait(b.resume_job(record['job_id']),('ready',));completed=wait(b.submit(continued['plan_id']))
            self.assertEqual(count(),100000)
            restored=wait(b.restore_job(record['job_id']));self.assertEqual(count(),0)
            record.update(boot_after=b.heartbeat()['boot'],stable_partial_count=first,completed=completed,restored=restored,no_replay_verified=True)
            atomic_json(path,record)
if __name__=='__main__':unittest.main()
