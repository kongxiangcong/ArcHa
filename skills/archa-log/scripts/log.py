#!/usr/bin/env python3
"""Use the project's deployed runtime, or the source checkout during development."""
from pathlib import Path
import argparse
import sys
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('-p', '--project', required=True)
args, _ = parser.parse_known_args()
runtime = Path(args.project).resolve() / '.opc/runtime'
sys.path.insert(0, str(runtime if (runtime / 'opc/log.py').is_file() else Path(__file__).resolve().parents[3]))
from opc.log import main
raise SystemExit(main())
