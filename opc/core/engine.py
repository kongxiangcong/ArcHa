"""The engine: the only owner of "the next attempt".

One attempt:

    EXPERT     research materials + results -> retrospective and next plan or stop
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..adapters.worker import Worker, WorkerCall, make_worker, validate_plan
from ..domain import DomainAdapter, Evaluation, bounded_data, experimental_data, load_domain
from . import accept as acceptance
from .config import Bindings, ComponentConfig, ProjectConfig, TaskSpec, WorkerSpec
from .ledger import Ledger
from .worker_config import load_worker_config, worker_options, load_budget_config
from .model import (BudgetExhausted, Cost, GateResult, Measurements, OPCError, Outcome, Verdict,
                    write_json, write_text)
from .workspace import (Workspaces, apply_patch, cas_update_ref, commit_tree, dirty_paths, git,
                        extract_patch, patch_digest, read_ref, rev_parse, sandbox, tracked_digest)

HISTORY_WINDOW = 12


@dataclass
class StopDecision:
    state: str            # closed | blocked | paused
    reason: str


class Engine:
    def __init__(self, project_root: Path, task_id: str, revision: str | None = None,
                 log: Callable[[str], None] = print):
        self.project = ProjectConfig.load(project_root)
        self.root = self.project.root
        self.task = TaskSpec.load(self.root, task_id, revision)
        self.worker_config = load_worker_config(self.root)
        self.comp = ComponentConfig.load(self.root, self.task.component)
        self.bindings = Bindings.load(self.project)
        self.ledger = Ledger(self.root / ".opc" / "local" / "ledger.sqlite3")
        self.ref = "refs/heads/opc/%s" % task_id
        preparations = [r for r in self.ledger.runs() if r["task_id"] == task_id and r["revision"] == "preparation"]
        self.preparation = preparations[-1]["run_id"] if preparations else None
        if self.preparation:
            limits = self.ledger.events(self.preparation, "preparation_budget")
            if limits:
                local_limits = load_budget_config(self.root)
                for field, key in (("max_tokens", "tokens"), ("max_wall_seconds", "wall_seconds")):
                    if field in local_limits:
                        continue
                    prior = limits[-1]["body"].get(key)
                    current = getattr(self.task.budget, field)
                    if prior is not None:
                        setattr(self.task.budget, field, min(current, prior) if current is not None else prior)
        self.log = log
        self.run_id: str | None = None
        self._domain: DomainAdapter | None = None
        self._rule = None
        self._workers: tuple[Worker, Worker] | None = None
        self._eval_tree: Path | None = None

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

    # -------------------------------------------------------------- preflight
    def static_check(self) -> dict[str, Any]:
        """Everything that can be checked without running project code."""
        problems, warnings = [], []
        if not self.project.execution_enabled:
            problems.append(".opc/project.json has execution_enabled=false; enable it after "
                            "reviewing the component and task contracts")
        try:
            base = rev_parse(self.root, self.task.base_ref)
        except OPCError as exc:
            return {"ok": False, "problems": [str(exc)], "warnings": warnings}
        if self.preparation:
            events = self.ledger.events(self.preparation, "preparation")
            receipt = events[-1]["body"] if events else {}
            if self.accounting_required() and self.ledger.unresolved_accounting(self.preparation):
                problems.append("preparation accounting incomplete; no new dispatch")
            if receipt.get("state") != "ready":
                problems.append("preparation not ready: " + receipt.get("reason", "unmetered draft"))
            else:
                for rel, digest in receipt.get("files", {}).items():
                    data = git("show", base + ":" + rel, cwd=self.root, binary=True)
                    if hashlib.sha256(data).hexdigest() != digest:
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
        digest, files = self.evaluator_digest(base)
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
                "editable_files": editable_hits,
                "required_metrics": acceptance.required_metrics(self.task.acceptance)}

    def domain(self, tree: Path) -> DomainAdapter:
        if self._domain is None:
            self._domain = load_domain(self.comp, tree)
            self._rule = acceptance.load_rule(self.task.acceptance, tree, self.evaluator_patterns())
        return self._domain

    def workers(self, tree: Path) -> tuple[Worker, Worker]:
        if self._workers is None:
            expert = make_worker(WorkerSpec(self.task.expert.kind, worker_options(
                self.worker_config, "expert", self.task.expert.options)), tree)
            designer = expert
            if self.task.designer:
                designer = make_worker(WorkerSpec(self.task.designer.kind, worker_options(
                    self.worker_config, "designer", self.task.designer.options)), tree)
            self._workers = (expert, designer)
        return self._workers

    def diagnostic_gates(self) -> frozenset[str]:
        optional = {g for r in self.task.requirements if r.get("required") is False
                    for g in r.get("gates", [])}
        mandatory = {g for r in self.task.requirements if r.get("required", True)
                     for g in r.get("gates", [])}
        return frozenset(optional - mandatory)

    def evaluate_commit(self, ws: Workspaces, commit: str, patch: str, out: Path,
                        name: str, *, fresh: bool = False, delivery: bool = False) -> tuple[Evaluation, Measurements | None, Path]:
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
        if ev is None:
            from ..domains.command import CommandDomain
            if delivery and isinstance(dom, CommandDomain):
                ev = dom.evaluate(tree, out, self.task.acceptance.repeats,
                                  diagnostic_gates=self.diagnostic_gates())
            else:
                ev = dom.evaluate(tree, out, self.task.acceptance.repeats)
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

    def preflight(self) -> dict[str, Any]:
        """Static checks, toolchain, and one full evaluation of the base commit."""
        rep = self.static_check()
        if not rep["ok"]:
            return rep
        ws = self.workspaces("preflight")
        out = self.root / ".opc" / "local" / "preflight"
        try:
            ev, meas, tree = self.evaluate_commit(ws, rep["base_commit"], "", out, "baseline")
            if self.preparation:
                self.ledger.charge(self.preparation, None, "preflight", Cost(ev.seconds, 0, 0.0))
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
                 base_ref: str | None = None) -> str:
        last = self.ledger.latest_run(self.task.task_id)
        if last is not None and not new_run and last["state"] == "closed":
            raise OPCError("run %s is closed (%s). Start another with --new-run; add --base %s "
                           "to continue from its champion instead of the task base"
                           % (last["run_id"], last["stop_reason"], self.ref))
        if last is not None and not new_run:
            if last["revision"] != self.task.revision or last["task_digest"] != self.task.digest:
                raise OPCError("task %s changed since run %s started (%s -> %s); an evaluator or "
                               "contract change is a new run: pass --new-run"
                               % (self.task.task_id, last["run_id"], last["revision"],
                                  self.task.revision))
            self.run_id = last["run_id"]
            if self.delivery_accounting():
                self.enable_delivery()
            if direction:
                self.ledger.event(self.run_id, "direction", None, text=direction)
            return self.run_id
        rep = self.static_check()
        if not rep["ok"]:
            raise OPCError("static check failed:\n  " + "\n  ".join(rep["problems"]))
        base = rev_parse(self.root, base_ref) if base_ref else rep["base_commit"]
        if base_ref:
            # the evaluator must be the task's, whatever commit the run starts from
            if self.evaluator_digest(base)[0] != rep["evaluator_digest"]:
                raise OPCError("--base %s carries a different evaluator than the task base"
                               % base_ref)
        tool_digest = self.toolchain_digest(base)
        self.run_id = self.ledger.create_run(
            task_id=self.task.task_id, revision=self.task.revision,
            task_digest=self.task.digest, component=self.comp.component_id, base_commit=base,
            evaluator_digest=rep["evaluator_digest"], toolchain_digest=tool_digest,
            champion_ref=self.ref, direction=direction or self.task.direction)
        if self.delivery_accounting():
            self.enable_delivery()
        write_json(self.artifact_dir() / "frozen" / "task.json", self.task.raw)
        write_json(self.artifact_dir() / "frozen" / "component.json", self.comp.raw)
        write_json(self.artifact_dir() / "frozen" / "baseline.json",
                   {"commit": base, "evaluator_digest": rep["evaluator_digest"],
                    "evaluator_files": rep["evaluator_files"], "toolchain_digest": tool_digest})
        self.log("run %s created on %s" % (self.run_id, base[:12]))
        return self.run_id

    def toolchain_digest(self, commit: str) -> str:
        if self._domain is not None:
            return self._domain.toolchain()[0]
        ws = self.workspaces("toolchain")
        try:
            tree = ws.checkout("probe", commit)
            return self.domain(tree).toolchain()[0]
        finally:
            ws.drop_all()

    def measure_champion(self, ws: Workspaces, commit: str, attempt: int | None,
                         reason: str) -> Measurements:
        out = self.artifact_dir() / "champion" / ("%s-%d" % (commit[:12], int(time.time())))
        ev, meas, tree = self.evaluate_commit(ws, commit, "", out, "champion")
        ws.drop(tree)
        self.ledger.charge(self.run_id, attempt, "evaluator", Cost(ev.seconds, 0, 0.0))
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
            self.ledger.finish_attempt(self.run_id, n, Outcome.ABANDONED.value,
                                       "controller stopped during '%s'; costs kept, no verdict"
                                       % a["state"], 0.0, Cost())
            self.log("attempt %d abandoned (was %s)" % (n, a["state"]))
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
        # toolchain drift: a champion measured under other tools is not comparable
        current = self.toolchain_digest(champ[0])
        if current != champ[1].toolchain_digest:
            self.log("toolchain changed; re-measuring champion %s" % champ[0][:12])
            self.ledger.update_toolchain(self.run_id, current)
            self.measure_champion(ws, champ[0], None, "re-measured: toolchain changed")

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
        t = self.ledger.task_totals(self.task.task_id) if self.preparation or self.delivery_accounting() else self.ledger.totals(self.run_id)
        attempts = self.ledger.attempts(self.run_id)
        if self.ledger.events(self.run_id, "delivery_repair"):
            attempts = [a for r in self.ledger.runs() if r["task_id"] == self.task.task_id for a in self.ledger.attempts(r["run_id"])]
        t["search_attempts"] = sum(1 for a in attempts if a["outcome"] and
                                   Outcome(a["outcome"]).counts_as_search)
        t["attempts"] = len(attempts)
        return t

    def accounting_required(self) -> bool:
        return self.task.budget.max_tokens is not None or self.task.budget.max_usd is not None

    def budget_left(self) -> dict[str, Any]:
        b, s = self.task.budget, self.spent()
        left = {"attempts": b.max_attempts - s["search_attempts"],
                "wall_seconds": (round(b.max_wall_seconds - s["wall_seconds"], 1)
                                 if b.max_wall_seconds is not None else None)}
        if b.max_tokens is not None:
            left["tokens"] = b.max_tokens - s["tokens"]
        if b.max_usd is not None:
            left["usd"] = round(b.max_usd - s["usd"], 4) if s["usd_known"] else "unknown"
        return left

    def admit(self) -> None:
        """Ask before spending. The estimate is the mean decided attempt so far."""
        b, s = self.task.budget, self.spent()
        if self.preparation or self.delivery_accounting():
            self.hard_check()
        if s["search_attempts"] >= b.max_attempts:
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

    def hard_check(self) -> None:
        """Between steps of one attempt: stop as soon as a cap is crossed."""
        b, s = self.task.budget, self.spent()
        if self.delivery_accounting():
            if self.accounting_required() and any(self.ledger.unresolved_accounting(r["run_id"]) for r in self.ledger.runs() if r["task_id"] == self.task.task_id):
                raise OPCError("usage accounting incomplete; no delivery dispatch")
            if self.ledger.control(self.run_id) in ("pause", "stop"):
                raise OPCError("user paused/stopped delivery")
            if b.max_usd is not None and (not s["usd_known"] or s["usd"] >= b.max_usd):
                raise BudgetExhausted("max_usd", "delivery budget unavailable")
        if self.preparation:
            receipts = self.ledger.events(self.preparation, "preparation")
            if not receipts or receipts[-1]["body"].get("state") != "ready":
                raise OPCError("preparation is not ready; no formal dispatch")
        if self.preparation and self.accounting_required() and self.ledger.unresolved_accounting(self.preparation):
            raise OPCError("usage accounting incomplete; no new dispatch")
        if b.max_wall_seconds is not None and s["wall_seconds"] >= b.max_wall_seconds:
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
        return rows

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
                          "editable": self.comp.editable, "scratch": self.comp.scratch},
            "working_version": {"commit": champ[0]},
            "champion": {"commit": champ[0], "values": metric_view(champ[1].values),
                         "params": next((a["plan"].get("params") for a in reversed(attempts)
                             if a["candidate"] == champ[0] and a["plan"] and a["plan"].get("params")), None)
                         if self.task.expert.kind == "scripted" else None} if acc.objective_metric else None,
            "baseline": {"commit": base["commit_sha"], "values": metric_view(base["metrics"]["values"])},
            "history": history, "background": background, "budget_left": self.budget_left(),
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

    def results_context(self) -> dict:
        from .results import snapshot
        try:
            return snapshot(self.root, self.bindings.artifact_root, self.task.raw['results_path'])
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

    def save_conclusions(self, output: dict[str, Any], ctx: dict[str, Any], n: int) -> str | None:
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
                return "conclusions must identify pending attempts with nonempty text"
            seen.add(row["attempt"])
        for row in conclusions:
            self.ledger.event(self.run_id, "conclusion", row["attempt"],
                              text=row["conclusion"], reviewed_by_attempt=n)
        if conclusions:
            self.sync_results()
        return None

    def save_candidate(self, ws: Workspaces, n: int, parent: str, patch: str, title: str) -> str:
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
        return Outcome.INFRA if call.extra.get("infra") else Outcome.WORKER_FAILED

    def attempt(self, ws: Workspaces) -> tuple[Outcome, StopDecision | None]:
        champ = self.ledger.champion(self.run_id)
        if champ is None:
            champ = (self.working_commit(), Measurements())
        focus = None
        if self.comp.focus_areas:
            focus = self.comp.focus_areas[(self.ledger.next_attempt_no(self.run_id) - 1)
                                          % len(self.comp.focus_areas)]
        n = self.ledger.begin_attempt(self.run_id, champ[0], focus)
        adir = self.attempt_dir(n)
        total = Cost(0.0, 0, 0.0)
        trees: list[Path] = []

        def charge(role: str, cost: Cost, call: WorkerCall | None = None) -> None:
            nonlocal total
            if call is not None and (self.preparation or self.delivery_accounting()):
                kind = self.task.expert.kind if role == "expert" else (self.task.designer or self.task.expert).kind
                if kind in ("codex", "dsh") and not call.extra.get("usage_complete", False):
                    self.ledger.event(self.preparation or self.run_id, "accounting_unknown", None, reason="usage unavailable")
                    if self.accounting_required():
                        call.ok = False
                        call.error = "usage unavailable; stop dispatch until actual accounting is reconciled"
                        call.extra["infra"] = True
            total = total.add(cost)
            self.ledger.charge(self.run_id, n, role, cost)
            if call is not None:
                self.ledger.event(self.run_id, "worker_call", n, role=role, call_id=call.call_id,
                                  ok=call.ok, tokens=cost.tokens, seconds=round(cost.wall_seconds, 2),
                                  error=call.error[:300], log_dir=call.log_dir)

        def finish(outcome: Outcome, reason: str, gain: float = 0.0, **kw: Any):
            self.ledger.finish_attempt(self.run_id, n, outcome.value, reason, gain, total, **kw)
            write_json(adir / "decision.json", {"attempt": n, "outcome": outcome.value,
                                                "reason": reason, "gain": gain,
                                                "cost": total.as_dict(),
                                                "champion_before": champ[0]})
            self.log("a%d %-18s %s" % (n, outcome.value, " ".join(reason.split())[:140]))
            self.sync_results()
            return outcome, None

        try:
            loader = ws.checkout("a%06d/material-source" % n, champ[0])
            trees.append(loader)
            expert, designer = self.workers(loader)
            ctx = self.context(n, champ, focus, loader)
            ws.drop(loader)
            trees.remove(loader)
            expert_tree = ws.root / ("a%06d/material" % n)
            expert_tree.mkdir(parents=True, exist_ok=True)
            trees.append(expert_tree)
            write_json(expert_tree / "research.json", ctx)
            write_json(adir / "context.json", ctx)
            call = expert.propose(ctx, expert_tree, adir / "expert")
            charge("expert", call.cost, call)
            if not call.ok:
                out = self._worker_outcome(call)
                finish(out, "expert: %s" % call.error)
                if out is Outcome.INFRA:
                    return out, StopDecision("blocked", "expert worker unavailable: %s"
                                             % call.error[:200])
                return out, None
            plan = (call.output or {}) if call.exhausted else call.output
            why = self.save_conclusions(plan, ctx, n) if isinstance(plan, dict) else "plan is not an object"
            if why:
                return finish(Outcome.WORKER_FAILED, "expert review: " + why)
            if call.exhausted or plan.get("exhausted") is True:
                reason = plan.get("stop_reason") or "expert has no further worthwhile work"
                if not isinstance(reason, str):
                    return finish(Outcome.WORKER_FAILED, "stop_reason must be text")
                try:
                    selected = self.development_parent(plan, champ[0], ws)
                except OPCError as exc:
                    return finish(Outcome.WORKER_FAILED, str(exc))
                self.ledger.event(self.run_id, "selected_version", n, commit=selected)
                self.ledger.event(self.run_id, "expert_stop", n, reason=reason)
                finish(Outcome.NO_CHANGE, reason)
                return Outcome.NO_CHANGE, StopDecision("closed", "expert_exhausted: " + reason)
            why = validate_plan(plan)
            if why is None:
                outside = [f for f in plan.get("files") or [] if not self.comp.is_editable(f)]
                if outside:
                    why = "plan names non-editable paths: %s" % ", ".join(outside)
            write_json(adir / "plan.json", plan)
            self.ledger.update_attempt(self.run_id, n, "planned", plan=plan)
            self.sync_results()
            if why:
                return finish(Outcome.WORKER_FAILED, "plan check: " + why)
            self.hard_check()

            try:
                parent = self.development_parent(plan, champ[0], ws)
            except OPCError as exc:
                return finish(Outcome.WORKER_FAILED, "plan check: " + str(exc))
            self.ledger.event(self.run_id, "development_parent", n, commit=parent,
                              base_attempt=plan.get("base_attempt"))
            ctx["parent"] = {"commit": parent, "base_attempt": plan.get("base_attempt")}
            design_tree = ws.checkout("a%06d/designer" % n, parent)
            trees.append(design_tree)
            call = designer.implement(plan, ctx, design_tree, adir / "designer")
            charge("designer", call.cost, call)
            self.ledger.event(self.run_id, "execution", n, completed=call.ok,
                              summary=(call.output or {}).get("summary", ""))
            if not call.ok:
                out = self._worker_outcome(call)
                finish(out, "designer: %s" % call.error)
                if out is Outcome.INFRA:
                    return out, StopDecision("blocked", "designer worker unavailable: %s"
                                             % call.error[:200])
                return out, None
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
            ev, meas, eval_tree = self.evaluate_commit(ws, candidate, "", adir / "eval",
                                                       "a%06d/eval" % n, fresh=not patch.strip())
            trees.append(eval_tree)
            charge("evaluator", Cost(ev.seconds, 0, 0.0))
            self.ledger.event(self.run_id, "experiment", n,
                              status="failed" if ev.failure else "completed", data=ev.data,
                              cached=ev.cached, repeats=ev.repeats, values=ev.values)
            gates = [g.as_dict() for g in ev.gates]
            if ev.failure is not None:
                return finish(ev.failure, ev.reason, gates=gates)
            if not self.task.acceptance.objective_metric:
                return finish(Outcome.WORK, "saved work; not numerically ranked", gates=gates,
                              metrics=meas.as_dict())
            if meas.toolchain_digest != champ[1].toolchain_digest:
                # tools changed under a live run: re-measure the champion now, or every
                # later candidate is incomparable with it
                self.log("toolchain changed; re-measuring champion %s" % champ[0][:12])
                self.ledger.update_toolchain(self.run_id, meas.toolchain_digest)
                champ = (champ[0], self.measure_champion(ws, champ[0], n,
                                                         "re-measured: toolchain changed"))
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
        except BudgetExhausted as exc:
            finish(Outcome.ABANDONED, "budget: %s" % exc)
            raise
        except KeyboardInterrupt:
            finish(Outcome.ABANDONED, "interrupted by user")
            raise
        finally:
            for t in trees:
                ws.drop(t)

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
            max_attempts_now: int | None = None, base_ref: str | None = None) -> dict[str, Any]:
        with self.ledger.writer():
            self.open_run(new_run, direction, base_ref)
            if self.ledger.control(self.run_id) != "run":
                self.ledger.set_control(self.run_id, "run")
            self.ledger.set_run_state(self.run_id, "active")
            ws = self.workspaces()
            stop: StopDecision | None = None
            done_now = 0
            try:
                self.backfill_history()
                self.reconcile(ws)
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
                    if max_attempts_now is not None and done_now >= max_attempts_now:
                        stop = StopDecision("paused", "session attempt limit reached")
                        break
                    try:
                        self.admit()
                        _, stop = self.attempt(ws)
                    except BudgetExhausted as exc:
                        stop = StopDecision("closed", "budget_exhausted: %s" % exc)
                    done_now += 1
                    self.write_views()
                    if stop:
                        break
            except KeyboardInterrupt:
                stop = StopDecision("paused", "interrupted by user")
            except Exception as exc:
                stop = StopDecision("blocked", "%s: %s" % (type(exc).__name__, str(exc)[:400]))
                raise
            finally:
                ws.drop_all()
                if stop is None:
                    stop = StopDecision("blocked", "controller error")
                self.ledger.set_run_state(self.run_id, stop.state, stop.reason)
                self.write_views()
            return self.summary()

    # ------------------------------------------------------------------ views
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
        return {"run_id": self.run_id, "task": self.task.task_id, "revision": self.task.revision,
                **({'results_path': self.task.raw['results_path'],
                    'results_registration_error': getattr(self, '_results_error', None)}
                   if self.task.raw.get('results_path') else {}),
                "state": run["state"], "stop_reason": run["stop_reason"], "result": business,
                "champion_ref": self.ref, "champion": best["commit_sha"] if best else None,
                "selected_version": self.selected_commit(),
                "working_version": self.working_commit() if not m else None,
                "baseline": run["base_commit"],
                "baseline_metrics": base["metrics"]["values"] if base else None,
                "champion_metrics": best["metrics"]["values"] if best else None,
                "target_met": bool(best and acceptance.target_met(
                    self.task.acceptance, best["metrics"]["values"])),
                "objective": m, "objective_gain": gain, "outcomes": outcomes,
                "pending_conclusions": [a["attempt_no"] for a in self.attempt_records()
                                        if a["plan"] and a["outcome"] and a["conclusion"] is None],
                "spent": self.spent(), "budget_left": self.budget_left()}

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
        write_text(views / "STATE.md", "\n".join(lines) + "\n")
        write_text(views / "LESSONS.md", "\n".join(lessons) + "\n")
        return results_error
