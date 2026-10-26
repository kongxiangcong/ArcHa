#!/usr/bin/env python3
"""Judge under a separate OS identity with trusted exam template and secret seed file."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--template',type=Path,required=True)
    p.add_argument('--rtl',type=Path,required=True)
    p.add_argument('--seeds',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--label',choices=['starter','direct','archa','opentpu'],required=True)
    a=p.parse_args()
    out=a.out.resolve(); out.mkdir(parents=True,exist_ok=False)
    work=out/'trusted'; shutil.copytree(a.template,work,ignore=shutil.ignore_patterns('.git','.opc','results','build','__pycache__'))
    shutil.rmtree(work/'rtl'); (work/'rtl').mkdir()
    files=list(a.rtl.glob('*.sv'))
    if not files or any(f.is_symlink() for f in files): raise ValueError('need regular SV files')
    hashes={}
    for f in files:
        shutil.copyfile(f,work/'rtl'/f.name)
        hashes[f.name]=hashlib.sha256(f.read_bytes()).hexdigest()
    seeds=json.loads(a.seeds.read_text())
    runs=[]
    for i,seed in enumerate(seeds):
        target=out/f'case-{i}'
        rc=subprocess.run([sys.executable,str(work/'harness/evaluate.py'),'--out',str(target),
                           '--seed',str(seed),'--rows','2048'],cwd=work).returncode
        report=json.loads((target/'metrics.json').read_text())
        runs.append(report)
        if rc: break
    summary={'label':a.label,'rtl_sha256':hashes,'runs':runs,
             'eligible':len(runs)==len(seeds) and bool(runs) and all(r['status']=='pass' for r in runs),
             'toolchain_sha256':hashlib.sha256((work/'toolchain.json').read_bytes()).hexdigest(),
             'frozen_sha256':hashlib.sha256((work/'frozen.json').read_bytes()).hexdigest(),
             'seeds_sha256':hashlib.sha256(a.seeds.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return 0 if summary['eligible'] else 1
if __name__=='__main__': sys.exit(main())
