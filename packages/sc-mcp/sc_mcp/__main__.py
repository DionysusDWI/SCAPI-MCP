import argparse
import sys
from sc_bridge import Bridge, Config
from .server import Server

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    if hasattr(sys.stdin, 'reconfigure'): sys.stdin.reconfigure(encoding='utf-8')
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    Server(Bridge(Config.load(args.config))).serve(sys.stdin, sys.stdout)

if __name__ == '__main__': main()
