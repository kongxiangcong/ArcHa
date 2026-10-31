#!/usr/bin/env python3
"""Reproducible qualification probe, not a final optimization evaluator."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, default=Path('/root/ramulator2'))
p.add_argument('--work', type=Path, default=Path('/tmp/ramulator2-preflight'))
p.add_argument('--sizes', nargs='+', type=int, default=[100000, 1000000])
p.add_argument('--repeats', type=int, default=3)
args = p.parse_args()
out = Path(__file__).resolve().parent
args.work.mkdir(parents=True, exist_ok=True)
cpu = min(os.sched_getaffinity(0))
records = []
manifest = []
for n in args.sizes:
    for pattern in ['stream', 'random', 'samebank']:
        name = f'{pattern}-{n}'
        trace = args.work / f'{name}.trace'
        rng = random.Random(20261031)
        with trace.open('w') as f:
            for i in range(n):
                if pattern == 'stream':
                    addr = (i * 64) % (1 << 30)
                elif pattern == 'random':
                    addr = rng.randrange((1 << 30) // 64) * 64
                else:
                    # 64B * 128 columns * 2 ranks * 4 BG * 4 banks.
                    addr = (i % 4096) * 262144
                f.write(f'{"ST" if i % 5 == 4 else "LD"} {addr}\n')
        config = {
            'Frontend': {'impl': 'LoadStoreTrace', 'clock_ratio': 1, 'path': str(trace)},
            'MemorySystem': {
                'impl': 'GenericDRAM', 'clock_ratio': 1,
                'DRAM': {'impl': 'DDR4', 'org': {'preset': 'DDR4_8Gb_x8', 'channel': 1, 'rank': 2},
                         'timing': {'preset': 'DDR4_2400R'}},
                'Controller': {'impl': 'Generic', 'Scheduler': {'impl': 'FRFCFS'},
                               'RefreshManager': {'impl': 'AllBank'},
                               'RowPolicy': {'impl': 'ClosedRowPolicy', 'cap': 4}},
                'AddrMapper': {'impl': 'RoBaRaCoCh'}}}
        cfg = out / f'{name}.json'
        cfg.write_text(json.dumps(config, indent=2) + '\n')
        manifest.append({'name': name, 'trace_sha256': hashlib.sha256(trace.read_bytes()).hexdigest(),
                         'bytes': trace.stat().st_size, 'seed': 20261031})
        for rep in range(args.repeats):
            stem = out / f'{name}-r{rep+1}'
            cmd = ['/usr/bin/time', '-f', '%e %U %S %M', '-o', str(stem) + '.time',
                   'taskset', '-c', str(cpu), str(args.repo / 'build/ramulator2'), '-f', str(cfg)]
            start = time.perf_counter()
            result = subprocess.run(cmd, cwd=args.repo, capture_output=True, text=True, timeout=180)
            wall = time.perf_counter() - start
            Path(str(stem) + '.stdout').write_text(result.stdout)
            Path(str(stem) + '.stderr').write_text(result.stderr)
            if result.returncode:
                raise RuntimeError(f'{name}: exit {result.returncode}: {result.stderr}')
            stats = result.stdout[result.stdout.index('Frontend:'):]
            def metric(key):
                return int(re.search(rf'^\s*{key}: (\d+)', stats, re.M)[1])
            accepted = metric('total_num_read_requests') + metric('total_num_write_requests')
            assert accepted == n, (accepted, n)
            times = Path(str(stem) + '.time').read_text().split()
            row = {'case': name, 'repeat': rep+1, 'wall_s': wall, 'user_s': float(times[1]),
                   'system_s': float(times[2]), 'maxrss_kib': int(times[3]), 'accepted': accepted,
                   'memory_cycles': metric('memory_system_cycles'), 'accepted_per_s': n / wall,
                   'stats_sha256': hashlib.sha256(stats.encode()).hexdigest(), 'cpu': cpu}
            records.append(row)
            (out / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
            print(json.dumps(row), flush=True)
(out / 'trace-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
summary = []
for case in sorted({r['case'] for r in records}):
    rows = [r for r in records if r['case'] == case]
    summary.append({'case': case, 'median_wall_s': statistics.median(r['wall_s'] for r in rows),
                    'min_wall_s': min(r['wall_s'] for r in rows),
                    'max_wall_s': max(r['wall_s'] for r in rows),
                    'stable_stats': len({r['stats_sha256'] for r in rows}) == 1})
(out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
