"""The dsh worker, driven by a fake `dsh` binary that speaks the headless --json stream.

The fake reproduces the contract this adapter actually depends on: session/status/
tool_call/status(step_end, usage)/status(turn_end)/final, exit 0 vs 1, and the
turn-end error code taxonomy. A real dsh is not required, and no test here claims
a real model ran.
"""
from __future__ import annotations

import json
import stat
import sys

import pytest

from opc.tests.conftest import task, write

from opc.adapters.dsh import extract_json, parse_events
from opc.adapters.worker import EXHAUSTED_SENTINEL
from opc.core.config import TaskSpec
from opc.core.model import OPCError, Outcome

FENCE = chr(96) * 3

#: A fake dsh. It reads the prompt on stdin, inspects DSH_PERMISSION_MODE for the
#: role, and emits the headless event stream. Behaviours are selected by
#: FAKE_DSH_MODE so one binary covers the normal and the failure paths.
FAKE_DSH = r'''
import json, os, sys, uuid
from pathlib import Path
mode = os.environ.get("FAKE_DSH_MODE", "ok")
sandbox = os.environ.get("DSH_PERMISSION_MODE", "")
prompt = sys.stdin.read()
cwd = Path.cwd()
sid = "session-" + uuid.uuid4().hex
FENCE = chr(96) * 3

def emit(**ev):
    print(json.dumps(ev), flush=True)

emit(type="session", sessionId=sid, cwd=str(cwd))
emit(type="status", phase="turn_start", turn=1)

if mode == "credential":
    emit(type="status", phase="turn_end", turn=1, reason={"kind": "error", "error": {
        "message": "no API key for provider route", "code": "MISSING_CREDENTIAL"}})
    emit(type="final", text="")
    sys.exit(1)

if mode == "quota":
    emit(type="status", phase="turn_end", turn=1, reason={"kind": "error", "error": {
        "message": "insufficient balance", "code": "QUOTA"}})
    emit(type="final", text="")
    sys.exit(1)

if mode == "dsh_home_missing":
    print("dsh: ENOENT: mkdir profiles/headless", file=sys.stderr)
    sys.exit(1)

emit(type="status", phase="step_start", turn=1, step=1)
x = json.loads((cwd / "params.json").read_text())["x"]

if sandbox == "read-only":
    assert "EXPERT" in prompt, "expert prompt arrived without the role marker"
    if mode == "exhausted":
        emit(type="tool_call", callId="c1", tool="read", input={"file_path": "params.json"})
        emit(type="tool_result", callId="c1", status="completed", result="{}")
        emit(type="status", phase="step_end", turn=1, step=1,
             usage={"inputTokens": 40, "outputTokens": 5})
        emit(type="status", phase="turn_end", turn=1, reason={"kind": "completed"})
        emit(type="final", text="NO_EXPERIMENT")
        sys.exit(0)
    if mode == "not_json":
        text = "I would rather describe the plan in prose than in JSON."
    else:
        plan = {"title": "x=%d" % (x + 1), "hypothesis": "closer to 7",
                "files": ["params.json"], "changes": "set x to %d" % (x + 1),
                "expected": "lower loss", "falsifier": "loss rises"}
        text = "Here is the plan:" + chr(10) + FENCE + "json" + chr(10) + json.dumps(plan) + chr(10) + FENCE
else:
    assert sandbox == "workspace-write", "designer ran without a writable policy"
    assert "DESIGNER" in prompt
    (cwd / "params.json").write_text(json.dumps({"x": x + 1}))
    if mode == "cheat":
        (cwd / ".opc/eval/evaluate.py").write_text("raise SystemExit(0)" + chr(10))
    text = "set x to %d" % (x + 1)

emit(type="status", phase="step_end", turn=1, step=1,
     usage={"inputTokens": 1000, "outputTokens": 200, "cacheReadTokens": 100})
emit(type="status", phase="turn_end", turn=1, reason={"kind": "completed"})
emit(type="final", text=text)
sys.exit(0)
'''


@pytest.fixture
def fake_dsh(tmp_path):
    p = tmp_path / "bin" / "dsh.py"
    p.parent.mkdir()
    p.write_text("#!/usr/bin/env python3" + FAKE_DSH, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def dsh_task(binary: str, **budget) -> dict:
    t = task()
    t["workers"] = {"expert": {"kind": "dsh", "binary": binary},
                    "designer": {"kind": "dsh", "binary": binary}}
    t["budget"].update({"max_tokens": 100000, **budget})
    return t


# ------------------------------------------------------------------ the loop
def test_dsh_worker_loop_records_identity_and_tokens(make_project, engine_for, fake_dsh):
    e = engine_for(make_project(tsk=dsh_task(fake_dsh)))
    s = e.run()
    assert s["result"] == "target_met"
    # Each call reports 1000 + 200 + 100 disjoint tokens, so the total is a
    # whole number of calls and every call is charged, not just the successes.
    assert s["spent"]["tokens"] % 1300 == 0 and s["spent"]["tokens"] > 0
    assert not s["spent"]["usd_known"], "dsh reports no price; usd must stay unknown"
    calls = e.ledger.events(e.run_id, "worker_call")
    assert calls and all(c["body"]["call_id"] for c in calls)
    assert len({c["body"]["call_id"] for c in calls}) == len(calls), "session ids must differ"


def test_dsh_editing_evaluator_fails_sandbox(make_project, engine_for, fake_dsh, monkeypatch):
    monkeypatch.setenv("FAKE_DSH_MODE", "cheat")
    e = engine_for(make_project(tsk=dsh_task(fake_dsh, max_attempts=1)))
    e.run()
    assert [a["outcome"] for a in e.ledger.attempts(e.run_id)] == [Outcome.SANDBOX.value]


@pytest.mark.parametrize("mode", ["credential", "quota"])
def test_dsh_account_failure_blocks_without_spending_search(make_project, engine_for,
                                                            fake_dsh, monkeypatch, mode):
    monkeypatch.setenv("FAKE_DSH_MODE", mode)
    e = engine_for(make_project(tsk=dsh_task(fake_dsh)))
    s = e.run()
    assert s["state"] == "blocked"
    assert [a["outcome"] for a in e.ledger.attempts(e.run_id)] == [Outcome.INFRA.value]
    assert s["spent"]["search_attempts"] == 0, "INFRA must not consume the search budget"


def test_dsh_exhausted_expert_closes_the_run(make_project, engine_for, fake_dsh, monkeypatch):
    monkeypatch.setenv("FAKE_DSH_MODE", "exhausted")
    e = engine_for(make_project(tsk=dsh_task(fake_dsh)))
    s = e.run()
    assert s["state"] == "closed" and s["stop_reason"] == "expert_exhausted"


def test_dsh_prose_reply_is_not_accepted_as_a_plan(make_project, engine_for, fake_dsh,
                                                   monkeypatch):
    monkeypatch.setenv("FAKE_DSH_MODE", "not_json")
    e = engine_for(make_project(tsk=dsh_task(fake_dsh, max_attempts=1)))
    e.run()
    attempts = e.ledger.attempts(e.run_id)
    assert attempts[0]["outcome"] != Outcome.IMPROVEMENT.value


def test_dsh_missing_binary_is_infra(make_project, engine_for):
    e = engine_for(make_project(tsk=dsh_task("/nonexistent/dsh")))
    s = e.run()
    assert s["state"] == "blocked"
    assert [a["outcome"] for a in e.ledger.attempts(e.run_id)] == [Outcome.INFRA.value]


def test_token_budget_stops_before_overspending(make_project, engine_for, fake_dsh):
    e = engine_for(make_project(tsk=dsh_task(fake_dsh, max_tokens=1300)))
    s = e.run()
    assert s["stop_reason"].startswith("budget_exhausted: max_tokens")
    assert s["spent"]["tokens"] <= 2600


# -------------------------------------------------------------- the contract
def test_dsh_task_requires_token_cap(tmp_path):
    t = dsh_task("dsh")
    t["budget"].pop("max_tokens")
    write(tmp_path / ".opc/tasks/t-toy/revisions/r0001/task.json", json.dumps(t))
    with pytest.raises(OPCError, match="max_tokens"):
        TaskSpec.load(tmp_path, "t-toy")


def test_dsh_expert_needs_a_designer(tmp_path):
    t = task()
    t["workers"] = {"expert": {"kind": "dsh"}}
    t["budget"]["max_tokens"] = 1000
    write(tmp_path / ".opc/tasks/t-toy/revisions/r0001/task.json", json.dumps(t))
    with pytest.raises(OPCError, match="needs a designer"):
        TaskSpec.load(tmp_path, "t-toy")


def test_unknown_worker_kind_still_rejected(tmp_path):
    t = task()
    t["workers"] = {"expert": {"kind": "claude"}}
    write(tmp_path / ".opc/tasks/t-toy/revisions/r0001/task.json", json.dumps(t))
    with pytest.raises(OPCError, match="codex, dsh or scripted"):
        TaskSpec.load(tmp_path, "t-toy")


# --------------------------------------------------------------- the parsing
def test_parse_completed_stream_sums_disjoint_usage():
    lines = [
        {"type": "session", "sessionId": "session-a"},
        {"type": "tool_call", "callId": "c1", "tool": "read", "input": {}},
        {"type": "status", "phase": "step_end", "turn": 1, "step": 1,
         "usage": {"inputTokens": 100, "outputTokens": 20, "cacheReadTokens": 5,
                   "cacheWriteTokens": 1}},
        {"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "completed"}},
        {"type": "final", "text": "done"},
    ]
    info = parse_events("\n".join(json.dumps(x) for x in lines))
    assert info["session_id"] == "session-a"
    assert info["tokens"] == 126 and info["usage_complete"] is True
    assert info["tool_calls"] == 1 and info["end_kind"] == "completed"
    assert info["text"] == "done"


def test_parse_step_without_usage_is_marked_incomplete():
    lines = [
        {"type": "status", "phase": "step_end", "turn": 1, "step": 1,
         "usage": {"inputTokens": 7}},
        {"type": "status", "phase": "step_end", "turn": 1, "step": 2},
    ]
    info = parse_events("\n".join(json.dumps(x) for x in lines))
    assert info["tokens"] == 7
    assert info["usage_complete"] is False, "a partial sum must not read as a total"


def test_parse_carries_the_turn_end_error_code():
    lines = [
        {"type": "status", "phase": "turn_end", "turn": 1,
         "reason": {"kind": "error", "error": {"message": "no key",
                                               "code": "MISSING_CREDENTIAL"}}},
        {"type": "final", "text": ""},
    ]
    info = parse_events("\n".join(json.dumps(x) for x in lines))
    assert info["end_kind"] == "error" and info["end_code"] == "MISSING_CREDENTIAL"


def test_parse_ignores_garbage_lines_and_empty_stream():
    assert parse_events("")["tokens"] == 0
    assert parse_events("not json\n{broken\n")["end_kind"] is None


def test_extract_json_handles_fences_and_braces_in_strings():
    assert extract_json(FENCE + 'json\n{"a": 1}\n' + FENCE) == {"a": 1}
    assert extract_json('lead {"changes": "use } here", "n": 2} tail') == \
        {"changes": "use } here", "n": 2}
    assert extract_json("no object here") is None
    assert extract_json('{"unterminated": 1') is None


def test_exhausted_sentinel_is_exported_for_prompt_and_test():
    assert EXHAUSTED_SENTINEL == "NO_EXPERIMENT"


# ------------------------------------------------ fail-closed extraction rules
def test_extract_json_skips_objects_missing_required_keys():
    """A prose reply can contain a stray empty object (an empty fence, a shell
    example). Returning it as a plan or a verdict would let an unjudged reply
    pass, so a candidate object must carry every required key."""
    reply = 'Example: {}\nReal: {"title": "t", "files": []}'
    assert extract_json(reply, require=("title", "files")) == {"title": "t", "files": []}
    assert extract_json("only an empty {} here", require=("verdict",)) is None
    # Without the constraint the first object still wins, so the guard is opt-in.
    assert extract_json("Example: {}\nReal: {\"a\": 1}") == {}


def test_promotion_blocks_when_the_reviewer_returns_no_verdict(make_project, engine_for,
                                                              monkeypatch):
    """Regression for the defect a real dsh run exposed: a reviewer that answered
    in prose and exited 0 read as 'nothing blocked', so promotion passed with no
    verdict at all."""
    from opc.core import promote as promote_mod

    monkeypatch.setattr(promote_mod, "run_reviewer", lambda *a, **k: {"ok": True, "call_id": "x"})
    e = engine_for(make_project())
    e.run()
    rep = promote_mod.promote(e, review="dsh")
    assert not rep["promotable"]
    assert any("no usable verdict" in f["text"] for f in rep["findings"])


def test_promotion_blocks_when_the_reviewer_is_unavailable(make_project, engine_for,
                                                           monkeypatch):
    from opc.core import promote as promote_mod

    monkeypatch.setattr(promote_mod, "run_reviewer",
                        lambda *a, **k: {"ok": False, "error": "dsh credit exhausted"})
    e = engine_for(make_project())
    e.run()
    rep = promote_mod.promote(e, review="dsh")
    assert not rep["promotable"]
    assert any("reviewer unavailable" in f["text"] for f in rep["findings"])


def test_promotion_accepts_a_real_verdict(make_project, engine_for, monkeypatch):
    from opc.core import promote as promote_mod

    monkeypatch.setattr(promote_mod, "run_reviewer",
                        lambda *a, **k: {"ok": True, "verdict": "accept", "summary": "fine"})
    e = engine_for(make_project())
    e.run()
    assert promote_mod.promote(e, review="dsh")["promotable"]



def test_both_workers_share_the_exhaustion_semantics():
    """Neither adapter may invent its own "nothing left" rule: the schema field is
    optional in PLAN_SCHEMA, and the shared sentinel is importable from worker.py,
    so either adapter can be deleted without changing termination behaviour."""
    from opc.adapters.worker import EXHAUSTED_SENTINEL, PLAN_SCHEMA
    assert PLAN_SCHEMA["properties"]["exhausted"]["type"] == "boolean"
    assert "exhausted" not in PLAN_SCHEMA["required"], "a normal plan must omit it"
    assert EXHAUSTED_SENTINEL == "NO_EXPERIMENT"


def test_dsh_honours_the_schema_style_exhausted_field(make_project, engine_for, fake_dsh,
                                                      monkeypatch):
    monkeypatch.setenv("FAKE_DSH_MODE", "not_json")
    e = engine_for(make_project(tsk=dsh_task(fake_dsh, max_attempts=1)))
    e.run()
    # A prose reply is a wasted attempt, never an accepted plan.
    assert [a["outcome"] for a in e.ledger.attempts(e.run_id)] != [Outcome.IMPROVEMENT.value]


def test_expert_prompt_carries_exhaustion_rule_for_both_workers():
    from opc.adapters.prompts import expert_prompt

    ctx = {"task": {"goal": "g", "direction": "", "acceptance": "x"},
           "component": {"id": "c", "editable": ["a"], "focus_areas": [], "description": "d"},
           "champion": {"commit": "abcdef123456", "values": {}}, "baseline": {"values": {}},
           "history": [], "lessons": [], "budget_left": {}, "domain": {"context_files": {}}}
    codex_prompt = expert_prompt(ctx)
    dsh_prompt = expert_prompt(ctx, plain_text_reply=True)
    # The role-level rule reaches both; only dsh gets the free-text sentinel.
    assert '"exhausted"' in codex_prompt and '"exhausted"' in dsh_prompt
    assert "NO_EXPERIMENT" not in codex_prompt
    assert "NO_EXPERIMENT" in dsh_prompt
