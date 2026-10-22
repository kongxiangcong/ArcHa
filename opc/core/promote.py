"""Promotion: the spec axis, run once on baseline -> champion, then one human decision.

A round asks "is this better?"; promotion asks "is this worth having, and does
the claim stay inside its evidence?". On openTPU the champion never reached main
automatically over 98 slots; that is correct, and this module keeps it so: it
produces a report and, only with an explicit flag, moves a branch the user named.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from . import accept as acceptance
from .engine import Engine
from .model import Measurements, OPCError, write_json, write_text
from .workspace import cas_update_ref, git, read_ref


def checked_out_branches(repo: Path) -> set[str]:
    out = str(git("worktree", "list", "--porcelain", cwd=repo))
    return {l.split(" ", 1)[1] for l in out.splitlines() if l.startswith("branch ")}


def promote(engine: Engine, confirm_repeats: int = 0, review: str | None = None,
            apply_to: str | None = None) -> dict[str, Any]:
    run = engine.ledger.latest_run(engine.task.task_id)
    if run is None:
        raise OPCError("task %s has no run" % engine.task.task_id)
    engine.run_id = run["run_id"]
    champs = engine.ledger.champions(engine.run_id)
    if len(champs) < 2:
        raise OPCError("run %s has no accepted candidate to promote" % engine.run_id)
    base, best = champs[0], champs[-1]
    root, task = engine.root, engine.task
    pid = "promotion-%d" % int(time.time())
    out = engine.artifact_dir() / "promotion" / pid
    findings: list[dict[str, str]] = []

    def finding(kind: str, severity: str, text: str) -> None:
        findings.append({"check": kind, "severity": severity, "text": text})

    # 1. scope: the cumulative change stays inside the editable paths
    names = str(git("diff", "--name-only", "-z", base["commit_sha"], best["commit_sha"], cwd=root))
    files = sorted(p for p in names.split("\0") if p)
    outside = [f for f in files if not engine.comp.is_editable(f)]
    if outside:
        finding("scope", "block", "champion changes non-editable paths: %s" % ", ".join(outside))
    patch = str(git("diff", "--binary", base["commit_sha"], best["commit_sha"], cwd=root))
    write_text(out / "cumulative.patch", patch)

    # 2. evaluator: the champion still carries the frozen evaluator
    pinned = run["evaluator_digest"]
    now = engine.evaluator_digest(best["commit_sha"])[0]
    if now != pinned:
        finding("evaluator", "block", "champion evaluator digest %s != pinned %s"
                % (now[:12], pinned[:12]))

    # 3. evidence chain: every champion step comparable with its predecessor
    for prev, cur in zip(champs, champs[1:]):
        ok, why = Measurements.from_dict(cur["metrics"]).comparable(
            Measurements.from_dict(prev["metrics"]))
        if not ok and "re-measured" not in cur["reason"]:
            finding("evidence", "block", "champion seq %d not comparable with seq %d: %s"
                    % (cur["seq"], prev["seq"], why))
        if cur["metrics"].get("degraded_by"):
            finding("evidence", "warn", "champion seq %d was judged without gates %s"
                    % (cur["seq"], cur["metrics"]["degraded_by"]))

    # 4. single-measurement wins: repeat baseline and champion to see the gain survive noise
    m = task.acceptance.objective_metric
    claimed = acceptance.relative_gain(task.acceptance, base["metrics"]["values"][m],
                                       best["metrics"]["values"][m])
    confirm = None
    if confirm_repeats > 1:
        ws = engine.workspaces("promotion")
        samples: dict[str, list[float]] = {"baseline": [], "champion": []}
        try:
            for label, commit in (("baseline", base["commit_sha"]), ("champion",
                                                                     best["commit_sha"])):
                for i in range(confirm_repeats):
                    ev, meas, tree = engine.evaluate_commit(ws, commit, "", out / "confirm" /
                                                            ("%s-%d" % (label, i)), label)
                    ws.drop(tree)
                    if ev.failure is not None:
                        finding("reproduce", "block", "%s failed on repeat %d: %s"
                                % (label, i, ev.reason))
                        break
                    samples[label].append(meas.values[m])
        finally:
            ws.drop_all()
        if samples["baseline"] and samples["champion"]:
            worst = acceptance.relative_gain(task.acceptance,
                                             min(samples["baseline"]) if task.acceptance.direction
                                             == "minimize" else max(samples["baseline"]),
                                             max(samples["champion"]) if task.acceptance.direction
                                             == "minimize" else min(samples["champion"]))
            confirm = {"samples": samples, "worst_case_gain": worst}
            if worst <= task.acceptance.min_rel_gain:
                finding("reproduce", "block", "worst-case gain %.2f%% over %d repeats does not "
                        "clear %.2f%%" % (100 * worst, confirm_repeats,
                                          100 * task.acceptance.min_rel_gain))
    else:
        finding("reproduce", "warn", "gain %.2f%% rests on single measurements; pass "
                "--confirm N to repeat" % (100 * claimed))

    # 5. requirements: "automated" says how a requirement is verified, not that it holds.
    #    A requirement with a machine check is judged on the champion's metrics.
    from .config import Constraint
    champ_values = best["metrics"]["values"]
    if task.acceptance.target and not acceptance.target_met(task.acceptance, champ_values):
        finding("target", "warn", "target %s not met (champion %s=%g)" % (
            task.acceptance.target.describe(), task.acceptance.target.metric,
            champ_values.get(task.acceptance.target.metric, float("nan"))))
    coverage = []
    for req in task.requirements:
        how = req.get("verification", "automated")
        chk = req.get("check")
        if chk:
            c = Constraint(metric=chk["metric"], op=chk["op"], value=float(chk["value"]))
            why = acceptance.check(c, champ_values, None)
            status = "met" if why is None else "not_met: " + why
            if why is not None:
                finding("requirements", "warn", "%s not met: %s" % (req.get("id"), why))
        elif how == "automated":
            status = "enforced_per_attempt (no separate check declared)"
        else:
            status = "needs_review"
            if not review:
                finding("requirements", "warn", "%s needs independent review" % req.get("id"))
        coverage.append({"id": req.get("id"), "text": req.get("text"), "verification": how,
                         "status": status})

    # 6. optional independent reviewer: a fresh read-only model session
    reviewer = None
    if review:
        reviewer = run_reviewer(engine, review, out, patch, base, best, coverage)
        # Fail closed on every path that is not a positive verdict. A reviewer
        # reply carrying no verdict once read as "nothing blocked", which let a
        # prose answer that never judged the change pass silently.
        verdict = reviewer.get("verdict")
        if not reviewer.get("ok"):
            finding("review", "block", "reviewer unavailable: %s" % reviewer.get("error", ""))
        elif verdict == "reject":
            finding("review", "block", "reviewer rejected: %s" % reviewer.get("summary", ""))
        elif verdict not in ("accept", "accept_with_conditions"):
            finding("review", "block", "reviewer returned no usable verdict (%r); a reply that "
                    "does not judge the change cannot pass it" % verdict)
        elif verdict == "accept_with_conditions":
            finding("review", "warn", "reviewer accepted with conditions: %s"
                    % reviewer.get("summary", ""))

    blocked = any(f["severity"] == "block" for f in findings)
    report = {"promotion_id": pid, "run_id": engine.run_id, "task": task.task_id,
              "baseline": base["commit_sha"], "champion": best["commit_sha"], "files": files,
              "objective": m, "claimed_gain": claimed, "confirm": confirm,
              "baseline_metrics": base["metrics"]["values"],
              "champion_metrics": best["metrics"]["values"], "requirements": coverage,
              "findings": findings, "reviewer": reviewer, "promotable": not blocked,
              "applied": False}

    if apply_to:
        if blocked:
            raise OPCError("promotion blocked: %s" % "; ".join(f["text"] for f in findings
                                                                 if f["severity"] == "block"))
        ref = "refs/heads/" + apply_to
        old = read_ref(root, ref)
        if old is None:
            raise OPCError("branch %s does not exist" % apply_to)
        if not _is_ancestor(root, old, best["commit_sha"]):
            raise OPCError("%s has moved since the run's base; merge %s by hand"
                           % (apply_to, engine.ref))
        if ref in checked_out_branches(root):
            report["apply_instructions"] = ("%s is checked out; run in that worktree: "
                                            "git merge --ff-only %s" % (apply_to, best["commit_sha"]))
        else:
            cas_update_ref(root, ref, best["commit_sha"], old)
            report["applied"] = True
        engine.ledger.event(engine.run_id, "promoted", None, to=apply_to,
                            commit=best["commit_sha"], applied=report["applied"])

    write_json(out / "report.json", report)
    write_text(out / "PROMOTION.md", render(report))
    report["report_dir"] = str(out)
    return report


def _is_ancestor(repo: Path, a: str, b: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", a, b],
                          cwd=str(repo)).returncode == 0


def run_reviewer(engine: Engine, kind: str, out: Path, patch: str, base: dict, best: dict,
                 coverage: list[dict]) -> dict[str, Any]:
    if kind not in ("codex", "dsh"):
        raise OPCError("the reviewer must be codex or dsh")
    # Both workers expose the same private _run(role, prompt, tree, log_dir,
    # sandbox, schema). dsh ignores the schema argument: headless has no
    # --output-schema, so the reply is parsed and a non-JSON reply is a
    # reviewer failure rather than a silent pass.
    if kind == "dsh":
        from ..adapters.dsh import DshWorker
        worker_cls = DshWorker
    else:
        from ..adapters.codex import CodexWorker
        worker_cls = CodexWorker
    schema = {"type": "object", "additionalProperties": False,
              "required": ["verdict", "summary", "overreach", "requirement_findings"],
              "properties": {
                  "verdict": {"type": "string", "enum": ["accept", "accept_with_conditions",
                                                         "reject"]},
                  "summary": {"type": "string"},
                  "overreach": {"type": "array", "items": {"type": "string"}},
                  "requirement_findings": {"type": "array", "items": {"type": "string"}}}}
    prompt = f"""You are an independent SPEC reviewer. You did not write this change.
Judge whether the cumulative change below is worth promoting and whether any claim overreaches
its evidence (single measurements, proxy metrics, skipped gates, scope creep).

Task goal: {engine.task.goal}
Requirements and how they were verified: {json.dumps(coverage, ensure_ascii=False)}
Baseline metrics: {json.dumps(base['metrics'])}
Champion metrics: {json.dumps(best['metrics'])}

Cumulative diff (baseline -> champion):
```
{patch[:60000]}
```
The working directory is a read-only checkout of the champion."""
    ws = engine.workspaces("review")
    try:
        tree = ws.checkout("reviewer", best["commit_sha"])
        worker = worker_cls(dict(engine.task.expert.options))
        call, text = worker._run("reviewer", prompt, tree, out / "reviewer", "read-only", schema)
    finally:
        ws.drop_all()
    engine.ledger.charge(engine.run_id, None, "reviewer", call.cost)
    engine.ledger.event(engine.run_id, "worker_call", None, role="reviewer",
                        call_id=call.call_id, ok=call.ok, tokens=call.cost.tokens,
                        error=call.error[:300])
    if not call.ok:
        return {"ok": False, "error": call.error, "call_id": call.call_id}
    try:
        return {"ok": True, "call_id": call.call_id, **json.loads(text)}
    except json.JSONDecodeError:
        pass
    # dsh has no --output-schema, so its reply may be fenced or wrapped in prose.
    # A reply with no object is a reviewer failure, never an implied accept.
    if kind == "dsh":
        from ..adapters.dsh import extract_json
        obj = extract_json(text, require=("verdict",))
        if obj is not None:
            return {"ok": True, "call_id": call.call_id, **obj}
    return {"ok": False, "error": "reviewer reply is not JSON", "call_id": call.call_id}


def render(r: dict[str, Any]) -> str:
    lines = ["# Promotion report %s" % r["promotion_id"], "",
             "- run: `%s`, task `%s`" % (r["run_id"], r["task"]),
             "- baseline `%s` -> champion `%s`" % (r["baseline"][:12], r["champion"][:12]),
             "- objective `%s`: claimed gain %+.2f%%" % (r["objective"], 100 * r["claimed_gain"]),
             "- files: %s" % ", ".join(r["files"]),
             "- **promotable: %s**" % r["promotable"], "", "## Findings", ""]
    for f in r["findings"] or [{"severity": "-", "check": "-", "text": "none"}]:
        lines.append("- [%s] %s: %s" % (f["severity"], f["check"], f["text"]))
    lines += ["", "## Requirements", ""]
    for c in r["requirements"]:
        lines.append("- %s (%s): %s" % (c["id"], c["verification"], c["status"]))
    if r.get("confirm"):
        lines += ["", "## Reproduction", "", "worst-case gain %+.2f%%" %
                  (100 * r["confirm"]["worst_case_gain"])]
    lines += ["", "The decision to merge is the user's. This report does not merge anything "
              "unless --apply was given."]
    return "\n".join(lines) + "\n"
