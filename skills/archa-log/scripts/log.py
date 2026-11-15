#!/usr/bin/env python3
"""Generate an explicit topic report using the project-local runtime."""
import argparse
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('-p', '--project', type=Path, required=True)
parser.add_argument('--topic', required=True)
args = parser.parse_args()
entry = args.project.resolve() / '.archa/archa.py'
if not entry.is_file():
    parser.error('deploy the topic runtime with archa-map/scripts/initialize.py first')
raise SystemExit(subprocess.call([sys.executable, str(entry), 'report', '-p', str(args.project.resolve()), '--topic', args.topic]))
