#!/usr/bin/env python3
"""Linux preparer only: record toolchain, public campaign, and immutable inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess

p=argparse.ArgumentParser()
p.add_argument('--exam',type=Path,required=True)
p.add_argument('--liberty',type=Path,required=True)
p.add_argument('--private',type=Path,required=True)
p.add_argument('--model',required=True)
p.add_argument('--reasoning',required=True)
p.add_argument('--yosys-plugin',default='',help='slang if built as loadable plugin; empty if built in')
a=p.parse_args()
root=a.exam.resolve(); private=a.private.resolve()
if private.is_relative_to(root): raise SystemExit('private must be outside exam')
if (root/'frozen.json').exists(): raise SystemExit('already frozen; use a new campaign/template')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
c={'jobs':4,'liberty':str(a.liberty.resolve()),'yosys_args':['-m',a.yosys_plugin] if a.yosys_plugin else [],'sha256':{},'versions':{}}
for name,flag in [('yosys','-V'),('verilator','--version'),('openroad','-version')]:
    binary=shutil.which(name)
    if not binary: raise SystemExit('missing '+name)
    c[name]=str(Path(binary).resolve())
    c['versions'][name]=subprocess.check_output([binary,flag],text=True,stderr=subprocess.STDOUT).strip()
for k in ('liberty','yosys','verilator','openroad'): c['sha256'][k]=sha(c[k])
helptext=subprocess.check_output([c['yosys'],*c['yosys_args'],'-p','help read_slang'],text=True,stderr=subprocess.STDOUT)
if 'No such command' in helptext: raise SystemExit('read_slang unavailable')
if 'Nangate' not in a.liberty.read_text() and 'NANGATE' not in a.liberty.read_text():
    raise SystemExit('Expected NanGate45 liberty; inspect manually')
campaign={'id':'fr64-v1','model':a.model,'reasoning_effort':a.reasoning,
          'per_arm_wall_seconds':28800,'per_arm_total_tokens':1000000,
          'loop_max_attempts':48,'max_development_evaluations':96,'repeats':3,
          'accounting':'wall and all model calls include simulated user, map, task, onboard, loop; cached tokens included once in input',
          'objective':'area_um2','constraints':{'correct':1,'wns_ns_min':0},
          'scope':'optimization from shared independently authored baseline; no blank-design claim',
          'clock_ns':10,'latency_enabled_edges':28,'initiation_interval':8}
(root/'toolchain.json').write_text(json.dumps(c,indent=2)+'\n')
(root/'campaign.json').write_text(json.dumps(campaign,indent=2)+'\n')
frozen={}
for path in sorted(root.rglob('*')):
    if path.is_file() and (path.parts[len(root.parts)] in ('primitives','harness') or path.name in ('SPEC.md','README.md','campaign.json','toolchain.json')):
        frozen[path.relative_to(root).as_posix()]=sha(path)
(root/'frozen.json').write_text(json.dumps(frozen,indent=2)+'\n')
private.mkdir(parents=True,exist_ok=True)
seedfile=private/'seeds.json'
if seedfile.exists(): raise SystemExit('private seed file already exists')
seedfile.write_text(json.dumps([secrets.randbits(63) for _ in range(4)])+'\n')
seedfile.chmod(0o600)
(private/'seed_commitment.sha256').write_text(sha(seedfile)+'  seeds.json\n')
print('Frozen. Next: neutral preflight on BOTH starter and sealed reference, then fresh contestant copies.')
