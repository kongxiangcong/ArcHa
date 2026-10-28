"""opc: the command-line entry to the engine.

    opc init      -p DIR --project-id ID --name NAME [--component C] [--task T] [--apply]
    opc onboard   -p DIR [--agent codex]          draft .opc contracts with an agent
    opc check     -p DIR --task T                 validate contracts, run nothing
    opc preflight -p DIR --task T                 evaluate the base commit with every gate
    opc run       -p DIR --task T [--direction TEXT] [--new-run] [--base REF] [--max-now N]
    opc status    -p DIR [--task T]
    opc pause|stop -p DIR --task T                takes effect at the next attempt boundary
    opc report    -p DIR --task T
    opc promote   -p DIR --task T [--confirm N] [--review codex] [--apply BRANCH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.model import OPCError


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _engine(a, log=print):
    from .core.engine import Engine
    return Engine(Path(a.project), a.task, a.revision, log=log)


def cmd_init(a) -> int:
    from .scaffold import init
    _print(init(Path(a.project), a.project_id, a.name, a.component, a.task or "t-main", a.apply))
    return 0


def cmd_check(a) -> int:
    e = _engine(a)
    rep = e.static_check()
    rep["task_digest"] = e.task.digest
    _print(rep)
    return 0 if rep["ok"] else 1


def cmd_preflight(a) -> int:
    rep = _engine(a).preflight()
    _print(rep)
    return 0 if rep["ok"] else 1


def cmd_run(a) -> int:
    e = _engine(a, log=lambda s: print("[opc] " + s, flush=True))
    if a.deliver:
        e.enable_delivery()
    if a.repair_promotion:
        s = e.repair_delivery(a.repair_promotion)
    else:
        s = e.run(new_run=a.new_run, direction=a.direction, max_attempts_now=a.max_now,
                  base_ref=a.base)
    if a.deliver:
        s["complete"] = False
        if s["state"] == "closed" and e.ledger.control(e.run_id) not in ("pause", "stop") and "by user" not in (s["stop_reason"] or ""):
            from .core.promote import promote
            review = a.review
            if review is None and any(r.get("verification", "automated") != "automated" and r.get("required", True) for r in e.task.requirements):
                review = e.task.expert.kind if e.task.expert.kind in ("codex", "dsh") else None
            try:
                s["delivery"] = promote(e, review=review, source_run=s["run_id"])
                s["complete"] = s["delivery"]["complete"]
            except OPCError as exc:
                s["delivery_error"] = str(exc)
    _print(s)
    return (0 if s.get("complete") else 1) if a.deliver else (0 if s["state"] in ("closed", "paused") else 2)


def cmd_status(a) -> int:
    from .core.config import ProjectConfig
    from .core.ledger import Ledger
    project = ProjectConfig.load(Path(a.project))
    ledger = Ledger(project.root / ".opc" / "local" / "ledger.sqlite3")
    rows = []
    for r in ledger.runs():
        if a.task and r["task_id"] != a.task:
            continue
        champ = ledger.champion(r["run_id"])
        attempts = ledger.attempts(r["run_id"])
        work = ledger.events(r["run_id"], "working_version")
        selected = ledger.events(r["run_id"], "selected_version")
        default_commit = champ[0] if champ else work[-1]["body"]["commit"] if work else r["base_commit"]
        rows.append({"run_id": r["run_id"], "task": r["task_id"], "revision": r["revision"],
                     "state": r["state"], "stop_reason": r["stop_reason"],
                     "preparation": [x["body"] for x in ledger.events(r["run_id"], "preparation")][-1:],
                     "control": ledger.control(r["run_id"]), "attempts": len(attempts),
                     "last": [{"n": x["attempt_no"], "outcome": x["outcome"] or x["state"],
                               "reason": (x["reason"] or "")[:100]} for x in attempts[-5:]],
                     "champion": champ[0][:12] if champ else None,
                     "champion_metrics": champ[1].values if champ else None,
                     "working_version": work[-1]["body"]["commit"] if work else None,
                     "selected_version": selected[-1]["body"]["commit"] if selected else default_commit,
                     "spent": ledger.totals(r["run_id"])})
    _print(rows)
    return 0


def cmd_control(a) -> int:
    e = _engine(a)
    run = e.ledger.latest_run(a.task)
    if run is None:
        raise OPCError("task %s has no run" % a.task)
    e.ledger.set_control(run["run_id"], a.command)
    _print({"run_id": run["run_id"], "control": a.command,
            "note": "applies at the next attempt boundary"})
    return 0


def cmd_report(a) -> int:
    e = _engine(a)
    run = e.ledger.latest_run(a.task)
    if run is None:
        raise OPCError("task %s has no run" % a.task)
    e.run_id = run["run_id"]
    e.write_views()
    s = e.summary()
    s["views"] = str(e.artifact_dir() / "views")
    _print(s)
    return 0


def cmd_promote(a) -> int:
    from .core.promote import promote
    rep = promote(_engine(a), confirm_repeats=a.confirm, review=a.review, apply_to=a.apply, source_run=a.source_run, standards_confirmation=a.standards_confirmation)
    _print({k: v for k, v in rep.items() if k not in ("reviewer",)} |
           {"reviewer": (rep.get("reviewer") or {}).get("verdict")})
    return 0 if rep["promotable"] else 1


def cmd_brief_check(a) -> int:
    from .scaffold.brief import load_brief
    report, _ = load_brief(Path(a.project), a.brief)
    _print(report)
    return 0 if report["ok"] else 1


def cmd_onboard(a) -> int:
    from .scaffold.onboard import onboard
    report = onboard(Path(a.project), a.agent, brief=a.brief, prepare=a.prepare, task_id=a.task,
                     max_tokens=a.max_tokens, max_wall_seconds=a.max_wall_seconds, prior_tokens=a.prior_tokens, prior_wall_seconds=a.prior_wall_seconds, record_usage_only=a.record_usage, reconcile_usage=a.reconcile_usage)
    _print(report)
    return 0 if report["ok"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="opc", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, task=True, task_required=True):
        p = sub.add_parser(name)
        p.add_argument("-p", "--project", required=True, help="target project root")
        if task:
            p.add_argument("--task", required=task_required)
            p.add_argument("--revision", default=None)
        p.set_defaults(fn=fn)
        return p

    p = add("init", cmd_init, task=False)
    p.add_argument("--project-id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--component", default="main")
    p.add_argument("--task", default="t-main")
    p.add_argument("--apply", action="store_true")
    p = add("onboard", cmd_onboard, task=False)
    p.add_argument("--agent", default="codex", choices=["codex", "dsh"])
    p.add_argument("--brief", help="project-relative task-brief.md from discussion")
    p.add_argument("--prepare", action="store_true", default=True, help="complete scoped preparation and read-only review; never start formal experiments")
    p.add_argument("--reconcile-usage", help="evidence-backed JSON missing-usage receipt; record only, no worker dispatch")
    p.add_argument("--record-usage", action="store_true", help="update cumulative host usage without dispatching workers")
    p.add_argument("--task", default="t-main")
    p.add_argument("--max-tokens", type=int)
    p.add_argument("--max-wall-seconds", type=float)
    p.add_argument("--prior-wall-seconds", type=float)
    p.add_argument("--prior-tokens", type=int, help="cumulative host/nested input+output including cached input, excluding metered worker receipts")
    p = add("brief-check", cmd_brief_check, task=False)
    p.add_argument("--brief", required=True)
    add("check", cmd_check)
    add("preflight", cmd_preflight)
    p = add("run", cmd_run)
    p.add_argument("--direction", default=None)
    p.add_argument("--new-run", action="store_true")
    p.add_argument("--base", default=None, help="start a new run from this ref")
    p.add_argument("--deliver", action="store_true", help="terminal delivery check; never apply")
    p.add_argument("--repair-promotion", help="registered failed report to continue from selected candidate")
    p.add_argument("--review", choices=["codex", "dsh"])
    p.add_argument("--max-now", type=int, default=None, help="attempts in this session")
    add("status", cmd_status, task_required=False)
    for c in ("pause", "stop"):
        p = add(c, cmd_control)
        p.set_defaults(command=c)
    add("report", cmd_report)
    p = add("promote", cmd_promote)
    p.add_argument("--standards-confirmation", help="explicit user-approved old/new standards JSON for reassessment")
    p.add_argument("--source-run", help="explicit execution run for delivery")
    p.add_argument("--confirm", type=int, default=0, help="repeat baseline and selected delivery N times for numeric comparison")
    p.add_argument("--review", default=None, choices=[None, "codex", "dsh"])
    p.add_argument("--apply", default=None, metavar="BRANCH")
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except OPCError as exc:
        print("opc: error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())