#!/usr/bin/env python3
"""Measure baseline-vs-baseline timing dispersion after builds finish."""
import argparse
import json
import math
from pathlib import Path
import statistics
from judge import TASK, PRIVATE, run, sha, EDITABLE, check_scope


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    project = TASK / 'runs/prepared/project'
    check_scope(project)
    frozen = json.loads((TASK / 'runs/prepared/manifest.json').read_text())['files']
    assert all(sha(project / p) == frozen[p] for p in EDITABLE), 'calibration requires the unmodified baseline'
    plain = PRIVATE / 'baseline-timed'
    rows = []
    for pattern in ['stream', 'random', 'samebank']:
        pairs = []
        for rep in range(5):
            values, outputs = {}, []
            for which in (['baseline', 'candidate'] if rep % 2 == 0 else ['candidate', 'baseline']):
                root = plain if which == 'baseline' else project
                binary = plain / 'ramulator2' if which == 'baseline' else project / 'build/ramulator2'
                output = root / 'results' / f'calibrate-{pattern}-{rep}'
                elapsed, stats = run(root, binary, output, pattern, 100000, 54071, 5,
                                     library=plain if which == 'baseline' else None)
                values[which] = elapsed
                values[which+'_rss_kib'] = int((output / 'max-rss-kib.txt').read_text())
                outputs.append(stats)
            assert outputs[0] == outputs[1]
            pairs.append(values)
        ratios = [p['baseline']/p['candidate'] for p in pairs]
        rows.append(dict(case=pattern,pairs=pairs,median_ratio=statistics.median(ratios),
                         min_ratio=min(ratios),max_ratio=max(ratios)))
    result = dict(comparison='unmodified baseline vs itself; no optimization',count=100000,
                  cases=rows,geometric_ratio=math.prod(r['median_ratio'] for r in rows)**(1/3))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))


if __name__ == '__main__':
    main()
