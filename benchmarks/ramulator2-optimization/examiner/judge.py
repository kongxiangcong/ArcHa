#!/usr/bin/env python3
"""External event-equivalence and paired-time judge for the fixed DDR4 task."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
from instrument import instrument

TASK = Path(__file__).resolve().parents[1]
BENCH = TASK.parent
PRIVATE = TASK / 'examiner/private'
spec = importlib.util.spec_from_file_location('frozen_workloads', TASK / 'starter/workloads.py')
workloads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workloads)
EDITABLE = {'source/src/dram_controller/impl/generic_dram_controller.cpp',
            'source/src/dram_controller/impl/scheduler/generic_scheduler.cpp'}


def sha(path):
    return hashlib.file_digest(open(path, 'rb'), 'sha256').hexdigest()


def check_scope(project):
    manifest = json.loads((TASK / 'runs/prepared/manifest.json').read_text())['files']
    for relative, expected in manifest.items():
        if (not relative.startswith('source/') and relative != 'build.sh') or relative in EDITABLE:
            continue
        path = project / relative
        if not path.is_file() or sha(path) != expected:
            raise ValueError(f'frozen source changed: {relative}')
    parents = {str(Path(x).parent) for x in EDITABLE}
    for path in (project / 'source').rglob('*'):
        if not path.is_file():
            continue
        relative = str(path.relative_to(project))
        if relative in manifest or relative == 'source/libramulator.so':
            continue
        if path.suffix == '.h' and str(Path(relative).parent) in parents:
            continue
        raise ValueError(f'new file outside permitted helper scope: {relative}')


def build(project):
    with (project / 'exam-build.log').open('w') as log:
        subprocess.run([sys.executable, str(BENCH / 'tools/isolate.py'), str(project),
                        '--', './build.sh'], stdout=log, stderr=subprocess.STDOUT, check=True)


def run(project, binary, output, pattern, count, seed, write_every, observed=False, library=None):
    output.mkdir(parents=True, exist_ok=True)
    config = workloads.generate(output, pattern, count, seed, write_every)
    command = ['env']
    if observed:
        command += [f'EXAM_TRACE={output / "events.tsv"}']
    if library:
        command += [f'LD_LIBRARY_PATH={library}']
    command += ['/usr/bin/time', '-f', '%M', '-o', str(output / 'max-rss-kib.txt'),
                'taskset', '-c', str(min(os.sched_getaffinity(0))), str(binary), '-f', str(config)]
    # Instrumented candidate and baseline use their own workspaces; no examiner
    # data outside that one workspace is visible to the process.
    start = time.perf_counter()
    result = subprocess.run([sys.executable, str(BENCH / 'tools/isolate.py'), str(project),
                             '--', *command], text=True, capture_output=True, timeout=180)
    elapsed = time.perf_counter() - start
    (output / 'stdout').write_text(result.stdout)
    (output / 'stderr').write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(f'simulator failed: {output}: {result.stderr[-500:]}')
    stats = result.stdout[result.stdout.index('Frontend:'):]
    (output / 'stats.txt').write_text(stats)
    return elapsed, stats


def compare(project, report_dir, smoke=False):
    project, report_dir = project.resolve(), report_dir.resolve()
    check_scope(project)
    plain = PRIVATE / 'baseline-timed'
    observed = PRIVATE / 'baseline-observed'
    # Always build candidate under the frozen toolchain; ignore submitted binaries.
    build(project)
    candidate = report_dir / 'candidate-observed'
    candidate.mkdir(parents=True)
    shutil.copytree(project / 'source', candidate / 'source', ignore=shutil.ignore_patterns('libramulator.so'))
    shutil.copy2(TASK / 'runs/prepared/project/build.sh', candidate / 'build.sh')
    instrument(candidate / 'source')
    manifest = json.loads((TASK / 'runs/prepared/manifest.json').read_text())['files']
    identical = all(sha(project / p) == manifest[p] for p in EDITABLE)
    if smoke and identical:
        (candidate / 'build').mkdir()
        shutil.copy2(observed / 'build/ramulator2', candidate / 'build/ramulator2')
        shutil.copy2(observed / 'source/libramulator.so', candidate / 'source/libramulator.so')
    else:
        build(candidate)
    checks, coverage = [], dict(rejected=0, refresh=0, complete=0, selected=0)
    for pattern in ['stream', 'random', 'samebank', 'local']:
        for period in [0, 1, 5]:
            name = f'{pattern}-rw{period}'
            count = 1000 if smoke else 3000
            _, reference_stats = run(observed, observed / 'build/ramulator2', observed / 'results' / name,
                                     pattern, count, 90917, period, True)
            _, candidate_stats = run(candidate, candidate / 'build/ramulator2', candidate / 'results' / name,
                                     pattern, count, 90917, period, True, library=candidate / 'source')
            ref_events = observed / 'results' / name / 'events.tsv'
            got_events = candidate / 'results' / name / 'events.tsv'
            event_ok = sha(ref_events) == sha(got_events)
            # Also prove the reference observer preserves original outputs.
            _, plain_stats = run(plain, plain / 'ramulator2', plain / 'results' / name,
                                 pattern, count, 90917, period, library=plain)
            checks.append(dict(case=name, events_equal=event_ok,
                               stats_equal=candidate_stats == reference_stats,
                               probe_preserves_stats=plain_stats == reference_stats,
                               trace_sha256=sha(ref_events)))
            for line in ref_events.open():
                fields = line.rstrip().split('\t')
                coverage['rejected'] += fields[0] == 'accept' and fields[3] == '0'
                coverage['refresh'] += fields[0] == 'command' and fields[3] == 'REFab'
                coverage['complete'] += fields[0] == 'complete'
                coverage['selected'] += fields[0] == 'select'
    correct = all(all(c[k] for k in ('events_equal', 'stats_equal', 'probe_preserves_stats')) for c in checks)
    correct = correct and all(coverage.values())
    timing = []
    if correct:
        for pattern in ['stream', 'random', 'samebank']:
            pairs = []
            for rep in range(3 if smoke else 5):
                values = {}
                for which in (['baseline', 'candidate'] if rep % 2 == 0 else ['candidate', 'baseline']):
                    root = plain if which == 'baseline' else project
                    binary = plain / 'ramulator2' if which == 'baseline' else project / 'build/ramulator2'
                    elapsed, stats = run(root, binary, root / 'results' / f'time-{pattern}-{rep}',
                                         pattern, 10000 if smoke else 100000, 54071, 5,
                                         library=plain if which == 'baseline' else None)
                    values[which] = elapsed
                    values[which+'_rss_kib'] = int((root / 'results' / f'time-{pattern}-{rep}' / 'max-rss-kib.txt').read_text())
                    values[which+'_stats'] = stats
                if values.pop('baseline_stats') != values.pop('candidate_stats'):
                    correct = False
                pairs.append(values)
            ratios = [p['baseline']/p['candidate'] for p in pairs]
            timing.append(dict(case=pattern, pairs=pairs, speedup=statistics.median(ratios),
                               min_pair_speedup=min(ratios), max_pair_speedup=max(ratios)))
    aggregate = math.prod(t['speedup'] for t in timing)**(1/len(timing)) if timing else None
    # A single faster noisy trial is insufficient: require median >= 5% and
    # at least 4/5 paired aggregate trials faster than the baseline.
    wins = sum(math.prod(t['pairs'][i]['baseline']/t['pairs'][i]['candidate'] for t in timing) > 1
               for i in range(len(timing[0]['pairs']))) if timing else 0
    gain = bool(aggregate and aggregate > 1.05 and min(t['speedup'] for t in timing) >= 0.95 and wins >= 4)
    report = dict(correctness=correct, coverage=coverage, checks=checks, timing=timing,
                  geometric_speedup=aggregate, paired_aggregate_wins=wins,
                  performance_passed=gain and not smoke, smoke_only=smoke,
                  passed=correct and gain and not smoke)
    report_dir.mkdir(exist_ok=True, parents=True)
    (report_dir / 'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('project', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--smoke', action='store_true')
    args = p.parse_args()
    result = compare(args.project, args.output, args.smoke)
    print(json.dumps({k: v for k, v in result.items() if k not in ('checks', 'timing')}, indent=2))
    raise SystemExit(0 if (result['correctness'] if args.smoke else result['passed']) else 1)
