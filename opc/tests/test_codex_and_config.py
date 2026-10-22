import json
import os
import stat
from pathlib import Path

import pytest

from opc.tests.conftest import component, task, write

from opc.adapters.codex import parse_events
from opc.core.config import ComponentConfig, TaskSpec
from opc.core.model import OPCError, Outcome

FAKE_CODEX = r'''#!/usr/bin/env python3
"""Mimics `codex exec --json`: event stream on stdout, last message to -o."""
import json, os, sys, uuid
from pathlib import Path
args = sys.argv[1:]
cwd = Path(args[args.index("-C") + 1]); last = Path(args[args.index("-o") + 1])
prompt = sys.stdin.read()
mode = os.environ.get("FAKE_CODEX_MODE", "ok")
print(json.dumps({"type": "thread.started", "thread_id": str(uuid.uuid4())}))
if mode == "limit":
    print(json.dumps({"type": "turn.failed", "error": {"message": "You've hit your usage limit."}}))
    sys.exit(1)
if mode.startswith("onboard"):
    assert "workspace-write" in args and "onboarding" in prompt
    (cwd / ".opc/README.md").write_text("Open items: none\n")
    if mode == "onboard_stray":
        with open(cwd / "params.json", "a") as f:
            f.write("\n")
    last.write_text("drafted"); sys.exit(0)
x = json.loads((cwd / "params.json").read_text())["x"]
if "--output-schema" in args:
    assert "read-only" in args and "EXPERT" in prompt
    if mode == "exhausted":
        msg = json.dumps({"title": "nothing left", "hypothesis": "search exhausted",
                          "files": [], "changes": "", "expected": "", "falsifier": "",
                          "exhausted": True})
        print(json.dumps({"type": "item.completed",
                          "item": {"type": "agent_message", "text": msg}}))
        print(json.dumps({"type": "turn.completed",
                          "usage": {"input_tokens": 10, "cached_input_tokens": 0,
                                    "output_tokens": 2}}))
        last.write_text(msg); sys.exit(0)
    msg = json.dumps({"title": "x=%d" % (x + 1), "hypothesis": "closer to 7",
                      "files": ["params.json"], "changes": "set x to %d" % (x + 1),
                      "expected": "lower loss", "falsifier": "loss rises"})
else:
    assert "workspace-write" in args and "DESIGNER" in prompt
    (cwd / "params.json").write_text(json.dumps({"x": x + 1}))
    if mode == "cheat":
        (cwd / ".opc/eval/evaluate.py").write_text("raise SystemExit(0)\n")
    msg = "set x"
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": msg}}))
print(json.dumps({"type": "turn.completed",
                  "usage": {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 200}}))
last.write_text(msg)
'''


@pytest.fixture
def fake_codex(tmp_path):
    p = tmp_path / "bin" / "codex"
    p.parent.mkdir()
    p.write_text(FAKE_CODEX)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def codex_task(binary: str, **budget) -> dict:
    t = task()
    t["workers"] = {"expert": {"kind": "codex", "binary": binary},
                    "designer": {"kind": "codex", "binary": binary}}
    t["budget"].update({"max_tokens": 100000, **budget})
    return t


def test_codex_worker_loop_records_identity_and_tokens(make_project, engine_for, fake_codex):
    e = engine_for(make_project(tsk=codex_task(fake_codex)))
    s = e.run()
    assert s["result"] == "target_met"
    assert s["spent"]["tokens"] == 4 * 2400
    assert not s["spent"]["usd_known"]
    calls = e.ledger.events(e.run_id, "worker_call")
    assert len(calls) == 8 and all(c["body"]["call_id"] for c in calls)
    assert len({c["body"]["call_id"] for c in calls}) == 8


def test_codex_editing_evaluator_fails_sandbox(make_project, engine_for, fake_codex,
                                               monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "cheat")
    e = engine_for(make_project(tsk=codex_task(fake_codex, max_attempts=1)))
    e.run()
    assert [a["outcome"] for a in e.ledger.attempts(e.run_id)] == [Outcome.SANDBOX.value]


def test_codex_usage_limit_blocks_the_run_at_once(make_project, engine_for, fake_codex,
                                                  monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "limit")
    e = engine_for(make_project(tsk=codex_task(fake_codex)))
    s = e.run()
    assert s["state"] == "blocked" and "usage limit" in s["stop_reason"]
    assert [a["outcome"] for a in e.ledger.attempts(e.run_id)] == [Outcome.INFRA.value]
    assert s["spent"]["search_attempts"] == 0


def test_token_budget_stops_before_overspending(make_project, engine_for, fake_codex):
    e = engine_for(make_project(tsk=codex_task(fake_codex, max_tokens=6000)))
    s = e.run()
    assert s["stop_reason"].startswith("budget_exhausted: max_tokens")
    assert s["spent"]["tokens"] <= 6000


@pytest.mark.parametrize("mode,ok", [("onboard", True), ("onboard_stray", False)])
def test_onboard_writes_only_under_opc(make_project, fake_codex, monkeypatch, mode, ok):
    from opc.scaffold.onboard import onboard
    root = make_project()
    with open(root / "params.json", "a") as f:
        f.write(" ")  # already dirty before the agent runs
    monkeypatch.setenv("OPC_CODEX_BIN", fake_codex)
    monkeypatch.setenv("FAKE_CODEX_MODE", mode)
    r = onboard(root, "codex")
    assert r["ok"] is ok
    assert r["changed_outside_opc"] == ([] if ok else ["params.json"])


def test_parse_real_codex_failure_stream():
    stream = "\n".join([
        '{"type":"thread.started","thread_id":"01a1"}',
        '{"type":"item.completed","item":{"id":"item_0","type":"error","message":"config warning"}}',
        '{"type":"turn.started"}',
        '{"type":"error","message":"You\u2019ve hit your usage limit."}',
        '{"type":"turn.failed","error":{"message":"You\u2019ve hit your usage limit."}}'])
    info = parse_events(stream)
    assert info["thread_id"] == "01a1" and info["failed"] and info["tokens"] == 0


# ------------------------------------------------------------------- contracts
def _write(root: Path, comp: dict | None = None, tsk: dict | None = None):
    if comp is not None:
        write(root / ".opc/components/toy.json", json.dumps(comp))
    if tsk is not None:
        write(root / ".opc/tasks/t-toy/revisions/r0001/task.json", json.dumps(tsk))


@pytest.mark.parametrize("over,match", [
    ({"editable": []}, "sandbox would be vacuous"),
    ({"evaluator_files": []}, "nothing pins"),
    ({"editable": [".opc/eval/evaluate.py"]}, "overlaps the evaluator"),
    ({"gates": [{"id": "g", "argv": ["sh", "-c", "echo hi"], "metrics": "m"}]}, "sh -c"),
    ({"gates": [{"id": "g", "argv": ["true"]}]}, "nothing can be measured"),
    ({"frozen": ["*.json"]}, "also frozen"),
])
def test_component_validation_fails_closed(tmp_path, over, match):
    _write(tmp_path, comp=component(**over))
    with pytest.raises(OPCError, match=match):
        ComponentConfig.load(tmp_path, "toy")


def test_unknown_fields_are_rejected_and_underscore_notes_allowed(tmp_path):
    _write(tmp_path, comp=component(schema_version="opc.component.v0.2"))
    with pytest.raises(OPCError, match="unknown field.*schema_version"):
        ComponentConfig.load(tmp_path, "toy")
    old = component()
    old["editable_paths"] = old.pop("editable")
    _write(tmp_path, comp=old)
    with pytest.raises(OPCError, match="unknown field.*editable_paths"):
        ComponentConfig.load(tmp_path, "toy")
    _write(tmp_path, comp=component(_note="why these gates"))
    ComponentConfig.load(tmp_path, "toy")
    t = task()
    t["acceptance"]["constraints"].append({"metric": "loss", "op": "<=", "value": 9, "unit": "x"})
    _write(tmp_path, tsk=t)
    with pytest.raises(OPCError, match="constraints.*unknown field.*unit"):
        TaskSpec.load(tmp_path, "t-toy")


def test_init_templates_parse_once_todos_are_filled(tmp_path):
    from opc.core.config import ProjectConfig
    from opc.scaffold import init
    init(tmp_path, "p-x", "X", "c-main", "t-main", apply=True)
    assert set(json.loads((tmp_path / ".opc/project.json").read_text())) == \
        {"project_id", "display_name", "components", "execution_enabled"}
    ProjectConfig.load(tmp_path)
    c = json.loads((tmp_path / ".opc/components/c-main.json").read_text())
    c["editable"] = ["src/a.py"]
    (tmp_path / ".opc/components/c-main.json").write_text(json.dumps(c))
    ComponentConfig.load(tmp_path, "c-main")
    TaskSpec.load(tmp_path, "t-main")
    with pytest.raises(OPCError, match="already exists"):
        init(tmp_path, "p-x", "X", "c-main", "t-main", apply=True)


def test_codex_task_requires_token_cap(tmp_path):
    t = codex_task("codex")
    t["budget"].pop("max_tokens")
    _write(tmp_path, tsk=t)
    with pytest.raises(OPCError, match="max_tokens"):
        TaskSpec.load(tmp_path, "t-toy")


def test_frozen_wins_over_editable_glob(tmp_path):
    _write(tmp_path, comp=component(editable=["src/**"], frozen=["src/golden/**"]))
    c = ComponentConfig.load(tmp_path, "toy")
    assert c.is_editable("src/a.py") and not c.is_editable("src/golden/ref.bin")


def test_codex_expert_can_declare_exhaustion(make_project, engine_for, fake_codex, monkeypatch):
    """The symmetry that matters: both model workers must be able to stop the
    search when nothing is worth trying. codex gets the same channel dsh has."""
    monkeypatch.setenv("FAKE_CODEX_MODE", "exhausted")
    t = task()
    t["workers"] = {"expert": {"kind": "codex", "binary": fake_codex},
                    "designer": {"kind": "codex", "binary": fake_codex}}
    t["budget"]["max_tokens"] = 100000
    e = engine_for(make_project(tsk=t))
    s = e.run()
    assert s["state"] == "closed" and s["stop_reason"] == "expert_exhausted"


def test_onboard_accepts_dsh_and_rejects_unknown(tmp_path):
    from opc.scaffold.onboard import onboard
    with pytest.raises(OPCError, match="init --apply"):
        onboard(tmp_path, "dsh")
    (tmp_path / ".opc").mkdir()
    (tmp_path / ".opc" / "project.json").write_text("{}")
    with pytest.raises(OPCError, match="must be codex or dsh"):
        onboard(tmp_path, "claude")
