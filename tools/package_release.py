"""Package only this repository; no game, upstream binary or private LAB data."""
import argparse,hashlib,json,subprocess,sys,zipfile,shutil
from pathlib import Path

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--build-dir',required=True);p.add_argument('--candidate',action='store_true');a=p.parse_args()
    root=Path(__file__).resolve().parents[1];out=Path(a.output).resolve();build=Path(a.build_dir).resolve()
    if out.exists():raise RuntimeError('Output already exists; preserve immutable artifacts')
    git=['git','-c',f'safe.directory={root.as_posix()}','-C',str(root)]
    dirty=subprocess.check_output(git+['status','--porcelain'],text=True).strip()
    if dirty and not a.candidate:raise RuntimeError('Formal release must be built from a clean committed tree')
    acceptance=json.loads((root/'docs/acceptance-0.5.json').read_text(encoding='utf-8'))
    if acceptance['status']!='passed' and not a.candidate:raise RuntimeError('Acceptance incomplete')
    commit=None if dirty else subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()
    names=subprocess.check_output(git+['ls-files','--cached','--others','--exclude-standard','-z']).decode().split('\0')
    sources=[]
    for name in sorted(set(filter(None,names))):
        f=root/name
        if not f.is_file():continue
        if f.is_symlink() or f.suffix.lower() in ('.dll','.scmod','.scworld','.pdb','.zip','.whl') or name.endswith('.local.json'):raise RuntimeError('Private/binary file in source index: '+name)
        if name.split('/')[0] not in ('packages','tools','docs','config','.gitignore','AGENTS.md','README.md','NOTICE.md'):raise RuntimeError('Unexpected source path: '+name)
        sources.append({'path':name,'sha256':sha(f)})
    if len((root/'README.md').read_text(encoding='utf-8'))>3000:raise RuntimeError('README exceeds 3000 characters')
    report=json.loads((build/'build.json').read_text(encoding='utf-8'))
    expected={'sdk':'10.0.401','api_commit':'97e29b3e1a5bdc39799bab8f6ba36cf22dd39239','official_commit':'f5bc2ef2c106db28a45d118a9a45387f5fec7c56'}
    if any(report.get(k)!=v for k,v in expected.items()):raise RuntimeError('Build provenance differs from pinned baseline')
    mod=build/'packages/sc-agentbridge-0.5.0.scmod'
    row=next(r for r in report['packages'] if Path(r['path']).name==mod.name)
    if sha(mod)!=row['sha256']:raise RuntimeError('Adapter changed since build')
    out.mkdir(parents=True);install=out/'SCAPI-MCP-0.5.0';(install/'wheels').mkdir(parents=True);(install/'packages').mkdir()
    subprocess.run([sys.executable,'-m','pip','wheel','--no-cache-dir','--no-build-isolation','--no-deps',str(root/'packages/sc-bridge'),str(root/'packages/sc-mcp'),'--wheel-dir',str(install/'wheels')],check=True)
    shutil.copy2(mod,install/'packages'/mod.name)
    for name in ('README.md','NOTICE.md','docs/install.md','docs/development.md','docs/acceptance-0.5.md','docs/acceptance-0.5.json','docs/tool-coverage.json','config/example.json','tools/install.ps1','packages/sc-bridge/docs/operations.md','packages/sc-bridge/docs/coverage.md','packages/sc-mcp/docs/operations-0.5.md'):
        dest=install/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,dest)
    metadata={'version':'0.5.0','protocol':3,'status':'candidate' if a.candidate else 'release','commit':commit,'source_tree_sha256':hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest(),'sources':sources,'build':{**expected,'game_assemblies':report['game_assemblies'],'adapter_sha256':sha(mod)}}
    (install/'build-manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    checksum=''.join(f'{sha(f)}  {f.relative_to(install).as_posix()}\n' for f in sorted(install.rglob('*')) if f.is_file());(install/'SHA256SUMS.txt').write_text(checksum,encoding='utf-8')
    with zipfile.ZipFile(out/'SCAPI-MCP-0.5.0-windows.zip','w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(install.rglob('*')):
            if f.is_file():z.write(f,f.relative_to(install).as_posix())
    with zipfile.ZipFile(out/'SCAPI-MCP-0.5.0-source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for row in sources:z.write(root/row['path'],row['path'])
    attachments=[out/'SCAPI-MCP-0.5.0-windows.zip',out/'SCAPI-MCP-0.5.0-source.zip']
    (out/'SHA256SUMS.txt').write_text(''.join(f'{sha(f)}  {f.name}\n' for f in attachments),encoding='utf-8')
    (out/'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'directory':str(out),'commit':commit,'status':metadata['status'],'sources':len(sources),'attachments':[f.name for f in attachments]+['SHA256SUMS.txt']},ensure_ascii=False))

if __name__=='__main__':main()
