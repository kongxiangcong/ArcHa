#!/usr/bin/env python3
"""Check this judge's fixtures without filling the candidate's missing model."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from judge import BENCH, judge


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root = args.output.resolve()
    project = root / 'project'
    project.mkdir(parents=True, exist_ok=False)
    task = BENCH / 'deepstack-development'
    for source in (task / 'starter').iterdir():
        if source.is_file():
            shutil.copy2(source, project / source.name)
    shutil.copy2(task / 'examiner/reference.py', project / 'model.py')
    positive = judge(project)
    public = subprocess.run([sys.executable, str(BENCH / 'tools/isolate.py'), str(project),
                             '--', 'python', 'test_public.py'], capture_output=True, text=True)
    (root / 'public.log').write_text(public.stdout + public.stderr)
    (project / 'model.py').write_text('def estimate(config, traffic):\n return dict(link_bytes=[],hop_time_s=0,link_time_s=0,total_time_s=0)\n')
    negative = judge(project)
    result = dict(reference=positive, public_passed=public.returncode == 0,
                  incorrect_implementation_rejected=not negative['passed'],
                  negative_failed_cases=len(negative.get('failed_cases', [])))
    (root / 'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    assert positive['passed'] and public.returncode == 0 and not negative['passed']


if __name__ == '__main__':
    main()
