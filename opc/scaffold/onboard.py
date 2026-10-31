"""`opc onboard`: metered scoped preparation and independent read-only review.

Preparation may write only under `.opc/`; inputs and execution-bound contracts
remain protected. Receipts certify the selected candidate's checked contents;
`opc check` and `opc preflight` still decide execution readiness.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from ..core.model import OPCError
from ..core.worker_config import CONFIG_PATH, load_worker_config, worker_options, load_budget_config, resolve_budget_limits
from ..core.workspace import dirty_paths

HERE = Path(__file__).resolve().parent


def _snapshot(root: Path) -> dict[str, str | None]:
    """Content hash of every dirty path, so edits to already-dirty user files count."""
    out: dict[str, str | None] = {}
    for p in dirty_paths(root):
        f = root / p
        out[p] = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
    return out


def _inputs_snapshot(root: Path) -> dict[str, str]:
    """Include clean and ignored inputs too; onboard must not rewrite its sources."""
    paths = [root / ".opc/archa.py", root / CONFIG_PATH]
    for directory in ("runtime", "research"):
        paths.extend((root / ".opc" / directory).rglob("*"))
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


def onboard(project_root: Path, agent: str, brief: str | Path | None = None, *,
            prepare: bool = True, task_id: str = "t-main", revision: str | None = None, max_tokens: int | None = None,
            max_wall_seconds: float | None = None, prior_tokens: int | None = None, prior_wall_seconds: float | None = None, record_usage_only: bool = False,
            reconcile_usage: str | Path | None = None) -> dict[str, Any]:
    """Develop readiness within scope; never dispatch a formal experiment here.

    prior_tokens is cumulative host/nested usage outside the worker receipts,
    including cached input. Missing usage is recorded as unknown; only an explicit relevant cap blocks dispatch.
    """
    from ..core.ledger import Ledger
    from ..core.model import Cost, write_json
    import json
    import time
    root = project_root.resolve()
    if agent not in ("codex", "dsh"):
        raise OPCError("the onboarding agent must be codex or dsh")
    if not (root / ".opc/project.json").exists():
        if brief:
            load_brief_text(root, brief)
        from . import init
        init(root, "research-project", root.name, "main", task_id, True)
    brief_identity = None
    if brief is not None:
        from .brief import load_brief
        report, _ = load_brief(root, brief)
        if not report['ok']:
            raise OPCError('brief is not ready: ' + '; '.join(report['problems']))
        brief_identity = {'brief': report['brief'], 'sha256': report['sha256']}
    # Resolve once before any worker dispatch. A newer draft cannot redirect preparation.
    from ..core.config import REV
    task_dir = root / ".opc/tasks" / task_id / "revisions"
    if revision is None:
        revisions = sorted(p.name for p in task_dir.glob("r[0-9][0-9][0-9][0-9]") if p.is_dir())
        revision = revisions[-1] if revisions else "r0001"
    if not REV.fullmatch(revision):
        raise OPCError("revision must be rNNNN")
    contract_path = task_dir / revision / "task.json"
    explicit = {key: value for key, value in (("max_tokens", max_tokens), ("max_wall_seconds", max_wall_seconds)) if value is not None}
    from ..core.config import resolve_task_defaults
    candidate = json.loads(contract_path.read_text(encoding="utf-8-sig")) if contract_path.exists() else {}
    resolved, _ = resolve_task_defaults(root, candidate)
    caps = resolve_budget_limits(resolved.get("budget", {}), load_budget_config(root) | explicit)
    for key, limit in resolved.get("hard_limits", {}).items():
        caps[key] = min(caps[key], limit) if caps.get(key) is not None else limit
    max_tokens, max_wall_seconds = caps.get("max_tokens"), caps.get("max_wall_seconds")
    ledger = Ledger(root / ".opc/local/ledger.sqlite3")
    with ledger.writer():
        rid = ledger.preparation_scope(task_id)
        def finish(state, reason, **fields):
            owner = "external prerequisite owner" if state == "external_blocked" else "agent"
            if state in ("accounting_unknown", "budget_exhausted"):
                owner = "accounting/budget owner"
            next_step = ("commit reviewed files, check/preflight; run only if authorized" if state == "ready"
                         else "resolve observed external prerequisite" if state == "external_blocked"
                         else "continue scoped preparation" if state == "pending" else "reconcile usage/budget before dispatch")
            ledger.event(rid, "preparation", None, state=state, reason=reason,
                         responsibility=owner, next=next_step, task_id=task_id, revision=revision, **fields)
            return {"responsibility": "external prerequisite owner" if state == "external_blocked" else
                    "accounting owner" if state == "accounting_unknown" else
                    "budget owner" if state == "budget_exhausted" else "agent",
                    "budget": {"scope": "task", "limits": {"tokens": max_tokens, "wall_seconds": max_wall_seconds},
                               "used": ledger.task_totals(task_id)},
                    "task": task_id, "revision": revision,
                    "ok": state == "ready", "preparation": state, "error": reason if state != "ready" else "", "reason": reason,
                    "next": "commit prepared files, check/preflight, then run only if authorized" if state == "ready"
                    else "continue scoped preparation after resolving the stated condition", **fields}
        if max_tokens is not None and prior_tokens is None:
            return finish("accounting_unknown", "cumulative host usage required for the configured limit")
        for value in (prior_tokens, prior_wall_seconds):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise OPCError("prior usage must be finite and nonnegative")
        limits = ledger.events(rid, "preparation_budget")
        budget = {"tokens": max_tokens, "wall_seconds": max_wall_seconds}
        if explicit:
            path = root / CONFIG_PATH
            data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
            data["budget"] = {**data.get("budget", {}), **explicit}
            write_json(path, data)
            ledger.event(rid, "task_budget_authorized", **explicit)
        if not limits or limits[-1]["body"] != budget:
            ledger.event(rid, "preparation_budget", None, **budget)
        prior = ledger.events(rid, "host_usage")
        previous = prior[-1]["body"]["tokens"] if prior else 0
        previous_wall = prior[-1]["body"].get("wall_seconds", 0) if prior else 0
        if ((prior_tokens is not None and prior_tokens < previous) or
                (prior_wall_seconds is not None and prior_wall_seconds < previous_wall)):
            raise OPCError("cumulative host usage cannot decrease")
        if prior_tokens is None or prior_wall_seconds is None:
            ledger.event(rid, "host_usage_unknown", tokens=prior_tokens, wall_seconds=prior_wall_seconds)
        if prior_tokens is not None or prior_wall_seconds is not None:
            ledger.charge(rid, None, "host", Cost(
                prior_wall_seconds - previous_wall if prior_wall_seconds is not None else 0,
                prior_tokens - previous if prior_tokens is not None else 0, None))
            ledger.event(rid, "host_usage", None,
                         tokens=prior_tokens if prior_tokens is not None else previous,
                         wall_seconds=prior_wall_seconds if prior_wall_seconds is not None else previous_wall)
        had_unknown = bool(ledger.unresolved_accounting(rid))
        if reconcile_usage is not None:
            try:
                document = json.loads((root / reconcile_usage).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise OPCError("cannot read reconciliation receipt: " + str(exc)) from exc
            if not isinstance(document, dict):
                raise OPCError("reconciliation receipt must be an object with entries")
            ledger.reconcile_accounting(rid, document.get("entries"), root)
        unknown = ledger.unresolved_accounting(rid)
        if unknown and max_tokens is not None:
            return finish("accounting_unknown", "unaccounted prior call; use --reconcile-usage with actual usage evidence",
                          unresolved_accounting=unknown)
        def remaining():
            used = ledger.task_totals(task_id)
            if ((max_tokens is not None and used["tokens"] >= max_tokens) or
                    (max_wall_seconds is not None and used["wall_seconds"] >= max_wall_seconds)):
                raise OPCError("preparation budget exhausted; saved work retained; no new dispatch")
            return max_wall_seconds - used["wall_seconds"] if max_wall_seconds is not None else None
        try:
            remaining()
        except OPCError as exc:
            return finish("budget_exhausted", str(exc))
        if record_usage_only or reconcile_usage is not None:
            previous_receipts = [e for e in ledger.events(rid, "preparation")
                                 if e["body"].get("revision", revision) == revision]
            previous_receipt = previous_receipts[-1]["body"] if previous_receipts else {}
            state = previous_receipt.get("state", "pending")
            reason = "usage updated; " + previous_receipt.get("reason", "preparation remains")
            if state == "accounting_unknown" or (had_unknown and max_tokens is not None):
                state = "pending"
                reason = "accounting reconciled; rerun preparation and independent review"
            return finish(state, reason,
                          files=previous_receipt.get("files", {}), evidence=previous_receipt.get("evidence", []))
        # Reuse the existing onboard worker and its scope checks; it develops .opc
        # tooling, not product code or formal device experiments.
        candidates = [e for e in ledger.events(rid, "preparation_candidate")
                      if e["body"].get("revision", revision) == revision]
        candidate = candidates[-1]["body"] if candidates else None
        reuse = False
        changed_inputs = None
        if candidate and not all((root / rel).is_file() and
                                 hashlib.sha256((root / rel).read_bytes()).hexdigest() == candidate.get("evidence_hashes", {}).get(rel)
                                 for rel in candidate["evidence"]):
            candidate = None
        if candidate:
            try:
                current_files = preparation_files(root, task_id, revision)
                previous_files = candidate["files"]
                changed_inputs = sorted(rel for rel in set(previous_files) | set(current_files)
                                        if previous_files.get(rel) != current_files.get(rel))
                reuse = (not changed_inputs and candidate.get("brief_input") == brief_identity)
            except OPCError:
                pass
        if reuse:
            config = load_worker_config(root)
            if agent == "dsh":
                from ..adapters.dsh import DshWorker as Worker
            else:
                from ..adapters.codex import CodexWorker as Worker
            import uuid
            log = root / ".opc/local/onboard" / uuid.uuid4().hex
            evidence = candidate["evidence"]
            timeout = remaining()
        if not reuse:
            started = time.monotonic()
            config = load_worker_config(root)
            if agent == "dsh":
                from ..adapters.dsh import DshWorker as Worker
            else:
                from ..adapters.codex import CodexWorker as Worker
            worker = Worker(worker_options(config, "onboard", {"timeout_s": remaining()}))
            before = _snapshot(root)
            protected = _inputs_snapshot(root)
            frozen_tasks = {}
            for run in ledger.runs():
                if run["revision"] != "preparation":
                    path = root / ".opc/tasks" / run["task_id"] / "revisions" / run["revision"] / "task.json"
                    if path.is_file():
                        frozen_tasks[path] = path.read_bytes()
            import uuid
            log = root / ".opc/local/onboard" / uuid.uuid4().hex
            used = ledger.task_totals(task_id)
            prompt = ("Remaining shared limits (null = unlimited): " + json.dumps({
                      "tokens": max_tokens-used["tokens"] if max_tokens is not None else None,
                      "wall_seconds": remaining()}) + "\n" +
                      (HERE / "ONBOARDING.md").read_text(encoding="utf-8") + "\n" +
                      f"Target task ID: {task_id}. Create its contract if missing; do not prepare another task.\n"
                      f"Target revision: {revision}. Modify this candidate in place; preparation and review do not freeze it.\n"
                      "PREPARATION: Complete necessary evaluator integration and focused validation "
                      "and bounded capability probes within the confirmed task. Write only .opc except protected "
                      "runtime/research/workers inputs. Do not change user requirements or execute formal device "
                      "experiments. Unknown capability calls for a bounded probe, not an invented external blocker. "
                      "Keep execution disabled. Preserve already-run task revisions; create a new revision/run when "
                      "acceptance changes, never edit a historical contract. Run local tooling checks and negative controls, preserve their "
                      "receipts in existing onboard logs. No nested model dispatch; host must meter any outside calls. "
                      "Return JSON {state: ready|pending|external_blocked, reason: text, evidence: [paths]}. "
                      "External blocking requires observed evidence and the specific unavailable prerequisite. " +
                      ("\nConfirmed brief:\n" + load_brief_text(root, brief) if brief else ""))
            if changed_inputs is not None:
                prompt += ("\nChanged preparation inputs: " + json.dumps(changed_inputs) +
                           "\nRetain unaffected checks and evidence; rerun only checks affected by these changes. "
                           "Prior evidence: " + json.dumps(candidate["evidence"]))
            call, text = worker._run("onboard", prompt, root, log, "workspace-write", None)
            ledger.charge(rid, None, "onboard", call.cost)
            ledger.charge(rid, None, "preparation overhead", Cost(max(0, time.monotonic()-started-call.cost.wall_seconds), 0, 0))
            if not call.extra.get("usage_complete", False):
                ledger.event(rid, "accounting_unknown", None, reason="worker usage missing/incomplete",
                             call_id=call.call_id, log_dir=str(log), charged=call.cost.as_dict(), error=call.error)
                if max_tokens is not None:
                    return finish("accounting_unknown", "worker usage unavailable; no further dispatch",
                                  worker_error=call.error, unresolved_accounting=ledger.unresolved_accounting(rid))
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
        from ..core.config import TaskSpec
        prepared_task = TaskSpec.load(root, task_id, revision)
        files = preparation_files(root, task_id, revision)
        if len(files) < 3:
            return finish("pending", "current task evaluator files are missing", evidence=evidence)
        if not reuse:
            ledger.event(rid, "preparation_candidate", task_id=task_id, revision=revision, files=files, evidence=evidence, brief_input=brief_identity,
                         evidence_hashes={rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in evidence})
        if not prepared_task.raw.get("preparation_review", False):
            return finish("ready", "necessary integration checks recorded; commit prepared files before execution",
                          files=files, evidence=evidence, brief_input=brief_identity)
        # Independent read-only inspection; cannot certify its own mutable drafts.
        review = Worker(worker_options(config, "reviewer", {"timeout_s": timeout}))
        files = preparation_files(root, task_id, revision)
        rc, reply = review._run("reviewer", "Review the task-required preparation checks and probe receipts. "
            "Verify against the confirmed brief without executing formal device experiments. "
            "Software checks prove tooling only. Accept only when independent acceptance is preserved. "
            "Return JSON {verdict: accept|reject, reason: text}. Evidence: " + json.dumps(evidence) +
            "\nBrief: " + (load_brief_text(root, brief) if brief else "read task contracts"),
            root, log / "reviewer", "read-only", None)
        ledger.charge(rid, None, "reviewer", rc.cost)
        if not rc.extra.get("usage_complete", False):
            ledger.event(rid, "accounting_unknown", None, reason="review usage missing",
                         call_id=rc.call_id, log_dir=str(log / "reviewer"), charged=rc.cost.as_dict(), error=rc.error)
            if max_tokens is not None:
                return finish("accounting_unknown", "review usage unavailable",
                              worker_error=rc.error, unresolved_accounting=ledger.unresolved_accounting(rid))
        try:
            accepted = rc.ok and json.loads(reply).get("verdict") == "accept"
        except ValueError:
            accepted = False
        if not accepted or files != preparation_files(root, task_id, revision):
            return finish("pending", "preparation review rejected or reviewed files changed", evidence=evidence)
        try:
            remaining()
        except OPCError as exc:
            return finish("budget_exhausted", str(exc), evidence=evidence)
        return finish("ready", "review accepted; commit the reviewed files before formal execution",
                      files=files, evidence=evidence, brief_input=brief_identity)


def load_brief_text(root: Path, brief) -> str:
    from .brief import load_brief
    report, body = load_brief(root, brief)
    if not report["ok"]:
        raise OPCError("brief is not ready: " + "; ".join(report["problems"]))
    return body


def preparation_files(root: Path, task_id: str | None = None, revision: str | None = None) -> dict[str, str]:
    from ..core.config import TaskSpec, ComponentConfig
    from ..core.workspace import git
    if task_id is None:
        raise OPCError("preparation_files requires an explicit task")
    task = TaskSpec.load(root, task_id, revision)
    component = ComponentConfig.load(root, task.component)
    patterns = component.evaluator_files + [task.path.relative_to(root).as_posix(),
                ".opc/components/%s.json" % task.component]
    names = str(git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "--",
                    *patterns, cwd=root)).split("\0")
    # Bind review to the bytes Git will commit, including its clean/EOL filters.
    # Prefix the blob ID so existing raw SHA-256 receipts remain distinguishable.
    return {rel: "git-blob:" + str(git("hash-object", "--path=" + rel, "--", rel, cwd=root)).strip()
            for rel in sorted(set(names)) if rel and (root / rel).is_file()}
