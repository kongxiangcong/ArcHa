"""The engine: the only owner of "the next attempt".

Run-level Expert decisions interpret results and select Attempt DAG nodes.
The controller advances their phases and owns every ledger write; workers only
execute fixed inputs and save receipts. One selected Attempt:

    PLAN_CHECK optional file hints within scope, not a repeat
    DESIGN     writable tree cut from the selected parent -> edits or measurement
    SANDBOX    every change classified; any non-editable change fails the attempt
    EVALUATE   editable-only candidate snapshot in a fresh tree; frozen gates run there
    ACCEPT     comparability (evaluator + toolchain + evidence), constraints, gain over noise
    CHAMPION   commit, ledger intent, compare-and-swap the ref, ledger record
    FEEDBACK   design + actual execution + data for the next expert to interpret

Per-attempt acceptance is deterministic and calls no reviewer. The spec axis
(is the result worth having, does the claim overreach) runs once, at promotion.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import sqlite3
import threading
import shutil
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import closing
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from ..adapters.worker import Worker, WorkerCall, make_worker, validate_plan
from ..domain import DomainAdapter, Evaluation, bounded_data, experimental_data, load_domain
from . import accept as acceptance
from .config import Bindings, Budget, ComponentConfig, ProjectConfig, TaskSpec, WorkerSpec
from .ledger import ClaimConflict, Ledger
from .platform import execution_control, portable_path
from .worker_config import load_worker_config, load_max_concurrency, resolve_worker
from .model import (BudgetExhausted, DispatchStopped, Cost, GateResult, Measurements, OPCError, Outcome, Verdict,
                    canonical_json, write_json, write_text)
from .workspace import (Workspaces, apply_patch, cas_update_ref, commit_tree, dirty_paths, git,
                        extract_patch, patch_digest, read_ref, rev_parse, sandbox, tracked_digest)

HISTORY_WINDOW = 12


@dataclass
class StopDecision:
    state: str            # closed | blocked | paused
    reason: str


def run_compatibility(frozen: Path, run) -> dict[str, Any]:
    """Read existing sources without probing tools or changing execution state."""
    missing = [name for name in ("task.json", "component.json", "baseline.json")
               if not (frozen / name).is_file()]
    report = {"record": {"state": "readable", "reason": "ledger and existing artifacts remain available"},
              "execution": {"state": "requires_check", "reason": "tool availability is checked when continuing"},
              "measurement": {"state": "unknown", "reason": "current environment has not been probed by this read"}}
    try:
        baseline = json.loads((frozen / "baseline.json").read_text(encoding="utf-8"))
        if not isinstance(baseline, dict):
            raise ValueError("baseline snapshot is not an object")
        if not baseline.get("execution"):
            missing.append("baseline.execution (legacy)")
    except (OSError, ValueError) as exc:
        missing.append(str(exc))
    if missing:
        report["execution"] = {"state": "blocked", "reason": "missing execution source: " + "; ".join(missing)}
        report["measurement"]["reason"] = "legacy/unknown: execution sources are incomplete"
    elif run["state"] == "closed":
        report["execution"] = {"state": "closed", "reason": "closed Run is observed without reopening"}
    return report


@dataclass
class CallExecution:
    role: str
    attempt: int | None
    inputs: dict
    tree: Path
    log_dir: Path
    invoke: Callable[[], WorkerCall]
    call_id: str = ""
    usage_default: bool = False
    wall_limits: list = field(default_factory=list)


@dataclass
class EvaluationExecution:
    invoke: Callable


class Engine:
    def __init__(self, project_root: Path, task_id: str, revision: str | None = None,
                 log: Callable[[str], None] = print, *, run_id: str | None = None):
        self.project = ProjectConfig.load(project_root)
        self.root = self.project.root
        self.requested_revision = revision
        self.requested_run_id = run_id
        self.bindings = Bindings.load(self.project)
        self.ledger = Ledger(self.root / ".opc/local/ledger.sqlite3")
        selected = None
        if run_id is not None:
            selected = self.ledger.select_run(task_id, revision, run_id)
        elif revision is None:
            resumable = [r for r in self.ledger.runs() if r["task_id"] == task_id
                         and r["revision"] != "preparation" and r["state"] != "closed"]
            if len(resumable) == 1:
                selected = resumable[0]
        source = None
        if selected is not None:
            revision = selected["revision"]
            path = (self.bindings.artifact_root / self.project.project_id / task_id /
                    selected["run_id"] / "frozen/task.json")
            try:
                source = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise OPCError("Run remains readable but frozen execution source is unavailable: %s" % exc) from exc
        self.task = TaskSpec.load(self.root, task_id, revision, source=source,
                                  resolve_local=source is None)
        self.worker_config = load_worker_config(self.root) if source is None else {}
        self.resolved_workers = {} if source is not None else self.resolve_workers()
        component_source = None
        if selected is not None:
            try:
                component_source = json.loads((path.parent / "component.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise OPCError("Run remains readable but frozen component source is unavailable: %s" % exc) from exc
        self.comp = ComponentConfig.load(self.root, self.task.component, source=component_source)
        self.ref = "refs/heads/opc/%s" % task_id
        self.preparation = self.ledger.preparation_scope(task_id, create=False)
        self.log = log
        self.run_id: str | None = None
        self._budget_origin: dict[str, Any] = {}
        self._project_hard_limits = self.project.raw.get("hard_limits", {})
        self._domain: DomainAdapter | None = None
        self._rule = None
        self._workers: tuple[Worker, Worker] | None = None
        self._eval_tree: Path | None = None
        self.max_concurrency = load_max_concurrency(self.root, self.task.configuration_sources) if source is None else 3
        self._inflight: dict[str, tuple[float, float | None]] = {}
        self._execution_lock = threading.Lock()
        self._abort_execution = threading.Event()
        self._abort_reason = ""

    # ------------------------------------------------------------------ paths
    def evaluator_patterns(self) -> list[str]:
        return self.comp.evaluator_files + [".opc/components/%s.json" % self.comp.component_id]

    def evaluator_digest(self, tree_ish: str) -> tuple[str, list[str]]:
        return tracked_digest(self.root, tree_ish, self.evaluator_patterns(), self.comp.scratch)

    def artifact_dir(self) -> Path:
        return self.bindings.artifact_root / self.project.project_id / self.task.task_id / \
            self.run_id

    def attempt_dir(self, n: int) -> Path:
        return self.artifact_dir() / "attempts" / ("a%06d" % n)

    def workspaces(self, run_id: str | None = None) -> Workspaces:
        return Workspaces(self.root, self.bindings.workspace_root / self.project.project_id /
                          self.task.task_id / (run_id or self.run_id or "preflight"))

    def preparation_receipt(self) -> dict[str, Any]:
        """Select evidence for this execution contract, retaining legacy receipts."""
        events = self.ledger.events(self.preparation, "preparation") if self.preparation else []
        matching = []
        unidentified = False
        contract = self.task.path.relative_to(self.root).as_posix()
        for event in events:
            receipt = event["body"]
            if receipt.get("task_id", self.task.task_id) != self.task.task_id:
                continue
            revision = receipt.get("revision")
            if revision is None:
                # Legacy evidence can identify its checked contract without new metadata.
                contracts = [path for path in receipt.get("files", {})
                             if path.startswith(".opc/tasks/") and path.endswith("/task.json")]
                if len(contracts) != 1:
                    unidentified = True
                    continue
                if contracts[0] != contract:
                    continue
            elif revision != self.task.revision:
                continue
            matching.append(receipt)
        if matching:
            return matching[-1]
        return ({"state": "legacy_unknown", "reason": "legacy preparation receipt lacks a unique checked contract identity"}
                if unidentified else {})

    def prepare_call(self, request: CallExecution) -> WorkerCall | None:
        """Only the controller allocates identities and reconciles stored receipts."""
        receipt = request.log_dir / "receipt.json"
        previous = next((c for c in self.ledger.calls(self.run_id)
                         if c["receipt_path"] == str(receipt)), None)
        if previous:
            if previous["result"] is None:
                if not receipt.is_file():
                    raise OPCError("Call %s execution unknown; inspect original execution before retry" % previous["call_id"])
                self.ledger.finish_call(previous["call_id"], json.loads(receipt.read_text(encoding="utf-8")))
                previous = next(c for c in self.ledger.calls(self.run_id) if c["call_id"] == previous["call_id"])
            return self.call_from_receipt(previous["call_id"], previous["result"])
        self.hard_check()
        request.call_id = self.ledger.begin_call(self.run_id, request.attempt, request.role,
                    {**request.inputs, "tree": str(request.tree), "owner_pid": __import__("os").getpid()}, str(receipt))
        kind = self.worker_spec(request.role if request.role in self.resolved_workers else "expert").kind
        request.usage_default = kind == "scripted" or request.role == "evaluator"
        request.wall_limits = self.execution_wall_limits()
        with self._execution_lock:
            self._inflight[request.call_id] = (time.monotonic(), None)
        return None

    @staticmethod
    def call_from_receipt(call_id: str, result: dict) -> WorkerCall:
        return WorkerCall(result["role"], result["ok"], Cost(**result["cost"]), call_id=call_id,
                          output=result.get("output"), error=result.get("error", ""),
                          exhausted=result.get("exhausted", False), log_dir=result.get("log_dir", ""),
                          extra=result.get("extra", {}))

    def execution_wall_limits(self) -> list[tuple[str, tuple, float]]:
        """Use the same quota ownership and lifetime scopes as persisted accounting."""
        task_sql = "SELECT COALESCE(SUM(c.wall_seconds),0) FROM charges c WHERE c.run_id IN (SELECT run_id FROM runs WHERE task_id=?) OR c.run_id=?"
        task_args = (self.task.task_id, "preparation:" + self.task.task_id)
        limits = []
        cap = self.effective_budget().max_wall_seconds
        if cap is not None:
            if self._budget_origin:
                sql = ("SELECT COALESCE(SUM(c.wall_seconds),0) FROM charges c JOIN runs r ON c.run_id=r.run_id "
                       "WHERE r.task_id=? AND r.revision!='preparation' AND r.rowid > (SELECT rowid FROM runs WHERE run_id=?)")
                args = (self.task.task_id, self._budget_origin["source_run"])
            else:
                sql, args = task_sql, task_args
            limits.append((sql, args, cap))
        for values, project_scope in ((self.task.raw.get("hard_limits", {}), False), (self._project_hard_limits, True)):
            cap = values.get("max_wall_seconds")
            if cap is not None:
                sql, args = (("SELECT COALESCE(SUM(wall_seconds),0) FROM charges", ()) if project_scope else (task_sql, task_args))
                limits.append((sql, args, cap))
        return limits

    def execute_call(self, request: CallExecution) -> dict:
        """Worker side: execute fixed input and save a receipt; never write the ledger."""
        with self._execution_lock:
            self._inflight[request.call_id] = (time.monotonic(), None)
        limits = request.wall_limits
        try:
            with closing(sqlite3.connect("file:%s?mode=ro" % self.ledger.path, uri=True)) as reader:
                def cancellation():
                    if self._abort_execution.is_set():
                        return self._abort_reason
                    row = reader.execute("SELECT command FROM control WHERE run_id=?", (self.run_id,)).fetchone()
                    if row and row[0] == "stop":
                        return "stopped by user"
                    with self._execution_lock:
                        active = sum((end or time.monotonic()) - start for start, end in self._inflight.values())
                        if any(reader.execute(sql, args).fetchone()[0] + active >= cap for sql, args, cap in limits):
                            return "budget_exhausted: max_wall_seconds"
                    return None
                with execution_control(cancellation, request.log_dir) as control:
                    call = request.invoke()
            if control.unknown:
                raise OPCError("cannot confirm execution termination: " + control.unknown)
            if control.cancelled and not call.extra.get("terminal_completed"):
                call.ok = False
                call.extra.update(cancelled=True, cancel_reason=control.cancelled)
                call.error = control.cancelled
            session_id = call.extra.get("session_id") or (call.call_id if call.call_id != "scripted" else None)
            if session_id:
                call.extra["session_id"] = session_id
            result = dict(role=request.role, ok=call.ok, cost=call.cost.as_dict(), session_id=session_id,
                          output=call.output, error=call.error, exhausted=call.exhausted,
                          log_dir=call.log_dir or str(request.log_dir), extra=call.extra,
                          usage_complete=call.extra.get("usage_complete", request.usage_default),
                          state=("not_started" if call.extra.get("not_started") else
                                 "unknown" if call.extra.get("execution_unknown") and not control.cancelled else
                                 "cancelled" if call.extra.get("cancelled") else "completed"))
            write_json(request.log_dir / "receipt.json", result)
            return result
        finally:
            with self._execution_lock:
                start, _ = self._inflight[request.call_id]
                self._inflight[request.call_id] = (start, time.monotonic())

    def complete_call(self, request: CallExecution, result: dict) -> WorkerCall:
        with self._execution_lock:
            self.ledger.finish_call(request.call_id, result)
            self._inflight.pop(request.call_id, None)
        call = self.call_from_receipt(request.call_id, result)
        if result["state"] == "unknown":
            raise OPCError("Call %s execution unknown; retain workspace and reconcile execution" % request.call_id)
        if call.extra.get("cancelled") and not call.extra.get("terminal_completed"):
            reason = call.extra.get("cancel_reason", "stopped by user")
            if reason.startswith("budget_exhausted"):
                raise BudgetExhausted(reason.removeprefix("budget_exhausted: ").split(":", 1)[0],
                                      "cancelled in-flight execution")
            raise DispatchStopped("closed", reason)
        return call

    def dispatch_call(self, role: str, attempt: int | None, inputs: dict[str, Any],
                      tree: Path, log_dir: Path, invoke: Callable[[], WorkerCall]) -> WorkerCall:
        request = CallExecution(role, attempt, inputs, tree, log_dir, invoke)
        replay = self.prepare_call(request)
        if replay is not None:
            return replay
        try:
            return self.complete_call(request, self.execute_call(request))
        except BaseException:
            with self._execution_lock:
                self._inflight.pop(request.call_id, None)
            raise

    def check_unknown_executions(self) -> None:
        """Unresolved execution owns the shared resource across all Runs in this project."""
        for row in self.ledger.db.execute("SELECT call_id, state, receipt_path FROM calls WHERE state IN ('dispatched','unknown')").fetchall():
            with self._execution_lock:
                active = self._inflight.get(row["call_id"])
            if active is not None:
                continue
            path = Path(row["receipt_path"])
            if row["state"] == "dispatched" and path.is_file():
                self.ledger.finish_call(row["call_id"], json.loads(path.read_text(encoding="utf-8")))
            else:
                raise OPCError("Call %s execution unknown; shared compute remains blocked until reconciled" % row["call_id"])

    def reconcile_calls(self) -> None:
        for call in self.ledger.calls(self.run_id):
            if call["state"] == "unknown":
                raise OPCError("Call %s execution unknown; inspect original logs before retry" % call["call_id"])
            if call["result"] is not None:
                continue
            path = Path(call["receipt_path"])
            if path.is_file():
                self.ledger.finish_call(call["call_id"], json.loads(path.read_text(encoding="utf-8")))
            else:
                raise OPCError("Call %s execution unknown; no reliable terminal receipt; retain workspace and inspect execution" % call["call_id"])

    # -------------------------------------------------------------- preflight
    def static_check(self) -> dict[str, Any]:
        """Everything that can be checked without running project code."""
        problems, warnings = [], []
        from ..scaffold.brief import execution_handoff
        brief_source = None
        try:
            brief_source = execution_handoff(self.root, self.task.task_id, self.task.revision,
                                             self.task.path, self.preparation_receipt().get("brief_input"))
        except OPCError as exc:
            problems.append(str(exc))
        if not self.project.execution_enabled:
            problems.append(".opc/project.json has execution_enabled=false; enable it after "
                            "reviewing the component and task contracts")
        try:
            base = rev_parse(self.root, self.task.base_ref)
        except OPCError as exc:
            return {"ok": False, "problems": [str(exc)], "warnings": warnings}
        digest, files = self.evaluator_digest(base)
        if self.preparation:
            receipt = self.preparation_receipt()
            if self.accounting_required() and self.unresolved_usage(self.preparation):
                problems.append("preparation accounting incomplete; no new dispatch")
            if receipt.get("state") != "ready":
                problems.append("preparation not ready: " + receipt.get("reason", "unmetered draft"))
            else:
                checked_files = receipt.get("files", {})
                current_files = set(files) | {self.task.path.relative_to(self.root).as_posix()}
                if current_files != set(checked_files):
                    problems.append("prepared inputs changed since review; rerun affected preparation checks")
                for rel, checked_digest in checked_files.items():
                    try:
                        if checked_digest.startswith("git-blob:"):
                            actual = "git-blob:" + str(git("rev-parse", base + ":" + rel, cwd=self.root)).strip()
                        else:
                            # Receipts created before Git-normalized preparation hashes.
                            data = git("show", base + ":" + rel, cwd=self.root, binary=True)
                            actual = hashlib.sha256(data).hexdigest()
                    except OPCError:
                        problems.append("prepared input missing from execution source: " + rel)
                        continue
                    if actual != checked_digest:
                        problems.append("prepared acceptance changed since review: " + rel)
        dirty = dirty_paths(self.root)
        from .config import denied
        frozen_dirty = [p for p in dirty if denied(p, self.evaluator_patterns() + [self.task.path.relative_to(self.root).as_posix(), ".opc/project.json"])
                        and not p.startswith(".opc/local/") and not self.comp.is_scratch(p)]
        if frozen_dirty:
            problems.append("uncommitted evaluator/.opc files (runs use the committed version): "
                            + ", ".join(frozen_dirty[:8]))
        edit_dirty = [p for p in dirty if self.comp.is_editable(p)]
        if edit_dirty:
            warnings.append("uncommitted edits in editable paths are NOT part of the baseline: "
                            + ", ".join(edit_dirty[:8]))
        if len(files) <= 1:
            problems.append("evaluator_files match no committed file at %s" % base[:12])
        editable_hits = tracked_digest(self.root, base, self.comp.editable)[1]
        if not editable_hits:
            warnings.append("no committed file matches the editable paths yet")
        source_context = [p for p in self.comp.context_files
                          if not p.startswith(".opc/context/") or not p.endswith(".md")]
        if source_context:
            warnings.append("expert no longer reads source context_files; put task background, "
                            "criteria, constraints and capabilities in .opc/context/*.md: "
                            + ", ".join(source_context[:8]))
        if (self.comp.adapter == "command" and acceptance.required_metrics(self.task.acceptance)
                and not any(g.metrics for g in self.comp.gates)):
            problems.append("required numeric metrics have no declared output")
        profile = (self.task.raw.get("profile") or {}).get("name")
        if profile == "tuning" and not self.task.acceptance.objective_metric:
            problems.append("tuning profile requires an objective and comparable baseline measurements")
        if profile == "exploration":
            materials = [p for p in (self.root / ".opc/context").glob("*.md") if p.is_file() and p.read_text(encoding="utf-8").strip()]
            if not materials:
                problems.append("exploration profile requires readable materials in .opc/context/*.md")
            if not self.task.requirements:
                problems.append("exploration profile requires an acceptance channel in requirements")
        gate_ids = {g.gate_id for g in self.comp.gates}
        for req in self.task.requirements:
            missing = set(req.get("gates") or []) - gate_ids
            if missing:
                problems.append("requirement %s names unknown gates: %s" % (req.get("id"), sorted(missing)))
        for p in self.comp.editable:
            if p in (".", "**", "*"):
                problems.append("editable %r covers the whole project" % p)
        return {"ok": not problems, "problems": problems, "warnings": warnings,
                "base_commit": base, "evaluator_digest": digest, "evaluator_files": files,
                "brief_source": brief_source,
                "editable_files": editable_hits,
                "required_metrics": acceptance.required_metrics(self.task.acceptance)}

    def domain(self, tree: Path) -> DomainAdapter:
        if self._domain is None:
            self._domain = load_domain(self.comp, tree)
            self._rule = acceptance.load_rule(self.task.acceptance, tree, self.evaluator_patterns())
        return self._domain

    def resolve_workers(self) -> dict[str, dict]:
        specs = {"expert": self.task.expert, "designer": self.task.designer}
        result = {}
        for role in ("expert", "designer", "reviewer", "onboard"):
            base = specs.get(role)
            if role == "designer" and base is None:
                continue
            default_kind = result.get("expert", {}).get("kind", self.task.expert.kind)
            if default_kind == "scripted":
                default_kind = "codex"
            if role in ("reviewer", "onboard"):
                # Share the selected installation, never another role's model or flags.
                base = WorkerSpec(default_kind, {key: value for key, value in result["expert"].items()
                                                if key in ("binary", "codex_home", "dsh_home")})
            spec = resolve_worker(self.worker_config, role, base,
                                  restricted=self.task.configuration_sources.get("workers.%s.kind" % role) == "task",
                                  default_kind=default_kind, sources=self.task.configuration_sources)
            result[role] = {"kind": spec.kind, **spec.options}
        return result

    def worker_spec(self, role: str) -> WorkerSpec:
        try:
            values = self.resolved_workers[role]
        except KeyError as exc:
            raise OPCError("Run remains readable but cannot dispatch %s: frozen role configuration unavailable" % role) from exc
        return WorkerSpec(values["kind"], {k: v for k, v in values.items() if k != "kind"})

    def workers(self, tree: Path) -> tuple[Worker, Worker]:
        if self._workers is None:
            expert = make_worker(self.worker_spec("expert"), tree)
            designer = make_worker(self.worker_spec("designer"), tree) if "designer" in self.resolved_workers else expert
            self._workers = (expert, designer)
        return self._workers

    def diagnostic_gates(self) -> frozenset[str]:
        optional = {g for r in self.task.requirements if r.get("required") is False
                    for g in r.get("gates", [])}
        mandatory = {g for r in self.task.requirements if r.get("required", True)
                     for g in r.get("gates", [])}
        return frozenset(optional - mandatory)

    def evaluate_commit(self, ws: Workspaces, commit: str, patch: str, out: Path,
                        name: str, *, fresh: bool = False, delivery: bool = False,
                        attempt: int | None = None) -> tuple[Evaluation, Measurements | None, Path]:
        """Evaluate `commit` (+ `patch`) in a fresh tree with the frozen gates."""
        tree = ws.checkout(name, commit)
        apply_patch(tree, patch)
        tree_id = str(git("write-tree", cwd=tree)).strip()
        digest = self.evaluator_digest(tree_id)[0]
        dom = self.domain(tree)
        tool_digest, _ = dom.toolchain()
        # contracts and notes do not change what the gates compute
        content = tracked_digest(self.root, tree_id, ["**"], self.comp.scratch + [
            ".opc/tasks/**", ".opc/context/**", ".opc/*.md", ".opc/README.md"])[0]
        ev = None if fresh or delivery else self._cached(content, digest, tool_digest)
        def evaluate() -> WorkerCall:
            value = ev
            if value is None:
                from ..domains.command import CommandDomain
                if delivery and isinstance(dom, CommandDomain):
                    value = dom.evaluate(tree, out, self.task.acceptance.repeats,
                                         diagnostic_gates=self.diagnostic_gates())
                else:
                    value = dom.evaluate(tree, out, self.task.acceptance.repeats)
            data = {**asdict(value), "gates": [g.as_dict() for g in value.gates],
                    "failure": value.failure.value if value.failure else None}
            return WorkerCall("evaluator", True, Cost(value.seconds, 0, 0.0), output=data)
        if self.run_id:
            call = self.dispatch_call("evaluator", attempt,
                    dict(commit=commit, patch=patch, fresh=fresh, delivery=delivery), tree, out, evaluate)
        else:
            call = evaluate()
        data = call.output
        ev = Evaluation(**{**data, "gates": [GateResult.from_dict(g) for g in data["gates"]],
                           "failure": Outcome(data["failure"]) if data["failure"] else None})
        if not delivery:
            self._store(content, digest, tool_digest, ev)
        meas = None
        if ev.failure is None:
            meas = Measurements(values=ev.values, evaluator_digest=digest,
                                toolchain_digest=tool_digest, source_commit=commit,
                                spread=ev.spread, repeats=ev.repeats, degraded_by=ev.degraded_by)
        write_json(out / "evaluation.json", {
            "commit": commit, "patch_sha": patch_digest(patch) if patch else None,
            "evaluator_digest": digest, "toolchain_digest": tool_digest,
            "gates": [g.as_dict() for g in ev.gates], "failure": ev.failure.value
            if ev.failure else None, "reason": ev.reason,
            "metrics": meas.as_dict() if meas else None,
            "data": ev.data, "cached": ev.cached})
        return ev, meas, tree

    def _cache_path(self, tree_id: str, ev_digest: str, tool_digest: str) -> Path:
        key = hashlib.sha256(("%s|%s|%s|%d" % (tree_id, ev_digest, tool_digest,
                                               self.task.acceptance.repeats)).encode()).hexdigest()
        return self.root / ".opc" / "local" / "cache" / "eval" / ("%s.json" % key)

    def _cached(self, tree_id: str, ev_digest: str, tool_digest: str) -> Evaluation | None:
        """Only for components that declare `deterministic`; keyed by the full tree,
        evaluator and toolchain (openTPU keyed by commit only, so a changed accept
        rule silently reused old numbers)."""
        if not self.comp.deterministic:
            return None
        p = self._cache_path(tree_id, ev_digest, tool_digest)
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        gates = [GateResult.from_dict(g) for g in d["gates"]]
        for g in gates:
            g.seconds, g.detail = 0.0, ("cached; " + g.detail).strip("; ")
        return Evaluation(gates=gates, values=d["values"], spread=d["spread"],
                          repeats=d["repeats"], degraded_by=d["degraded_by"],
                          failure=Outcome(d["failure"]) if d["failure"] else None,
                          reason=d["reason"], seconds=0.0, data=d.get("data", []), cached=True)

    def _store(self, tree_id: str, ev_digest: str, tool_digest: str, ev: Evaluation) -> None:
        if not self.comp.deterministic or ev.failure is Outcome.INFRA:
            return
        write_json(self._cache_path(tree_id, ev_digest, tool_digest), {
            "gates": [g.as_dict() for g in ev.gates], "values": ev.values, "spread": ev.spread,
            "repeats": ev.repeats, "degraded_by": ev.degraded_by,
            "failure": ev.failure.value if ev.failure else None, "reason": ev.reason,
            "data": ev.data})

    def preflight(self, base_ref: str | None = None) -> dict[str, Any]:
        """Static checks, toolchain, and one full evaluation of the base commit."""
        rep = self.static_check()
        if not rep["ok"]:
            return rep
        try:
            self.hard_check()
        except (BudgetExhausted, OPCError) as exc:
            rep["ok"] = False
            rep["problems"].append(str(exc))
            return rep
        if base_ref is not None:
            rep["base_commit"] = rev_parse(self.root, base_ref)
        ws = self.workspaces("preflight")
        out = self.root / ".opc" / "local" / "preflight"
        try:
            ev, meas, tree = self.evaluate_commit(ws, rep["base_commit"], "", out, "baseline")
            self.ledger.charge(self.ledger.preparation_scope(self.task.task_id),
                               None, "preflight", Cost(ev.seconds, 0, 0.0))
            rep["toolchain"] = self.domain(tree).toolchain()[1]
            self.workers(tree)
        finally:
            ws.drop_all()
        rep["gates"] = [g.as_dict() for g in ev.gates]
        if ev.failure is Outcome.BROKEN and not self.task.acceptance.objective_metric:
            rep["baseline_failure"] = ev.reason
            rep["baseline_metrics"] = None
            return rep
        if ev.failure is not None:
            rep["ok"] = False
            rep["problems"].append("baseline fails gate: %s (%s)" % (ev.reason, ev.failure.value))
            return rep
        missing = [m for m in rep["required_metrics"] if m not in meas.values]
        if missing:
            rep["ok"] = False
            rep["problems"].append("baseline did not report required metrics: %s; the acceptance "
                                   "rule could never be evaluated" % ", ".join(missing))
        for c in self.task.acceptance.constraints:
            if c.relative_to_champion is None and c.metric in meas.values:
                why = acceptance.check(c, meas.values, meas.values)
                if why:
                    rep["warnings"].append("baseline already violates constraint: " + why)
        if acceptance.target_met(self.task.acceptance, meas.values):
            rep["warnings"].append("baseline already meets the target; expert decides whether to continue")
        rep["baseline_metrics"] = meas.values
        rep["degraded_by"] = meas.degraded_by
        return rep

    # ------------------------------------------------------------------- runs
    def open_run(self, new_run: bool = False, direction: str | None = None,
                 base_ref: str | None = None, *, switch_backend: bool = False) -> str:
        if switch_backend and not new_run:
            raise OPCError("explicit backend switch requires a new Run")
        if new_run:
            self.check_unknown_executions()
        if new_run and self.requested_run_id:
            raise OPCError("--run-id selects an existing Run; it cannot create a new Run")
        if new_run:
            self.run_id = None
            self.task = TaskSpec.load(self.root, self.task.task_id, self.requested_revision)
            self.worker_config = load_worker_config(self.root)
            self.resolved_workers = self.resolve_workers()
            self.max_concurrency = load_max_concurrency(self.root, self.task.configuration_sources)
            self._workers = None
            self.comp = ComponentConfig.load(self.root, self.task.component)
        previous = self.ledger.latest_run(self.task.task_id)
        if previous is not None:
            origins = self.ledger.events(previous["run_id"], "budget_origin")
            self._budget_origin = origins[-1]["body"] if origins else {}
        if switch_backend:
            if previous is None:
                raise OPCError("backend switch requires a previous Run")
            prior_calls = self.ledger.calls(previous["run_id"])
            if (previous["state"] == "active" or any(c["state"] in ("dispatched", "unknown", "running")
                                                     for c in prior_calls)):
                raise OPCError("backend switch requires a quiescent previous Run with no unknown execution")
            prior = self.bindings.artifact_root / self.project.project_id / self.task.task_id / previous["run_id"] / "frozen/baseline.json"
            old_workers = json.loads(prior.read_text(encoding="utf-8"))["execution"]["workers"]
            old_kind, new_kind = old_workers["expert"]["kind"], self.resolved_workers["expert"]["kind"]
            if old_kind not in ("codex", "dsh") or new_kind not in ("codex", "dsh") or old_kind == new_kind:
                raise OPCError("backend switch requires an explicit change between Codex and DSH")
            totals = self.ledger.task_totals(self.task.task_id)
            self._budget_origin = dict(wall_seconds=totals["wall_seconds"], tokens=totals["tokens"],
                                       after_event=self.ledger.db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0],
                                       source_run=previous["run_id"], previous_backend=old_kind, backend=new_kind)
        last = None if new_run else self.ledger.select_run(
            self.task.task_id, self.requested_revision, self.requested_run_id)
        if last is not None:
            self.restore_run(last["run_id"])
            if last["state"] != "closed":
                if not self.project.execution_enabled:
                    raise OPCError("execution_enabled=false; cannot resume execution")
                if self.evaluator_digest(last["base_commit"])[0] != last["evaluator_digest"]:
                    raise OPCError("frozen evaluator source is unavailable or changed; cannot resume")
                if self.delivery_accounting():
                    self.enable_delivery()
                if direction:
                    self.ledger.event(self.run_id, "direction", None, text=direction)
            return self.run_id
        source_digest = hashlib.sha256(canonical_json(json.loads(self.task.path.read_text(encoding="utf-8-sig"))).encode()).hexdigest()
        frozen_digest = TaskSpec.frozen_digest(self.root, self.task.task_id, self.task.revision)
        if frozen_digest is not None and source_digest != frozen_digest:
            raise OPCError("frozen revision %s cannot be overwritten; save a new revision" % self.task.revision)
        rep = self.static_check()
        if not rep["ok"]:
            raise OPCError("static check failed:\n  " + "\n  ".join(rep["problems"]))
        bound = next((r for r in self.ledger.runs()
                      if r["task_id"] == self.task.task_id and r["revision"] == self.task.revision), None)
        if bound is not None and bound["evaluator_digest"] != rep["evaluator_digest"]:
            raise OPCError("frozen revision %s evaluation or scope changed; save a new revision" % self.task.revision)
        base = rev_parse(self.root, base_ref) if base_ref else rep["base_commit"]
        if base_ref:
            # the evaluator must be the task's, whatever commit the run starts from
            if self.evaluator_digest(base)[0] != rep["evaluator_digest"]:
                raise OPCError("--base %s carries a different evaluator than the task base"
                               % base_ref)
        if not self.task.acceptance.objective_metric or self.task.raw.get("profile"):
            capability = self.preflight(base_ref=base)
            if not capability["ok"]:
                raise OPCError("preflight failed:\n  " + "\n  ".join(capability["problems"]))
        tool_digest = self.toolchain_digest(base)
        self.run_id = self.ledger.create_run(
            task_id=self.task.task_id, revision=self.task.revision,
            task_digest=self.task.digest, component=self.comp.component_id, base_commit=base,
            evaluator_digest=rep["evaluator_digest"], toolchain_digest=tool_digest,
            champion_ref=self.ref, direction=direction or self.task.direction)
        if self._budget_origin:
            self.ledger.event(self.run_id, "budget_origin", **self._budget_origin)
        if self.delivery_accounting():
            self.enable_delivery()
        write_json(self.artifact_dir() / "frozen" / "task.json", self.task.raw)
        write_json(self.artifact_dir() / "frozen" / "component.json", self.comp.raw)
        write_json(self.artifact_dir() / "frozen" / "baseline.json",
                   {"commit": base, "evaluator_digest": rep["evaluator_digest"],
                    "evaluator_files": rep["evaluator_files"], "toolchain_digest": tool_digest,
                    "source_commit": rep["base_commit"], "source_contract_digest": source_digest,
                    "brief_source": rep.get("brief_source"),
                    "sources": {"contract": self.task.path.relative_to(self.root).as_posix(),
                                "workers": ".opc/local/workers.json", "bindings": ".opc/local/bindings.json"},
                    "execution": {"task_digest": self.task.digest, "budget": asdict(self.task.budget),
                                  "configuration_sources": self.task.configuration_sources,
                                  "budget_origin": self._budget_origin,
                                  "project_hard_limits": self._project_hard_limits,
                                  "workers": self.resolved_workers,
                                  "worker_config": self.worker_config,
                                  "max_concurrency": self.max_concurrency,
                                  "bindings": {"artifact_root": str(self.bindings.artifact_root),
                                               "workspace_root": str(self.bindings.workspace_root)}},
                    "startpoint": {"kind": "explicit_base" if base_ref else "task_base",
                                   "ref": base_ref or self.task.base_ref, "commit": base}})
        self.log("run %s created on %s" % (self.run_id, base[:12]))
        return self.run_id

    def restore_run(self, run_id: str) -> None:
        """Load the execution snapshot without reapplying mutable defaults."""
        run = self.ledger.select_run(self.task.task_id, None, run_id)
        self.run_id = run_id
        latest = self.ledger.latest_run(run["task_id"])
        self.ref = (run["champion_ref"] if latest["run_id"] == run_id else
                    "refs/opc/%s/%s" % (run["task_id"], run_id))
        frozen = self.artifact_dir() / "frozen"
        try:
            baseline = json.loads((frozen / "baseline.json").read_text(encoding="utf-8"))
            task = json.loads((frozen / "task.json").read_text(encoding="utf-8"))
            component = json.loads((frozen / "component.json").read_text(encoding="utf-8"))
            execution = baseline.get("execution")
            if execution is None and run["state"] != "closed":
                raise KeyError("execution")
        except (OSError, ValueError, KeyError) as exc:
            raise OPCError("run %s remains readable but cannot resume: missing frozen execution source (%s)"
                           % (run_id, exc)) from exc
        self.task = TaskSpec.load(self.root, run["task_id"], run["revision"],
                                  source=task, resolve_local=False)
        if execution:
            self._budget_origin = execution.get("budget_origin", {})
            self._project_hard_limits = execution.get("project_hard_limits", {})
            if self.task.digest != execution["task_digest"]:
                raise OPCError("frozen task source differs from execution identity; use original sources")
            self.task.budget = Budget(**execution["budget"])
            self.task.digest = execution["task_digest"]
            self.worker_config = execution["worker_config"]
            self.max_concurrency = execution.get("max_concurrency", 3)
            self.resolved_workers = execution["workers"]
            if any(v["kind"] != "scripted" and not v.get("frozen_config") for v in self.resolved_workers.values()) and run["state"] != "closed":
                raise OPCError("legacy Run remains readable but cannot resume: CLI installation was not frozen")
            if any(v["kind"] == "codex" and not v.get("native_defaults_frozen")
                   for v in self.resolved_workers.values()) and run["state"] != "closed":
                raise OPCError("legacy Run remains readable but cannot resume: native Codex model/provider selection was not frozen")
            self._workers = None
            current_bindings = {key: str(value) for key, value in vars(self.bindings).items()}
            if current_bindings != execution["bindings"]:
                self._binding_repair = {"previous": execution["bindings"], "current": current_bindings}
            self.task.configuration_sources = execution.get("configuration_sources", {})
            if execution["task_digest"] != run["task_digest"]:
                raise OPCError("frozen execution identity differs from ledger; use original sources")
        self.comp = ComponentConfig.load(self.root, run["component"], source=component)
        original_component = json.loads(git("show", run["base_commit"] + ":.opc/components/" + run["component"] + ".json", cwd=self.root))
        if component != original_component:
            raise OPCError("frozen component permissions or evaluator changed; save a new revision and Run")
        if baseline["commit"] != run["base_commit"]:
            raise OPCError("frozen base identity differs from ledger; use original sources")
        if self.evaluator_digest(run["base_commit"])[0] != run["evaluator_digest"]:
            raise OPCError("frozen evaluator source is unavailable or changed; a changed contract needs a new revision")
        self._domain = self._rule = None
        self._eval_tree = None

    def toolchain_digest(self, commit: str) -> str:
        def checked(domain):
            digest, details = domain.toolchain()
            unavailable = [key + ": " + value for key, value in details.items()
                           if str(value).startswith("unavailable:")]
            if unavailable:
                raise OPCError("toolchain unavailable: " + "; ".join(unavailable))
            return digest
        if self._domain is not None:
            return checked(self._domain)
        ws = self.workspaces("toolchain")
        try:
            tree = ws.checkout("probe", commit)
            return checked(self.domain(tree))
        finally:
            ws.drop_all()

    def measure_champion(self, ws: Workspaces, commit: str, attempt: int | None,
                         reason: str, *, fresh: bool = False) -> Measurements:
        out = self.artifact_dir() / "champion" / ("%s-%d" % (commit[:12], time.time_ns()))
        if reason == "baseline":
            saved = [c for c in self.ledger.calls(self.run_id) if c["role"] == "evaluator"
                     and c["attempt_no"] is None and c["input"].get("commit") == commit
                     and c["result"] is not None and not c["result"]["output"].get("failure")]
            if saved:
                out = Path(saved[-1]["receipt_path"]).parent
        ev, meas, tree = self.evaluate_commit(ws, commit, "", out, "champion", fresh=fresh)
        ws.drop(tree)
        if ev.failure is not None:
            raise OPCError("champion %s fails its own gates (%s): %s"
                           % (commit[:12], ev.failure.value, ev.reason))
        self.ledger.set_champion(self.run_id, commit, meas, attempt, reason)
        return meas

    def move_champion_ref(self, new: str, old: str | None) -> None:
        """The task branch follows the latest run; every run also keeps its own ref so
        a later run started from another base cannot erase an earlier champion."""
        cas_update_ref(self.root, self.ref, new, old)
        git("update-ref", "refs/opc/%s/%s" % (self.task.task_id, self.run_id), new, cwd=self.root)

    def reconcile(self, ws: Workspaces) -> None:
        """Make ledger and git agree before anything new is dispatched."""
        run = self.ledger.run(self.run_id)
        self.reconcile_calls()
        if getattr(self, "_binding_repair", None):
            repairs = self.ledger.events(self.run_id, "binding_repaired")
            if not repairs or repairs[-1]["body"] != self._binding_repair:
                self.ledger.event(self.run_id, "binding_repaired", **self._binding_repair)
        for a in self.ledger.open_attempts(self.run_id):
            n = a["attempt_no"]
            intents = [e for e in self.ledger.events(self.run_id, "champion_intent")
                       if e["attempt"] == n]
            ref = read_ref(self.root, self.ref)
            if intents and a["metrics"]:
                new = intents[-1]["body"]["new"]
                if ref == new:
                    meas = Measurements.from_dict(a["metrics"])
                    self.ledger.set_champion(self.run_id, new, meas, n,
                                             "recovered after controller stop")
                    self.ledger.finish_attempt(self.run_id, n, Outcome.IMPROVEMENT.value,
                                               "champion move recovered on resume",
                                               a["gain"] or 0.0, Cost())
                    continue
            if (not any(c["attempt_no"] == n for c in self.ledger.calls(self.run_id))
                    and not any(e["attempt"] == n for e in self.ledger.events(self.run_id, "work_selected"))):
                raise OPCError("Attempt %d cannot resume: missing reliable Call/input records; "
                               "existing artifacts remain readable" % n)
        current = self.toolchain_digest(run["base_commit"])
        self._compatibility = run_compatibility(self.artifact_dir() / "frozen", run)
        self._compatibility["execution"] = {"state": "resumable", "reason": "frozen sources and required tools are available"}
        drift = current != run["toolchain_digest"]
        self._compatibility["measurement"] = {"state": "reusable", "reason": "toolchain matches existing measurements"}
        if drift:
            self._compatibility["measurement"] = {"state": "requires_recheck", "reason": "toolchain changed; prior measurements cannot establish current comparability"}
            self.remeasure_environment(ws, current)
            self._compatibility["measurement"] = {"state": "rechecked", "reason": "old measurements retained; affected baseline and selected work freshly measured"}
        if not self.task.acceptance.objective_metric:
            return
        champ = self.ledger.champion(self.run_id)
        if champ is None:
            self.log("measuring baseline %s" % run["base_commit"][:12])
            meas = self.measure_champion(ws, run["base_commit"], None, "baseline")
            self.move_champion_ref(run["base_commit"], read_ref(self.root, self.ref))
            self.log("baseline metrics %s" % json.dumps(meas.values))
            return
        ref = read_ref(self.root, self.ref)
        if ref is None:
            self.move_champion_ref(champ[0], None)
        elif ref != champ[0]:
            raise OPCError("%s points at %s but the ledger champion is %s; the ref was moved "
                           "outside OPC" % (self.ref, ref[:12], champ[0][:12]))
    def remeasure_environment(self, ws: Workspaces, current: str) -> None:
        """Rebuild only this Run's comparison baseline and current selected work."""
        run = self.ledger.run(self.run_id)
        out = self.artifact_dir() / "environment" / str(time.time_ns())
        ev, meas, tree = self.evaluate_commit(ws, run["base_commit"], "", out / "baseline", "environment-baseline", fresh=True)
        ws.drop(tree)
        if ev.failure is not None and (self.task.acceptance.objective_metric or ev.failure is not Outcome.BROKEN):
            raise OPCError("changed environment baseline failed: " + ev.reason)
        self.ledger.event(self.run_id, "measurement_baseline", commit=run["base_commit"],
                          metrics=meas.as_dict() if meas else None, cached=False, reason=ev.reason,
                          toolchain_digest=current, evidence=str(out / "baseline/evaluation.json"))
        champ = self.ledger.champion(self.run_id)
        if champ:
            self.hard_check()
            self.measure_champion(ws, champ[0], None, "re-measured: toolchain changed", fresh=True)
        else:
            selected = self.working_commit()
            if selected != run["base_commit"]:
                self.hard_check()
                ev, _, tree = self.evaluate_commit(ws, selected, "", out / "working", "environment-working", fresh=True)
                ws.drop(tree)
                if ev.failure is not None and ev.failure is not Outcome.BROKEN:
                    raise OPCError("changed environment working version failed: " + ev.reason)
        self.ledger.update_toolchain(self.run_id, current)


    # ----------------------------------------------------------------- budget
    def enable_delivery(self) -> None:
        """Request delivery accounting, persisting it as soon as a run is bound."""
        self._delivery_requested = True
        if self.run_id and not self.ledger.events(self.run_id, "delivery"):
            self.ledger.event(self.run_id, "delivery", accounting_scope="task")

    def delivery_accounting(self) -> bool:
        # Recognize existing repair/report records as well as newly marked runs.
        return bool(getattr(self, "_delivery_requested", False) or
                    (self.run_id and any(self.ledger.events(self.run_id, kind)
                     for kind in ("delivery", "delivery_repair", "promotion_report"))))

    def spent(self) -> dict[str, Any]:
        t = self.ledger.task_totals(self.task.task_id)
        attempts = [a for r in self.ledger.runs() if r["task_id"] == self.task.task_id
                    for a in self.ledger.attempts(r["run_id"])]
        t["search_attempts"] = sum(1 for a in attempts if a["outcome"] and
                                   Outcome(a["outcome"]).counts_as_search)
        t["attempts"] = len(attempts)
        if self._budget_origin:
            # Scope by original Run ownership, so a late correction to an older
            # Call remains historical usage rather than consuming the new quota.
            row = self.ledger.db.execute(
                "SELECT COALESCE(SUM(c.wall_seconds),0), COALESCE(SUM(c.tokens),0) FROM charges c "
                "JOIN runs r ON c.run_id=r.run_id WHERE r.task_id=? AND r.revision!='preparation' "
                "AND r.rowid > (SELECT rowid FROM runs WHERE run_id=?)",
                (self.task.task_id, self._budget_origin["source_run"])).fetchone()
            t["wall_seconds"], t["tokens"] = row
        return t

    def effective_budget(self):
        """Explicit Task allowance changes preserve the frozen execution contract."""
        caps = {}
        scope = self.ledger.preparation_scope(self.task.task_id, create=False)
        if scope:
            for event in self.ledger.events(scope, "task_budget_authorized"):
                caps.update(event["body"])
        budget = replace(self.task.budget, **caps)
        for key, limit in self.task.raw.get("hard_limits", {}).items():
            value = getattr(budget, key)
            setattr(budget, key, min(value, limit) if value is not None else limit)
        return budget

    def unresolved_usage(self, scope: str) -> list[dict[str, Any]]:
        unknown = self.ledger.unresolved_accounting(scope)
        lifetime = (self.effective_budget().max_usd is not None
                    or "max_tokens" in self.task.raw.get("hard_limits", {})
                    or self._project_hard_limits.get("max_tokens") is not None)
        cutoff = 0 if lifetime else self._budget_origin.get("after_event", 0)
        return [event for event in unknown if event["seq"] > cutoff]

    def accounting_required(self) -> bool:
        b = self.effective_budget()
        return b.max_tokens is not None or b.max_usd is not None

    def budget_left(self) -> dict[str, Any]:
        b, s = self.effective_budget(), self.spent()
        left = {"attempts": b.max_attempts - s["search_attempts"] if b.max_attempts is not None else None,
                "wall_seconds": (round(b.max_wall_seconds - s["wall_seconds"], 1)
                                 if b.max_wall_seconds is not None else None)}
        if b.max_tokens is not None:
            left["tokens"] = b.max_tokens - s["tokens"]
        if b.max_usd is not None:
            left["usd"] = round(b.max_usd - s["usd"], 4) if s["usd_known"] else "unknown"
        for limits, project_scope in ((self.task.raw.get("hard_limits", {}), False),
                                      (self._project_hard_limits, True)):
            for key, cap in limits.items():
                if cap is None:
                    continue
                metric = {"max_tokens": "tokens", "max_wall_seconds": "wall_seconds"}[key]
                used = (self.ledger.db.execute("SELECT COALESCE(SUM(%s),0) FROM charges" % metric).fetchone()[0]
                        if project_scope else self.ledger.task_totals(self.task.task_id)[metric])
                available = cap - used
                left[metric] = min(left[metric], available) if left.get(metric) is not None else available
        return left

    def admit(self) -> None:
        """Ask before spending. The estimate is the mean decided attempt so far."""
        b, s = self.effective_budget(), self.spent()
        self.hard_check()
        if b.max_attempts is not None and s["search_attempts"] >= b.max_attempts:
            raise BudgetExhausted("max_attempts", "%d search attempts used" % s["search_attempts"])
        done = [a for a in self.ledger.attempts(self.run_id) if a["cost"]]
        est_wall = sum(a["cost"]["wall_seconds"] for a in done) / len(done) if done else 0.0
        est_tok = sum(a["cost"]["tokens"] for a in done) / len(done) if done else 0.0
        if self.delivery_accounting():
            reserve = self.ledger.db.execute(
                "SELECT MAX(c.wall_seconds), MAX(c.tokens) FROM charges c JOIN runs r ON c.run_id=r.run_id "
                "WHERE r.task_id=? AND c.role IN ('evaluator','reviewer')", (self.task.task_id,)).fetchone()
            est_wall += reserve[0] or 0
            est_tok += reserve[1] or 0
        if b.max_wall_seconds is not None and s["wall_seconds"] + est_wall > b.max_wall_seconds:
            raise BudgetExhausted("max_wall_seconds", "spent %.0fs, next ~%.0fs, cap %.0fs"
                                  % (s["wall_seconds"], est_wall, b.max_wall_seconds))
        if b.max_tokens is not None and s["tokens"] + est_tok > b.max_tokens:
            raise BudgetExhausted("max_tokens", "spent %d, next ~%d, cap %d"
                                  % (s["tokens"], est_tok, b.max_tokens))
        if b.max_usd is not None:
            if not s["usd_known"]:
                raise BudgetExhausted("max_usd", "some charges have unknown price")
            if s["usd"] >= b.max_usd:
                raise BudgetExhausted("max_usd", "spent %.4f of %.4f" % (s["usd"], b.max_usd))

    def dispatch_boundary(self) -> None:
        if self.run_id:
            command = self.ledger.control(self.run_id)
            if command == "pause":
                raise DispatchStopped("paused", "paused by user at call boundary")
            if command == "stop":
                raise DispatchStopped("closed", "stopped by user at call boundary")

    def hard_check(self) -> None:
        """Between steps of one attempt: stop as soon as a cap is crossed."""
        self.dispatch_boundary()
        self.check_unknown_executions()
        b, s = self.effective_budget(), self.spent()
        with self._execution_lock:
            active_wall = sum((end or time.monotonic()) - start for start, end in self._inflight.values())
        for key, cap in self.task.raw.get("hard_limits", {}).items():
            total_key = {"max_tokens": "tokens", "max_wall_seconds": "wall_seconds"}[key]
            if self.task.configuration_sources.get("hard_limits." + key) == "project":
                used = self.ledger.db.execute("SELECT COALESCE(SUM(%s),0) FROM charges" % total_key).fetchone()[0]
            else:
                used = self.ledger.task_totals(self.task.task_id)[total_key]
            if used + (active_wall if key == "max_wall_seconds" else 0) >= cap:
                raise BudgetExhausted(key, "lifetime hard limit reached")
        for key, cap in self._project_hard_limits.items():
            total_key = {"max_tokens": "tokens", "max_wall_seconds": "wall_seconds"}[key]
            used = self.ledger.db.execute("SELECT COALESCE(SUM(%s),0) FROM charges" % total_key).fetchone()[0]
            if cap is not None and used + (active_wall if key == "max_wall_seconds" else 0) >= cap:
                raise BudgetExhausted(key, "project lifetime hard limit reached")
        if self._project_hard_limits.get("max_tokens") is not None:
            scopes = [row[0] for row in self.ledger.db.execute(
                "SELECT DISTINCT run_id FROM events WHERE kind='accounting_unknown'")]
            if any(self.ledger.unresolved_accounting(scope) for scope in scopes):
                raise OPCError("project usage accounting incomplete; no new dispatch")
        if self.accounting_required() and any(self.unresolved_usage(r["run_id"])
                for r in self.ledger.runs() if r["task_id"] == self.task.task_id):
            raise OPCError("usage accounting incomplete; no new dispatch")
        if self.delivery_accounting():
            if b.max_usd is not None and (not s["usd_known"] or s["usd"] >= b.max_usd):
                raise BudgetExhausted("max_usd", "delivery budget unavailable")
        if self.preparation and not self.run_id:
            if self.preparation_receipt().get("state") != "ready":
                raise OPCError("preparation is not ready; no formal dispatch")
        if self.preparation and self.accounting_required() and self.unresolved_usage(self.preparation):
            raise OPCError("usage accounting incomplete; no new dispatch")
        if b.max_wall_seconds is not None and s["wall_seconds"] + active_wall >= b.max_wall_seconds:
            raise BudgetExhausted("max_wall_seconds", "crossed mid-attempt")
        if b.max_tokens is not None and s["tokens"] >= b.max_tokens:
            raise BudgetExhausted("max_tokens", "crossed mid-attempt")

    def stop_condition(self) -> StopDecision | None:
        decided = [a for a in self.ledger.attempts(self.run_id) if a["outcome"]]
        infra = 0
        for a in reversed(decided):
            if Outcome(a["outcome"]) is not Outcome.INFRA:
                break
            infra += 1
        if infra >= self.task.budget.max_consecutive_infra:
            return StopDecision("blocked", "%d consecutive infrastructure failures; last: %s"
                                % (infra, decided[-1]["reason"]))
        return None

    # --------------------------------------------------------------- feedback
    def backfill_history(self) -> None:
        """Reuse older final replies and measurement artifacts on resume, when present.

        Missing artifacts stay missing. No execution, measurement or interpretation
        is inferred from a patch, and no worker is dispatched by this migration.
        """
        calls = self.ledger.events(self.run_id, "worker_call")
        for a in self.attempt_records():
            n = a["attempt_no"]
            adir = self.attempt_dir(n)
            if a["execution"] is None:
                design = [e["body"] for e in calls if e["attempt"] == n
                          and e["body"].get("role") == "designer"]
                if design:
                    summary = ""
                    last = adir / "designer/designer-last.txt"
                    if last.is_file():
                        summary = last.read_text(encoding="utf-8", errors="replace")[-2000:]
                    else:
                        events = adir / "designer/designer-events.jsonl"
                        if events.is_file():
                            from ..adapters.dsh import parse_events
                            summary = parse_events(events.read_text(encoding="utf-8"))["text"][-2000:]
                    self.ledger.event(self.run_id, "execution", n,
                                      completed=design[-1]["ok"], summary=summary)
            evaluation = adir / "eval/evaluation.json"
            if a["experiment"] is None and evaluation.is_file():
                ev = json.loads(evaluation.read_text(encoding="utf-8"))
                data = ev.get("data", [])
                if not data:
                    for g in a["gates"] or []:
                        spec = next((s for s in self.comp.gates if
                                     s.gate_id == g["gate_id"].split("#")[0]), None)
                        if spec and spec.metrics and "{out}" in spec.metrics:
                            path = Path(spec.metrics.replace("{out}", g["log_dir"]))
                            if path.is_file():
                                try:
                                    data.append({"gate": g["gate_id"], "data": experimental_data(
                                                 json.loads(path.read_text(encoding="utf-8")))})
                                except (OSError, ValueError):
                                    pass  # retain missing evidence rather than fabricate it
                cached = ev.get("cached")
                if cached is None:
                    cached = any(g.get("detail", "").startswith("cached;")
                                 for g in ev.get("gates", []))
                self.ledger.event(self.run_id, "experiment", n,
                                  status="failed" if ev.get("failure") else "completed",
                                  data=data, cached=cached, values=(a["metrics"] or {}).get("values", {}))

    def attempt_records(self) -> list[dict[str, Any]]:
        """Project existing events onto attempts; no second history authority."""
        rows = self.ledger.attempts(self.run_id)
        by_no = {a["attempt_no"]: a for a in rows}
        for a in rows:
            a.update(parent=a["champion_before"], candidate=None, execution=None,
                     experiment=None, conclusion=None, comparison=None)
            a["recoverable_patch"] = bool(a["patch_sha"] and
                                          (self.attempt_dir(a["attempt_no"]) / "candidate.patch").is_file())
        for event in self.ledger.events(self.run_id):
            a = by_no.get(event["attempt"])
            if a is None:
                continue
            body = event["body"]
            if event["kind"] == "development_parent":
                a["parent"] = body["commit"]
                a["base_attempt"] = body.get("base_attempt")
            elif event["kind"] == "candidate_saved":
                a["candidate"] = body["commit"]
                a["parent"] = body["parent"]
            elif event["kind"] in ("execution", "experiment"):
                a[event["kind"]] = body
            elif event["kind"] == "comparison_baseline":
                a["comparison"] = body
            elif event["kind"] == "conclusion":
                a["conclusion"] = body["text"]
        for a in rows:
            a["adopted_claims"] = list((a["plan"] or {}).get("adopted_claims") or [])
            for ref in (a["execution"] or {}).get("adopted_claims") or []:
                if ref not in a["adopted_claims"]:
                    a["adopted_claims"].append(ref)
        return rows

    def prior_run_materials(self) -> list[dict[str, Any]]:
        """References for an explicit backend change, separate from this Run's feedback."""
        source = self._budget_origin.get("source_run")
        materials = []
        while source:
            run = self.ledger.run(source)
            root = self.artifact_dir().parent / source
            attempts = self.ledger.attempts(source)
            concluded = {e["attempt"] for e in self.ledger.events(source, "conclusion")}
            decisions = {e["body"]["call_id"] for e in self.ledger.events(source, "expert_decision")}
            calls = [c for c in self.ledger.calls(source) if c["call_id"] in decisions]
            materials.append({"run_id": source, "revision": run["revision"], "state": run["state"],
                              "evidence_root": str(root),
                              "results": [{"attempt": a["attempt_no"], "outcome": a["outcome"],
                                           "path": str(root / "attempts" / ("a%06d" % a["attempt_no"]) / "decision.json")}
                                          for a in attempts[-HISTORY_WINDOW:] if a["outcome"]],
                              "decisions": [{"call_id": c["call_id"], "path": str(root / Path(c["receipt_path"]).relative_to(
                                                Path(c["input"]["tree"]).parent))}
                                            for c in calls[-HISTORY_WINDOW:]],
                              "pending_feedback": [a["attempt_no"] for a in attempts
                                                   if a["outcome"] and a["attempt_no"] not in concluded]})
            origins = self.ledger.events(source, "budget_origin")
            source = origins[-1]["body"].get("source_run") if origins else None
        return materials

    def context(self, n: int, champ: tuple[str, Measurements], focus: str | None,
                tree: Path) -> dict[str, Any]:
        self.sync_results()
        attempts = self.attempt_records()
        champions = self.ledger.champions(self.run_id)
        decided = [a for a in attempts if a["outcome"] and a["plan"]]
        keep = {a["attempt_no"] for a in decided[-HISTORY_WINDOW:]}
        metric_names = acceptance.required_metrics(self.task.acceptance)
        def metric_view(values):
            return {k: values[k] for k in metric_names if k in values}
        def measurement_view(measurement):
            if not measurement:
                return None
            return {**measurement, "values": metric_view(measurement.get("values") or {}),
                    "spread": metric_view(measurement.get("spread") or {})}
        history = []
        for a in decided:
            if a["attempt_no"] not in keep:
                continue
            plan = a["plan"]
            prior = [c for c in champions if c["commit_sha"] == a["champion_before"]
                     and c["at"] <= a["finished_at"]
                     and (c["attempt_no"] is None or c["attempt_no"] <= a["attempt_no"])]
            metrics = measurement_view(a["metrics"])
            experiment = a["experiment"]
            if experiment:
                experiment = dict(experiment)
                experiment.pop("values", None)
                data = []
                for entry in experiment.get("data", []):
                    entry = dict(entry)
                    payload = dict(entry.get("data") or {})
                    if "metrics" in payload:
                        payload["metrics"] = metric_view(payload["metrics"])
                    entry["data"] = payload
                    data.append(entry)
                experiment["data"] = bounded_data(data)
                experiment["evidence"] = str(self.attempt_dir(a["attempt_no"]) / "eval/evaluation.json")
            # No gate verdict text, worker errors or raw logs in expert context.
            history.append({
                "attempt": a["attempt_no"],
                **{k: plan.get(k) for k in ("title", "hypothesis", "changes", "expected", "falsifier", "experiment_id")},
                "plan_params": plan.get("params"), "parent": a["parent"],
                "candidate": a["candidate"], "outcome": a["outcome"],
                "adopted_claims": a["adopted_claims"],
                "execution": bounded_data(a["execution"]),
                "experiment": experiment or {
                    "status": "not_recorded" if a["gates"] else "not_executed", "data": []},
                "champion_before": measurement_view(a["comparison"]) or (
                    {"values": metric_view(prior[-1]["metrics"]["values"])} if prior else None),
                "metrics": {k: metrics.get(k) for k in ("values", "spread", "repeats", "degraded_by")}
                if metrics else None, "conclusion": a["conclusion"]})
        run = self.ledger.run(self.run_id)
        directions = [e["body"]["text"] for e in self.ledger.events(self.run_id, "direction")]
        base = champions[0] if champions else {"commit_sha": run["base_commit"], "metrics": {"values": {}}}
        baselines = self.ledger.events(self.run_id, "measurement_baseline")
        if baselines and baselines[-1]["body"].get("metrics"):
            base = {"commit_sha": run["base_commit"], "metrics": baselines[-1]["body"]["metrics"]}
        acc = self.task.acceptance
        streak = 0
        for a in reversed(attempts):
            if a["outcome"] == Outcome.IMPROVEMENT.value:
                break
            if a["outcome"] and Outcome(a["outcome"]).counts_as_search:
                streak += 1
        # Onboard already maps task-brief background/done criteria/constraints to
        # these notes. Never inject component.context_files source contents or
        # arbitrary custom-domain material into the expert's input.
        notes = [p for p in self.comp.context_files if p.startswith(".opc/context/")
                 and p.endswith(".md") and ".." not in Path(p).parts]
        if not notes:
            notes = [".opc/context/" + p + ".md" for p in ("PROJECT", "REQUIREMENTS", "DECISIONS")]
        background = {}
        for rel in notes[:2]:
            path = tree / rel
            if path.is_file() and not path.is_symlink():
                background[rel] = {"excerpt": path.read_text(encoding="utf-8")[:1500], "source": str(self.root / rel)}
        return {
            "attempt": n, "focus": focus,
            **({"task_results": self.results_context()} if self.task.raw.get("results_path") else {}),
            "task": {"goal": self.task.goal,
                     "direction": directions[-1] if directions else run["direction"],
                     "requirements": self.task.requirements,
                     "acceptance": {"objective": {"metric": acc.objective_metric,
                                                  "direction": acc.direction,
                                                  "min_rel_gain": acc.min_rel_gain} if acc.objective_metric else None,
                                    "constraints": [c.describe() for c in acc.constraints],
                                    "target": acc.target.describe() if acc.target else None}},
            "component": {"id": self.comp.component_id, "description": self.comp.description,
                          "editable": self.comp.editable, "scratch": self.comp.scratch,
                          "frozen": self.comp.frozen, "evaluator_files": self.comp.evaluator_files},
            "working_version": {"commit": champ[0]},
            "champion": {"commit": champ[0], "values": metric_view(champ[1].values),
                         "params": next((a["plan"].get("params") for a in reversed(attempts)
                             if a["candidate"] == champ[0] and a["plan"] and a["plan"].get("params")), None)
                         if self.worker_spec("expert").kind == "scripted" else None} if acc.objective_metric else None,
            "baseline": {"commit": base["commit_sha"], "values": metric_view(base["metrics"]["values"])},
            "history": history, "claims": self.claims(),
            "decision_conflicts": [e["body"] for e in self.ledger.events(self.run_id, "expert_conflict")],
            "background": background, "budget_left": self.budget_left(),
            "pending_feedback": [{"attempt": a["attempt_no"], "evidence": str(self.attempt_dir(a["attempt_no"]))}
                                 for a in decided if a["conclusion"] is None],
            "evidence_root": str(self.artifact_dir()),
            "prior_runs": self.prior_run_materials(),
            "progress": {"target_met": acceptance.target_met(acc, champ[1].values),
                         "no_gain_streak": streak, "stagnation_hint": self.task.budget.max_stagnation},
            "candidates": [{"attempt": a["attempt_no"], "commit": a["candidate"],
                            "parent": a["parent"], "title": (a["plan"] or {}).get("title"),
                            "evidence": str(self.attempt_dir(a["attempt_no"]))}
                           for a in attempts[-HISTORY_WINDOW:] if a["candidate"] or a["recoverable_patch"]],
            "tried_params": [a["plan"]["params"] for a in decided
                             if a["plan"].get("params") is not None
                             and a["outcome"] != Outcome.INFRA.value],
        }

    def authorized_claims(self, task_id: str | None = None, claim_id: str | None = None, *,
                          version: int | None = None, history: bool = False) -> list[dict]:
        """Read own claims and explicitly named foreign material, without write rights."""
        selected = self.task.task_id if task_id is None else task_id
        if selected == self.task.task_id:
            return self.ledger.claims(selected, claim_id, version=version, history=history)
        allowed = {dep['claim_id'] for dep in self.task.raw.get('knowledge_dependencies', [])
                   if dep['task_id'] == selected}
        if not allowed or (claim_id is not None and claim_id not in allowed):
            raise OPCError('claim is outside authorized task material')
        return [claim for claim in self.ledger.claims(selected, claim_id, version=version, history=history) if claim['claim_id'] in allowed]

    def knowledge_context(self, context_path: Path, claims: list[dict]) -> dict:
        """Fixed scoped material for a Call; the ledger alone owns claim state."""
        import sys
        from . import results
        task_ids = [self.task.task_id]
        for dep in self.task.raw.get('knowledge_dependencies', []):
            found = self.authorized_claims(dep['task_id'], dep['claim_id'])
            if not found:
                raise OPCError('unknown knowledge dependency: ' + dep['task_id'] + '/' + dep['claim_id'])
            if dep['task_id'] not in task_ids:
                task_ids.append(dep['task_id'])
            for claim in found:
                if not any(c['task_id'] == claim['task_id'] and c['claim_id'] == claim['claim_id'] for c in claims):
                    claims.extend(results.claim_sources([claim], self.bindings.artifact_root, self.project.project_id))
        latest = {(c['task_id'], c['claim_id']): c['version'] for c in claims}
        history = self.ledger.claims(self.task.task_id, history=True)
        for dep in self.task.raw.get('knowledge_dependencies', []):
            history.extend(self.authorized_claims(dep['task_id'], dep['claim_id'], history=True))
        older = {(c['task_id'], c['claim_id'], c['version']): c for c in history
                 if c['version'] < latest[(c['task_id'], c['claim_id'])]}
        historical = results.claim_sources(list(older.values()), self.bindings.artifact_root, self.project.project_id)
        return dict(task_ids=task_ids, claims=claims, claim_history=historical, context=str(context_path),
                    command=[str(Path(sys.executable).resolve()), str(Path(results.__file__).resolve()), str(context_path)],
                    as_of='fixed_call_input')

    def results_context(self) -> dict:
        from .results import snapshot
        try:
            return {**snapshot(self.root, self.bindings.artifact_root, self.task.raw['results_path']),
                    'claims': self.claims()}
        except (OSError, ValueError, OPCError) as exc:
            return {'entry': self.task.raw.get('results_path'), 'sources': [], 'issues': [str(exc)]}

    def sync_results(self) -> str | None:
        from .results import sync_engine
        try:
            sync_engine(self)
        except (OSError, ValueError, OPCError) as exc:
            self._results_error = str(exc)
            self.log('results registration pending: ' + str(exc))
            return str(exc)
        self._results_error = None
        return None

    def claims(self, claim_id: str | None = None, *,
               version: int | None = None, history: bool = False) -> list[dict]:
        """Task claim entry, with explicit pending feedback and source availability."""
        claims = self.ledger.claims(self.task.task_id, claim_id, version=version, history=history)
        pending = [{"run_id": self.run_id, "attempt": a["attempt_no"]}
                   for a in self.attempt_records()
                   if a["outcome"] and a["conclusion"] is None]
        for claim in claims:
            claim["pending_feedback"] = pending
        from .results import claim_sources
        return claim_sources(claims, self.bindings.artifact_root, self.project.project_id)

    def validate_claims(self, output: dict) -> str | None:
        claims = output.get("claims", [])
        if not isinstance(claims, list):
            return "claims must be a list"
        if not claims:
            return None
        current = {c["claim_id"]: c for c in self.ledger.claims(self.task.task_id)}
        seen = set(current)
        proposed = set()
        for claim in claims:
            if not isinstance(claim, dict):
                return "claim must be an object"
            ident = claim.get("claim_id")
            if not isinstance(ident, str) or not ident.strip() or not portable_path(ident) or "/" in ident:
                return "claim_id must be a stable identifier"
            if ident in proposed:
                return "duplicate claim identity in decision: " + ident
            proposed.add(ident)
            prior = current.get(ident)
            base = claim.get("base_version")
            if prior:
                if type(base) is not int or base < 1:
                    return "existing claim requires base_version: " + ident
            elif base is not None:
                return "unknown claim revision identity: " + ident
            seen.add(ident)
            if claim.get("task_id", self.task.task_id) != self.task.task_id:
                return "claim write outside current task is forbidden"
            if claim.get("status") not in ("unresolved", "supported", "refuted"):
                return "claim status must be unresolved, supported or refuted"
            for field in ("statement", "scope", "reason"):
                if not isinstance(claim.get(field), str) or not claim[field].strip():
                    return "claim requires nonempty " + field
            for field in ("unresolved", "related_claims"):
                if not isinstance(claim.get(field, []), list) or any(
                        not isinstance(v, str) or not v.strip() for v in claim.get(field, [])):
                    return "claim " + field + " must contain nonempty strings"
            for field in ("evidence", "counterevidence"):
                if not isinstance(claim.get(field, []), list):
                    return "claim " + field + " must be a list of source references"
                for ref in claim.get(field, []):
                    if (not isinstance(ref, dict) or not isinstance(ref.get("run_id"), str)
                            or type(ref.get("attempt")) is not int
                            or not isinstance(ref.get("artifact"), str) or not portable_path(ref["artifact"])):
                        return "claim source requires run_id, attempt and relative artifact"
                    owner = next((r for r in self.ledger.runs() if r["run_id"] == ref["run_id"]), None)
                    if owner is None or owner["task_id"] != self.task.task_id:
                        return "claim source is unknown or outside authorized task"
                    if not any(a["attempt_no"] == ref["attempt"] and a["outcome"]
                               for a in self.ledger.attempts(ref["run_id"])):
                        return "claim source must identify a saved work result"
        for claim in claims:
            if any(related not in seen for related in claim.get("related_claims", [])):
                return "unknown related claim identity"
        return None

    def validate_conclusions(self, output: dict[str, Any]) -> str | None:
        pending = {a["attempt_no"] for a in self.attempt_records()
                   if a["plan"] and a["outcome"] and a["conclusion"] is None}
        conclusions = output.get("conclusions", [])
        if not isinstance(conclusions, list):
            return "conclusions must be a list"
        seen = set()
        for row in conclusions:
            if (not isinstance(row, dict) or type(row.get("attempt")) is not int
                    or row["attempt"] not in pending or row["attempt"] in seen
                    or not isinstance(row.get("conclusion"), str) or not row["conclusion"].strip()):
                return "conclusions must identify pending attempts with an interpretation or follow-up"
            if row["conclusion"].strip().rstrip(".!。！").casefold() in {
                    "read", "reviewed", "acknowledged", "noted", "已读", "已阅读", "已阅"}:
                return "conclusions require an interpretation or follow-up, not a read acknowledgment"
            seen.add(row["attempt"])
        return None

    def adopted_claims(self, value, proposed=()) -> list[dict]:
        """Validate explicit adoption at the Worker boundary; reading is separate."""
        if not isinstance(value, list):
            raise OPCError("adopted_claims must be a list")
        refs = []
        for ref in value:
            if (not isinstance(ref, dict) or not isinstance(ref.get("claim_id"), str)
                    or type(ref.get("version")) is not int or ref["version"] < 1
                    or not isinstance(ref.get("task_id", self.task.task_id), str)):
                raise OPCError("adopted_claims requires task_id, claim_id and positive version")
            normalized = dict(task_id=ref.get("task_id", self.task.task_id),
                              claim_id=ref["claim_id"], version=ref["version"])
            new = any(c["claim_id"] == ref["claim_id"]
                      and (c.get("base_version") or 0) + 1 == ref["version"] for c in proposed)
            if not (normalized["task_id"] == self.task.task_id and new):
                if not self.authorized_claims(normalized["task_id"], ref["claim_id"], version=ref["version"]):
                    raise OPCError("unknown adopted claim identity or version: " + str(normalized))
            if normalized not in refs:
                refs.append(normalized)
        return refs

    def validate_work_batch(self, works: list[dict]) -> str | None:
        existing = self.attempt_records()
        graph = {(a["plan"] or {}).get("work_id") or "a%d" % a["attempt_no"]:
                 (a["plan"] or {}).get("dependencies") or [] for a in existing}
        new_ids = []
        first = self.ledger.next_attempt_no(self.run_id)
        for index, work in enumerate(works):
            work_id = work.get("work_id") or "a%d" % (first + index)
            if not isinstance(work_id, str) or not work_id.strip() or "/" in work_id or "\\" in work_id:
                return "work_id must be a stable nonempty identifier"
            if work_id in graph:
                return "duplicate work_id: " + work_id
            dependencies = work.get("dependencies") or []
            directions = work.get("directions") or []
            deliverables = work.get("deliverables") or []
            if not isinstance(deliverables, list) or not all(isinstance(path, str) and portable_path(path)
                    and (self.comp.is_editable(path) or self.comp.is_scratch(path)) for path in deliverables):
                return "deliverables must be relative editable/scratch file paths"
            if not isinstance(directions, list) or not all(isinstance(d, str) and d.strip() for d in directions):
                return "directions must be a list of nonempty labels"
            if not isinstance(dependencies, list) or not all(
                    isinstance(d, dict) and isinstance(d.get("work_id"), str)
                    and isinstance(d.get("artifact"), str) and portable_path(d["artifact"]) for d in dependencies):
                return "dependencies must reference a work_id and relative artifact, candidate or result"
            base_work = work.get("base_work_id")
            if base_work is not None and (not isinstance(base_work, str) or not any(
                    d["work_id"] == base_work and d["artifact"] == "candidate" for d in dependencies)):
                return "base_work_id requires an explicit candidate dependency"
            graph[work_id] = dependencies
            new_ids.append(work_id)
        for work_id in new_ids:
            for dep in graph[work_id]:
                if dep["work_id"] not in graph:
                    return "unknown dependency: " + dep["work_id"]
        visited, visiting = set(), set()
        def visit(work_id):
            if work_id in visiting:
                return True
            if work_id in visited:
                return False
            visiting.add(work_id)
            for dependency in graph[work_id]:
                if visit(dependency["work_id"]):
                    return True
            visiting.remove(work_id)
            visited.add(work_id)
            return False
        if any(visit(work_id) for work_id in new_ids):
            return "dependency cycle in selected work"
        return None

    def dag(self) -> list[dict]:
        attempts = self.attempt_records()
        by_id = {(a["plan"] or {}).get("work_id") or "a%d" % a["attempt_no"]: a for a in attempts}
        nodes = []
        for work_id, attempt in by_id.items():
            plan = attempt["plan"] or {}
            missing = []
            for dependency in plan.get("dependencies") or []:
                upstream = by_id[dependency["work_id"]]
                artifact = dependency["artifact"]
                available = (bool(upstream["candidate"]) if artifact == "candidate" else
                             (self.attempt_dir(upstream["attempt_no"]) / ("decision.json" if artifact == "result" else artifact)).is_file())
                if artifact.startswith("outputs/"):
                    available = available and any(e["attempt"] == upstream["attempt_no"] and artifact in e["body"]["paths"]
                                                  for e in self.ledger.events(self.run_id, "deliverables_saved"))
                if not available:
                    missing.append(dependency["work_id"] + ":" + artifact)
            nodes.append(dict(work_id=work_id, attempt=attempt["attempt_no"], title=plan.get("title"),
                              directions=plan.get("directions") or [], dependencies=plan.get("dependencies") or [],
                              blocked_by=missing, state=attempt["state"], outcome=attempt["outcome"], parent=attempt["parent"]))
        return nodes

    def choose_work(self, ws: Workspaces) -> tuple[int | None, StopDecision | None]:
        """Run-level decisions select work; receipt/decision replay never calls the expert twice."""
        while True:
            champ = self.ledger.champion(self.run_id) or (self.working_commit(), Measurements())
            decisions = self.ledger.events(self.run_id, "expert_decision")
            consumed = {e["body"]["decision_call"] for e in self.ledger.events(self.run_id, "work_selected")}
            consumed.update(e["body"]["call_id"] for e in self.ledger.events(self.run_id, "decision_applied"))
            decision = next((e["body"] for e in decisions if e["body"]["call_id"] not in consumed), None)
            if decision is None:
                loader = ws.checkout("expert-source", champ[0])
                try:
                    expert, _ = self.workers(loader)
                    ctx = self.context(self.ledger.next_attempt_no(self.run_id), champ, None, loader)
                except BaseException:
                    ws.drop(loader)
                    raise
                ctx["source_root"] = str(loader)
                tree = self.artifact_dir() / "materials"
                tree.mkdir(parents=True, exist_ok=True)
                processed = {e["body"]["call_id"] for e in decisions}
                processed.update(e["body"]["call_id"] for e in self.ledger.events(self.run_id, "expert_rejected"))
                processed.update(e["body"]["call_id"] for e in self.ledger.events(self.run_id, "expert_conflict"))
                calls = [c for c in self.ledger.calls(self.run_id)
                         if c["role"] == "expert" and c["attempt_no"] is None]
                replay = next((c for c in calls if c["call_id"] not in processed), None)
                log_dir = Path(replay["receipt_path"]).parent if replay else self.artifact_dir() / "expert" / ("decision-%06d" % (len(calls) + 1))
                if replay:
                    ctx = replay["input"]["context"]
                else:
                    invalid = {e["body"]["session_id"] for e in self.ledger.events(self.run_id, "expert_session_rebuilt")}
                    invalid.update(c["session_id"] for c in calls if c["result"]
                                   and c["result"].get("extra", {}).get("session_unavailable"))
                    prior_session = next((c for c in reversed(calls)
                                          if c["session_id"] and c["session_id"] not in invalid
                                          and c["result"] is not None and c["state"] == "completed"), None)
                    if prior_session:
                        if prior_session["input"]["tree"] != str(tree):
                            self.ledger.event(self.run_id, "expert_session_rebuilt", call_id=prior_session["call_id"],
                                              session_id=prior_session["session_id"], reason="Run materials directory relocated; rebuild from persisted inputs")
                        else:
                            ctx["session_id"] = prior_session["session_id"]
                if not replay:
                    ctx["knowledge"] = self.knowledge_context(tree / "research.json", ctx["claims"])
                    ctx["claims"] = ctx["knowledge"].pop("claims")
                    ctx["claim_history"] = ctx["knowledge"].pop("claim_history")
                write_json(tree / "research.json", ctx)
                call = self.dispatch_call("expert", None, {"context": ctx}, tree, log_dir,
                                          lambda: expert.propose(ctx, tree, log_dir))
                if not call.ok:
                    self.ledger.event(self.run_id, "expert_rejected", call_id=call.call_id, reason=call.error)
                    if call.extra.get("session_unavailable"):
                        self.ledger.event(self.run_id, "expert_session_rebuilt", call_id=call.call_id,
                                          session_id=ctx["session_id"], reason=call.error)
                        self.hard_check()
                        continue
                    return None, StopDecision("blocked", "expert worker unavailable: " + call.error[:200])
                ws.drop(loader)
                output = call.output or {} if call.exhausted else call.output
                why = self.validate_conclusions(output) if isinstance(output, dict) else "expert reply is not an object"
                if why is None:
                    why = self.validate_claims(output)
                if why is None and not (call.exhausted or output.get("exhausted") or output.get("select_work") is False):
                    works = output.get("works") if output.get("works") is not None else [output]
                    if not isinstance(works, list) or not works:
                        why = "works must be a nonempty list of selected work"
                    else:
                        for work in works:
                            why = validate_plan(work)
                            if why is None and "adopted_claims" in work:
                                try:
                                    work["adopted_claims"] = self.adopted_claims(work["adopted_claims"], output.get("claims", []))
                                except OPCError as exc:
                                    why = str(exc)
                            if why is None and any(not self.comp.is_editable(f) for f in work.get("files") or []):
                                why = "plan names non-editable paths"
                            if why:
                                break
                        if why is None:
                            why = self.validate_work_batch(works)
                if why:
                    self.ledger.event(self.run_id, "expert_rejected", call_id=call.call_id, reason=why)
                    return None, StopDecision("blocked", "expert decision: " + why)
                if call.exhausted:
                    output = {**output, "exhausted": True}
                try:
                    self.ledger.record_decision(self.run_id, call.call_id, output)
                except ClaimConflict as exc:
                    self.ledger.event(self.run_id, "expert_conflict", call_id=call.call_id,
                                      conflicts=exc.conflicts)
                    self.hard_check()
                    continue
                decision = dict(call_id=call.call_id, output=output)
            output, call_id = decision["output"], decision["call_id"]
            if output.get("exhausted"):
                pending = [a["attempt_no"] for a in self.attempt_records()
                           if a["outcome"] and a["conclusion"] is None]
                if pending:
                    self.ledger.event(self.run_id, "decision_applied", call_id=call_id)
                    return None, StopDecision("blocked", "expert stopped with pending feedback: " + str(pending))
                selected = self.development_parent(output, champ[0], ws)
                reason = output.get("stop_reason") or "expert has no further worthwhile work"
                if not isinstance(reason, str):
                    return None, StopDecision("blocked", "expert stop_reason must be text")
                self.ledger.event(self.run_id, "selected_version", commit=selected)
                self.ledger.event(self.run_id, "expert_stop", call_id=call_id, reason=reason)
                self.ledger.event(self.run_id, "decision_applied", call_id=call_id)
                return None, StopDecision("closed", "expert_exhausted: " + reason)
            if output.get("select_work") is False:
                self.ledger.event(self.run_id, "decision_applied", call_id=call_id)
                self.hard_check()
                continue
            works = output.get("works") if output.get("works") is not None else [output]
            try:
                selected = [(work, self.development_parent(work, champ[0], ws)) for work in works]
            except OPCError as exc:
                self.ledger.event(self.run_id, "decision_applied", call_id=call_id)
                return None, StopDecision("blocked", "selected work input: " + str(exc))
            focus = (self.comp.focus_areas[(self.ledger.next_attempt_no(self.run_id) - 1)
                                         % len(self.comp.focus_areas)] if self.comp.focus_areas else None)
            if output.get("works") is None:
                n = self.ledger.begin_selected_attempt(self.run_id, call_id, output, selected[0][1], champ[0], focus)
            else:
                n = self.ledger.begin_selected_works(self.run_id, call_id, selected, champ[0], focus)[0]
            return n, None

    def save_candidate(self, ws: Workspaces, n: int, parent: str, patch: str, title: str) -> str:
        saved = [e for e in self.ledger.events(self.run_id, "candidate_saved") if e["attempt"] == n]
        if saved:
            return saved[-1]["body"]["commit"]
        tree = ws.checkout("a%06d/snapshot" % n, parent)
        try:
            apply_patch(tree, patch)
            candidate = commit_tree(tree, "opc %s a%d candidate: %s" %
                                    (self.task.task_id, n, title)) if patch.strip() else parent
            git("update-ref", "refs/opc-candidates/%s/%s/a%d" %
                (self.task.task_id, self.run_id, n), candidate, cwd=self.root)
            self.ledger.event(self.run_id, "candidate_saved", n, commit=candidate, parent=parent)
            return candidate
        finally:
            ws.drop(tree)

    def development_parent(self, plan: dict[str, Any], champion: str, ws: Workspaces) -> str:
        selected = plan.get("base_attempt")
        if selected is None:
            return champion
        if selected == 0:
            return self.ledger.run(self.run_id)["base_commit"]
        prior = next((a for a in self.attempt_records() if a["attempt_no"] == selected), None)
        if prior and prior["candidate"]:
            return rev_parse(self.root, prior["candidate"])
        if prior and prior["recoverable_patch"]:
            # Older runs already saved base + patch. Restore them on selection,
            # without a measurement or a new eligibility decision.
            patch = (self.attempt_dir(selected) / "candidate.patch").read_text(encoding="utf-8")
            if patch_digest(patch) != prior["patch_sha"]:
                raise OPCError("saved candidate patch digest differs for a%d" % selected)
            return self.save_candidate(ws, selected, prior["parent"], patch,
                                       (prior["plan"] or {}).get("title", "restored candidate"))
        raise OPCError("base_attempt %s has no saved candidate in this run" % selected)

    def working_commit(self) -> str:
        events = self.ledger.events(self.run_id, "working_version")
        return events[-1]["body"]["commit"] if events else self.ledger.run(self.run_id)["base_commit"]

    def selected_commit(self) -> str:
        events = self.ledger.events(self.run_id, "selected_version")
        if events:
            return events[-1]["body"]["commit"]
        champ = self.ledger.champion(self.run_id)
        return champ[0] if champ else self.working_commit()

    # ---------------------------------------------------------------- attempt
    def _worker_outcome(self, call: WorkerCall) -> Outcome:
        return Outcome.INFRA if call.extra.get("infra") or call.extra.get("not_started") else Outcome.WORKER_FAILED

    def attempt_steps(self, ws: Workspaces, n: int):
        champ = self.ledger.champion(self.run_id)
        if champ is None:
            champ = (self.working_commit(), Measurements())
        selected = next(a for a in self.ledger.attempts(self.run_id) if a["attempt_no"] == n)
        plan = selected["plan"]
        focus = selected["focus"]
        adir = self.attempt_dir(n)
        trees: list[Path] = []

        def attempt_cost() -> Cost:
            total = Cost(0, 0, 0.0)
            for record in self.ledger.calls(self.run_id):
                if record["attempt_no"] == n and record["result"] is not None:
                    total = total.add(Cost(**record["result"]["cost"]))
            return total

        def finish(outcome: Outcome, reason: str, gain: float = 0.0, **kw: Any):
            total = attempt_cost()
            self.ledger.finish_attempt(self.run_id, n, outcome.value, reason, gain, total, **kw)
            write_json(adir / "decision.json", {"attempt": n, "outcome": outcome.value,
                                                "reason": reason, "gain": gain,
                                                "cost": total.as_dict(),
                                                "champion_before": champ[0]})
            self.log("a%d %-18s %s" % (n, outcome.value, " ".join(reason.split())[:140]))
            self.sync_results()
            return outcome, None

        try:
            parent_event = next(e for e in reversed(self.ledger.events(self.run_id, "development_parent"))
                                if e["attempt"] == n)
            parent = parent_event["body"]["commit"]
            if plan.get("base_work_id"):
                upstream = next(a for a in self.attempt_records() if (a["plan"] or {}).get("work_id") == plan["base_work_id"])
                parent = upstream["candidate"]
                if parent != parent_event["body"]["commit"]:
                    self.ledger.event(self.run_id, "development_parent", n, commit=parent,
                                      base_work_id=plan["base_work_id"])
            loader = ws.checkout("a%06d/material-source" % n, parent)
            try:
                _, designer = self.workers(loader)
                context_path = adir / "context.json"
                if context_path.is_file():
                    ctx = json.loads(context_path.read_text(encoding="utf-8"))
                else:
                    ctx = self.context(n, champ, focus, loader)
                    ctx["parent"] = {"commit": parent, "base_attempt": plan.get("base_attempt")}
                    dependencies = []
                    for dependency in plan.get("dependencies") or []:
                        upstream = next(a for a in self.attempt_records() if (a["plan"] or {}).get("work_id") == dependency["work_id"])
                        artifact = dependency["artifact"]
                        path = self.attempt_dir(upstream["attempt_no"]) / ("candidate.patch" if artifact == "candidate" else
                                "decision.json" if artifact == "result" else artifact)
                        dependencies.append({**dependency, "path": str(path), "candidate": upstream["candidate"]})
                    claim_index = ctx["claims"]
                    ctx = {key: ctx[key] for key in ("attempt", "task", "component", "parent", "champion", "budget_left")}
                    ctx["knowledge"] = self.knowledge_context(context_path, claim_index)
                    ctx["claims"] = ctx["knowledge"].pop("claims")
                    ctx["claim_history"] = ctx["knowledge"].pop("claim_history")
                    ctx["handoff"] = {"purpose": plan["changes"], "deliverables": plan.get("deliverables", []),
                                      "inputs": dependencies, "evidence": str(self.artifact_dir()),
                                      "adopted_claims": plan.get("adopted_claims", [])}
                    write_json(context_path, ctx)
            finally:
                ws.drop(loader)
            ctx["component"].update(frozen=self.comp.frozen, evaluator_files=self.comp.evaluator_files)
            write_json(adir / "plan.json", plan)
            self.hard_check()
            design_tree = ws.root / ("a%06d/designer" % n)
            if not design_tree.exists():
                design_tree = ws.checkout("a%06d/designer" % n, parent)
            trees.append(design_tree)
            if plan.get("designer") is not False:
                failed_designs = [c for c in self.ledger.calls(self.run_id)
                                 if c["attempt_no"] == n and c["role"] == "designer" and c["result"]
                                 and not c["result"]["ok"] and (c["state"] == "not_started" or c["result"].get("extra", {}).get("infra"))]
                designer_log = adir / ("designer-%d" % (len(failed_designs) + 1) if failed_designs else "designer")
                call = yield CallExecution("designer", n, {"plan": plan, "context": ctx, "parent": parent},
                                           design_tree, designer_log,
                                           lambda: designer.implement(plan, ctx, design_tree, designer_log))
                execution = dict(call.output or {})
                adoption_error = None
                if "adopted_claims" in execution:
                    try:
                        execution["adopted_claims"] = self.adopted_claims(execution["adopted_claims"])
                    except OPCError as exc:
                        adoption_error = str(exc)
                        execution.pop("adopted_claims")
                if not any(e["body"].get("call_id") == call.call_id for e in self.ledger.events(self.run_id, "execution")):
                    self.ledger.event(self.run_id, "execution", n,
                                      **{**execution, "completed": call.ok and not adoption_error,
                                         "error": "; ".join(part for part in (call.error, adoption_error) if part),
                                         "call_id": call.call_id})
                if adoption_error:
                    return finish(Outcome.WORKER_FAILED, "designer adoption: " + adoption_error
                                  + ("; " + call.error if call.error else ""))
                if not call.ok:
                    out = self._worker_outcome(call)
                    if out is Outcome.INFRA:
                        self.ledger.update_attempt(self.run_id, n, "planned", reason=call.error,
                                                   cost=attempt_cost().as_dict())
                        return out, StopDecision("blocked", "designer execution incomplete: %s" % call.error[:200])
                    return finish(out, "designer: %s" % call.error)
                missing = self.collect_deliverables(n, design_tree, plan)
                if missing:
                    return finish(Outcome.WORKER_FAILED, missing)
            rep = sandbox(self.comp, design_tree, parent)
            write_json(adir / "sandbox.json", rep.as_dict())
            if not rep.ok:
                return finish(Outcome.SANDBOX, "changed non-editable paths: %s"
                              % ", ".join(rep.violations[:6]), files=rep.violations)
            patch = extract_patch(design_tree, parent, rep.editable)
            write_text(adir / "candidate.patch", patch)
            self.ledger.update_attempt(self.run_id, n, "designed", patch_sha=patch_digest(patch),
                                       files=rep.editable)
            # Snapshot only authorized edits, before gates can create outputs.
            # Keep a ref even for NO_GAIN/BROKEN; selecting it never moves champion.
            candidate = self.save_candidate(ws, n, parent, patch, plan["title"])
            if not self.task.acceptance.objective_metric:
                self.ledger.event(self.run_id, "working_version", n, commit=candidate)
            self.hard_check()

            if not (plan.get("evaluate") if plan.get("evaluate") is not None else
                    bool(self.task.acceptance.objective_metric)):
                return finish(Outcome.WORK, "saved work; formal evaluation not requested")
            self.ledger.event(self.run_id, "experiment", n, status="started", data=[], cached=False)
            failed_evaluations = [c for c in self.ledger.calls(self.run_id)
                                  if c["attempt_no"] == n and c["role"] == "evaluator"
                                  and c["result"] and (c["result"].get("output") or {}).get("failure") == Outcome.INFRA.value]
            eval_out = adir / ("eval-%d" % (len(failed_evaluations) + 1) if failed_evaluations else "eval")
            ev, meas, eval_tree = yield EvaluationExecution(lambda: self.evaluate_commit(
                ws, candidate, "", eval_out, "a%06d/eval" % n, fresh=not patch.strip(), attempt=n))
            trees.append(eval_tree)
            self.ledger.event(self.run_id, "experiment", n,
                              status="failed" if ev.failure else "completed", data=ev.data,
                              cached=ev.cached, repeats=ev.repeats, values=ev.values)
            gates = [g.as_dict() for g in ev.gates]
            if ev.failure is Outcome.INFRA:
                self.ledger.update_attempt(self.run_id, n, "designed", gates=gates,
                                           reason=ev.reason, cost=attempt_cost().as_dict())
                return Outcome.INFRA, StopDecision("blocked", "evaluation incomplete: " + ev.reason)
            if ev.failure is not None:
                return finish(ev.failure, ev.reason, gates=gates)
            if not self.task.acceptance.objective_metric:
                return finish(Outcome.WORK, "saved work; not numerically ranked", gates=gates,
                              metrics=meas.as_dict())
            champ = self.ledger.champion(self.run_id) or champ
            if meas.toolchain_digest != champ[1].toolchain_digest:
                self.remeasure_environment(ws, meas.toolchain_digest)
                champ = self.ledger.champion(self.run_id)
            self.ledger.event(self.run_id, "comparison_baseline", n, commit=champ[0],
                              values=champ[1].values, spread=champ[1].spread, repeats=champ[1].repeats)
            ok, why = meas.comparable(champ[1])
            if ok and sorted(meas.degraded_by) != sorted(champ[1].degraded_by):
                ok, why = False, "evidence differs: candidate skipped %s, champion skipped %s" % (
                    meas.degraded_by or "none", champ[1].degraded_by or "none")
            if not ok:
                return finish(Outcome.INCOMPARABLE, why, gates=gates, metrics=meas.as_dict())
            verdict: Verdict = acceptance.judge(self.task.acceptance, champ[1], meas, self._rule)
            gain = verdict.gain if math.isfinite(verdict.gain) else 0.0
            if not verdict.accepted:
                return finish(Outcome.NO_GAIN, verdict.reason, gain, gates=gates,
                              metrics=meas.as_dict())
            self.ledger.update_attempt(self.run_id, n, "evaluated", gates=gates,
                                       metrics=meas.as_dict(), gain=gain)
            new = candidate
            meas.source_commit = new
            self.ledger.record_champion_intent(self.run_id, n, champ[0], new)
            self.move_champion_ref(new, champ[0])
            self.ledger.set_champion(self.run_id, new, meas, n, verdict.reason)
            return finish(Outcome.IMPROVEMENT, verdict.reason, gain, gates=gates,
                          metrics=meas.as_dict())
        finally:
            if not self.ledger.open_attempts(self.run_id):
                for t in trees:
                    ws.drop(t)

    def collect_deliverables(self, n: int, tree: Path, plan: dict) -> str | None:
        if any(e["attempt"] == n for e in self.ledger.events(self.run_id, "deliverables_saved")):
            return None
        saved = []
        for rel in plan.get("deliverables") or []:
            source = tree / rel
            if not source.is_file() or not source.resolve().is_relative_to(tree.resolve()):
                return "declared deliverable missing or outside workspace: " + rel
            target = self.attempt_dir(n) / "outputs" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            saved.append("outputs/" + rel)
        if saved:
            self.ledger.event(self.run_id, "deliverables_saved", n, paths=saved)
        return None

    def run_selected_work(self, ws: Workspaces, max_starts: int | None = None,
                          resuming: set[int] | None = None) -> tuple[int, StopDecision | None]:
        """Advance Attempt phases on the controller; only Worker invocations run in threads."""
        active = {}
        generators = {}
        evaluations = []
        completed = set()
        stop = None
        started = 0
        session_waiting = False
        resuming = resuming or set()
        waiting = {}
        def observe_waiting():
            nodes = self.dag()
            for node in nodes:
                n = node["attempt"]
                if node["outcome"] or n in generators:
                    continue
                reason = ("inputs" if node["blocked_by"] else "measurement" if evaluations else
                          "concurrency" if len(active) >= self.max_concurrency else "ready")
                fact = (reason, tuple(node["blocked_by"]))
                if waiting.get(n) != fact:
                    self.ledger.event(self.run_id, "node_waiting", n, reason=reason, blocked_by=node["blocked_by"])
                    waiting[n] = fact
            return {node["attempt"]: node for node in nodes}
        def advance(n, value=None):
            nonlocal stop
            generator = generators[n]
            try:
                request = generator.send(value)
            except StopIteration as finished:
                completed.add(n)
                _, decision = finished.value
                stop = stop or decision
                return
            except (DispatchStopped, BudgetExhausted):
                raise
            if isinstance(request, EvaluationExecution):
                evaluations.append((n, request))
                return
            replay = self.prepare_call(request)
            if replay is not None:
                advance(n, replay)
            else:
                active[pool.submit(self.execute_call, request)] = (n, request)
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            failure = None
            try:
                while True:
                    nodes = observe_waiting()
                    progressed = False
                    if not evaluations:
                        for attempt in self.ledger.open_attempts(self.run_id):
                            n = attempt["attempt_no"]
                            if n in generators or n in completed:
                                continue
                            if len(active) >= self.max_concurrency:
                                break
                            node = nodes[n]
                            if node["blocked_by"]:
                                continue
                            if max_starts is not None and started >= max_starts and n not in resuming:
                                session_waiting = True
                                continue
                            cap = self.effective_budget().max_attempts
                            used = self.spent()["search_attempts"]
                            if cap is not None and used + len(generators) - len(completed) >= cap:
                                if used >= cap:
                                    raise BudgetExhausted("max_attempts", "search allowance used; selected work remains pending")
                                continue
                            if waiting.get(n) != ("ready", ()):
                                self.ledger.event(self.run_id, "node_waiting", n, reason="ready", blocked_by=[])
                                waiting[n] = ("ready", ())
                            self.admit()
                            started += 1
                            progressed = True
                            generators[n] = self.attempt_steps(ws, n)
                            advance(n)
                            if evaluations:
                                break
                    if active:
                        ready, _ = wait(active, timeout=.05, return_when=FIRST_COMPLETED)
                        for future in ready:
                            n, request = active.pop(future)
                            result = future.result()
                            call = self.complete_call(request, result)
                            advance(n, call)
                        continue
                    if evaluations:
                        n, request = evaluations.pop(0)
                        self.hard_check()
                        advance(n, request.invoke())
                        continue
                    if not self.ledger.open_attempts(self.run_id):
                        break
                    if progressed:
                        continue
                    stop = stop or (StopDecision("paused", "session attempt limit reached") if session_waiting else
                                    StopDecision("blocked", "selected work is waiting for inputs or a failed execution"))
                    break
            except BaseException as exc:
                failure = exc
                if not isinstance(exc, DispatchStopped) or exc.state != "paused":
                    self._abort_reason = ("budget_exhausted: " + exc.kind if isinstance(exc, BudgetExhausted) else
                                          str(exc) if isinstance(exc, DispatchStopped) else
                                          "controller cancelled peers after execution failure")
                    self._abort_execution.set()
            finally:
                for future, (_, request) in active.items():
                    try:
                        self.complete_call(request, future.result())
                    except BaseException as exc:
                        failure = failure or exc
                for generator in generators.values():
                    generator.close()
                with self._execution_lock:
                    self._inflight.clear()
            if failure is not None:
                raise failure
            return started, stop

    # -------------------------------------------------------------------- run
    def repair_delivery(self, report_path: str | Path) -> dict[str, Any]:
        """Continue a registered failed promotion from its exact selected version."""
        path = Path(report_path).resolve()
        report = json.loads(path.read_text(encoding="utf-8"))
        source = self.ledger.run(report["run_id"])
        if source["task_id"] != self.task.task_id:
            raise OPCError("repair requires the same task")
        registered = [e for e in self.ledger.events(source["run_id"], "promotion_report")
                      if Path(e["body"]["report_path"]).resolve() == path]
        if not registered or registered[-1]["body"]["complete"] or report.get("complete"):
            raise OPCError("repair requires a registered failed promotion")
        self.run_id = source["run_id"]
        self.enable_delivery()
        if source["state"] != "closed" or self.ledger.control(self.run_id) in ("pause", "stop"):
            raise OPCError("repair cannot override pause/stop or an active run")
        if registered[-1]["body"].get("report_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise OPCError("promotion report changed after registration")
        if report.get("acceptance_task_digest", source["task_digest"]) != self.task.digest:
            raise OPCError("repair requires the acceptance contract bound to this report")
        if source["task_digest"] != self.task.digest:
            from .promote import validate_standards_confirmation
            if (not report.get("reassessed") or
                report.get("acceptance_task_digest") != self.task.digest or
                report.get("acceptance_revision") != self.task.revision or
                report.get("execution_task_digest") != source["task_digest"]):
                raise OPCError("repair requires a confirmed acceptance revision bound to this report")
            validate_standards_confirmation(self, source, report.get("standards_confirmation"))
        if report["selected_version"] != self.selected_commit():
            raise OPCError("repair must start from the selected candidate")
        if any(f["check"] in ("evaluator", "scope") for f in report["findings"] if f["severity"] == "block"):
            raise OPCError("repair needs an explicit contract/evaluator revision")
        if any(f["check"] == "review" and "unavailable" in f["text"] for f in report["findings"]):
            raise OPCError("retry promotion reviewer only; no candidate development needed")
        # Every repair uses task-wide accounting, including projects without preparation.
        used = self.ledger.task_totals(self.task.task_id)
        if (self.task.budget.max_wall_seconds is not None and used["wall_seconds"] >= self.task.budget.max_wall_seconds) or (
            self.task.budget.max_tokens is not None and used["tokens"] >= self.task.budget.max_tokens):
            raise OPCError("task budget exhausted; no repair dispatch")
        self.hard_check()
        with self.ledger.writer():
            new_id = self.open_run(new_run=True, base_ref=report["selected_version"],
                                   direction="Repair delivery findings: " + json.dumps(report["findings"]))
            self.ledger.event(new_id, "delivery_repair", source_run=source["run_id"],
                              source_promotion=report["promotion_id"], selected_commit=report["selected_version"],
                              execution_revision=source["revision"], acceptance_revision=self.task.revision)
        return self.run()

    def run(self, new_run: bool = False, direction: str | None = None,
            max_attempts_now: int | None = None, base_ref: str | None = None,
            *, switch_backend: bool = False) -> dict[str, Any]:
        with self.ledger.writer():
            self._abort_execution.clear()
            self.open_run(new_run, direction, base_ref, switch_backend=switch_backend)
            if self.ledger.run(self.run_id)["state"] == "closed":
                self._returned_closed = True
                return self.summary()
            if self.ledger.control(self.run_id) != "run":
                self.ledger.set_control(self.run_id, "run")
            self.ledger.set_run_state(self.run_id, "active")
            ws = self.workspaces()
            stop: StopDecision | None = None
            done_now = 0
            try:
                self.reconcile_calls()
                self.hard_check()
                self.backfill_history()
                self.reconcile(ws)
                resuming = {a["attempt_no"] for a in self.ledger.open_attempts(self.run_id)}
                while True:
                    ctl = self.ledger.control(self.run_id)
                    if ctl == "pause":
                        stop = StopDecision("paused", "paused by user")
                        break
                    if ctl == "stop":
                        stop = StopDecision("closed", "stopped by user")
                        break
                    stop = self.stop_condition()
                    if stop:
                        break
                    if (max_attempts_now is not None and done_now >= max_attempts_now
                            and not self.ledger.open_attempts(self.run_id)):
                        stop = StopDecision("paused", "session attempt limit reached")
                        break
                    try:
                        self.admit()
                        if not self.ledger.open_attempts(self.run_id):
                            _, stop = self.choose_work(ws)
                        if not stop:
                            started, stop = self.run_selected_work(ws,
                                None if max_attempts_now is None else max_attempts_now - done_now, resuming)
                            done_now += started
                    except BudgetExhausted as exc:
                        stop = StopDecision("closed", "budget_exhausted: %s" % exc)
                    self.write_views()
                    if stop:
                        break
            except BudgetExhausted as exc:
                stop = StopDecision("closed", "budget_exhausted: %s" % exc)
            except DispatchStopped as exc:
                stop = StopDecision(exc.state, str(exc))
            except KeyboardInterrupt:
                stop = StopDecision("paused", "interrupted by user")
            except Exception as exc:
                stop = StopDecision("blocked", "%s: %s" % (type(exc).__name__, str(exc)[:400]))
                raise
            finally:
                if not self.ledger.open_attempts(self.run_id) and not any(
                        c["result"] is None or c["state"] == "unknown" for c in self.ledger.calls(self.run_id)):
                    ws.drop_all()
                if stop is None:
                    stop = StopDecision("blocked", "controller error")
                self.ledger.set_run_state(self.run_id, stop.state, stop.reason)
                self.write_views()
            return self.summary()

    # ------------------------------------------------------------------ views
    def startpoint(self) -> dict[str, Any]:
        path = self.artifact_dir() / "frozen" / "baseline.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8")).get("startpoint", {
                "kind": "legacy", "commit": self.ledger.run(self.run_id)["base_commit"]})
        return {"kind": "legacy", "commit": self.ledger.run(self.run_id)["base_commit"]}

    def summary(self) -> dict[str, Any]:
        run = self.ledger.run(self.run_id)
        champs = self.ledger.champions(self.run_id)
        attempts = self.ledger.attempts(self.run_id)
        outcomes: dict[str, int] = {}
        for a in attempts:
            if a["outcome"]:
                outcomes[a["outcome"]] = outcomes.get(a["outcome"], 0) + 1
        best = champs[-1] if champs else None
        base = champs[0] if champs else None
        baselines = self.ledger.events(self.run_id, "measurement_baseline")
        if baselines and baselines[-1]["body"].get("metrics"):
            base = {"metrics": baselines[-1]["body"]["metrics"]}
        m = self.task.acceptance.objective_metric
        gain = None
        if best and base and m in base["metrics"]["values"] and m in best["metrics"]["values"]:
            gain = acceptance.relative_gain(self.task.acceptance, base["metrics"]["values"][m],
                                            best["metrics"]["values"][m])
        result = {"target_met": "target_met", "budget_exhausted": "best_within_budget",
                  "stagnation": "best_within_budget", "expert_exhausted": "exploration_stopped"}
        business = None
        if run["state"] == "closed":
            key = (run["stop_reason"] or "").split(":")[0]
            business = result.get(key, "inconclusive")
            if business == "best_within_budget" and len(champs) <= 1:
                business = "no_valid_candidate"
            if best and acceptance.target_met(self.task.acceptance, best["metrics"]["values"]):
                business = "target_met"
        compatibility = (getattr(self, "_compatibility", None) if run["state"] != "closed" else None) or run_compatibility(self.artifact_dir() / "frozen", run)
        if run["state"] == "blocked":
            compatibility["execution"] = {"state": "blocked", "reason": run["stop_reason"]}
        return {"run_id": self.run_id, "task": self.task.task_id, "revision": self.task.revision,
                **({'results_path': self.task.raw['results_path'],
                    'results_registration_error': getattr(self, '_results_error', None)}
                   if self.task.raw.get('results_path') else {}),
                "state": run["state"], "stop_reason": run["stop_reason"], "result": business,
                "champion_ref": self.ref, "champion": best["commit_sha"] if best else None,
                "selected_version": self.selected_commit(),
                "working_version": self.working_commit() if not m else None,
                "baseline": run["base_commit"], "startpoint": self.startpoint(),
                "workers": self.resolved_workers,
                "backend_validation": {"dsh": "implemented; not runtime verified"},
                "configuration_sources": self.task.configuration_sources,
                "compatibility": compatibility,
                "baseline_metrics": base["metrics"]["values"] if base else None,
                "champion_metrics": best["metrics"]["values"] if best else None,
                "target_met": bool(best and acceptance.target_met(
                    self.task.acceptance, best["metrics"]["values"])),
                "objective": m, "objective_gain": gain, "outcomes": outcomes,
                "pending_conclusions": [a["attempt_no"] for a in self.attempt_records()
                                        if a["plan"] and a["outcome"] and a["conclusion"] is None],
                "control": self.ledger.control(self.run_id),
                "inflight_calls": [c["call_id"] for c in self.ledger.calls(self.run_id) if c["result"] is None],
                "claims": self.claims(),
                "claim_history": self.claims(history=True),
                "decision_conflicts": self.ledger.events(self.run_id, "expert_conflict"),
                "decisions": self.ledger.events(self.run_id, "expert_decision"),
                "materials": str(self.artifact_dir() / "materials"),

                "max_concurrency": self.max_concurrency,
                "dag": self.dag(),
                "calls": self.ledger.calls(self.run_id),
                "unresolved_accounting": self.ledger.unresolved_accounting(self.run_id),
                "spent": self.spent(), "budget_left": self.budget_left(),
                "budget": {"scope": "task", "origin": self._budget_origin,
                           "historical_used": self.ledger.task_totals(self.task.task_id), "limits": {"wall_seconds": self.effective_budget().max_wall_seconds,
                           "tokens": self.effective_budget().max_tokens, "attempts": self.effective_budget().max_attempts},
                           "used": self.spent()}}

    def write_views(self) -> str | None:
        if not self.run_id:
            return
        results_error = self.sync_results()
        s = self.summary()
        views = self.artifact_dir() / "views"
        write_json(views / "report.json", {**s, "attempts": self.attempt_records(),
                                           "champions": self.ledger.champions(self.run_id)})
        lines = ["# %s / %s" % (self.task.task_id, self.run_id), "",
                 "Projection of the ledger; not an authority.", "",
                 "- state: **%s** (%s)" % (s["state"], s["stop_reason"] or ""),
                 "- result: %s" % (s["result"] or "running"),
                 "- champion: `%s` (ref `%s`)" % ((s["champion"] or "")[:12], self.ref),
                 "- objective `%s`: baseline %s -> champion %s (%s)" % (
                     s["objective"], (s["baseline_metrics"] or {}).get(s["objective"]),
                     (s["champion_metrics"] or {}).get(s["objective"]),
                     "n/a" if s["objective_gain"] is None else "%+.2f%%" % (100 * s["objective_gain"])),
                 "- spent: %s" % json.dumps(s["spent"]), "- left: %s" % json.dumps(s["budget_left"]),
                 "", "| # | outcome | title | gain | reason |", "|---|---|---|---|---|"]
        lessons = ["# Lessons (generated)", ""]
        for a in self.attempt_records():
            title = ((a["plan"] or {}).get("title") or "")[:50]
            lines.append("| %d | %s | %s | %s | %s |" % (
                a["attempt_no"], a["outcome"] or a["state"], title,
                "" if a["gain"] is None else "%+.2f%%" % (100 * a["gain"]),
                (a["reason"] or "").replace("|", "/").replace("\n", " ")[:120]))
            if a["outcome"] and a["outcome"] != Outcome.IMPROVEMENT.value:
                lessons.append("- a%d %s `%s`: %s" % (a["attempt_no"], a["outcome"], title,
                                                     (a["reason"] or "")[:200]))
            if a["plan"]:
                lessons.append("- a%d expert conclusion: %s" %
                               (a["attempt_no"], a["conclusion"] or "pending review"))
        if s["claims"]:
            lines += ["", "## Claims", "", "Pending feedback: " + str(s["pending_conclusions"])]
            for claim in s["claims"]:
                lines += ["", "### %s v%d — %s" % (claim["claim_id"], claim["version"], claim["status"]),
                          claim["statement"], "Scope: " + claim["scope"], "Reason: " + claim["reason"],
                          "Evidence / counterevidence / unresolved: " + json.dumps(
                              {key: claim.get(key, []) for key in ("evidence", "counterevidence", "unresolved")}, ensure_ascii=False)]
        write_text(views / "STATE.md", "\n".join(lines) + "\n")
        write_text(views / "LESSONS.md", "\n".join(lessons) + "\n")
        return results_error
