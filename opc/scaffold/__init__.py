"""`opc init`: the `.opc/` skeleton with component/task/evaluator templates.

Never writes outside `.opc/`, never overwrites.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.config import ID
from ..core.model import OPCError
from ..core.platform import is_link, portable_path

HERE = Path(__file__).resolve().parent


def _context(name: str, project_id: str) -> dict[str, str]:
    return {
        "context/PROJECT.md": (
            "# %s\n\nProject ID: `%s`\n\n## Goal and users\n\nTODO\n\n"
            "## Existing assets and constraints\n\nTODO\n\n## Out of scope\n\nTODO\n"
            % (name, project_id)),
        "context/REQUIREMENTS.md": (
            "# Requirements\n\n| ID | Observable requirement | Source | Acceptance evidence |\n"
            "| --- | --- | --- | --- |\n| REQ-001 | TODO | TODO | TODO |\n"),
        "context/DECISIONS.md": (
            "# Decisions\n\n## Locked\n\nTODO\n\n## Agent discretion\n\nTODO\n\n"
            "## Deferred\n\nTODO\n"),
    }


def component_template(component_id: str) -> dict[str, Any]:
    return {
        "component_id": component_id,
        "description": "TODO: what this component does and what is being optimized",
        "editable": ["TODO/path/to/editable/file"],
        "frozen": ["tests/**"],
        "evaluator_files": [".opc/eval/**", "tests/**"],
        "toolchain": [["{python}", "--version"]],
        "gates": [
            {"id": "evaluate", "argv": ["{python}", ".opc/eval/evaluate.py", "--out", "{out}"],
             "metrics": "{out}/metrics.json", "timeout_s": 3600, "repeat": True}
        ],
        "context_files": ["README.md"],
        "focus_areas": [],
    }


def task_template(task_id: str, component_id: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "revision": "r0001",
        "component": component_id,
        "goal": "TODO: one sentence goal",
        "direction": "",
        "requirements": [
            {"id": "REQ-001", "text": "TODO: correctness requirement", "verification": "automated"}
        ],
        "acceptance": {
            "objective": {"metric": "TODO_metric", "direction": "minimize", "min_rel_gain": 0.01},
            "constraints": [{"metric": "correct", "op": "==", "value": 1}],
            "repeats": 1,
            "noise_k": 2.0,
        },
        "budget": {"max_attempts": 20, "max_wall_seconds": 7200, "max_tokens": 2000000,
                   "max_stagnation": 6, "max_consecutive_infra": 3},
        "workers": {"expert": {"kind": "codex", "timeout_s": 900},
                    "designer": {"kind": "codex", "timeout_s": 1800}},
        "base_ref": "HEAD",
    }


def init(project_root: Path, project_id: str, name: str, component_id: str, task_id: str,
         apply: bool) -> dict[str, Any]:
    for v in (project_id, component_id, task_id):
        if not ID.fullmatch(v) or not portable_path(v):
            raise OPCError("%r is not a portable id (lowercase, digits, '-')" % v)
    if not name.strip():
        raise OPCError("display name must not be empty")
    root = project_root.resolve()
    if not root.is_dir():
        raise OPCError("project root %s is not a directory" % root)
    controls = [e for e in root.iterdir() if e.name.casefold() == ".opc"]
    if controls:
        control = controls[0]
        # The research initializer deploys a runtime before any contract exists.
        # Only that layout may be extended; never overwrite an existing scaffold.
        if (control.name != ".opc" or is_link(control) or not control.is_dir()
                or not (control / "runtime/opc/cli.py").is_file()
                or not (control / "archa.py").is_file()
                or any(p.name not in {"runtime", "archa.py", "research", "local"} or is_link(p)
                       for p in control.iterdir())):
            raise OPCError(".opc already exists in %s; refusing to overwrite" % root)
        local = control / "local"
        if local.exists() and (not local.is_dir() or any(
                p.name != "workers.json" or is_link(p) or not p.is_file() for p in local.iterdir())):
            raise OPCError(".opc/local must contain only workers.json before initialization")
    project = {"project_id": project_id, "display_name": name, "components": [component_id],
               "execution_enabled": False}
    files: dict[str, str] = {
        "project.json": json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        ".gitignore": "# ledger, artifacts, machine bindings and generated views\n/local/\n",
        **_context(name, project_id),
    }
    files["ONBOARDING.md"] = (HERE / "ONBOARDING.md").read_text(encoding="utf-8")
    if not (root / ".opc/local/workers.json").exists():
        files["local/workers.json"] = (HERE / "workers.json").read_text(encoding="utf-8")
    files["components/%s.json" % component_id] = json.dumps(
        component_template(component_id), ensure_ascii=False, indent=2) + "\n"
    files["tasks/%s/revisions/r0001/task.json" % task_id] = json.dumps(
        task_template(task_id, component_id), ensure_ascii=False, indent=2) + "\n"
    files["eval/evaluate.py"] = (HERE / "evaluate_template.py").read_text(encoding="utf-8")
    result = {"project_root": str(root), "applied": apply, "files": sorted(files),
              "next": ["fill TODOs (see .opc/ONBOARDING.md)", "opc check",
                       "git add .opc && git commit", "set execution_enabled=true",
                       "opc preflight", "opc run"]}
    if not apply:
        return result
    for rel, content in files.items():
        path = root / ".opc" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as f:
            f.write(content)
    (root / ".opc" / "eval" / "evaluate.py").chmod(0o755)
    return result

