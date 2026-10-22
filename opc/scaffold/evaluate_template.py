#!/usr/bin/env python3
"""OPC evaluator: run the project's existing flow on this tree and write metrics.json.

Runs with cwd = the candidate tree. Exit codes:
    0 passed, 75 infrastructure failure, 77 skipped, anything else = candidate failure.
Replace every TODO with the project's real commands and metric names.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

EX_TEMPFAIL, EX_SKIP = 75, 77


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # TODO: tools the flow needs; a missing tool is the host's fault, not the candidate's
    for tool in ("python3",):
        if shutil.which(tool) is None:
            print("missing tool %s" % tool, file=sys.stderr)
            return EX_TEMPFAIL

    # TODO: the command that already works on the baseline
    r = subprocess.run([sys.executable, "-c", "print('TODO: run the flow')"],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        return 1

    # TODO: check correctness against the reference and parse the real metrics
    metrics = {"correct": 1, "TODO_metric": 0.0}
    (out / "metrics.json").write_text(json.dumps({"metrics": metrics}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
