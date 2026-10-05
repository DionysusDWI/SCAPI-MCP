import concurrent.futures
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from sc_bridge import Bridge, BridgeError, Config
from sc_bridge.client import atomic_json
from sc_bridge.deploy import deploy
from sc_bridge.native_deploy import restore_native

class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ['game', 'runtime', 'artifacts', 'backups']:
            (self.root / name).mkdir()
        (self.root / 'game/init.js').write_text('var frameHandlers = [];\n', encoding='utf-8')
        (self.root / 'backups/world.scworld').write_bytes(b'original backup')
        config = {'game_dir':'game','runtime_dir':'runtime','artifacts_dir':'artifacts','backups_dir':'backups',
            'target':{'directory':'app:/doc/Worlds/World1','name':'SC MCP LAB fixture','validated':True,'test_only':True,'world_token':'fixture-token',
                'backup':'backups/world.scworld','backup_sha256':hashlib.sha256(b'original backup').hexdigest()},
            'limits':{'max_region_cells':4096,'max_write_cells':64},'timeout_seconds':.2}
        atomic_json(self.root / 'config.json', config)
        self.config = Config.load(self.root / 'config.json')
        atomic_json(self.root / 'runtime/heartbeat.json',{'protocol':3,'version':'0.5.0','boot':'test','time':time.time()*1000})
        self.bridge = Bridge(self.config)

    def test_backup_checksum(self):
        self.bridge.verify_backup()
        (self.root / 'backups/world.scworld').write_bytes(b'changed')
        with self.assertRaises(BridgeError) as caught: self.bridge.verify_backup()
        self.assertEqual(caught.exception.code,'BACKUP_MISMATCH')

    def test_concurrent_clients_receive_own_responses(self):
        done = threading.Event()
        def host():
            while not done.is_set():
                for file in (self.root / 'runtime/inbox').glob('*.json'):
                    request=json.loads(file.read_text(encoding='utf-8'))
                    atomic_json(self.root / 'runtime/outbox' / file.name,
                        {'id':request['id'],'boot':'test','ok':True,'data':request['args']})
                    file.unlink()
                time.sleep(.005)
        thread=threading.Thread(target=host); thread.start()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda n: Bridge(self.config).call('status',{'caller':n}), [1,2]))
            self.assertEqual(results,[{'caller':1},{'caller':2}])
        finally:
            done.set(); thread.join()

    def test_timeout_retains_request_for_audit(self):
        with self.assertRaises(BridgeError) as caught: self.bridge.call('status')
        self.assertEqual(caught.exception.code,'TIMEOUT')
        self.assertEqual(len(list((self.root/'runtime/inbox').glob('*.json'))),1)

    def test_protocol_and_heartbeat_failure(self):
        atomic_json(self.root/'runtime/heartbeat.json',{'protocol':1,'version':'0.1.0','time':time.time()*1000})
        with self.assertRaises(BridgeError) as caught: self.bridge.heartbeat()
        self.assertEqual(caught.exception.code,'INCOMPATIBLE_VERSION')

    def test_deploy_redeploy_and_restore(self):
        import zipfile
        packages=self.root/'artifacts/sc-bridge/build/packages';packages.mkdir(parents=True)
        for filename,package in [('commandblock-4.1.8-official.scmod','zh.command'),('sc-agentbridge-0.5.0.scmod','local.sc.agentbridge')]:
            with zipfile.ZipFile(packages/filename,'w') as archive:archive.writestr('modinfo.json',json.dumps({'PackageName':package,'Version':'4.1.8' if package=='zh.command' else '0.5.0'}))
        (self.root/'game/Mods').mkdir()
        world=self.root/'game/doc/Worlds/World1';world.mkdir(parents=True)
        (world/'Project.xml').write_text('<Project><Subsystems><Values Name="GameInfo"><Value Name="WorldName" Value="SC MCP LAB fixture" /></Values></Subsystems></Project>')
        original=(self.root/'game/init.js').read_bytes()
        first=deploy(self.config)
        second=deploy(self.config)
        settings=self.root/'game/scagentbridge.json';installed=settings.read_bytes();settings.write_bytes(b'tampered')
        with self.assertRaises(ValueError):restore_native(self.config,second['record'])
        settings.write_bytes(installed)
        restore_native(self.config,second['record'])
        restore_native(self.config,first['record'])
        self.assertEqual((self.root/'game/init.js').read_bytes(),original)
        self.assertFalse((world/'scagent-world-id.txt').exists())

if __name__ == '__main__': unittest.main()
