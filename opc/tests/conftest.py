"""A toy domain unrelated to hardware: one parameter file, one loss function.

If the core works here and on the PIM example without a code change, the core
does not depend on either domain.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ARCHA = Path(__file__).resolve().parents[2]
if str(ARCHA) not in sys.path:
    sys.path.insert(0, str(ARCHA))

EVALUATE = """
import json, sys
from pathlib import Path
out = Path(sys.argv[sys.argv.index("--out") + 1]); out.mkdir(parents=True, exist_ok=True)
x = json.loads(Path("params.json").read_text())["x"]
(out / "metrics.json").write_text(json.dumps({"metrics": {"loss": (x - 7) ** 2 + 1, "correct": 1}}))
"""

STRATEGY = """
import json
from pathlib import Path
class Step:
    def __init__(self, options): self.options = options
    def propose(self, ctx, tree):
        x = json.loads((tree / "params.json").read_text())["x"]
        tried = {json.dumps(t, sort_keys=True) for t in ctx.get("tried_params") or []}
        for nx in (x + 1, x - 1):
            if json.dumps({"x": nx}, sort_keys=True) not in tried:
                return {"title": "x=%d" % nx, "hypothesis": "closer to optimum",
                        "files": ["params.json"], "changes": "set x", "expected": "",
                        "falsifier": "", "params": {"x": nx}}
        return None
    def implement(self, plan, tree):
        (tree / "params.json").write_text(json.dumps(plan["params"]))
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def component(**over) -> dict:
    d = {
        "component_id": "toy",
        "editable": ["params.json"],
        "evaluator_files": [".opc/eval/**", ".opc/strategy.py"],
        "toolchain": [["{python}", "--version"]],
        "gates": [{"id": "evaluate", "argv": ["{python}", ".opc/eval/evaluate.py", "--out",
                                             "{out}"], "metrics": "{out}/metrics.json",
                   "timeout_s": 60}],
    }
    d.update(over)
    return d


def task(**over) -> dict:
    d = {
        "task_id": "t-toy", "revision": "r0001", "component": "toy", "goal": "minimize loss",
        "requirements": [{"id": "REQ-001", "text": "loss <= 1", "verification": "automated",
                          "check": {"metric": "loss", "op": "<=", "value": 1}}],
        "acceptance": {"objective": {"metric": "loss", "direction": "minimize",
                                     "min_rel_gain": 0.0},
                       "constraints": [{"metric": "correct", "op": "==", "value": 1}],
                       "target": {"metric": "loss", "op": "<=", "value": 1}},
        "budget": {"max_attempts": 20, "max_wall_seconds": 600, "max_stagnation": 5,
                   "max_consecutive_infra": 2},
        "workers": {"expert": {"kind": "scripted", "strategy": ".opc/strategy.py:Step"}},
    }
    for k, v in over.items():
        d[k] = v
    return d


@pytest.fixture
def make_project(tmp_path):
    def make(evaluate: str = EVALUATE, strategy: str = STRATEGY, comp: dict | None = None,
             tsk: dict | None = None, x: int = 3, extra: dict[str, str] | None = None) -> Path:
        root = tmp_path / "proj"
        root.mkdir()
        write(root / "params.json", json.dumps({"x": x}))
        write(root / ".gitignore", "build/\n__pycache__/\n")
        write(root / ".opc" / "project.json", json.dumps(
            {"project_id": "p-toy", "components": ["toy"], "execution_enabled": True}))
        write(root / ".opc" / ".gitignore", "/local/\n")
        write(root / ".opc" / "eval" / "evaluate.py", evaluate)
        write(root / ".opc" / "strategy.py", strategy)
        write(root / ".opc" / "components" / "toy.json", json.dumps(comp or component()))
        t = tsk or task()
        write(root / ".opc" / "tasks" / t["task_id"] / "revisions" / t["revision"] / "task.json",
              json.dumps(t))
        for rel, text in (extra or {}).items():
            write(root / rel, text)
        git(root, "init", "-q")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "base")
        return root
    return make


@pytest.fixture
def engine_for():
    from opc.core.engine import Engine

    def make(root: Path, task_id: str = "t-toy"):
        return Engine(root, task_id, log=lambda s: None)
    return make
