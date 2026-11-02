"""External acceptance material for ONE task; no agent or benchmark orchestration.

Synthetic inputs, deterministic seeds; cycle-stepping oracle stays outside workers.
"""
from __future__ import annotations
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys

SEEDS = (1701, 4301)


def base(depth=1):
    return {"config": {"queue_depth": depth, "bytes_per_cycle": 2, "setup_cycles": 1},
            "memory": [1, 2, 3, 4] + [0] * 8,
            "descriptors": [
                {"id": "a", "kind": "dma", "src": 0, "dst": 4, "nbytes": 4},
                {"id": "b", "kind": "dma", "src": 4, "dst": 8, "nbytes": 4},
                {"id": "c", "kind": "compute", "src": 0, "nbytes": 4, "cycles": 2}]}


def oracle(case):
    """Slow cycle-by-cycle executable specification, for valid SMALL cases only."""
    cfg = case["config"]
    memory = list(case["memory"])
    jobs = case["descriptors"]
    pending, events, done, checksums = [], {}, set(), {}
    active_dma = active_compute = None
    cursor = 0
    for now in range(10000):
        # Commit all completions before any starts/issue at this cycle.
        if active_dma is not None and active_dma[1] == now:
            job, _, payload = active_dma
            memory[job["dst"]:job["dst"] + job["nbytes"]] = payload
            done.add(job["id"])
            active_dma = None
        if active_compute is not None and active_compute[1] == now:
            job, _, value = active_compute
            checksums[job["id"]] = value
            done.add(job["id"])
            active_compute = None

        def start_dma(job):
            n = job["nbytes"]
            end = now + cfg["setup_cycles"] + (n + cfg["bytes_per_cycle"] - 1) // cfg["bytes_per_cycle"]
            events[job["id"]].update(start=now, end=end)
            return job, end, memory[job["src"]:job["src"] + n]

        if active_dma is None and pending:
            active_dma = start_dma(pending.pop(0))
        # Ordered, zero-cost issue until the first blocked descriptor.
        while cursor < len(jobs):
            job = jobs[cursor]
            if now < job.get("release", 0) or not set(job.get("depends", [])) <= done:
                break
            if job["kind"] == "dma":
                if len(pending) + int(active_dma is not None) >= cfg["queue_depth"]:
                    break
                events[job["id"]] = {"id": job["id"], "admitted": now}
                if active_dma is None:
                    active_dma = start_dma(job)
                else:
                    pending.append(job)
            else:
                if active_compute is not None:
                    break
                end = now + job["cycles"]
                value = sum(memory[job["src"]:job["src"] + job["nbytes"]])
                events[job["id"]] = {"id": job["id"], "admitted": now, "start": now, "end": end}
                active_compute = job, end, value
            cursor += 1
        if cursor == len(jobs) and not pending and active_dma is None and active_compute is None:
            return {"events": [events[j["id"]] for j in jobs], "memory": memory,
                    "checksums": checksums, "total_cycles": now}
    raise AssertionError("oracle fixture exceeded its small-case time bound")


def corpus():
    rows = []

    def add(name, case, invalid=False):
        rows.append({"name": name, "invalid": invalid, "input": copy.deepcopy(case)})

    add("depth_one", base(1))
    add("depth_two", base(2))
    data = base(2)
    data["descriptors"][2].update(src=8, depends=["b"])
    add("dependency", data)
    data = base(2)
    data["descriptors"][2].update(src=4, cycles=8)
    add("compute_reads_at_start", data)
    data = base(2)
    data["descriptors"][2].update(src=4, release=3)
    add("completion_before_issue", data)
    data = base(2)
    data["descriptors"][0]["release"] = 5
    add("head_of_line_release", data)
    data = base()
    data["descriptors"] = []
    add("empty", data)
    data = base()
    data["memory"] = [1, 2, 3, 4, 5, 6]
    data["config"].update(bytes_per_cycle=1, setup_cycles=0)
    data["descriptors"] = [{"id": "move", "kind": "dma", "src": 0, "dst": 1, "nbytes": 4}]
    add("overlapping_copy", data)
    data = base()
    data["descriptors"] = [{"id": "one", "kind": "dma", "src": 0, "dst": 4, "nbytes": 3}]
    add("ceil_bandwidth", data)
    data = base()
    data["descriptors"] = [{"id": "x", "kind": "compute", "src": 0, "nbytes": 4, "cycles": 3},
                           {"id": "y", "kind": "compute", "src": 0, "nbytes": 4, "cycles": 1}]
    add("compute_busy", data)
    for seed in SEEDS:
        rng = random.Random(seed)
        for index in range(32):
            data = {"config": {"queue_depth": rng.randint(1, 4), "bytes_per_cycle": rng.randint(1, 7),
                               "setup_cycles": rng.randint(0, 3)},
                    "memory": [rng.randrange(256) for _ in range(48)], "descriptors": []}
            for j in range(rng.randint(1, 18)):
                n = rng.randint(1, 12)
                job = {"id": f"j{j}", "kind": rng.choice(["dma", "compute"]), "nbytes": n,
                       "src": rng.randint(0, 48-n), "release": rng.randint(0, 12),
                       "depends": [f"j{rng.randrange(j)}"] if j and rng.random() < .35 else []}
                if job["kind"] == "dma":
                    job["dst"] = rng.randint(0, 48-n)
                else:
                    job["cycles"] = rng.randint(1, 8)
                data["descriptors"].append(job)
            add(f"seed_{seed}_{index:02d}", data)
    mutations = [
        ("zero_depth", lambda d: d["config"].update(queue_depth=0)),
        ("bool_bandwidth", lambda d: d["config"].update(bytes_per_cycle=True)),
        ("negative_setup", lambda d: d["config"].update(setup_cycles=-1)),
        ("zero_length", lambda d: d["descriptors"][0].update(nbytes=0)),
        ("out_of_range", lambda d: d["descriptors"][0].update(dst=11)),
        ("duplicate_id", lambda d: d["descriptors"][1].update(id="a")),
        ("forward_dependency", lambda d: d["descriptors"][0].update(depends=["b"])),
        ("bad_byte", lambda d: d["memory"].__setitem__(0, 256)),
    ]
    for name, change in mutations:
        data = base()
        change(data)
        add(name, data, True)
    return {"provenance": "synthetic; not a hardware trace", "seeds": list(SEEDS), "cases": rows}


def check_function(simulate, rows):
    failures = []
    for row in rows:
        original = copy.deepcopy(row["input"])
        working = copy.deepcopy(original)
        try:
            actual = simulate(working)
        except ValueError as exc:
            if not row["invalid"]:
                failures.append({"name": row["name"], "reason": f"unexpected ValueError: {exc}"})
            if working != original:
                failures.append({"name": row["name"], "reason": "input mutated before rejection"})
            continue
        except Exception as exc:
            failures.append({"name": row["name"], "reason": f"{type(exc).__name__}: {exc}"})
            continue
        if row["invalid"]:
            failures.append({"name": row["name"], "reason": "invalid input was accepted"})
        elif working != original:
            failures.append({"name": row["name"], "reason": "input mutated"})
        else:
            expected = oracle(original)
            # JSON equality also rejects floats or bools where exact integer output is required.
            if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                failures.append({"name": row["name"], "reason": "output differs",
                                 "expected": expected, "actual": actual})
    return {"passed": not failures, "cases": len(rows), "failures": failures}


def load_candidate(path):
    spec = importlib.util.spec_from_file_location("candidate_dma", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("output", type=Path)
    for action in ("evaluate", "_worker"):
        run = sub.add_parser(action)
        run.add_argument("--candidate", required=True, type=Path)
        run.add_argument("--data", required=True, type=Path)
        run.add_argument("--output", type=Path)
        run.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if args.action == "generate":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(corpus(), indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(corpus()['cases'])} synthetic cases to {args.output}")
        return 0
    if args.action == "_worker":
        data = json.loads(args.data.read_text(encoding="utf-8"))
        result = check_function(load_candidate(args.candidate.resolve()).simulate, data["cases"])
        # Exercise the supported CLI on one valid and one invalid input, outside the candidate tree.
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            for row in (data["cases"][0], next(r for r in data["cases"] if r["invalid"])):
                path = Path(directory) / "input.json"
                path.write_text(json.dumps(row["input"]), encoding="utf-8")
                proc = subprocess.run([sys.executable, str(args.candidate.resolve()), str(path)],
                                      capture_output=True, text=True, timeout=10)
                if row["invalid"]:
                    ok = proc.returncode == 2
                else:
                    try:
                        ok = proc.returncode == 0 and json.dumps(json.loads(proc.stdout), sort_keys=True) == json.dumps(oracle(row["input"]), sort_keys=True)
                    except ValueError:
                        ok = False
                if not ok:
                    result["failures"].append({"name": "cli_" + row["name"], "reason": "CLI contract failed"})
        result["passed"] = not result["failures"]
        print(json.dumps(result, sort_keys=True))
        return 0 if result["passed"] else 1
    command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--candidate",
               str(args.candidate.resolve()), "--data", str(args.data.resolve())]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
        result = json.loads(proc.stdout)
        if proc.returncode not in (0, 1):
            raise ValueError(proc.stderr[-1000:])
    except (subprocess.TimeoutExpired, ValueError) as exc:
        result = {"passed": False, "error": str(exc), "failures": []}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "failures": len(result["failures"]),
                      "error": result.get("error")}, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
