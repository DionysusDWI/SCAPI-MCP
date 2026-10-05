"""Build fixed upstream in a disposable workspace; never edit reference sources."""
from pathlib import Path
import os
import shutil
import subprocess
import zipfile
from .client import atomic_json
from .deploy import sha256

def build(root=None, *, source_root=None, game_dir=None, api_source=None, commandblock_source=None, sdk=None, output_dir=None, tooling_dir=None):
    root = Path(root or Path.cwd()).resolve()
    source = Path(source_root or Path(__file__).resolve().parents[3]).resolve()
    game = Path(game_dir or root / '.GAME_SCAPI-1.9.3.2').resolve()
    api = Path(api_source or root / 'reference/SurvivalcraftApi').resolve()
    reference = Path(commandblock_source or root / 'reference/SC-CommandBlock').resolve()
    runtime = Path(tooling_dir or root / 'runtime/tooling').resolve()
    sdk = Path(sdk or runtime / 'dotnet/dotnet.exe').resolve()
    output = Path(output_dir or root / 'artifacts/sc-bridge/build').resolve()
    if not sdk.exists():
        raise RuntimeError('Provide the verified local .NET 10.0.401 SDK')
    sdk_version = subprocess.check_output([str(sdk), '--version'], text=True).strip()
    if sdk_version != '10.0.401':
        raise RuntimeError('Pinned .NET SDK 10.0.401 required')
    adapter = source / 'packages/sc-bridge/game-adapter'
    if not (adapter / 'ScAgentBridge.csproj').exists():
        raise RuntimeError('Provide --source-root pointing to the SCAPI-MCP source checkout')
    env = dict(os.environ, DOTNET_CLI_HOME=str(runtime / 'dotnet-home'),
               NUGET_PACKAGES=str(runtime / 'nuget'), DOTNET_CLI_TELEMETRY_OPTOUT='1')
    commit = subprocess.check_output(['git', '-c', f'safe.directory={reference.as_posix()}', '-C', str(reference), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != 'f5bc2ef2c106db28a45d118a9a45387f5fec7c56':
        raise RuntimeError('Official command block source differs from pinned 4.1.8')
    for source,pinned in [(reference,commit),(api,'97e29b3e1a5bdc39799bab8f6ba36cf22dd39239')]:
        git=['git','-c',f'safe.directory={source.as_posix()}','-C',str(source)]
        if subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()!=pinned or subprocess.check_output(git+['diff','HEAD','--name-only'],text=True).strip():
            raise RuntimeError('Pinned upstream must retain unmodified tracked sources')
    copy = runtime / 'commandblock-official'
    shutil.copytree(reference, copy, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git', 'bin', 'obj'))
    shutil.copy2(api / 'nuget.config', copy / 'nuget.config')
    for project, destination in [(copy / 'CommandBlock.csproj', output / 'commandblock-official'),
            (adapter / 'ScAgentBridge.csproj', output / 'adapter')]:
        subprocess.run([str(sdk), 'build', str(project), '-c', 'Release', '-o', str(destination), f'-p:GameDir={game}', f'-p:CommandBlockAssembly={output / "commandblock-official/CommandBlock.dll"}'], env=env, check=True)
    packages = output / 'packages'
    packages.mkdir(parents=True, exist_ok=True)
    # Upstream package references are not copied by its library project. Include the
    # dependency absent from the actual game; never bundle a second game API DLL.
    shutil.copy2(runtime / 'nuget/tomlyn/2.0.0/lib/net10.0/Tomlyn.dll', output / 'commandblock-official/Tomlyn.dll')
    for name, directory, files in [('commandblock-4.1.8-official.scmod', output / 'commandblock-official', None),
            ('sc-agentbridge-0.5.0.scmod', output / 'adapter', ['ScAgentBridge.dll'])]:
        with zipfile.ZipFile(packages / name, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(directory.rglob('*')):
                if not path.is_file() or path.suffix in ('.pdb',) or path.name.endswith('.deps.json'): continue
                if files is None or path.name in files: archive.write(path, path.relative_to(directory).as_posix())
            if files: archive.write(adapter / 'modinfo.json', 'modinfo.json')
    record = {'official_commit': commit, 'sdk': subprocess.check_output([str(sdk), '--version'], env=env, text=True).strip(),
              'api_commit':'97e29b3e1a5bdc39799bab8f6ba36cf22dd39239',
              'game_assemblies':{name:sha256(game/name) for name in ('Survivalcraft.dll','Engine.dll','EntitySystem.dll')},
              'packages': [{'path': p.as_posix(), 'sha256': sha256(p)} for p in [packages/'commandblock-4.1.8-official.scmod',packages/'sc-agentbridge-0.5.0.scmod']]}
    atomic_json(output / 'build.json', record)
    return record
