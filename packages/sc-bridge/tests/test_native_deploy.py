"""Native transactional deployment and independent LAB token registration."""
import json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from sc_bridge import Config
from sc_bridge.native_deploy import deploy_native,restore_native

class NativeDeployTests(unittest.TestCase):
    def world(self,path,name,token):
        path.mkdir(parents=True);(path/'Project.xml').write_text(f'<Project><Subsystems><Values Name="GameInfo"><Value Name="WorldName" Value="{name}"/></Values></Subsystems></Project>');(path/'scagent-world-id.txt').write_text(token)
    def config(self,root,**target):
        p=root/'config.json';p.write_text(json.dumps({'game_dir':'game','runtime_dir':'runtime','artifacts_dir':'artifacts','backups_dir':'backups','target':{'name':'SC MCP LAB COPY','directory':'app:/doc/Worlds/World2','validated':True,'test_only':True,'world_token':'b'*32,**target}}));return Config.load(p)
    def packages(self,root):
        dest=root/'packages';dest.mkdir()
        for name,package in [('commandblock-4.1.8-official.scmod','zh.command'),('sc-agentbridge-0.5.0.scmod','local.sc.agentbridge')]:
            with zipfile.ZipFile(dest/name,'w') as z:z.writestr('modinfo.json',json.dumps({'PackageName':package,'Version':'4.1.8' if package=='zh.command' else '0.5.0'}))
        return dest
    def test_copy_registration_backed_restore_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'game';(game/'Mods').mkdir(parents=True);(game/'init.js').write_text('// original');source=game/'doc/Worlds/World1';copy=game/'doc/Worlds/World2';self.world(source,'SC MCP LAB','a'*32);self.world(copy,'SC MCP LAB COPY','a'*32)
            cfg=self.config(root,copied_lab_token='a'*32,source_lab_directory='app:/doc/Worlds/World1')
            with patch('sc_bridge.native_deploy.assert_not_running'):
                record=deploy_native(cfg,self.packages(root));self.assertEqual((copy/'scagent-world-id.txt').read_text(),'b'*32);self.assertEqual((source/'scagent-world-id.txt').read_text(),'a'*32);restore_native(cfg,record['record'])
            self.assertEqual((copy/'scagent-world-id.txt').read_text(),'a'*32);self.assertEqual((game/'init.js').read_text(),'// original')
    def test_same_world_or_non_lab_source_cannot_replace_token(self):
        for source_name,source_path in [('SC MCP LAB COPY','app:/doc/Worlds/World2'),('Production','app:/doc/Worlds/World1')]:
            with self.subTest(source=source_path),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);game=root/'game';(game/'Mods').mkdir(parents=True);(game/'init.js').write_text('// original');self.world(game/'doc/Worlds/World1',source_name,'a'*32);copy=game/'doc/Worlds/World2';self.world(copy,'SC MCP LAB COPY','a'*32)
                cfg=self.config(root,copied_lab_token='a'*32,source_lab_directory=source_path)
                with patch('sc_bridge.native_deploy.assert_not_running'),self.assertRaises(ValueError):deploy_native(cfg,self.packages(root))
                self.assertEqual((copy/'scagent-world-id.txt').read_text(),'a'*32)
