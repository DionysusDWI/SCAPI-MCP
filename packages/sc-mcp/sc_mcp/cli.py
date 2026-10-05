"""One entry point; bridge remains an installed shared dependency."""
import argparse
import json
import sys
from pathlib import Path
from sc_bridge import Bridge,Config

def main():
    parser=argparse.ArgumentParser(prog='scapi-mcp')
    parser.add_argument('--config',required=True)
    subs=parser.add_subparsers(dest='command',required=True)
    for name in ('serve','status','world-info','players','isolate-local','export-backup'):subs.add_parser(name)
    build=subs.add_parser('build')
    for name in ('source-root','api-source','commandblock-source','sdk','output-dir','tooling-dir'):build.add_argument('--'+name,required=True)
    deploy=subs.add_parser('deploy');deploy.add_argument('--packages',required=True);deploy.add_argument('--commandblock-package')
    restore=subs.add_parser('restore');restore.add_argument('record')
    args=parser.parse_args();config=Config.load(args.config)
    if args.command=='serve':
        from .server import Server
        if hasattr(sys.stdin,'reconfigure'):sys.stdin.reconfigure(encoding='utf-8')
        if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
        Server(Bridge(config)).serve(sys.stdin,sys.stdout);return
    if args.command=='build':
        from sc_bridge.build import build
        result=build(game_dir=config.game_dir,**{name:getattr(args,name) for name in ('source_root','api_source','commandblock_source','sdk','output_dir','tooling_dir')})
    elif args.command=='deploy':
        from sc_bridge.native_deploy import deploy_native
        if args.commandblock_package:
            import tempfile,shutil
            # Stage only files, never mutate the caller's release directory.
            with tempfile.TemporaryDirectory(dir=config.runtime_dir if config.runtime_dir.exists() else None) as temp:
                shutil.copy2(Path(args.packages)/'sc-agentbridge-0.5.0.scmod',Path(temp)/'sc-agentbridge-0.5.0.scmod')
                shutil.copy2(args.commandblock_package,Path(temp)/'commandblock-4.1.8-official.scmod')
                result=deploy_native(config,temp)
        else:result=deploy_native(config,args.packages)
    elif args.command=='restore':
        from sc_bridge.native_deploy import restore_native
        result=restore_native(config,args.record)
    else:result=getattr(Bridge(config),args.command.replace('-','_'))()
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
