#!/usr/bin/env python3
"""Compare frozen final submissions; never substitute a missing score with zero."""
import argparse
import json
from pathlib import Path
import statistics

p=argparse.ArgumentParser()
p.add_argument('summaries',nargs='+',type=Path)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
data=[json.loads(f.read_text()) for f in a.summaries]
for key in ('toolchain_sha256','frozen_sha256','seeds_sha256'):
    if len({d[key] for d in data})!=1: raise SystemExit('Incomparable '+key)
lines=['| arm | eligible | area_um2 (median) | worst WNS ns |','|---|---|---:|---:|']
for d in data:
    measured=[r['metrics'] for r in d['runs'] if 'area_um2' in r['metrics']]
    area=statistics.median(m['area_um2'] for m in measured) if measured else None
    wns=min(m['wns_ns'] for m in measured) if measured else None
    lines.append(f"| {d['label']} | {d['eligible']} | {area if area is not None else 'not measured'} | {wns if wns is not None else 'not measured'} |")
lines+=['','Only eligible submissions can be ranked. These are synthesis estimates, not silicon or placed/routed PPA.',
         'Report total and map/task/onboard/loop wall time, all model usage, eval calls, stop reasons, and interventions separately.',
         'Multiple summaries per arm are independent repeats, not candidates to cherry-pick. Missing cost logs prevent cost-effectiveness claims.']
a.out.write_text('\n'.join(lines)+'\n')
