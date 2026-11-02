#!/usr/bin/env python3
"""Freeze baselines during preparation, before candidate work starts."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from instrument import instrument

TASK = Path(__file__).resolve().parents[1]
BENCH = TASK.parent
PROJECT = TASK / 'runs/prepared/project'
PRIVATE = TASK / 'examiner/private'


def build(project):
    with (project / 'exam-build.log').open('w') as output:
        subprocess.run([sys.executable, str(BENCH / 'tools/isolate.py'), str(project), '--', './build.sh'],
                       stdout=output, stderr=subprocess.STDOUT, check=True)


def main():
    manifest = json.loads((PROJECT.parent / 'manifest.json').read_text())
    for relative, digest in manifest['files'].items():
        if relative.startswith('source/') or relative == 'build.sh':
            actual = hashlib.sha256((PROJECT / relative).read_bytes()).hexdigest()
            if actual != digest:
                raise RuntimeError('Prepare baselines before candidate work: ' + relative)
    timed = PRIVATE / 'baseline-timed'
    if not (timed / 'ramulator2').exists():
        build(PROJECT)
        timed.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / 'build/ramulator2', timed / 'ramulator2')
        shutil.copy2(PROJECT / 'source/libramulator.so', timed / 'libramulator.so')
    observed = PRIVATE / 'baseline-observed'
    if not observed.exists():
        observed.mkdir(parents=True)
        shutil.copytree(PROJECT / 'source', observed / 'source', ignore=shutil.ignore_patterns('libramulator.so'))
        shutil.copy2(PROJECT / 'build.sh', observed / 'build.sh')
        instrument(observed / 'source')
    if not (observed / 'build/ramulator2').exists():
        build(observed)
    hashes = {}
    for p in [timed / 'ramulator2', timed / 'libramulator.so', observed / 'build/ramulator2', observed / 'source/libramulator.so']:
        hashes[str(p.relative_to(PRIVATE))] = hashlib.sha256(p.read_bytes()).hexdigest()
    (PRIVATE / 'baselines.json').write_text(json.dumps({'source': manifest['source'], 'sha256': hashes}, indent=2)+'\n')
    print('Frozen timed and observed baselines ready')


if __name__ == '__main__':
    main()
