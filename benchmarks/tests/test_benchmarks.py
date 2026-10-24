"""Integration checks for the benchmark boundary, never an optimization run."""
import ast
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid

import pytest

BENCH = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bench", BENCH / "bench.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


@pytest.fixture
def work():
    # Ordinary mkdir inherits Windows ACLs; evidence remains in the ignored cache.
    root = BENCH / "cache/validation" / uuid.uuid4().hex
    root.mkdir(parents=True)
    return root


def copy_project(case, work):
    source = BENCH / "projects" / case
    root = work / case
    bench.archive(source, "HEAD", root)
    return root


def evaluate(root, out):
    return subprocess.run([sys.executable, str(root / ".opc/eval/evaluate.py"), "--out", str(out)],
                          text=True, capture_output=True, timeout=180)


@pytest.mark.parametrize("case,metric,value", [
    ("vliw-pack", "bundles", 1234), ("kernel-opt", "cycles", 147734),
    ("riscv-restore", "remaining_cases", 3),
])
def test_valid_subtarget_baseline(case, metric, value, work):
    root = copy_project(case, work)
    result = evaluate(root, work / "out")
    assert result.returncode == 0, result.stderr
    assert bench.read(work / "out/metrics.json")["metrics"][metric] == value


def test_bad_packer_rejected_and_stale_report_removed(work):
    root = copy_project("vliw-pack", work)
    path = root / "perf_takehome.py"
    text = path.read_text()
    text = text.replace("instrs.append({engine: [slot]})", "pass", 1)
    path.write_text(text)
    out = work / "out"
    bench.write(out / "metrics.json", {"metrics": {"correct": 1, "bundles": 0}})
    result = evaluate(root, out)
    assert result.returncode not in (0, 75)
    assert not (out / "metrics.json").exists()


def test_candidate_missing_import_is_not_infrastructure_failure(work):
    root = copy_project("vliw-pack", work)
    path = root / "perf_takehome.py"
    path.write_text("import nonexistent_candidate_dependency_4528\n" + path.read_text())
    result = evaluate(root, work / "out")
    assert result.returncode not in (0, 75)


def restore_rule(root, names):
    relative = "xdsl/transforms/canonicalization_patterns/riscv.py"
    upstream = (BENCH / "cache/xdsl" / relative).read_text()
    path = root / relative
    lines = path.read_text().splitlines(keepends=True)
    original = {n.name: n for n in ast.parse(upstream).body if isinstance(n, ast.ClassDef)}
    changes = []
    for node in ast.parse("".join(lines)).body:
        if isinstance(node, ast.ClassDef) and node.name in names:
            method = next(n for n in node.body if isinstance(n, ast.FunctionDef))
            source = next(n for n in original[node.name].body if isinstance(n, ast.FunctionDef))
            replacement = upstream.splitlines(keepends=True)[source.body[0].lineno - 1:source.end_lineno]
            changes.append((method.body[0].lineno - 1, method.end_lineno, replacement))
    for start, end, replacement in sorted(changes, reverse=True):
        lines[start:end] = replacement
    path.write_text("".join(lines))


def test_riscv_partial_and_complete_recovery(work):
    root = copy_project("riscv-restore", work)
    for names, expected in [("AddImmediateZero", 2), ("AndiZero", 1), ("XoriZero", 0)]:
        restore_rule(root, {names})
        result = evaluate(root, work / "out")
        assert result.returncode == 0, result.stderr
        assert bench.read(work / "out/metrics.json")["metrics"]["remaining_cases"] == expected


def test_riscv_incorrect_semantics_rejected(work):
    root = copy_project("riscv-restore", work)
    restore_rule(root, {"AndiZero"})
    path = root / "xdsl/transforms/canonicalization_patterns/riscv.py"
    path.write_text(path.read_text().replace("rewriter.replace(op, rv32.LiOp(0, rd=rd))",
                                            "rewriter.replace(op, rv32.LiOp(1, rd=rd))"))
    result = evaluate(root, work / "out")
    assert result.returncode not in (0, 75)


def test_ft06_reproducible_and_budget_not_editable(work):
    root = copy_project("ft06-search", work)
    values = []
    for _ in range(2):
        result = evaluate(root, work / "out")
        assert result.returncode == 0, result.stderr
        metrics = bench.read(work / "out/metrics.json")["metrics"]
        assert metrics["correct"] == 1 and metrics["inner_steps"] == 1000
        values.append(metrics["makespan"])
    assert values[0] == values[1] and values[0] > 59
    config = bench.read(root / "configs/search.json")
    config["steps"] = 100000
    bench.write(root / "configs/search.json", config)
    assert evaluate(root, work / "out").returncode not in (0, 75)


def test_collect_preserves_unknown_cost_and_reviewer_split(work, monkeypatch):
    # Synthetic ledger is test data only, outside the real experiment inventory.
    monkeypatch.setattr(bench, "HERE", work)
    exp = work / "experiments/fake"
    bench.write(exp / "manifest.json", {
        "experiment_id": "fake", "case": "test", "profile_name": "fixture", "template_commit": "baseline",
        "framework": {"sha256": "runtime"}})
    bench.write(work / "cases/test/case.json", {"metric": "score"})
    from opc.core.ledger import Ledger
    from opc.core.model import Cost, Measurements
    ledger = Ledger(exp / "project/.opc/local/ledger.sqlite3")
    rid = ledger.create_run(task_id="t-main", revision="r0001", task_digest="task", component="main",
                           base_commit="base", evaluator_digest="eval", toolchain_digest="tool",
                           champion_ref="ref", direction="")
    ledger.set_champion(rid, "base", Measurements(values={"score": 100}), None, "baseline")
    ledger.charge(rid, None, "expert", Cost(tokens=100, wall_seconds=2))
    ledger.charge(rid, None, "reviewer", Cost(tokens=20, wall_seconds=1))
    bench.collect()
    summary = bench.read(exp / "summary.json")["summary"]
    assert summary["tokens"] == 120 and summary["reviewer_tokens"] == 20
    assert summary["usd"] is None and summary["baseline"] == 100
    ledger.db.close()


def test_repeated_experiment_id_cannot_overwrite(work, monkeypatch):
    monkeypatch.setattr(bench, "HERE", work)
    shutil.copytree(BENCH / "profiles", work / "profiles")
    shutil.copytree(BENCH / "cases", work / "cases")
    (work / "experiments/taken").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        bench.new("vliw-pack", "codex-medium", "taken")
    with pytest.raises(ValueError, match="only defined"):
        bench.new("vliw-pack", "scripted", "new")


def test_compact_patterns_cover_frozen_source_without_editable():
    from opc.core.config import matches
    root = BENCH / "projects/riscv-restore"
    editable = bench.read(BENCH / "cases/riscv-restore/case.json")["editable"]
    patterns = bench.frozen_patterns(root, editable)
    assert len(patterns) < 250
    for file in bench.git(root, "ls-files").splitlines():
        if file.startswith(".opc/") or file in ("BENCHMARK.md", "BENCHMARK-PROVENANCE.json"):
            continue
        assert matches(file, patterns) == (file not in editable), file
