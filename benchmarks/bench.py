"""Prepare immutable task projects and isolated, reproducible ArcHa experiments."""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import platform
from pathlib import Path
import re
import runpy
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args, cwd=None):
    return subprocess.check_output([str(x) for x in args], cwd=cwd).decode("utf-8").strip()


def git(root, *args):
    return command(["git", "-C", root, *args])


def archive(source, ref, dest):
    raw = subprocess.check_output(["git", "-C", str(source), "archive", "--format=zip", ref])
    dest.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
        for info in zipped.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise ValueError("unsafe archive path")
        zipped.extractall(dest)


def commit(root, message):
    git(root, "add", "--all")
    git(root, "-c", "user.name=ArcHa Benchmark", "-c", "user.email=benchmark@localhost",
        "-c", "commit.gpgsign=false", "commit", "-qm", message)


def init_git(root):
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")


def runtime(root):
    installer = runpy.run_path(str(REPO / "skills/archa-map/scripts/initialize.py"))
    hashes = {}
    for name in installer["RUNTIME_FILES"]:
        src = REPO / name
        dest = root / ".opc/runtime" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        hashes[name] = digest(src)
    (root / ".opc/archa.py").write_text(installer["LAUNCHER"], encoding="utf-8")
    return {"head": git(REPO, "rev-parse", "HEAD"), "files": hashes,
            "sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
            "working_tree_status": git(REPO, "status", "--short", "--", "opc", "skills/archa-map/scripts/initialize.py")}


def frozen_patterns(root, editable):
    """Cover the same source tree with sibling subtrees, not thousands of literals."""
    result = []
    def visit(directory):
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root).as_posix()
            if relative in (".git", ".opc", "BENCHMARK.md", "BENCHMARK-PROVENANCE.json") or relative in editable:
                continue
            if path.is_dir():
                if any(e.startswith(relative + "/") for e in editable):
                    visit(path)
                else:
                    result.append(relative + "/**")
            else:
                result.append(relative)
    visit(root)
    return result


def prepare(case_id):
    from opc.scaffold import init, task_template, component_template
    spec = read(HERE / "cases" / case_id / "case.json")
    source = read(HERE / "sources.lock.json")[spec["source"]]
    cache = HERE / "cache" / spec["source"]
    root = HERE / "projects" / case_id
    if root.exists():
        raise ValueError(f"refusing to overwrite {root}")
    if not cache.exists():
        command(["git", "clone", "--no-checkout", "--filter=blob:none", source["url"], cache])
    git(cache, "cat-file", "-e", source["commit"] + "^{commit}")
    archive(cache, source["commit"], root)
    if spec["source"] == "performance":
        shutil.copyfile(root / "tests/frozen_problem.py", root / "tests_frozen.py")
    if case_id == "riscv-restore":
        path = root / spec["editable"][0]
        body = path.read_text(encoding="utf-8")
        lines = body.splitlines(keepends=True)
        edits = []
        for node in ast.parse(body).body:
            if isinstance(node, ast.ClassDef) and node.name in ("AddImmediateZero", "AndiZero", "XoriZero"):
                method = next(n for n in node.body if isinstance(n, ast.FunctionDef))
                edits.append((method.body[0].lineno - 1, method.end_lineno))
        assert len(edits) == 3
        for start, end in sorted(edits, reverse=True):
            lines[start:end] = ["        pass  # Deliberately disabled benchmark baseline.\n"]
        path.write_text("".join(lines), encoding="utf-8")
    if case_id == "ft06-search":
        write(root / "configs/search.json", {"neighbor": "adjacent", "initial_temperature": 25000,
                                             "ending_temperature": 2.5})
    init(root, case_id, spec["title"], "main", "t-main", True)
    shutil.copyfile(HERE / "adapters/evaluate.py", root / ".opc/eval/evaluate.py")
    write(root / ".opc/eval/case.json", {"case": case_id})
    if case_id == "riscv-restore":
        tree = ast.parse((root / spec["editable"][0]).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in ("AddImmediateZero", "AndiZero", "XoriZero"):
                for method in node.body:
                    if isinstance(method, ast.FunctionDef):
                        method.body = [ast.Pass()]
        (root / ".opc/eval/riscv-outside.sha256").write_text(hashlib.sha256(ast.dump(tree).encode()).hexdigest() + "\n")
    framework = runtime(root)
    component = component_template("main")
    # All source inputs except the editable file(s) and runtime are frozen evaluator inputs.
    inputs = frozen_patterns(root, spec["editable"])
    component.update(description=spec["title"], editable=spec["editable"],
                     frozen=spec["frozen"], evaluator_files=[".opc/eval/**", *inputs],
                     context_files=["BENCHMARK.md", ".opc/research/tasks/R01/task-brief.md"],
                     toolchain=[["{python}", "--version"], ["{python}", "-m", "pip", "freeze"]])
    component["gates"][0]["timeout_s"] = 300
    write(root / ".opc/components/main.json", component)
    task = task_template("t-main", "main")
    task.update(goal=spec["title"], direction=spec["direction"])
    task["requirements"] = [{"id": "REQ-001", "text": "冻结语义和合法性检查通过",
                             "verification": "automated", "check": {"metric": "correct", "op": "==", "value": 1}}]
    task["acceptance"]["objective"].update(metric=spec["metric"], min_rel_gain=0.0)
    task["acceptance"]["target"] = {"metric": spec["metric"], "op": "<=", "value": spec["target"]}
    write(root / ".opc/tasks/t-main/revisions/r0001/task.json", task)
    research = root / ".opc/research"
    (research / "tasks/R01").mkdir(parents=True)
    (research / "research-map.md").write_text(
        f"# {spec['title']}\n\nR01 active: {spec['direction']}\n\n任务定义来自 benchmarks/cases/{case_id}。本项目只承载一个独立基线。\n", encoding="utf-8")
    brief = f"""# {spec['title']}

## Source
Map: .opc/research/research-map.md
Status: ready-for-onboard

## Question and use
检验 ArcHa 在冻结评价下提出、实施、接纳和停止的能力。

## Goal
Goal: {spec['title']}
Done when: correct == 1 且 {spec['metric']} <= {spec['target']}
Direction: {spec['direction']}

## Evidence
固定来源 {source['url']} @ {source['commit']}。
真实评价器 .opc/eval/evaluate.py；基线需独立实测，准备项目不代表自动优化已通过。

## Scope and deliverables
- D1: 仅在 {', '.join(spec['editable'])} 内产生候选改进。
- R1: 保持冻结语义与合法性 | verification=automated
- R2: 达到上述目标 | verification=automated
Objective: {spec['metric']} minimize

## Open decisions
预算与模型在创建实验时由 profile 固定；目标是本测试集的工程阈值，不代表研究结论或上游排名。
"""
    (research / "tasks/R01/task-brief.md").write_text(brief, encoding="utf-8")
    (root / "BENCHMARK.md").write_text(brief + "\n不得修改评分器、种子或机器规格；不得读取旧实验冠军、源码缓存或上游答案。\n", encoding="utf-8")
    for name, content in {"PROJECT": spec["title"], "REQUIREMENTS": task["goal"],
                          "DECISIONS": spec["direction"]}.items():
        (root / f".opc/context/{name}.md").write_text(content + "\n", encoding="utf-8")
    write(root / "BENCHMARK-PROVENANCE.json", {"case": case_id, "source": source,
          "case_definition": spec, "adapter_sha256": digest(HERE / "adapters/evaluate.py"),
          "framework": framework})
    with (root / ".gitignore").open("a", encoding="utf-8") as f:
        f.write("\n__pycache__/\n*.pyc\n.opc/local/\n")
    init_git(root)
    commit(root, "benchmark: frozen task baseline (execution disabled)")
    print(root)


def new(case_id, profile_name, experiment_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", experiment_id):
        raise ValueError("experiment id must be lowercase letters/digits/hyphens, <=64 chars")
    template = HERE / "projects" / case_id
    profile = read(HERE / "profiles" / (profile_name + ".json"))
    spec = read(HERE / "cases" / case_id / "case.json")
    if profile["kind"] == "scripted" and case_id != "ft06-search":
        raise ValueError("scripted profile is only defined for FT06 parameter search")
    exp = HERE / "experiments" / experiment_id
    if exp.exists():
        raise FileExistsError(exp)
    if read(template / "BENCHMARK-PROVENANCE.json")["case_definition"] != spec:
        raise ValueError("case definition changed since preparation: prepare a new baseline first")
    exp.mkdir(parents=True, exist_ok=False)
    root = exp / "project"
    baseline = git(template, "rev-parse", "HEAD")
    archive(template, baseline, root)
    framework = runtime(root)
    project = read(root / ".opc/project.json")
    project["execution_enabled"] = True
    write(root / ".opc/project.json", project)
    path = root / ".opc/tasks/t-main/revisions/r0001/task.json"
    task = read(path)
    task["budget"] = profile["budget"]
    if profile["kind"] == "scripted":
        worker = {"kind": "scripted", "strategy": "builtin:param_search",
                  "options": {"file": "configs/search.json", "space": spec["search_space"]}}
        task["workers"] = {"expert": worker, "designer": worker}
    write(path, task)
    write(root / ".opc/local/workers.json", profile["workers"])
    init_git(root)
    commit(root, "benchmark: isolated experiment baseline")
    manifest = {"experiment_id": experiment_id, "case": case_id, "case_definition": spec, "profile_name": profile_name,
                "profile": profile, "template_commit": baseline, "base_commit": git(root, "rev-parse", "HEAD"),
                "framework": framework, "source": read(root / "BENCHMARK-PROVENANCE.json")["source"],
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "host": platform.platform(), "python": sys.version, "executable": sys.executable,
                "dependencies": command([sys.executable, "-m", "pip", "freeze"]),
                "workers_sha256": digest(root / ".opc/local/workers.json"),
                "task_sha256": digest(path), "adapter_sha256": digest(root / ".opc/eval/evaluate.py")}
    write(exp / "manifest.json", manifest)
    print(exp)


def execute(experiment_id, phase):
    exp = HERE / "experiments" / experiment_id
    manifest = read(exp / "manifest.json")
    root = exp / "project"
    if digest(root / ".opc/local/workers.json") != manifest["workers_sha256"]:
        raise ValueError("worker config changed: create a new experiment for a new configuration")
    if digest(root / ".opc/tasks/t-main/revisions/r0001/task.json") != manifest["task_sha256"]:
        raise ValueError("task configuration changed: create a new experiment")
    for name, expected in manifest["framework"]["files"].items():
        if digest(root / ".opc/runtime" / name) != expected:
            raise ValueError(f"framework snapshot changed: {name}")
    if command([sys.executable, "-m", "pip", "freeze"]) != manifest["dependencies"]:
        raise ValueError("dependency environment changed: create a new experiment")
    if str(Path(sys.executable).resolve()) != str(Path(manifest["executable"]).resolve()):
        raise ValueError("use the Python interpreter recorded in manifest.json")
    argv = [sys.executable, str(root / ".opc/archa.py"), phase, "-p", str(root), "--task", "t-main"]
    if phase == "promote":
        argv += ["--confirm", "3", "--review", "codex"]
    logs = exp / "logs"
    logs.mkdir(exist_ok=True)
    label = phase + "-" + uuid.uuid4().hex[:8]
    start = time.perf_counter()
    with (logs / (label + ".stdout.txt")).open("w", encoding="utf-8") as out, \
            (logs / (label + ".stderr.txt")).open("w", encoding="utf-8") as err:
        result = subprocess.run(argv, cwd=root, stdout=out, stderr=err)
    write(logs / (label + ".json"), {"phase": phase, "argv": argv, "returncode": result.returncode,
                                    "wall_seconds": time.perf_counter() - start})
    print((logs / (label + ".stdout.txt")).read_text(encoding="utf-8"))
    return result.returncode


def collect():
    rows = []
    for path in sorted((HERE / "experiments").glob("*/manifest.json")):
        manifest = read(path)
        exp = path.parent
        ledger = exp / "project/.opc/local/ledger.sqlite3"
        row = {k: manifest[k] for k in ("experiment_id", "case", "profile_name", "template_commit")}
        row.update(framework_sha256=manifest["framework"]["sha256"], state="not_run",
                   tokens=None, usd=None, attempts=None, baseline=None, champion=None)
        profile = manifest.get("profile", {})
        row.update({"budget_" + k: v for k, v in profile.get("budget", {}).items()})
        for role, settings in profile.get("workers", {}).items():
            row.update({role + "_" + k: v for k, v in settings.items()})
        commands = [read(p) for p in (exp / "logs").glob("*.json")]
        row["command_wall_seconds"] = sum(c["wall_seconds"] for c in commands)
        row["command_failures"] = sum(c["returncode"] != 0 for c in commands)
        for phase in ("preflight", "run", "promote"):
            row[phase + "_wall_seconds"] = sum(c["wall_seconds"] for c in commands if c["phase"] == phase)
        details = {"manifest": manifest, "commands": commands, "runs": []}
        definition = manifest.get("case_definition") or read(HERE / "cases" / manifest["case"] / "case.json")
        for receipt in sorted((exp / "logs").glob("*.json"), key=lambda p: p.stat().st_mtime):
            command_record = read(receipt)
            if command_record["phase"] == "preflight" and command_record["returncode"] == 0:
                preflight = read(receipt.with_suffix(".stdout.txt"))
                if preflight.get("ok"):
                    row["baseline"] = preflight["baseline_metrics"][definition["metric"]]
                    row["state"] = "preflight_passed"
                    row["evaluator_digest"] = preflight["evaluator_digest"]
        if ledger.exists():
            with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                for run in db.execute("SELECT * FROM runs ORDER BY created_at, rowid"):
                    run = dict(run)
                    rid = run["run_id"]
                    charges = [dict(r) for r in db.execute("SELECT * FROM charges WHERE run_id=?", (rid,))]
                    attempts = [dict(r) for r in db.execute("SELECT * FROM attempts WHERE run_id=? ORDER BY attempt_no", (rid,))]
                    champions = [dict(r) for r in db.execute("SELECT * FROM champions WHERE run_id=? ORDER BY seq", (rid,))]
                    details["runs"].append(dict(run=run, charges=charges, attempts=attempts, champions=champions))
                if len(details["runs"]) > 1:
                    raise ValueError(f"{exp.name}: multiple runs; don't hide restarts in comparison")
                if details["runs"]:
                    r = details["runs"][0]
                    row.update({k: r["run"][k] for k in ("state", "stop_reason", "run_id", "evaluator_digest", "toolchain_digest")})
                    row["attempts"] = len(r["attempts"])
                    row["accepted"] = sum(a["outcome"] == "improvement" for a in r["attempts"])
                    row["infra_attempts"] = sum(a["outcome"] == "infra" for a in r["attempts"])
                    row["tokens"] = sum(c["tokens"] for c in r["charges"])
                    row["usd"] = sum(c["usd"] or 0 for c in r["charges"]) if r["charges"] and all(c["usd_known"] for c in r["charges"]) else None
                    for role in sorted({c["role"] for c in r["charges"]}):
                        row[role + "_tokens"] = sum(c["tokens"] for c in r["charges"] if c["role"] == role)
                        row[role + "_charged_seconds"] = sum(c["wall_seconds"] for c in r["charges"] if c["role"] == role)
                    metric = definition["metric"]
                    if r["champions"]:
                        for key, c in (("baseline", r["champions"][0]), ("champion", r["champions"][-1])):
                            row[key] = json.loads(c["metrics"])["values"][metric]
                        row["improvement_fraction"] = ((row["baseline"] - row["champion"]) / row["baseline"]
                                                       if row["baseline"] else None)
        write(exp / "summary.json", {"summary": row, **details})
        rows.append(row)
    target = HERE / "experiments/comparison.csv"
    fields = sorted({k for r in rows for k in r})
    with target.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    cases = sorted(p.name for p in (HERE / "cases").iterdir() if p.is_dir())
    p = sub.add_parser("prepare")
    p.add_argument("case", choices=["all", *cases])
    p = sub.add_parser("new")
    p.add_argument("case", choices=cases)
    p.add_argument("--profile", choices=[p.stem for p in (HERE / "profiles").glob("*.json")], required=True)
    p.add_argument("--id", required=True)
    p = sub.add_parser("exec")
    p.add_argument("id")
    p.add_argument("phase", choices=["check", "preflight", "run", "report", "promote"])
    sub.add_parser("collect")
    args = parser.parse_args()
    if args.cmd == "prepare":
        for case in cases if args.case == "all" else [args.case]:
            prepare(case)
    elif args.cmd == "new":
        new(args.case, args.profile, args.id)
    elif args.cmd == "exec":
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.id):
            parser.error("invalid experiment id")
        return execute(args.id, args.phase)
    else:
        collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
