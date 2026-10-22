"""The engine: the only owner of "the next attempt".

One attempt:

    EXPERT     read-only champion tree -> plan
    PLAN_CHECK plan files within editable scope, not a repeat
    DESIGN     writable tree cut from the champion commit -> edits
    SANDBOX    every change classified; any non-editable change fails the attempt
    EVALUATE   editable-only patch applied to a fresh champion tree; frozen gates run there
    ACCEPT     comparability (evaluator + toolchain + evidence), constraints, gain over noise
    CHAMPION   commit, ledger intent, compare-and-swap the ref, ledger record
    FEEDBACK   history + lessons for the next expert; stop conditions checked

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
from ..domain import DomainAdapter, Evaluation, load_domain
from . import accept as acceptance
from .config import Bindings, ComponentConfig, ProjectConfig, TaskSpec
from .ledger import Ledger
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
        self.comp = ComponentConfig.load(self.root, self.task.component)
        self.bindings = Bindings.load(self.project)
        self.ledger = Ledger(self.root / ".opc" / "local" / "ledger.sqlite3")
        self.ref = "refs/heads/opc/%s" % task_id
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
        dirty = dirty_paths(self.root)
        from .config import matches
        frozen_dirty = [p for p in dirty if matches(p, self.evaluator_patterns() + [".opc/**"])
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
            expert = make_worker(self.task.expert, tree)
            designer = make_worker(self.task.designer, tree) if self.task.designer else expert
            self._workers = (expert, designer)
        return self._workers

    def evaluate_commit(self, ws: Workspaces, commit: str, patch: str, out: Path,
                        name: str) -> tuple[Evaluation, Measurements | None, Path]:
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
        ev = self._cached(content, digest, tool_digest)
        if ev is None:
            ev = dom.evaluate(tree, out, self.task.acceptance.repeats)
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
            "metrics": meas.as_dict() if meas else None})
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
        d = json.loads(p.read_text())
        gates = [GateResult.from_dict(g) for g in d["gates"]]
        for g in gates:
            g.seconds, g.detail = 0.0, ("cached; " + g.detail).strip("; ")
        return Evaluation(gates=gates, values=d["values"], spread=d["spread"],
                          repeats=d["repeats"], degraded_by=d["degraded_by"],
                          failure=Outcome(d["failure"]) if d["failure"] else None,
                          reason=d["reason"], seconds=0.0)

    def _store(self, tree_id: str, ev_digest: str, tool_digest: str, ev: Evaluation) -> None:
        if not self.comp.deterministic or ev.failure is Outcome.INFRA:
            return
        write_json(self._cache_path(tree_id, ev_digest, tool_digest), {
            "gates": [g.as_dict() for g in ev.gates], "values": ev.values, "spread": ev.spread,
            "repeats": ev.repeats, "degraded_by": ev.degraded_by,
            "failure": ev.failure.value if ev.failure else None, "reason": ev.reason})

    def preflight(self) -> dict[str, Any]:
        """Static checks, toolchain, and one full evaluation of the base commit."""
        rep = self.static_check()
        if not rep["ok"]:
            return rep
        ws = self.workspaces("preflight")
        out = self.root / ".opc" / "local" / "preflight"
        try:
            ev, meas, tree = self.evaluate_commit(ws, rep["base_commit"], "", out, "baseline")
            rep["toolchain"] = self.domain(tree).toolchain()[1]
            self.workers(tree)
        finally:
            ws.drop_all()
        rep["gates"] = [g.as_dict() for g in ev.gates]
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
            rep["warnings"].append("baseline already meets the target; a run would stop at once")
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
    def spent(self) -> dict[str, Any]:
        t = self.ledger.totals(self.run_id)
        attempts = self.ledger.attempts(self.run_id)
        t["search_attempts"] = sum(1 for a in attempts if a["outcome"] and
                                   Outcome(a["outcome"]).counts_as_search)
        t["attempts"] = len(attempts)
        return t

    def budget_left(self) -> dict[str, Any]:
        b, s = self.task.budget, self.spent()
        left = {"attempts": b.max_attempts - s["search_attempts"],
                "wall_seconds": round(b.max_wall_seconds - s["wall_seconds"], 1)}
        if b.max_tokens is not None:
            left["tokens"] = b.max_tokens - s["tokens"]
        if b.max_usd is not None:
            left["usd"] = round(b.max_usd - s["usd"], 4) if s["usd_known"] else "unknown"
        return left

    def admit(self) -> None:
        """Ask before spending. The estimate is the mean decided attempt so far."""
        b, s = self.task.budget, self.spent()
        if s["search_attempts"] >= b.max_attempts:
            raise BudgetExhausted("max_attempts", "%d search attempts used" % s["search_attempts"])
        done = [a for a in self.ledger.attempts(self.run_id) if a["cost"]]
        est_wall = sum(a["cost"]["wall_seconds"] for a in done) / len(done) if done else 0.0
        est_tok = sum(a["cost"]["tokens"] for a in done) / len(done) if done else 0.0
        if s["wall_seconds"] + est_wall > b.max_wall_seconds:
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
        if s["wall_seconds"] > b.max_wall_seconds:
            raise BudgetExhausted("max_wall_seconds", "crossed mid-attempt")
        if b.max_tokens is not None and s["tokens"] > b.max_tokens:
            raise BudgetExhausted("max_tokens", "crossed mid-attempt")

    def stop_condition(self) -> StopDecision | None:
        champ = self.ledger.champion(self.run_id)
        if champ and acceptance.target_met(self.task.acceptance, champ[1].values):
            return StopDecision("closed", "target_met")
        decided = [a for a in self.ledger.attempts(self.run_id) if a["outcome"]]
        streak = 0
        for a in reversed(decided):
            o = Outcome(a["outcome"])
            if o is Outcome.IMPROVEMENT:
                break
            if o.counts_as_search:
                streak += 1
        if streak >= self.task.budget.max_stagnation:
            return StopDecision("closed", "stagnation: %d attempts without improvement" % streak)
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
    def context(self, n: int, champ: tuple[str, Measurements], focus: str | None,
                tree: Path) -> dict[str, Any]:
        attempts = self.ledger.attempts(self.run_id)
        history, lessons = [], []
        decided = [a for a in attempts if a["outcome"]]
        keep = {a["attempt_no"] for a in decided[-HISTORY_WINDOW:]} | \
            {a["attempt_no"] for a in decided if a["outcome"] == Outcome.IMPROVEMENT.value}
        for a in decided:
            plan = a["plan"] or {}
            row = {"attempt": a["attempt_no"], "title": plan.get("title"),
                   "hypothesis": (plan.get("hypothesis") or "")[:300], "files": a["files"] or
                   plan.get("files"), "outcome": a["outcome"], "reason": a["reason"],
                   "gain": a["gain"], "plan_params": plan.get("params")}
            if a["attempt_no"] in keep:
                history.append(row)
            o = a["outcome"]
            if o in (Outcome.BROKEN.value, Outcome.SANDBOX.value, Outcome.NO_GAIN.value,
                     Outcome.INCOMPARABLE.value, Outcome.WORKER_FAILED.value):
                lessons.append("a%d %s '%s': %s" % (a["attempt_no"], o, plan.get("title") or "?",
                                                    (a["reason"] or "")[:200]))
        run = self.ledger.run(self.run_id)
        directions = [e["body"]["text"] for e in self.ledger.events(self.run_id, "direction")]
        base = self.ledger.champions(self.run_id)[0]
        acc = self.task.acceptance
        return {
            "attempt": n, "focus": focus,
            "task": {"goal": self.task.goal,
                     "direction": directions[-1] if directions else run["direction"],
                     "requirements": self.task.requirements,
                     "acceptance": {"objective": {"metric": acc.objective_metric,
                                                  "direction": acc.direction,
                                                  "min_rel_gain": acc.min_rel_gain},
                                    "constraints": [c.describe() for c in acc.constraints],
                                    "target": acc.target.describe() if acc.target else None}},
            "component": {"id": self.comp.component_id, "description": self.comp.description,
                          "editable": self.comp.editable},
            "champion": {"commit": champ[0], "values": champ[1].values},
            "baseline": {"commit": base["commit_sha"], "values": base["metrics"]["values"]},
            "history": history, "lessons": lessons[-20:], "budget_left": self.budget_left(),
            "tried_params": [a["plan"]["params"] for a in decided
                             if (a["plan"] or {}).get("params") is not None
                             and a["outcome"] != Outcome.INFRA.value],
            "domain": self.domain(tree).expert_context(tree),
        }

    # ---------------------------------------------------------------- attempt
    def _worker_outcome(self, call: WorkerCall) -> Outcome:
        return Outcome.INFRA if call.extra.get("infra") else Outcome.WORKER_FAILED

    def attempt(self, ws: Workspaces) -> tuple[Outcome, StopDecision | None]:
        champ = self.ledger.champion(self.run_id)
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
            return outcome, None

        try:
            expert_tree = ws.checkout("a%06d/expert" % n, champ[0])
            trees.append(expert_tree)
            expert, designer = self.workers(expert_tree)
            ctx = self.context(n, champ, focus, expert_tree)
            write_json(adir / "context.json", ctx)
            call = expert.propose(ctx, expert_tree, adir / "expert")
            charge("expert", call.cost, call)
            if call.exhausted:
                finish(Outcome.NO_CHANGE, "expert has no further experiment")
                return Outcome.NO_CHANGE, StopDecision("closed", "expert_exhausted")
            if not call.ok:
                out = self._worker_outcome(call)
                finish(out, "expert: %s" % call.error)
                if out is Outcome.INFRA:
                    return out, StopDecision("blocked", "expert worker unavailable: %s"
                                             % call.error[:200])
                return out, None
            plan = call.output
            why = validate_plan(plan)
            if why is None:
                outside = [f for f in plan["files"] if not self.comp.is_editable(f)]
                if outside:
                    why = "plan names non-editable paths: %s" % ", ".join(outside)
            if why is None:
                key = (plan.get("title"), tuple(sorted(plan["files"])), plan.get("changes"),
                       json.dumps(plan.get("params"), sort_keys=True))
                retryable = (Outcome.INFRA.value, Outcome.ABANDONED.value)
                for a in self.ledger.attempts(self.run_id):
                    p = a["plan"] or {}
                    if a["outcome"] in retryable:
                        continue
                    if a["attempt_no"] != n and (p.get("title"), tuple(sorted(p.get("files") or [])),
                                                 p.get("changes"),
                                                 json.dumps(p.get("params"), sort_keys=True)) == key:
                        why = "repeats attempt %d" % a["attempt_no"]
                        break
            write_json(adir / "plan.json", plan)
            self.ledger.update_attempt(self.run_id, n, "planned", plan=plan)
            if why:
                return finish(Outcome.WORKER_FAILED, "plan check: " + why)
            self.hard_check()

            design_tree = ws.checkout("a%06d/designer" % n, champ[0])
            trees.append(design_tree)
            call = designer.implement(plan, ctx, design_tree, adir / "designer")
            charge("designer", call.cost, call)
            if not call.ok:
                out = self._worker_outcome(call)
                finish(out, "designer: %s" % call.error)
                if out is Outcome.INFRA:
                    return out, StopDecision("blocked", "designer worker unavailable: %s"
                                             % call.error[:200])
                return out, None
            rep = sandbox(self.comp, design_tree, champ[0])
            write_json(adir / "sandbox.json", rep.as_dict())
            if not rep.ok:
                return finish(Outcome.SANDBOX, "changed non-editable paths: %s"
                              % ", ".join(rep.violations[:6]), files=rep.violations)
            patch = extract_patch(design_tree, champ[0], rep.editable)
            if not patch.strip():
                return finish(Outcome.NO_CHANGE, "designer left no editable change")
            write_text(adir / "candidate.patch", patch)
            self.ledger.update_attempt(self.run_id, n, "designed", patch_sha=patch_digest(patch),
                                       files=rep.editable)
            self.hard_check()

            ev, meas, eval_tree = self.evaluate_commit(ws, champ[0], patch, adir / "eval",
                                                       "a%06d/eval" % n)
            trees.append(eval_tree)
            charge("evaluator", Cost(ev.seconds, 0, 0.0))
            gates = [g.as_dict() for g in ev.gates]
            if ev.failure is not None:
                return finish(ev.failure, ev.reason, gates=gates)
            if meas.toolchain_digest != champ[1].toolchain_digest:
                # tools changed under a live run: re-measure the champion now, or every
                # later candidate is incomparable with it
                self.log("toolchain changed; re-measuring champion %s" % champ[0][:12])
                self.ledger.update_toolchain(self.run_id, meas.toolchain_digest)
                champ = (champ[0], self.measure_champion(ws, champ[0], n,
                                                         "re-measured: toolchain changed"))
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
            msg = "opc %s a%d: %s\n\n%s\n\n%s" % (self.task.task_id, n, plan["title"],
                                                  plan.get("hypothesis", ""), verdict.reason)
            new = commit_tree(eval_tree, msg)
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
                  "stagnation": "best_within_budget", "expert_exhausted": "best_within_budget"}
        business = None
        if run["state"] == "closed":
            key = (run["stop_reason"] or "").split(":")[0]
            business = result.get(key, "inconclusive")
            if business == "best_within_budget" and len(champs) <= 1:
                business = "no_valid_candidate"
        return {"run_id": self.run_id, "task": self.task.task_id, "revision": self.task.revision,
                "state": run["state"], "stop_reason": run["stop_reason"], "result": business,
                "champion_ref": self.ref, "champion": best["commit_sha"] if best else None,
                "baseline": base["commit_sha"] if base else None,
                "baseline_metrics": base["metrics"]["values"] if base else None,
                "champion_metrics": best["metrics"]["values"] if best else None,
                "objective": m, "objective_gain": gain, "outcomes": outcomes,
                "spent": self.spent(), "budget_left": self.budget_left()}

    def write_views(self) -> None:
        if not self.run_id:
            return
        s = self.summary()
        views = self.artifact_dir() / "views"
        write_json(views / "report.json", {**s, "attempts": self.ledger.attempts(self.run_id),
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
        for a in self.ledger.attempts(self.run_id):
            title = ((a["plan"] or {}).get("title") or "")[:50]
            lines.append("| %d | %s | %s | %s | %s |" % (
                a["attempt_no"], a["outcome"] or a["state"], title,
                "" if a["gain"] is None else "%+.2f%%" % (100 * a["gain"]),
                (a["reason"] or "").replace("|", "/").replace("\n", " ")[:120]))
            if a["outcome"] and a["outcome"] != Outcome.IMPROVEMENT.value:
                lessons.append("- a%d %s `%s`: %s" % (a["attempt_no"], a["outcome"], title,
                                                     (a["reason"] or "")[:200]))
        write_text(views / "STATE.md", "\n".join(lines) + "\n")
        write_text(views / "LESSONS.md", "\n".join(lessons) + "\n")
