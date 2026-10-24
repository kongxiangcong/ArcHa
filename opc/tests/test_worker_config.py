"""Verify role isolation and the options reaching real subprocess argv."""
import json
from types import SimpleNamespace

import pytest

from opc.adapters.codex import CodexWorker
from opc.adapters.dsh import DshWorker
from opc.core.config import TaskSpec
from opc.core.model import Cost, OPCError
from opc.core.promote import run_reviewer
from opc.core.worker_config import CONFIG_PATH, load_worker_config
from opc.scaffold import init
from opc.scaffold.onboard import onboard
from opc.tests.conftest import task, write
from opc.tests.test_codex_and_config import fake_codex  # noqa: F401
from opc.tests.test_dsh_worker import fake_dsh  # noqa: F401


def settings(root, data):
    write(root / CONFIG_PATH, json.dumps(data))


@pytest.mark.parametrize("data", [[], {"experrt": {}}, {"expert": []},
                                  {"expert": {"reasoning_effrot": "high"}},
                                  {"onboard": {"model": 4}},
                                  {"designer": {"reasoning_effort": " "}}])
def test_invalid_environment_fails_closed(tmp_path, data):
    settings(tmp_path, data)
    with pytest.raises(OPCError):
        load_worker_config(tmp_path)


def test_missing_null_and_bom(tmp_path):
    assert load_worker_config(tmp_path) == {}
    settings(tmp_path, {"expert": {"model": None}})
    path = tmp_path / CONFIG_PATH
    path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8-sig")
    assert load_worker_config(tmp_path) == {"expert": {}}
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(OPCError, match="cannot read"):
        load_worker_config(tmp_path)


def test_expert_designer_environment_overrides_contract_without_changing_digest(make_project, engine_for):
    t = task(workers={"expert": {"kind": "codex", "model": "task-expert", "timeout_s": 17},
                      "designer": {"kind": "codex", "model": "task-designer"}})
    t["budget"]["max_tokens"] = 10000
    root = make_project(tsk=t)
    digest = TaskSpec.load(root, "t-toy").digest
    settings(root, {"expert": {"model": "local-expert", "reasoning_effort": "high"},
                    "designer": {"model": None, "reasoning_effort": "medium"}})
    engine = engine_for(root)
    expert, designer = engine.workers(root)
    assert (expert.model, expert.reasoning_effort, expert.timeout) == ("local-expert", "high", 17)
    assert (designer.model, designer.reasoning_effort) == ("task-designer", "medium")
    assert engine.task.digest == digest
    assert engine.static_check()["ok"]


def test_codex_explicit_fields_reach_argv(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "onboard")
    (tmp_path / ".opc").mkdir()
    worker = CodexWorker({"binary": fake_codex, "model": "role-model", "reasoning_effort": "high",
                          "extra_args": ["--model=old", "-c", 'model_reasoning_effort="low"']})
    call, _ = worker._run("onboard", "onboarding", tmp_path, tmp_path / "logs", "workspace-write", None)
    assert call.ok
    argv = json.loads((tmp_path / "logs/onboard-request.json").read_text())["argv"]
    assert argv[-5:] == ["-c", 'model_reasoning_effort="high"', "-m", "role-model", "-"]
    assert "--model=old" not in argv


def test_dsh_selection_uses_per_call_patch(tmp_path, fake_dsh):
    write(tmp_path / "params.json", '{"x": 3}')
    worker = DshWorker({"binary": fake_dsh, "provider": "test-provider", "model": "test-model",
                        "reasoning_effort": "max"})
    worker._run("expert", "EXPERT", tmp_path, tmp_path / "logs", "read-only")
    argv = json.loads((tmp_path / "logs/expert-request.json").read_text())["argv"]
    patch = tmp_path / "logs/expert-model.patch.json"
    assert argv[argv.index("--patch") + 1] == str(patch.resolve())
    assert json.loads(patch.read_text()) == [{"id": "agent-default-model", "config": {
        "provider": "test-provider", "model": "test-model", "reasoningEffort": "max"}}]
    with pytest.raises(OPCError, match="both provider and model"):
        DshWorker({"reasoning_effort": "high"})


def test_onboard_uses_own_configuration_and_protects_it(tmp_path, monkeypatch):
    init(tmp_path, "demo", "Demo", "main", "t-main", True)
    settings(tmp_path, {"expert": {"model": "expert"},
                        "onboard": {"model": "drafter", "reasoning_effort": "high"}})
    monkeypatch.setattr("opc.scaffold.onboard._snapshot", lambda root: {})

    def run(self, *args):
        assert (self.model, self.reasoning_effort) == ("drafter", "high")
        settings(tmp_path, {})
        return SimpleNamespace(ok=True, call_id="fake", cost=Cost(0, 0, None), error=""), "drafted"

    monkeypatch.setattr(CodexWorker, "_run", run)
    result = onboard(tmp_path, "codex")
    assert not result["ok"] and CONFIG_PATH in result["changed_protected_opc"]


@pytest.mark.parametrize("configured", [True, False])
def test_reviewer_does_not_inherit_expert(make_project, engine_for, monkeypatch, configured):
    t = task(workers={"expert": {"kind": "codex", "model": "task-expert-model"},
                      "designer": {"kind": "codex"}})
    t["budget"]["max_tokens"] = 10000
    root = make_project(tsk=t)
    config = {"expert": {"model": "expert-model"}}
    if configured:
        config["reviewer"] = {"model": "review-model", "reasoning_effort": "high"}
    settings(root, config)
    engine = engine_for(root)
    # Set up a ledger run without invoking an optimization worker.
    engine.open_run()

    def run(self, role, *args):
        assert role == "reviewer"
        expected = ("review-model", "high") if configured else (None, None)
        assert (self.model, self.reasoning_effort) == expected
        return SimpleNamespace(ok=True, call_id="fake", cost=Cost(0, 0, None), error=""), '{"verdict":"accept"}'

    monkeypatch.setattr(CodexWorker, "_run", run)
    commit = engine.ledger.run(engine.run_id)["base_commit"]
    result = run_reviewer(engine, "codex", root / ".opc/local/review",
                          "", {"metrics": {}}, {"metrics": {}, "commit_sha": commit}, [])
    assert result["verdict"] == "accept"


def test_init_generates_local_environment(tmp_path):
    init(tmp_path, "demo", "Demo", "main", "t-main", True)
    assert load_worker_config(tmp_path) == {
        "expert": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
        "designer": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
        "reviewer": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
        "onboard": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
    }
    assert "/local/" in (tmp_path / ".opc/.gitignore").read_text()


def test_runtime_only_init_preserves_preconfigured_onboard(tmp_path):
    write(tmp_path / ".opc/runtime/opc/cli.py", "# deployed runtime")
    write(tmp_path / ".opc/archa.py", "# launcher")
    settings(tmp_path, {"onboard": {"model": "my-drafter", "reasoning_effort": "high"}})
    before = (tmp_path / CONFIG_PATH).read_bytes()
    init(tmp_path, "demo", "Demo", "main", "t-main", True)
    assert (tmp_path / CONFIG_PATH).read_bytes() == before


def test_first_onboard_uses_newly_generated_defaults(tmp_path, monkeypatch):
    write(tmp_path / ".opc/runtime/opc/cli.py", "# deployed runtime")
    write(tmp_path / ".opc/archa.py", "# launcher")
    monkeypatch.setattr("opc.scaffold.onboard._snapshot", lambda root: {})

    def run(self, *args):
        assert (self.model, self.reasoning_effort) == ("gpt-6.1-sol", "medium")
        return SimpleNamespace(ok=True, call_id="fake", cost=Cost(0, 0, None), error=""), "drafted"

    monkeypatch.setattr(CodexWorker, "_run", run)
    assert onboard(tmp_path, "codex")["ok"]
