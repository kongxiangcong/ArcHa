"""`opc onboard`: an agent drafts the `.opc/` contracts from the project itself.

The agent may write only under `.opc/`; any other change is reported and the
command fails, so the user's source tree is never silently edited. The drafts
are not trusted: `opc check` and `opc preflight` still decide readiness, and the
user enables execution by hand.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from ..core.model import OPCError
from ..core.workspace import dirty_paths

HERE = Path(__file__).resolve().parent


def _snapshot(root: Path) -> dict[str, str | None]:
    """Content hash of every dirty path, so edits to already-dirty user files count."""
    out: dict[str, str | None] = {}
    for p in dirty_paths(root):
        f = root / p
        out[p] = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
    return out


def _dsh_options() -> dict[str, Any]:
    """Options for the dsh onboarding worker, taken from the documented env vars.

    The onboarding call happens before any task exists, so it has no contract to
    read a binary or DSH_HOME from; the environment is the only source.
    """
    options: dict[str, Any] = {}
    if os.environ.get("OPC_DSH_BIN"):
        options["binary"] = os.environ["OPC_DSH_BIN"]
    if os.environ.get("OPC_DSH_HOME"):
        options["dsh_home"] = os.environ["OPC_DSH_HOME"]
    return options


def _inputs_snapshot(root: Path) -> dict[str, str]:
    """Include clean and ignored inputs too; onboard must not rewrite its sources."""
    paths = [root / ".opc/archa.py"]
    for directory in ("runtime", "research"):
        paths.extend((root / ".opc" / directory).rglob("*"))
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


def onboard(project_root: Path, agent: str, brief: str | Path | None = None) -> dict[str, Any]:
    root = project_root.resolve()
    deployed = (root / ".opc/runtime/opc/cli.py").is_file() and (root / ".opc/archa.py").is_file()
    if not (root / ".opc" / "project.json").exists() and not deployed:
        raise OPCError("run `opc init --apply` first")
    if agent not in ("codex", "dsh"):
        raise OPCError("the onboarding agent must be codex or dsh")
    brief_report = None
    brief_text = ""
    if brief is not None:
        from .brief import load_brief
        brief_report, brief_text = load_brief(root, brief)
        if not brief_report["ok"]:
            raise OPCError("brief is not ready for drafting: " + "; ".join(brief_report["problems"]))
    before = _snapshot(root)
    inputs_before = _inputs_snapshot(root)
    if not (root / ".opc/project.json").exists():
        from . import init
        init(root, "research-project", root.name, "main", "t-main", True)
    guide = (HERE / "ONBOARDING.md").read_text(encoding="utf-8")
    prompt = ("You are onboarding this repository to OPC. Follow the guide below. Fill the "
              "TODOs in .opc/components/*.json, .opc/tasks/*/revisions/r0001/task.json, "
              ".opc/eval/evaluate.py and .opc/context/*.md from what the repository actually "
              "contains. Write ONLY under .opc/. List anything you could not determine in "
              ".opc/README.md under 'Open items'.\n\n" + guide)
    if brief_report is not None:
        prompt += (
            "\n\n## Discussion handoff\n"
            "Draft the contract from the task brief below, following section 7 of the guide. "
            "Keep execution_enabled=false.\n"
            + "Source: " + str(brief_report) + "\n\n" + brief_text
        )
    # Both adapters expose the same _run(role, prompt, tree, log_dir, sandbox, schema)
    # contract; dsh ignores the schema and is asked to write its answer as prose.
    if agent == "dsh":
        from ..adapters.dsh import DshWorker
        worker = DshWorker({"timeout_s": 1800, **_dsh_options()})
    else:
        from ..adapters.codex import CodexWorker
        worker = CodexWorker({"timeout_s": 1800})
    log = root / ".opc" / "local" / "onboard"
    call, text = worker._run("onboard", prompt, root, log, "workspace-write", None)
    after = _snapshot(root)
    inputs_after = _inputs_snapshot(root)
    outside = sorted(p for p in set(before) | set(after)
                     if before.get(p) != after.get(p) and not p.startswith(".opc/"))
    protected = sorted(p for p in set(inputs_before) | set(inputs_after)
                       if inputs_before.get(p) != inputs_after.get(p))
    result = {"ok": call.ok and not outside and not protected, "call_id": call.call_id, "tokens": call.cost.tokens,
              "error": call.error, "changed_outside_opc": outside, "summary": text[-1500:],
              "changed_protected_opc": protected,
              "next": ["review .opc/ drafts and resolve Open items",
                       "when execution preparation is authorized, set execution_enabled=true",
                       "opc check", "git add .opc && git commit", "opc preflight"]}
    if brief_report is not None:
        result["brief_input"] = brief_report
        from ..core.model import write_json, write_text
        write_json(log / "brief-input.json", brief_report)
        write_text(log / "task-brief.md", brief_text)
    if outside:
        result["error"] = "agent changed files outside .opc/: revert them before continuing"
    elif protected:
        result["error"] = "agent changed runtime or research inputs: restore them before continuing"
    return result