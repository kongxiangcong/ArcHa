"""Usable serial descriptor executor; queue admission and overlap are not implemented.

Python 3.10+, standard library only. The task is specified in TASK.md.
"""
from __future__ import annotations
import argparse
import json


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def validate(case):
    if not isinstance(case, dict):
        raise ValueError("input must be an object")
    cfg, memory, jobs = case.get("config"), case.get("memory"), case.get("descriptors")
    if not isinstance(cfg, dict) or not isinstance(memory, list) or not isinstance(jobs, list):
        raise ValueError("config, memory and descriptors are required")
    for name in ("queue_depth", "bytes_per_cycle"):
        _integer(cfg.get(name), name, 1)
    _integer(cfg.get("setup_cycles"), "setup_cycles")
    for byte in memory:
        if _integer(byte, "memory byte") > 255:
            raise ValueError("memory bytes must be <= 255")
    seen = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("descriptor must be an object")
        ident, kind = job.get("id"), job.get("kind")
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError("id must be a unique nonempty string")
        if kind not in ("dma", "compute"):
            raise ValueError("kind must be dma or compute")
        n = _integer(job.get("nbytes"), "nbytes", 1)
        for name in (("src", "dst") if kind == "dma" else ("src",)):
            start = _integer(job.get(name), name)
            if start + n > len(memory):
                raise ValueError("memory range is out of bounds")
        _integer(job.get("release", 0), "release")
        deps = job.get("depends", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) or d not in seen for d in deps):
            raise ValueError("dependencies must refer to earlier descriptors")
        if kind == "compute":
            _integer(job.get("cycles"), "cycles", 1)
        seen.add(ident)


def simulate(case):
    """Serial baseline: correct functional execution, no DMA/compute overlap."""
    validate(case)
    memory = list(case["memory"])
    cfg = case["config"]
    now, events, checksums = 0, [], {}
    for job in case["descriptors"]:
        now = max(now, job.get("release", 0))
        start = now
        n, src = job["nbytes"], job["src"]
        if job["kind"] == "dma":
            duration = cfg["setup_cycles"] + (n + cfg["bytes_per_cycle"] - 1) // cfg["bytes_per_cycle"]
            memory[job["dst"]:job["dst"] + n] = memory[src:src + n]
        else:
            duration = job["cycles"]
            checksums[job["id"]] = sum(memory[src:src + n])
        now += duration
        events.append({"id": job["id"], "admitted": start, "start": start, "end": now})
    return {"events": events, "memory": memory, "checksums": checksums, "total_cycles": now}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="JSON descriptor input")
    args = parser.parse_args()
    try:
        with open(args.input, encoding="utf-8") as stream:
            result = simulate(json.load(stream))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"invalid input: {exc}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
