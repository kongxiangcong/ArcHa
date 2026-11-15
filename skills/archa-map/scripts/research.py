#!/usr/bin/env python3
"""Initialize a topic through the deployed runtime."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--topic', required=True)
    parser.add_argument('--goal', default='')
    parser.add_argument('--max-rounds', type=int, default=10)
    parser.add_argument('--template', choices=('default', 'pim'), default='default')
    args = parser.parse_args()
    entry = args.project.resolve() / '.archa/archa.py'
    if not entry.is_file():
        parser.error('deploy with initialize.py first')
    return subprocess.call([sys.executable, str(entry), 'init', '-p', str(args.project.resolve()),
                            '--topic', args.topic, '--goal', args.goal, '--max-rounds', str(args.max_rounds),
                            '--template', args.template])


if __name__ == '__main__':
    raise SystemExit(main())
