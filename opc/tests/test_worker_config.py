"""Verify role isolation and the options reaching real subprocess argv."""
import json
from types import SimpleNamespace
from pathlib import Path

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
    call, _ = worker._run("onboard", "PREPARATION", tmp_path, tmp_path / "logs", "workspace-write", None)
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
        return SimpleNamespace(ok=True, call_id="fake", cost=Cost(0, 0, None), error="", extra={"usage_complete": True}), "drafted"

    monkeypatch.setattr(CodexWorker, "_run", run)
    result = onboard(tmp_path, "codex")
    assert not result["ok"] and "scope violation" in result["reason"]


@pytest.mark.parametrize("configured", [True, False])
def test_reviewer_does_not_inherit_expert(make_project, engine_for, monkeypatch, configured):
    t = task(workers={"expert": {"kind": "codex", "model": "task-expert-model"},
                      "designer": {"kind": "codex"}})
    t["budget"]["max_tokens"] = 10000
    root = make_project(tsk=t)
    native_home = root / ".opc/local/native-home"
    native_home.mkdir(parents=True)
    (native_home / "config.toml").write_text('model = "native-model"\nmodel_reasoning_effort = "low"\n')
    monkeypatch.setenv("OPC_CODEX_HOME", str(native_home))
    config = {"expert": {"model": "expert-model"}}
    if configured:
        config["reviewer"] = {"model": "review-model", "reasoning_effort": "high"}
    settings(root, config)
    engine = engine_for(root)
    # Set up a ledger run without invoking an optimization worker.
    engine.open_run()

    def run(self, role, *args):
        assert role == "reviewer"
        expected = ("review-model", "high") if configured else ("native-model", "low")
        assert (self.model, self.reasoning_effort) == expected
        return SimpleNamespace(ok=True, call_id="fake", cost=Cost(0, 0, None), error="", extra={"usage_complete": True}), '{"verdict":"accept"}'

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
        return SimpleNamespace(ok=True, call_id="fake", cost=Cost(0, 0, None), error="", extra={"usage_complete": True}), "drafted"

    monkeypatch.setattr(CodexWorker, "_run", run)
    result = onboard(tmp_path, "codex")
    assert result["preparation"] == "pending"
    assert "not structured evidence" in result["reason"]


@pytest.mark.parametrize("binary_form", ["path", "argv", "json"])
def test_environment_backend_and_installation_are_frozen_on_resume(make_project, engine_for, fake_codex, monkeypatch, binary_form):
    t = task(workers={"expert": {}, "designer": {}})
    root = make_project(tsk=t)
    settings(root, {"expert": {"kind": "codex", "model": "frozen-expert"},
                    "designer": {"kind": "codex", "model": "frozen-designer"},
                    "reviewer": {"kind": "codex", "model": "frozen-reviewer"}})
    import sys
    prefix = [sys.executable, fake_codex]
    selected = fake_codex if binary_form == "path" else [str(Path(sys.executable).resolve()), fake_codex]
    if binary_form == "argv":
        config = json.loads((root / CONFIG_PATH).read_text())
        config["expert"]["binary"] = config["designer"]["binary"] = prefix
        settings(root, config)
    else:
        monkeypatch.setenv("OPC_CODEX_BIN", json.dumps(prefix) if binary_form == "json" else fake_codex)
    first = engine_for(root)
    result = first.run(max_attempts_now=0)
    expected = result["workers"]
    assert expected["expert"]["kind"] == "codex"
    assert expected["expert"]["binary"] == selected
    assert expected["expert"]["model"] == "frozen-expert"
    assert expected["reviewer"]["model"] == "frozen-reviewer"
    settings(root, {"expert": {"model": "changed"}})
    monkeypatch.setenv("OPC_CODEX_BIN", "/no-longer-selected/codex")
    resumed = engine_for(root)
    resumed.open_run()
    assert resumed.summary()["workers"] == expected
    expert, designer = resumed.workers(root)
    assert expert.binary == selected and expert.model == "frozen-expert"
    assert designer.model == "frozen-designer"


def test_explicit_contract_backend_conflict_prevents_start(make_project, engine_for):
    root = make_project()
    settings(root, {"expert": {"kind": "codex"}})
    with pytest.raises(OPCError, match="backend.*conflict"):
        engine_for(root).open_run()


def test_new_run_may_select_backend_without_inheriting_profile_parameters(make_project, engine_for, fake_codex, monkeypatch):
    t = task(profile={"name": "development", "version": 2}, workers={})
    profile = {"name": "development", "version": 2, "workers": {
        "expert": {"kind": "scripted", "strategy": ".opc/strategy.py:Step", "model": "other-backend-model"},
        "designer": {"kind": "scripted", "strategy": ".opc/strategy.py:Step"}}}
    root = make_project(tsk=t, extra={".opc/profiles/development/v2.json": json.dumps(profile)})
    native_home = root / ".opc/local/native-home"
    native_home.mkdir(parents=True)
    (native_home / "config.toml").write_text('model = "native-model"\n')
    monkeypatch.setenv("OPC_CODEX_HOME", str(native_home))
    first = engine_for(root)
    first.run(max_attempts_now=0)
    settings(root, {"expert": {"kind": "codex", "binary": fake_codex},
                    "designer": {"kind": "codex", "binary": fake_codex}})
    second = engine_for(root)
    second.open_run(new_run=True)
    result = second.summary()
    assert result["revision"] == "r0001" and result["run_id"] != first.run_id
    assert result["workers"]["expert"]["kind"] == "codex"
    assert result["workers"]["expert"]["model"] == "native-model"
    assert "strategy" not in result["workers"]["expert"]
    assert result["configuration_sources"]["workers.expert.kind"] == CONFIG_PATH


@pytest.mark.parametrize("profile", [None, "research"])
def test_resume_pins_native_model_provider_and_profile_defaults(make_project, engine_for, fake_codex, monkeypatch, profile):
    home = Path(fake_codex).parent / "native-home"
    home.mkdir()
    native = home / "config.toml"
    native.write_text('model = "model-a"\nmodel_reasoning_effort = "low"\n'
                      '[model_providers.local]\nname = "Local"\nbase_url = "http://localhost:8123/v1"\n'
                      'env_key = "MODEL_API_KEY"\nwire_api = "responses"\n'
                      '[profiles.research]\nmodel = "profile-model-a"\nmodel_provider = "local"\nmodel_reasoning_effort = "high"\n')
    t = task(workers={"expert": {"kind": "codex", "binary": fake_codex},
                      "designer": {"kind": "codex", "binary": fake_codex}})
    root = make_project(tsk=t)
    settings(root, {"expert": {"codex_home": str(home), **({"profile": profile} if profile else {})},
                    "designer": {"codex_home": str(home)}})
    monkeypatch.setenv("MODEL_API_KEY", "do-not-copy-credential")
    first = engine_for(root)
    paused = first.run(max_attempts_now=0)
    native.write_text('model = "model-b"\nmodel_provider = "other"\n')
    monkeypatch.setenv("FAKE_CODEX_MODE", "exhausted")
    resumed = engine_for(root)
    result = resumed.run()
    assert result["run_id"] == paused["run_id"]
    expected_model = "profile-model-a" if profile else "model-a"
    assert result["workers"]["expert"]["model"] == expected_model
    request = next(resumed.artifact_dir().rglob("expert-request.json"))
    argv = json.loads(request.read_text())["argv"]
    assert argv[argv.index("-m") + 1] == expected_model
    assert "--ignore-user-config" in argv
    assert "-p" not in argv and "--profile" not in argv
    assert ('model_provider="local"' if profile else 'model_provider="openai"') in argv
    if profile:
        assert result["workers"]["expert"]["native_profile"] == "research"
        assert any('model_providers.' in arg and 'base_url=' in arg and '8123' in arg for arg in argv)
    assert "do-not-copy-credential" not in json.dumps(result["workers"])


def test_resume_can_repair_same_frozen_executable_without_searching_new_path(make_project, engine_for, fake_codex, monkeypatch):
    missing = Path(fake_codex).parent / "restored-codex"
    t = task(workers={"expert": {"kind": "codex", "binary": str(missing)},
                      "designer": {"kind": "codex", "binary": str(missing)}})
    root = make_project(tsk=t)
    first = engine_for(root)
    paused = first.run(max_attempts_now=0)
    missing.write_text(Path(fake_codex).read_text())
    missing.chmod(0o755)
    monkeypatch.setenv("OPC_CODEX_BIN", "/must-not-use/another-codex")
    monkeypatch.setenv("FAKE_CODEX_MODE", "exhausted")
    resumed = engine_for(root)
    result = resumed.run()
    assert result["run_id"] == paused["run_id"]
    assert result["state"] == "closed" and result["stop_reason"].startswith("expert_exhausted")
    assert result["workers"]["expert"]["binary"] == str(missing)


def test_unfrozen_native_selection_stays_readable_but_cannot_resume(make_project, engine_for, fake_codex):
    root = make_project(tsk=task(workers={"expert": {"kind": "codex", "binary": fake_codex},
                                        "designer": {"kind": "codex", "binary": fake_codex}}))
    first = engine_for(root)
    first.run(max_attempts_now=0)
    baseline = first.artifact_dir() / "frozen/baseline.json"
    snapshot = json.loads(baseline.read_text())
    for spec in snapshot["execution"]["workers"].values():
        spec.pop("native_defaults_frozen", None)
    baseline.write_text(json.dumps(snapshot))
    with pytest.raises(OPCError, match="native Codex model/provider selection was not frozen"):
        engine_for(root).open_run()
    assert first.ledger.run(first.run_id)["state"] == "paused"


@pytest.mark.parametrize("extra", [["-m", "legacy-model"], ["--model=legacy-model"],
                                    ["-c", 'model="legacy-model"'], ["-p", "legacy-profile"],
                                    ["-c", 'model_provider="legacy-provider"']])
def test_native_default_freeze_rejects_ambiguous_legacy_selection(make_project, engine_for, fake_codex, extra):
    root = make_project(tsk=task(workers={"expert": {"kind": "codex", "binary": fake_codex, "extra_args": extra},
                                        "designer": {"kind": "codex", "binary": fake_codex}}))
    with pytest.raises(OPCError, match="overrides must use role fields"):
        engine_for(root).open_run()


def test_explicit_role_model_still_outranks_legacy_extra_args(make_project, engine_for, fake_codex, monkeypatch):
    root = make_project(tsk=task(workers={"expert": {"kind": "codex", "binary": fake_codex,
        "model": "role-model", "extra_args": ["--model=legacy-model", "-c", 'model="legacy-model"']},
        "designer": {"kind": "codex", "binary": fake_codex}}))
    monkeypatch.setenv("FAKE_CODEX_MODE", "exhausted")
    engine = engine_for(root)
    result = engine.run()
    assert result["workers"]["expert"]["model"] == "role-model"
    request = next(engine.artifact_dir().rglob("expert-request.json"))
    argv = json.loads(request.read_text())["argv"]
    assert "--model=legacy-model" not in argv
    assert argv[argv.index("-m") + 1] == "role-model"


def test_missing_executable_is_frozen_without_later_path_substitution(make_project, engine_for, fake_codex, monkeypatch):
    import os
    name = "codex-unavailable-s2"
    root = make_project(tsk=task(workers={"expert": {"kind": "codex", "binary": name},
                                        "designer": {"kind": "codex", "binary": name}}))
    monkeypatch.chdir(root)
    first = engine_for(root)
    paused = first.run(max_attempts_now=0)
    frozen = paused["workers"]["expert"]["binary"]
    assert Path(frozen).is_absolute()
    assert frozen == str(root / name)
    replacement_dir = Path(fake_codex).parent / "changed-path"
    replacement_dir.mkdir()
    marker = replacement_dir / "started"
    replacement = replacement_dir / name
    replacement.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\nPath(%r).touch()\n' % str(marker))
    replacement.chmod(0o755)
    monkeypatch.setenv("PATH", str(replacement_dir) + os.pathsep + os.environ["PATH"])
    resumed = engine_for(root)
    result = resumed.run()
    assert result["run_id"] == paused["run_id"]
    assert result["workers"]["expert"]["binary"] == frozen
    assert result["state"] == "blocked"
    assert not marker.exists()
