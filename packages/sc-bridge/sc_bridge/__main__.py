import argparse
import json
from . import Bridge, Config
from .deploy import deploy, restore_deployment

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('command', choices=['build', 'deploy', 'deploy-native', 'restore-native', 'restore-deployment', 'status', 'world-info', 'players', 'isolate-local', 'export-backup'])
    parser.add_argument('record', nargs='?')
    args = parser.parse_args()
    config = Config.load(args.config)
    if args.command == 'build':
        from .build import build
        result = build(config.game_dir.parent)
    elif args.command == 'deploy-native':
        from .native_deploy import deploy_native
        result = deploy_native(config, config.game_dir.parent / 'artifacts/sc-bridge/build/packages')
    elif args.command == 'restore-native':
        from .native_deploy import restore_native
        if not args.record: parser.error('restore-native requires record path')
        result = restore_native(config, args.record)
    elif args.command == 'deploy':
        result = deploy(config)
    elif args.command == 'restore-deployment':
        if not args.record: parser.error('restore-deployment requires record path')
        result = restore_deployment(config, args.record)
    else:
        result = getattr(Bridge(config), args.command.replace('-', '_'))()
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
