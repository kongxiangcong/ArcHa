#!/usr/bin/env python3
"""External functional judge. Candidate code runs behind the common isolation launcher."""
import argparse
import copy
import json
import math
from pathlib import Path
import random
import subprocess
import sys
from reference import estimate

BENCH = Path(__file__).resolve().parents[2]


def cases():
    rng = random.Random(791934)
    for i in range(96):
        if i % 2:
            n = rng.randrange(2, 10)
            config = dict(topology='ring', nodes=n)
        else:
            rows, cols = rng.randrange(1, 5), rng.randrange(1, 5)
            n = rows * cols
            config = dict(topology='mesh', rows=rows, cols=cols)
        config.update(bandwidth_bytes_s=rng.choice([1, 17, 1e9]), hop_latency_s=rng.choice([0, 1e-9, 0.5]))
        traffic = [[rng.randrange(10000) if rng.random() < 0.35 else 0 for _ in range(n)] for _ in range(n)]
        if i % 5 == 0 and n > 1:
            dest = 1 if config['topology'] == 'ring' or config['cols'] > 1 else config['cols']
            config['links'] = [dict(src=0, dst=dest, bandwidth_bytes_s=3, hop_latency_s=0.7)]
        yield dict(config=config, traffic=traffic)
    base = dict(config=dict(topology='ring', nodes=4, bandwidth_bytes_s=10, hop_latency_s=0.1),
                traffic=[[0, 0, 20, 0], [0]*4, [0]*4, [0]*4])
    yield base
    for field, value in [('nodes', 0), ('nodes', True), ('bandwidth_bytes_s', -1),
                         ('hop_latency_s', -1), ('topology', 'torus')]:
        case = copy.deepcopy(base)
        case['config'][field] = value
        yield case
    for matrix in [[], [[1]], [[0, 0, -1, 0]]+[[0]*4 for _ in range(3)],
                   [[0, 0, True, 0]]+[[0]*4 for _ in range(3)]]:
        case = copy.deepcopy(base)
        case['traffic'] = matrix
        yield case
    for links in [[dict(src=0, dst=2, bandwidth_bytes_s=10, hop_latency_s=0)],
                  [dict(src=0, dst=1, bandwidth_bytes_s=0, hop_latency_s=0)],
                  [dict(src=0, dst=1, bandwidth_bytes_s=3, hop_latency_s=0)]*2]:
        case = copy.deepcopy(base)
        case['config']['links'] = links
        yield case
    for n in (2, 4):
        yield dict(config=dict(topology='ring', nodes=n, bandwidth_bytes_s=0, hop_latency_s=0),
                   traffic=[[19 if s == d else 0 for d in range(n)] for s in range(n)])


def judge(project):
    project = Path(project).resolve()
    requests = list(cases())
    expected = []
    for item in requests:
        try:
            expected.append(estimate(**item))
        except (ValueError, TypeError, KeyError):
            expected.append(None)
    # Freeze transport; only the requested model and private helpers are editable.
    runner = BENCH / 'deepstack-development/starter/runner.py'
    if (project / 'runner.py').read_bytes() != runner.read_bytes():
        return dict(passed=False, reason='fixed runner changed')
    result = subprocess.run([sys.executable, str(BENCH / 'tools/isolate.py'), str(project),
                             '--', 'python', 'runner.py'],
                            input=''.join(json.dumps(x)+'\n' for x in requests),
                            text=True, capture_output=True, timeout=30)
    if result.returncode:
        return dict(passed=False, reason='candidate execution failed', stderr=result.stderr[-2000:])
    try:
        actual = [json.loads(line) for line in result.stdout.splitlines()]
    except ValueError:
        return dict(passed=False, reason='invalid JSONL output')
    failed = []
    if len(actual) != len(expected):
        return dict(passed=False, reason='wrong number of outputs')
    for i, (want, row) in enumerate(zip(expected, actual)):
        if want is None:
            ok = row.get('error') in ('ValueError', 'TypeError', 'KeyError')
        else:
            got = row.get('result', {})
            ok = isinstance(got, dict) and got.get('link_bytes') == want['link_bytes']
            for key in ('hop_time_s', 'link_time_s', 'total_time_s'):
                value = got.get(key) if isinstance(got, dict) else None
                ok = ok and isinstance(value, (float, int)) and not isinstance(value, bool) and math.isclose(
                    value, want[key], rel_tol=1e-10, abs_tol=1e-12)
        if not ok:
            failed.append(i)
    return dict(passed=not failed, cases=len(requests), failed_cases=failed)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('project', type=Path)
    args = p.parse_args()
    report = judge(args.project)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)
