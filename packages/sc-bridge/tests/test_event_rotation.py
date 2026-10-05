"""Exercise the actual audit writer's size and retention boundaries in LAB runtime files."""
import hashlib,json,os,time,unittest,uuid,zipfile
from pathlib import Path
from sc_bridge import Bridge,Config
from sc_bridge.client import atomic_json

@unittest.skipUnless(os.getenv('SC_OPERATION_TEST_CONFIG'),'Explicit LAB required')
class EventRotationTests(unittest.TestCase):
    def test_native_writer_rotates_and_retains_eight(self):
        b=Bridge(Config.load(os.environ['SC_OPERATION_TEST_CONFIG']));assert b.config.target.get('test_only') and b.config.target['name'].startswith('SC MCP LAB');b.isolate_local()
        directory=b.config.runtime_dir/'events';directory.resolve().relative_to(b.config.runtime_dir.resolve());files=list(directory.glob('*.jsonl*'))
        archive=b.config.artifacts_dir/'event-rotation-originals.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for p in files:z.write(p,p.name)
        boot=b.heartbeat()['boot'];session=b.world_info()['session'];current=directory/f'{boot}-{session}.jsonl'
        # Explicit synthetic padding exercises storage only; it never claims a native event.
        with current.open('ab') as f:
            padding=max(0,16*1024*1024-current.stat().st_size-32);f.write(b' '+b' ' * padding+b'\n')
        for _ in range(9):(directory/f'{uuid.uuid4().hex}-{uuid.uuid4().hex}.jsonl').write_text('')
        b.call('lab_event_native_attempt',identity=b.identity());deadline=time.monotonic()+5
        while not current.exists() or current.stat().st_size>1024*1024:
            self.assertLess(time.monotonic(),deadline);time.sleep(.03)
        time.sleep(.15);remaining=list(directory.glob('*.jsonl*'));self.assertLessEqual(len(remaining),8);self.assertLessEqual(current.stat().st_size,16*1024*1024)
        result={'archive':str(archive),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'size_limit':16*1024*1024,'remaining_files':[{'name':p.name,'bytes':p.stat().st_size} for p in remaining],'rotation_verified':True,'rotated_file_may_also_be_pruned_by_eight_file_retention':True,'fixture_is_synthetic_storage_padding':True}
        atomic_json(b.config.artifacts_dir/'event-rotation-live.json',result)
