"""`opc onboard`: metered scoped preparation and independent read-only review.

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
from ..core.worker_config import CONFIG_PATH, load_worker_config, worker_options
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
    paths = [root / ".opc/archa.py", root / CONFIG_PATH]
    for directory in ("runtime", "research"):
        paths.extend((root / ".opc" / directory).rglob("*"))
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


def _draft(project_root: Path, agent: str, brief: str | Path | None = None) -> dict[str, Any]:
    root = project_root.resolve()
    config = load_worker_config(root)
    deployed = (root / ".opc/runtime/opc/cli.py").is_file() and (root / ".opc/archa.py").is_file()
    if not (root / ".opc" / "project.json").exists() and not deployed:
        raise OPCError("run `opc init --apply` first")
    if agent not in ("codex", "dsh"):
        raise OPCError("the onboarding agent must be codex or dsh")
    brief_report = None
    brief_text = ""
    brief_bytes = b""
    if brief is not None:
        from .brief import load_brief
        brief_report, brief_text = load_brief(root, brief)
        brief_bytes = (root / brief_report["brief"]).read_bytes()
        if not brief_report["ok"]:
            raise OPCError("brief is not ready for drafting: " + "; ".join(brief_report["problems"]))
    before = _snapshot(root)
    if not (root / ".opc/project.json").exists():
        from . import init
        init(root, "research-project", root.name, "main", "t-main", True)
        config = load_worker_config(root)
    inputs_before = _inputs_snapshot(root)
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
        worker = DshWorker(worker_options(config, "onboard", {"timeout_s": 1800, **_dsh_options()}))
    else:
        from ..adapters.codex import CodexWorker
        worker = CodexWorker(worker_options(config, "onboard", {"timeout_s": 1800}))
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
        from ..core.model import write_json
        write_json(log / "brief-input.json", brief_report)
        (log / "task-brief.md").write_bytes(brief_bytes)
    if outside:
        result["error"] = "agent changed files outside .opc/: revert them before continuing"
    elif protected:
        result["error"] = ("agent changed runtime, research or worker configuration inputs: "
                           "restore them before continuing")
    return result


def onboard(project_root: Path, agent: str, brief: str | Path | None = None, *,
            prepare: bool = True, task_id: str = "t-main", max_tokens: int | None = None,
            max_wall_seconds: float | None = None, prior_tokens: int | None = None, prior_wall_seconds: float | None = None) -> dict[str, Any]:
    """Develop readiness within scope; never dispatch a formal experiment here.

    prior_tokens is cumulative host/nested usage outside the worker receipts,
    including cached input. Unknown accounting stops dispatch, rather than guessing.
    """
    from ..core.ledger import Ledger
    from ..core.model import Cost, write_json
    from ..core.workspace import git
    import json
    import time
    root = project_root.resolve()
    if agent not in ("codex", "dsh"):
        raise OPCError("the onboarding agent must be codex or dsh")
    if any(value is None for value in (max_tokens, max_wall_seconds, prior_tokens, prior_wall_seconds)):
        return {"ok": False, "preparation": "accounting_unknown", "responsibility": "accounting owner",
                "error": "authorized budget and cumulative host/nested tokens and wall time required; no dispatch"}
    if not (root / ".opc/project.json").exists():
        if brief:
            load_brief_text(root, brief)
        from . import init
        init(root, "research-project", root.name, "main", task_id, True)
    ledger = Ledger(root / ".opc/local/ledger.sqlite3")
    with ledger.writer():
        rows = [r for r in ledger.runs() if r["task_id"] == task_id and r["revision"] == "preparation"]
        rid = rows[-1]["run_id"] if rows else ledger.create_run(
            task_id=task_id, revision="preparation", task_digest="preparation", component="preparation",
            base_commit=str(git("rev-parse", "--verify", "HEAD", cwd=root, check=False)).strip(), evaluator_digest="", toolchain_digest="",
            champion_ref="", direction="authorized preparation only")
        def finish(state, reason, **fields):
            owner = "external prerequisite owner" if state == "external_blocked" else "agent"
            if state in ("accounting_unknown", "budget_exhausted"):
                owner = "accounting/budget owner"
            next_step = ("commit reviewed files, check/preflight; run only if authorized" if state == "ready"
                         else "resolve observed external prerequisite" if state == "external_blocked"
                         else "continue scoped preparation" if state == "pending" else "reconcile usage/budget before dispatch")
            ledger.event(rid, "preparation", None, state=state, reason=reason,
                         responsibility=owner, next=next_step, **fields)
            ledger.set_run_state(rid, "paused" if state == "ready" else "blocked", reason)
            return {"responsibility": "external prerequisite owner" if state == "external_blocked" else
                    "accounting owner" if state == "accounting_unknown" else
                    "budget owner" if state == "budget_exhausted" else "agent",
                    "ok": state == "ready", "preparation": state, "error": reason if state != "ready" else "", "reason": reason,
                    "next": "freeze, check/preflight, then run only if authorized" if state == "ready"
                    else "continue scoped preparation after resolving the stated condition", **fields}
        if max_tokens is None or max_wall_seconds is None or prior_tokens is None or prior_wall_seconds is None:
            return finish("accounting_unknown", "authorized budget and cumulative host/nested token usage required")
        if max_tokens <= 0 or max_wall_seconds <= 0 or prior_tokens < 0 or prior_wall_seconds < 0:
            raise OPCError("preparation budget must be positive; prior_tokens must be nonnegative")
        limits = ledger.events(rid, "preparation_budget")
        budget = {"tokens": max_tokens, "wall_seconds": max_wall_seconds}
        if limits and limits[0]["body"] != budget:
            raise OPCError("preparation budget is already authorized; do not reset it")
        if not limits:
            ledger.event(rid, "preparation_budget", None, **budget)
        prior = ledger.events(rid, "host_usage")
        previous = prior[-1]["body"]["tokens"] if prior else 0
        previous_wall = prior[-1]["body"].get("wall_seconds", 0) if prior else 0
        if prior_tokens < previous or prior_wall_seconds < previous_wall:
            raise OPCError("cumulative host usage cannot decrease")
        ledger.charge(rid, None, "host", Cost(prior_wall_seconds - previous_wall, prior_tokens - previous, None))
        ledger.event(rid, "host_usage", None, tokens=prior_tokens, wall_seconds=prior_wall_seconds)
        unknown = ledger.events(rid, "accounting_unknown")
        if unknown:
            return finish("accounting_unknown", "unaccounted prior call; reconcile its actual usage before dispatch")
        def remaining():
            used = ledger.task_totals(task_id)
            if used["tokens"] >= max_tokens or used["wall_seconds"] >= max_wall_seconds:
                raise OPCError("preparation budget exhausted; saved work retained; no new dispatch")
            return max_wall_seconds - used["wall_seconds"]
        try:
            remaining()
        except OPCError as exc:
            return finish("budget_exhausted", str(exc))
        # Reuse the existing onboard worker and its scope checks; it develops .opc
        # tooling, not product code or formal device experiments.
        started = time.monotonic()
        config = load_worker_config(root)
        if agent == "dsh":
            from ..adapters.dsh import DshWorker as Worker
        else:
            from ..adapters.codex import CodexWorker as Worker
        worker = Worker(worker_options(config, "onboard", {"timeout_s": remaining()}))
        if not (root / ".opc/project.json").exists():
            from . import init
            init(root, "research-project", root.name, "main", task_id, True)
        before = _snapshot(root)
        protected = _inputs_snapshot(root)
        frozen_tasks = {}
        for run in ledger.runs():
            if run["revision"] != "preparation":
                path = root / ".opc/tasks" / run["task_id"] / "revisions" / run["revision"] / "task.json"
                if path.is_file():
                    frozen_tasks[path] = path.read_bytes()
        log = root / ".opc/local/onboard"
        used = ledger.task_totals(task_id)
        prompt = ("Remaining shared tokens: %d; wall seconds: %.1f.\n" %
                  (max_tokens-used["tokens"], max_wall_seconds-used["wall_seconds"]) +
                  (HERE / "ONBOARDING.md").read_text(encoding="utf-8") + "\n" +
                  "PREPARATION: Develop missing evaluators, negative controls, evidence capture, usage monitoring "
                  "and bounded capability probes within the confirmed task. Write only .opc except protected "
                  "runtime/research/workers inputs. Do not change user requirements or execute formal device "
                  "experiments. Unknown capability calls for a bounded probe, not an invented external blocker. "
                  "Keep execution disabled. Preserve already-run task revisions; create a new revision/run when "
                  "acceptance changes, never edit a historical contract. Run local tooling checks and negative controls, preserve their "
                  "receipts in existing onboard logs. No nested model dispatch; host must meter any outside calls. "
                  "Return JSON {state: ready|pending|external_blocked, reason: text, evidence: [paths]}. "
                  "External blocking requires observed evidence and the specific unavailable prerequisite. " +
                  ("\nConfirmed brief:\n" + load_brief_text(root, brief) if brief else ""))
        call, text = worker._run("onboard", prompt, root, log, "workspace-write", None)
        ledger.charge(rid, None, "onboard", call.cost)
        ledger.charge(rid, None, "preparation overhead", Cost(max(0, time.monotonic()-started-call.cost.wall_seconds), 0, 0))
        if not call.extra.get("usage_complete", False):
            ledger.event(rid, "accounting_unknown", None, reason="worker usage missing/incomplete")
            return finish("accounting_unknown", "worker usage unavailable; no further dispatch")
        after = _snapshot(root)
        outside = [p for p in set(before)|set(after) if before.get(p)!=after.get(p) and not p.startswith(".opc/")]
        if (outside or protected != _inputs_snapshot(root) or any(
                not p.is_file() or p.read_bytes() != data for p, data in frozen_tasks.items())):
            return finish("pending", "preparation scope violation; retain diagnostics and restore unauthorized edits")
        if not call.ok:
            return finish("pending", call.error)
        try:
            result = json.loads(text)
        except ValueError:
            return finish("pending", "preparation reply is not structured evidence")
        evidence = result.get("evidence") or []
        paths = []
        for rel in evidence:
            path = (root / rel).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                return finish("pending", "preparation evidence must be readable project files")
            paths.append(path)
        if not paths:
            return finish("pending", "preparation needs observed evidence, including negative controls")
        if result.get("state") != "ready":
            return finish("external_blocked" if result.get("state") == "external_blocked" else "pending",
                          result.get("reason", "preparation remains"), evidence=evidence)
        try:
            timeout = remaining()
        except OPCError as exc:
            return finish("budget_exhausted", str(exc), evidence=evidence)
        if frozen_tasks:
            from ..core.config import TaskSpec
            current = TaskSpec.load(root, task_id)
            old = ledger.latest_run(task_id)
            if old is not None and current.revision == old["revision"]:
                return finish("pending", "existing execution requires a new revision before preparing changed acceptance")
        # Independent read-only inspection; cannot certify its own mutable drafts.
        review = Worker(worker_options(config, "reviewer", {"timeout_s": timeout}))
        files = preparation_files(root)
        rc, reply = review._run("reviewer", "Review the prepared evaluator, negative controls and probe receipts. "
            "Verify against the confirmed brief without executing formal device experiments. "
            "Software checks prove tooling only. Accept only when independent acceptance is preserved. "
            "Return JSON {verdict: accept|reject, reason: text}. Evidence: " + json.dumps(evidence) +
            "\nBrief: " + (load_brief_text(root, brief) if brief else "read task contracts"),
            root, log / "reviewer", "read-only", None)
        ledger.charge(rid, None, "reviewer", rc.cost)
        if not rc.extra.get("usage_complete", False):
            ledger.event(rid, "accounting_unknown", None, reason="review usage missing")
            return finish("accounting_unknown", "review usage unavailable")
        try:
            accepted = rc.ok and json.loads(reply).get("verdict") == "accept"
        except ValueError:
            accepted = False
        if not accepted or files != preparation_files(root):
            return finish("pending", "preparation review rejected or reviewed files changed", evidence=evidence)
        try:
            remaining()
        except OPCError as exc:
            return finish("budget_exhausted", str(exc), evidence=evidence)
        return finish("ready", "review accepted; commit the reviewed files before formal execution",
                      files=files, evidence=evidence)


def load_brief_text(root: Path, brief) -> str:
    from .brief import load_brief
    report, body = load_brief(root, brief)
    if not report["ok"]:
        raise OPCError("brief is not ready: " + "; ".join(report["problems"]))
    return body


def preparation_files(root: Path) -> dict[str, str]:
    from ..core.workspace import git
    names = str(git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "--",
                    ".opc/eval", ".opc/components", ".opc/tasks", cwd=root)).split("\0")
    return {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
            for rel in sorted(set(names)) if rel and (root / rel).is_file()}
