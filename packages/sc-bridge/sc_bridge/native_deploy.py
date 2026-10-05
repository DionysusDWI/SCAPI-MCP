"""Transactional C# host deployment with preserved original packages and CAS rollback."""
from pathlib import Path
import json
import shutil
import uuid
import zipfile
import xml.etree.ElementTree as ET
from .client import atomic_json
from .deploy import assert_not_running, sha256

def package_name(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read('modinfo.json').decode('utf-8-sig'))['PackageName']

def deploy_native(config, packages):
    assert_not_running(config)
    packages = Path(packages).resolve()
    incoming = [packages / 'commandblock-4.1.8-official.scmod', packages / 'sc-agentbridge-0.5.0.scmod']
    for path,expected in zip(incoming,('4.1.8','0.5.0')):
        with zipfile.ZipFile(path) as archive:
            metadata=json.loads(archive.read('modinfo.json').decode('utf-8-sig'))
            if metadata.get('Version')!=expected:raise ValueError('Dependency or adapter version mismatch')
    names = {package_name(p) for p in incoming}
    if names != {'zh.command', 'local.sc.agentbridge'}: raise ValueError('Unexpected packages')
    record_dir = config.backups_dir / 'deployments' / uuid.uuid4().hex
    record_dir.mkdir(parents=True)
    record = {'version': '0.5.0', 'protocol': 3, 'game_dir': config.game_dir.as_posix(), 'state': 'prepared', 'files': []}
    mutations = [(config.game_dir / 'init.js', (config.game_dir / 'init.js').read_text(encoding='utf-8-sig').split('// SC_BRIDGE_DEPLOYMENT_BEGIN')[0].encode('utf-8')),
                 (config.game_dir / 'scagentbridge.json', json.dumps(config.host_settings(), ensure_ascii=False).encode('utf-8'))]
    token = config.target.get('world_token')
    virtual = config.target.get('directory', '')
    if not token or not virtual.startswith('app:/doc/Worlds/'):
        raise ValueError('Native host needs an explicitly registered world token')
    world = (config.game_dir / virtual.removeprefix('app:/')).resolve()
    world.relative_to(config.game_dir / 'doc/Worlds')
    name = ET.parse(world / 'Project.xml').find("./Subsystems/Values[@Name='GameInfo']/Value[@Name='WorldName']")
    if name is None or name.get('Value') != config.target['name']:
        raise ValueError('Actual world identity differs from configured target')
    if config.target.get('test_only') and not name.get('Value').startswith('SC MCP LAB'):
        raise ValueError('Test registration cannot target a production world')
    marker = (config.game_dir / virtual.removeprefix('app:/') / 'scagent-world-id.txt').resolve()
    marker.relative_to(config.game_dir / 'doc/Worlds')
    if marker.exists() and marker.read_text(encoding='utf-8') != token:
        copied=config.target.get('copied_lab_token');source=config.target.get('source_lab_directory','')
        if not config.target.get('test_only') or not copied or not source.startswith('app:/doc/Worlds/'):
            raise ValueError('World identity marker conflicts with registration')
        origin=(config.game_dir/source.removeprefix('app:/')).resolve();origin.relative_to(config.game_dir/'doc/Worlds')
        origin_name=ET.parse(origin/'Project.xml').find("./Subsystems/Values[@Name='GameInfo']/Value[@Name='WorldName']")
        if origin==world or origin_name is None or not origin_name.get('Value','').startswith('SC MCP LAB') or (origin/'scagent-world-id.txt').read_text(encoding='utf-8')!=copied or marker.read_text(encoding='utf-8')!=copied:
            raise ValueError('Independent LAB copy registration could not verify source identity')
        mutations.append((marker,token.encode('utf-8')))
    if not marker.exists(): mutations.append((marker, token.encode('utf-8')))
    for old in (config.game_dir / 'Mods').glob('*.scmod'):
        if package_name(old) in names: mutations.append((old, None))
    for path in incoming: mutations.append((config.game_dir / 'Mods' / path.name, path.read_bytes()))
    # Collect every original before changing any game file.
    originals = {}
    for destination, _ in mutations:
        if destination in originals: continue
        destination.resolve().relative_to(config.game_dir.resolve())
        backup = record_dir / (str(len(originals)) + '.original')
        if destination.exists(): shutil.copy2(destination, backup)
        originals[destination] = {'destination': destination.as_posix(), 'backup': backup.as_posix() if backup.exists() else None,
                                'original_sha256': sha256(backup) if backup.exists() else None, 'deployed_sha256': None}
    record['files'] = list(originals.values())
    atomic_json(record_dir / 'deployment.json', record)
    try:
        for destination, data in mutations:
            if data is None: destination.unlink(missing_ok=True)
            else:
                temp = destination.with_name(destination.name + '.deploy-tmp')
                temp.write_bytes(data); temp.replace(destination)
            originals[destination]['deployed_sha256'] = sha256(destination) if destination.exists() else None
        record['state'] = 'installed'
        atomic_json(record_dir / 'deployment.json', record)
    except Exception:
        for destination, item in originals.items():
            if item['backup']: shutil.copy2(item['backup'], destination)
            else: destination.unlink(missing_ok=True)
        record['state'] = 'rolled_back'
        atomic_json(record_dir / 'deployment.json', record)
        raise
    return {'record': (record_dir / 'deployment.json').as_posix(), **record}

def restore_native(config, record_path):
    assert_not_running(config)
    path = Path(record_path).resolve()
    path.relative_to(config.backups_dir / 'deployments')
    record = json.loads(path.read_text(encoding='utf-8'))
    if Path(record['game_dir']).resolve() != config.game_dir or record['state'] != 'installed': raise ValueError('Wrong deployment')
    for item in record['files']:
        destination = Path(item['destination']).resolve()
        destination.relative_to(config.game_dir)
        if (sha256(destination) if destination.exists() else None) != item['deployed_sha256']: raise ValueError('Game file changed; rollback refused')
        if item['backup']:
            backup = Path(item['backup']).resolve(); backup.relative_to(path.parent)
            if sha256(backup) != item['original_sha256']: raise ValueError('Backup changed')
    for item in record['files']:
        destination = Path(item['destination'])
        if item['backup']: shutil.copy2(item['backup'], destination)
        else: destination.unlink(missing_ok=True)
    record['state'] = 'restored'; atomic_json(path, record)
    return {'restored': True, 'record': str(path)}
