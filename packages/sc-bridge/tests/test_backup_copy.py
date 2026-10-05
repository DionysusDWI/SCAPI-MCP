"""Load the explicitly registered import copy; never select worlds by display name."""
import os,time,unittest
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json
@unittest.skipUnless(os.getenv('SC_BACKUP_TEST_CONFIG'),'Explicit import verification LAB required')
class BackupCopyTests(unittest.TestCase):
    def test_load_native_import_and_read_state(self):
        b=Bridge(Config.load(os.environ['SC_BACKUP_TEST_CONFIG']));assert b.config.target.get('test_only') and b.config.target['name']=='SC MCP LAB BACKUP VERIFY'
        self.assertFalse(b.world_info()['loaded']);b.call('lab_load_target');deadline=time.monotonic()+30
        while True:
            try:b.isolate_local();identity=b.identity();break
            except BridgeError:
                self.assertLess(time.monotonic(),deadline);time.sleep(.05)
        self.assertEqual(identity['directory'],b.config.target['directory']);self.assertEqual(identity['world_token'],b.config.target['world_token']);self.assertNotEqual(identity['world_token'],b.config.target['copied_lab_token'])
        state={'world':b.world_info(),'identity':identity,'environment':b.environment_info(),'inventory':b.inventory_read(),'override':b.player_override('query'),'region':b.read_region([-150,80,-98],[-150,80,-98]),'original_backup_sha256':b.config.target['backup_sha256'],'import_loaded_verified':True}
        self.assertEqual(state['environment']['game_mode'],'Creative');self.assertFalse(state['override']['enabled']);self.assertTrue(state['inventory']['creative_supply']);self.assertEqual(len(state['region']['cells']),1)
        atomic_json(b.config.artifacts_dir/'backup-loaded-live.json',state)
        b.call('lab_save_unload',identity=b.identity())
