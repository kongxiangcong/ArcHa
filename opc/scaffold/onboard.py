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


def onboard(project_root: Path, agent: str) -> dict[str, Any]:
    root = project_root.resolve()
    if not (root / ".opc" / "project.json").exists():
        raise OPCError("run `opc init --apply` first")
    if agent not in ("codex", "dsh"):
        raise OPCError("the onboarding agent must be codex or dsh")
    before = _snapshot(root)
    guide = (HERE / "ONBOARDING.md").read_text(encoding="utf-8")
    prompt = ("You are onboarding this repository to OPC. Follow the guide below. Fill the "
              "TODOs in .opc/components/*.json, .opc/tasks/*/revisions/r0001/task.json, "
              ".opc/eval/evaluate.py and .opc/context/*.md from what the repository actually "
              "contains. Write ONLY under .opc/. List anything you could not determine in "
              ".opc/README.md under 'Open items'.\n\n" + guide)
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
    outside = sorted(p for p in set(before) | set(after)
                     if before.get(p) != after.get(p) and not p.startswith(".opc/"))
    result = {"ok": call.ok and not outside, "call_id": call.call_id, "tokens": call.cost.tokens,
              "error": call.error, "changed_outside_opc": outside, "summary": text[-1500:],
              "next": ["review .opc/ drafts", "opc check", "git add .opc && git commit",
                       "set execution_enabled=true", "opc preflight"]}
    if outside:
        result["error"] = "agent changed files outside .opc/: revert them before continuing"
    return result
