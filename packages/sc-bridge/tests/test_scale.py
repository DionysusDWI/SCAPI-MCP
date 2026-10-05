"""Explicit million-cell acceptance on an already loaded, registered lab only."""
import os
import time
import unittest
import hashlib
from pathlib import Path
from sc_bridge import Bridge,Config
from sc_bridge.client import atomic_json

@unittest.skipUnless(os.environ.get('SC_MILLION_TEST_CONFIG'),'Million-cell lab run is opt-in')
class ScaleTests(unittest.TestCase):
    def test_million_cancel_boundary(self):
        b=Bridge(Config.load(os.environ['SC_MILLION_TEST_CONFIG']))
        self.assertTrue(b.config.target.get('test_only'));self.assertTrue(b.config.target['name'].startswith('SC MCP LAB'))
        lo=[-205,100,-145];hi=[-106,199,-46];result=b.fill(lo,hi,3)
        deadline=time.monotonic()+180
        while result['state']!='ready':
            self.assertNotEqual(result['state'],'paused',str(result));self.assertLess(time.monotonic(),deadline)
            time.sleep(.1);result=b.job_status(result['job_id'])
        result=b.submit(result['plan_id'])
        while result['processed']==0:
            self.assertNotEqual(result['state'],'paused',str(result));time.sleep(.05);result=b.job_status(result['job_id'])
        started=time.monotonic();b.cancel_job(result['job_id'])
        while result['state']!='cancelled':
            self.assertLess(time.monotonic()-started,10);time.sleep(.05);result=b.job_status(result['job_id'])
        seconds=time.monotonic()-started;self.assertGreater(result['processed'],0);self.assertLess(result['processed'],1000000)
        restored=b.restore_job(result['job_id'])
        while restored['state']!='restored':
            self.assertNotEqual(restored['state'],'paused',str(restored));time.sleep(.05);restored=b.job_status(restored['job_id'])
        # The following full-scale test also checks every original cell was restored.
        atomic_json(b.config.artifacts_dir/'million-cancel-live.json',{'region_volume':1000000,'cancel_seconds':seconds,'cancelled':result,'restored':restored})

    def test_million_fill_verify_restore(self):
        b=Bridge(Config.load(os.environ['SC_MILLION_TEST_CONFIG']))
        self.assertTrue(b.config.target.get('test_only'));self.assertTrue(b.config.target['name'].startswith('SC MCP LAB'))
        lo=[-205,100,-145];hi=[-106,199,-46]
        self.assertTrue(b.prepare_region(lo,hi)['ready'])
        def runtime_bytes():return sum(p.stat().st_size for p in b.config.runtime_dir.rglob('*') if p.is_file())
        evidence={'minimum':lo,'maximum':hi,'volume':1000000,'started':time.time(),'stages':[],'samples':[],'status':b.status(),'runtime_bytes_before':runtime_bytes()}
        def wait(result,terminal):
            started=time.monotonic();last=0
            while result['state'] not in terminal:
                self.assertNotIn(result['state'],('paused','cancelled'),str(result))
                self.assertLess(time.monotonic()-started,3600,str(result))
                if time.monotonic()-last>20:
                    evidence['samples'].append(result)
                    evidence['current']=result;atomic_json(b.config.artifacts_dir/'million-live.json',evidence)
                    print(result,flush=True);last=time.monotonic()
                time.sleep(.25);result=b.job_status(result['job_id'])
            evidence['stages'].append({'seconds':time.monotonic()-started,'result':result})
            atomic_json(b.config.artifacts_dir/'million-live.json',evidence)
            return result
        plan=wait(b.fill(lo,hi,3),('ready',));job=wait(b.submit(plan['plan_id']),('completed',))
        for offset in range(0,1000000,4096):
            page=b.read_region_page(lo,hi,offset,4096)
            self.assertTrue(all(c['value']==3 for c in page['cells']))
        evidence['fill_readback_count']=1000000
        b.camera([-210,150,-150],[-156,150,-98]);time.sleep(2);evidence['filled_screenshot']=b.screenshot()
        restored=wait(b.restore_job(job['job_id']),('restored',))
        for offset in range(0,1000000,4096):
            page=b.read_region_page(lo,hi,offset,4096)
            self.assertTrue(all(c['value']==0 for c in page['cells']))
        evidence['restored_readback_count']=1000000;evidence['finished']=time.time()
        time.sleep(2);evidence['restored_screenshot']=b.screenshot()
        self.assertNotEqual(hashlib.sha256(Path(evidence['filled_screenshot']['path']).read_bytes()).hexdigest(),hashlib.sha256(Path(evidence['restored_screenshot']['path']).read_bytes()).hexdigest())
        evidence['runtime_bytes_after']=runtime_bytes();evidence['runtime_byte_delta']=evidence['runtime_bytes_after']-evidence['runtime_bytes_before']
        evidence['journal_bytes']=sum(p.stat().st_size for identifier in (job['job_id'],restored['job_id']) for p in (b.config.runtime_dir/'jobs'/identifier).rglob('*') if p.is_file())
        atomic_json(b.config.artifacts_dir/'million-live.json',evidence)
