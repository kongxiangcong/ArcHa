"""Frozen benchmark adapter. Correct but sub-target is a successful measurement."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def packing():
    from perf_takehome import KernelBuilder
    from tests_frozen import Machine, DebugInfo, SLOT_LIMITS

    # RAW, WAR, WAW, capacity overflow, unsupported engine barriers and empty input.
    cases = [[], [("alu", ("+", 20 + i, 0, 1)) for i in range(25)],
             [("alu", ("+", 2, 0, 1)), ("alu", ("*", 3, 2, 1))],
             [("alu", ("+", 2, 0, 1)), ("alu", ("+", 0, 3, 1))],
             [("alu", ("+", 2, 0, 1)), ("alu", ("*", 2, 0, 1))],
             [("alu", ("+", 2, 0, 1)), ("load", ("const", 0, 7)),
              ("alu", ("+", 3, 0, 2))]]
    rng = random.Random(4271)
    for _ in range(30):
        cases.append([("alu", (rng.choice(["+", "^", "*", "&"]),
                               rng.randrange(16), rng.randrange(16), rng.randrange(16)))
                      for _ in range(40)])
    total = 0
    for slots in cases:
        expected = [{engine: [slot]} for engine, slot in slots]
        actual = KernelBuilder().build(slots, vliw=True)
        assert sum(len(s) for b in actual for s in b.values()) == len(slots)
        for bundle in actual:
            assert all(len(s) <= SLOT_LIMITS[e] for e, s in bundle.items())
        for _ in range(3):
            initial = [rng.randrange(1000) for _ in range(1536)]
            machines = [Machine([0] * 32, code, DebugInfo({})) for code in (expected, actual)]
            for machine in machines:
                machine.cores[0].scratch[:] = initial
                machine.run()
            assert machines[0].cores[0].scratch == machines[1].cores[0].scratch
            assert machines[0].mem == machines[1].mem
        total += len(actual)
    return {"bundles": total, "correct": 1, "cases": len(cases)}


def kernel():
    from perf_takehome import KernelBuilder
    from tests_frozen import Machine, Tree, Input, build_mem_image, reference_kernel2

    cycles = []
    for seed in (17, 41, 73):
        random.seed(seed)
        forest = Tree.generate(10)
        inp = Input.generate(forest, 256, 16)
        mem = build_mem_image(forest, inp)
        kb = KernelBuilder()
        kb.build_kernel(10, len(forest.values), 256, 16)
        machine = Machine(mem, kb.instrs, kb.debug_info(), n_cores=1)
        machine.enable_pause = machine.enable_debug = False
        machine.run()
        for reference in reference_kernel2(mem):
            pass
        start = reference[6]
        assert machine.mem[start:start + 256] == reference[start:start + 256]
        cycles.append(machine.cycle)
    return {"cycles": max(cycles), "correct": 1, "cases": len(cycles)}


def jobshop():
    from job_shop_lib.benchmarking import load_benchmark_instance
    from job_shop_lib.metaheuristics import (
        SimulatedAnnealingSolver, swap_adjacent_operations,
        swap_in_critical_path, swap_random_operations,
    )
    config = json.loads((ROOT / "configs/search.json").read_text())
    assert set(config) == {"neighbor", "initial_temperature", "ending_temperature"}
    assert config["neighbor"] in ("adjacent", "critical", "random")
    assert 0 < config["ending_temperature"] <= config["initial_temperature"] <= 50000
    neighbors = dict(adjacent=swap_adjacent_operations, critical=swap_in_critical_path,
                     random=swap_random_operations)
    scores = []
    for seed in (42, 43, 44):
        instance = load_benchmark_instance("ft06")
        schedule = SimulatedAnnealingSolver(
            initial_temperature=config["initial_temperature"],
            ending_temperature=config["ending_temperature"], steps=1000, updates=0,
            seed=seed, neighbor_generator=neighbors[config["neighbor"]],
        ).solve(instance)
        # Recompute feasibility and makespan from operations, not a solver score.
        seen = {}
        end = 0
        for machine_id, operations in enumerate(schedule.schedule):
            last = 0
            for scheduled in sorted(operations, key=lambda s: s.start_time):
                key = (scheduled.job_id, scheduled.position_in_job)
                assert key not in seen
                op = instance.jobs[key[0]][key[1]]
                assert scheduled.operation is op
                assert scheduled.machine_id == machine_id and machine_id in op.machines
                assert scheduled.start_time >= last and scheduled.start_time >= 0
                last = scheduled.start_time + op.duration
                seen[key] = (scheduled.start_time, last)
                end = max(end, last)
        assert len(seen) == sum(map(len, instance.jobs))
        for j, job in enumerate(instance.jobs):
            for k in range(1, len(job)):
                assert seen[j, k][0] >= seen[j, k - 1][1]
        scores.append(end)
    return {"makespan": max(scores), "mean_makespan": sum(scores) / len(scores),
            "correct": 1, "inner_steps": 1000, "seeds": 3}


def riscv():
    from xdsl.dialects import riscv, rv32
    from xdsl.ir import Block, Region
    from xdsl.pattern_rewriter import PatternRewriteWalker
    from xdsl.transforms.canonicalization_patterns.riscv import (
        AddImmediateZero, AndiZero, XoriZero,
    )

    tree = ast.parse((ROOT / "xdsl/transforms/canonicalization_patterns/riscv.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in ("AddImmediateZero", "AndiZero", "XoriZero"):
            for method in node.body:
                if isinstance(method, ast.FunctionDef):
                    method.body = [ast.Pass()]
    outside = hashlib.sha256(ast.dump(tree).encode()).hexdigest()
    assert outside == (ROOT / ".opc/eval/riscv-outside.sha256").read_text().strip(), "unrelated rules changed"

    remaining = 0
    for cls, rule, expected in [(riscv.AddiOp, AddImmediateZero, riscv.MVOp),
                                (riscv.AndiOp, AndiZero, rv32.LiOp),
                                (riscv.XoriOp, XoriZero, riscv.MVOp)]:
        complete = True
        for reg in (riscv.Registers.A1, riscv.Registers.A2, riscv.Registers.UNALLOCATED_INT):
            for imm in (0, 1, -1, 7):
                block = Block(arg_types=[riscv.Registers.A0])
                op = cls(block.args[0], imm, rd=reg)
                block.add_op(op)
                PatternRewriteWalker(rule()).rewrite_region(Region(block))
                output = block.last_op
                assert output is not None and len(tuple(block.ops)) == 1
                output.verify()
                assert output.results[0].type == reg
                for value in (0, 1, 0x7fffffff, 0xffffffff, 1973):
                    def interpret(operation):
                        if isinstance(operation, rv32.LiOp):
                            return operation.immediate.value.data & 0xffffffff
                        assert operation.operands[0] is block.args[0]
                        if isinstance(operation, riscv.MVOp):
                            return value
                        n = operation.immediate.value.data
                        if isinstance(operation, riscv.AddiOp):
                            return (value + n) & 0xffffffff
                        if isinstance(operation, riscv.AndiOp):
                            return value & n
                        if isinstance(operation, riscv.XoriOp):
                            return (value ^ n) & 0xffffffff
                        raise AssertionError("unsupported replacement")
                    wanted = ((value + imm) if cls is riscv.AddiOp else
                              (value & imm) if cls is riscv.AndiOp else (value ^ imm)) & 0xffffffff
                    assert interpret(output) == wanted
                if imm == 0:
                    complete &= isinstance(output, expected)
                else:
                    assert isinstance(output, cls), "nonzero immediate must remain unchanged"
        remaining += not complete
    return {"remaining_cases": remaining, "correct": 1, "semantic_checks": 180}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / "metrics.json"
    report.unlink(missing_ok=True)  # Never reuse a stale successful result.
    case = json.loads((ROOT / ".opc/eval/case.json").read_text())["case"]
    started = time.perf_counter()
    dependencies = {"ft06-search": ["numpy", "networkx", "simanneal", "pandas"],
                    "riscv-restore": ["immutabledict", "ordered_set", "typing_extensions"]}
    for dependency in dependencies.get(case, []):
        if importlib.util.find_spec(dependency) is None:
            print(f"Missing dependency: {dependency}", file=sys.stderr)
            raise SystemExit(75)
    # An import invented by a candidate is a candidate failure, not missing infrastructure.
    metrics = {"vliw-pack": packing, "kernel-opt": kernel,
               "ft06-search": jobshop, "riscv-restore": riscv}[case]()
    metrics["evaluation_wall_seconds"] = time.perf_counter() - started
    report.write_text(json.dumps({"metrics": metrics}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics))
