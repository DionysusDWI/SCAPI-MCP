from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import uuid
import zipfile
from .client import atomic_json

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def assert_not_running(config):
    # Read-only process inspection; never stop other installations by name.
    if __import__('os').name != 'nt':
        return
    script = "Get-Process | Where-Object { $_.ProcessName -eq 'Survivalcraft' } | ForEach-Object { $_.Path } | ConvertTo-Json -Compress"
    inspected = subprocess.run(['powershell', '-NoProfile', '-Command', script],
                               capture_output=True, text=True, timeout=10)
    if inspected.returncode != 0:
        raise RuntimeError('Cannot verify game process state; close the target before deploying')
    paths = json.loads(inspected.stdout) if inspected.stdout.strip() else []
    if isinstance(paths, str): paths = [paths]
    for path in paths:
        if path is None:
            raise RuntimeError('A game process path is unavailable; cannot safely deploy')
        if Path(path).resolve() == config.game_dir / 'Survivalcraft.exe':
            raise RuntimeError('The target game is running; close this instance before deployment')

def deploy(config):
    from .native_deploy import deploy_native
    return deploy_native(config, config.game_dir.parent / 'artifacts/sc-bridge/build/packages')


def restore_deployment(config, record_path):
    assert_not_running(config)
    record_path = Path(record_path).resolve()
    record_path.relative_to(config.backups_dir / 'deployments')
    record = json.loads(record_path.read_text(encoding='utf-8'))
    destination, backup = Path(record['destination']).resolve(), Path(record['backup']).resolve()
    if destination != config.game_dir / 'init.js':
        raise ValueError('Deployment target differs from configured game')
    backup.relative_to(config.backups_dir / 'deployments')
    if sha256(backup) != record['original_sha256'] or sha256(destination) != record['deployed_sha256']:
        raise ValueError('Deployment or backup changed; refusing to overwrite')
    shutil.copy2(backup, destination)
    return {'restored': destination.as_posix(), 'sha256': sha256(destination)}
