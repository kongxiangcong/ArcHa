import json
import subprocess
import sys

import pytest

from opc.tests.conftest import EVALUATE, STRATEGY, component, git, task, write

from opc.core.model import OPCError, Outcome
from opc.core.workspace import read_ref


def outcomes(engine):
    return [a["outcome"] for a in engine.ledger.attempts(engine.run_id)]


def test_reaches_target_and_leaves_user_checkout_alone(make_project, engine_for):
    root = make_project()
    head = git(root, "rev-parse", "HEAD").strip()
    e = engine_for(root)
    s = e.run()
    assert s["state"] == "closed" and s["result"] == "target_met"
    assert s["champion_metrics"]["loss"] == 1
    assert read_ref(root, e.ref) == s["champion"]
    assert read_ref(root, "refs/opc/t-toy/%s" % e.run_id) == s["champion"]
    assert git(root, "rev-parse", "HEAD").strip() == head
    assert json.loads((root / "params.json").read_text(encoding="utf-8"))["x"] == 3
    assert git(root, "status", "--porcelain").strip() == ""
    views = e.artifact_dir() / "views"
    assert (views / "STATE.md").exists() and (views / "report.json").exists()


def test_budget_exhaustion_returns_best_within_budget(make_project, engine_for):
    t = task()
    t["budget"]["max_attempts"] = 2
    e = engine_for(make_project(tsk=t))
    s = e.run()
    assert s["state"] == "closed" and s["stop_reason"].startswith("budget_exhausted")
    assert s["result"] == "best_within_budget"
    assert s["spent"]["search_attempts"] == 2


def test_candidate_editing_evaluator_is_a_sandbox_violation(make_project, engine_for):
    cheat = STRATEGY.replace(
        '(tree / "params.json").write_text(json.dumps(plan["params"]))',
        '(tree / "params.json").write_text(json.dumps(plan["params"])); '
        '(tree / ".opc/eval/evaluate.py").write_text("raise SystemExit(0)")')
    t = task()
    t["budget"]["max_attempts"] = 1
    e = engine_for(make_project(strategy=cheat, tsk=t))
    s = e.run()
    assert outcomes(e) == [Outcome.SANDBOX.value]
    assert s["champion"] == s["baseline"]


def test_ignored_files_cannot_reach_evaluation(make_project, engine_for):
    """openTPU symlinked build/ into every slot; a candidate could poison it."""
    evaluate = EVALUATE.replace(
        'x = json.loads(Path("params.json").read_text())["x"]',
        'x = json.loads(Path("params.json").read_text())["x"]\n'
        'if Path("build/override").exists(): x = 7')
    poison = STRATEGY.replace(
        '(tree / "params.json").write_text(json.dumps(plan["params"]))',
        '(tree / "params.json").write_text(json.dumps({"x": 0})); '
        '(tree / "build").mkdir(exist_ok=True); (tree / "build/override").write_text("1")')
    t = task()
    t["budget"]["max_attempts"] = 1
    e = engine_for(make_project(evaluate=evaluate, strategy=poison, tsk=t))
    e.run()
    a = e.ledger.attempts(e.run_id)[0]
    assert a["outcome"] == Outcome.NO_GAIN.value
    assert a["metrics"]["values"]["loss"] == 50


def test_infra_failures_block_without_consuming_search_budget(make_project, engine_for):
    evaluate = EVALUATE + '\nimport os\nif json.loads(Path("params.json").read_text())["x"] != 3: raise SystemExit(75)\n'
    e = engine_for(make_project(evaluate=evaluate))
    s = e.run()
    assert s["state"] == "blocked"
    assert outcomes(e) == [Outcome.INFRA.value, Outcome.INFRA.value]
    assert s["spent"]["search_attempts"] == 0


def test_missing_metric_is_a_rejection_not_a_pass(make_project, engine_for):
    evaluate = EVALUATE.replace(
        '{"metrics": {"loss": (x - 7) ** 2 + 1, "correct": 1}}',
        '{"metrics": {"loss": (x - 7) ** 2 + 1, "correct": 1} if x == 3 else {"correct": 1}}')
    t = task()
    t["budget"]["max_attempts"] = 1
    e = engine_for(make_project(evaluate=evaluate, tsk=t))
    e.run()
    a = e.ledger.attempts(e.run_id)[0]
    assert a["outcome"] == Outcome.NO_GAIN.value and "did not report loss" in a["reason"]


def test_skipped_gate_is_rejected_by_default(make_project, engine_for):
    comp = component()
    comp["gates"].append({"id": "perf", "argv": ["{python}", ".opc/eval/perf.py"],
                          "timeout_s": 30})
    perf = 'import json\nfrom pathlib import Path\nraise SystemExit(77 if json.loads(Path("params.json").read_text())["x"] != 3 else 0)\n'
    e = engine_for(make_project(comp=comp, extra={".opc/eval/perf.py": perf}))
    s = e.run()
    assert s["state"] == "blocked"
    assert all(o == Outcome.INFRA.value for o in outcomes(e))


def test_degraded_evidence_is_not_compared_with_full_evidence(make_project, engine_for):
    comp = component(on_skip="degrade")
    comp["gates"].append({"id": "perf", "argv": ["{python}", ".opc/eval/perf.py"],
                          "timeout_s": 30})
    perf = 'import json\nfrom pathlib import Path\nraise SystemExit(77 if json.loads(Path("params.json").read_text())["x"] != 3 else 0)\n'
    t = task()
    t["budget"]["max_attempts"] = 1
    e = engine_for(make_project(comp=comp, tsk=t, extra={".opc/eval/perf.py": perf}))
    e.run()
    a = e.ledger.attempts(e.run_id)[0]
    assert a["outcome"] == Outcome.INCOMPARABLE.value and "evidence differs" in a["reason"]


def test_noise_floor_rejects_gains_inside_measured_spread(make_project, engine_for):
    evaluate = EVALUATE.replace("(x - 7) ** 2 + 1", "100 - x + random.uniform(-5, 5)") \
        .replace("import json, sys", "import json, sys, random")
    comp = component()
    comp["gates"][0]["repeat"] = True
    t = task()
    t["acceptance"]["repeats"] = 4
    t["acceptance"].pop("target")
    t["budget"]["max_attempts"] = 3
    e = engine_for(make_project(evaluate=evaluate, comp=comp, tsk=t))
    e.run()
    judged = [a for a in e.ledger.attempts(e.run_id) if a["outcome"] == Outcome.NO_GAIN.value]
    assert len(judged) == 2
    assert all("noise" in a["reason"] for a in judged)
    assert e.ledger.champions(e.run_id)[0]["metrics"]["spread"]["loss"] > 0


def test_toolchain_change_remeasures_champion(make_project, engine_for, tmp_path):
    marker = tmp_path / "toolversion"
    marker.write_text("1.0", encoding="utf-8")
    comp = component(toolchain=[["{python}", "-c", "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())", str(marker)]])
    t = task()
    t["budget"]["max_attempts"] = 1
    root = make_project(comp=comp, tsk=t)
    e = engine_for(root)
    e.run(max_attempts_now=0)
    marker.write_text("2.0", encoding="utf-8")
    t2 = engine_for(root)
    t2.run()
    kinds = [ev["kind"] for ev in t2.ledger.events(t2.run_id)]
    assert "toolchain_changed" in kinds
    reasons = [c["reason"] for c in t2.ledger.champions(t2.run_id)]
    assert "re-measured: toolchain changed" in reasons


def test_pause_then_resume(make_project, engine_for):
    root = make_project()
    e = engine_for(root)
    e.run(max_attempts_now=1)
    assert e.ledger.run(e.run_id)["state"] == "paused"
    e.ledger.set_control(e.run_id, "pause")
    e2 = engine_for(root)
    s = e2.run()
    assert s["run_id"] == e.run_id and s["state"] == "closed" and s["result"] == "target_met"


def test_crash_mid_attempt_is_reconciled_as_abandoned(make_project, engine_for):
    root = make_project()
    e = engine_for(root)
    e.run(max_attempts_now=0)
    champ = e.ledger.champion(e.run_id)[0]
    n = e.ledger.begin_attempt(e.run_id, champ, None)
    e.ledger.update_attempt(e.run_id, n, "designed", patch_sha="x", files=["params.json"])
    e2 = engine_for(root)
    e2.run()
    first = e2.ledger.attempts(e2.run_id)[0]
    assert first["outcome"] == Outcome.ABANDONED.value and "designed" in first["reason"]


def test_crash_after_ref_move_recovers_champion(make_project, engine_for):
    root = make_project()
    e = engine_for(root)
    e.run(max_attempts_now=0)
    old, meas = e.ledger.champion(e.run_id)
    git(root, "worktree", "add", "-q", "--detach", str(root.parent / "wt"), old)
    (root.parent / "wt" / "params.json").write_text(json.dumps({"x": 4}), encoding="utf-8")
    git(root.parent / "wt", "commit", "-qam", "candidate")
    new = git(root.parent / "wt", "rev-parse", "HEAD").strip()
    n = e.ledger.begin_attempt(e.run_id, old, None)
    meas.values["loss"] = 10.0
    e.ledger.update_attempt(e.run_id, n, "evaluated", metrics=meas.as_dict(), gain=0.5)
    e.ledger.record_champion_intent(e.run_id, n, old, new)
    git(root, "update-ref", e.ref, new, old)
    e2 = engine_for(root)
    e2.run(max_attempts_now=0)
    assert e2.ledger.champion(e2.run_id)[0] == new
    assert e2.ledger.attempts(e2.run_id)[0]["outcome"] == Outcome.IMPROVEMENT.value


def test_ref_moved_outside_opc_is_refused(make_project, engine_for):
    root = make_project()
    e = engine_for(root)
    e.run(max_attempts_now=1)
    git(root, "update-ref", e.ref, git(root, "rev-parse", "HEAD").strip())
    with pytest.raises(OPCError, match="moved outside OPC"):
        engine_for(root).run()


def test_second_controller_is_refused(make_project, engine_for):
    root = make_project()
    e = engine_for(root)
    with e.ledger.writer():
        with pytest.raises(OPCError, match="another controller"):
            engine_for(root).run()


def test_deterministic_cache_skips_reevaluation(make_project, engine_for):
    comp = component(deterministic=True)
    root = make_project(comp=comp)
    e = engine_for(root)
    e.run()
    t = task(revision="r0002")
    p = root / ".opc/tasks/t-toy/revisions/r0002/task.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(t), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "r0002")
    e2 = engine_for(root)
    e2.run(new_run=True)
    cached = [g for a in e2.ledger.attempts(e2.run_id) for g in (a["gates"] or [])
              if g["detail"].startswith("cached")]
    assert cached


def test_promotion_reports_unmet_target_and_applies_only_on_request(make_project, engine_for):
    from opc.core.promote import promote
    t = task()
    t["budget"]["max_attempts"] = 2
    root = make_project(tsk=t)
    git(root, "branch", "release")
    e = engine_for(root)
    e.run()
    rep = promote(engine_for(root))
    assert not rep["promotable"] and not rep["applied"]
    assert any(f["check"] == "target" for f in rep["findings"])
    assert rep["requirements"][0]["status"].startswith("not_met")
    with pytest.raises(OPCError, match="promotion blocked"):
        promote(engine_for(root), apply_to="release")


@pytest.mark.parametrize('field', ['title', 'changes'])
@pytest.mark.parametrize('value', [None, '', '  ', 42])
def test_plan_requires_existing_text_fields(field, value):
    from opc.adapters.worker import validate_plan
    plan = dict(title='t', hypothesis='h', changes='c', expected='e', falsifier='f', files=['a'])
    if value is None:
        del plan[field]
    else:
        plan[field] = value
    assert validate_plan(plan) == 'plan.%s is empty' % field


@pytest.mark.parametrize('files', [[''], ['  '], [42], 'a'])
def test_plan_requires_nonempty_paths(files):
    from opc.adapters.worker import validate_plan
    plan = dict(title='t', hypothesis='h', changes='c', expected='e', falsifier='f', files=files)
    assert validate_plan(plan)


def test_next_expert_receives_original_plan_and_measured_evidence(make_project, engine_for):
    from opc.adapters.prompts import expert_prompt
    e = engine_for(make_project())
    e.run(max_attempts_now=2)
    attempts = e.ledger.attempts(e.run_id)
    ctx = json.loads((e.attempt_dir(2) / 'context.json').read_text(encoding='utf-8'))
    previous = ctx['history'][0]
    for field in ('hypothesis', 'expected', 'falsifier'):
        assert previous[field] == attempts[0]['plan'][field]
    assert previous['metrics']['values'] == attempts[0]['metrics']['values']
    assert 'gates' not in previous and 'reason' not in previous
    assert previous['champion_before']['values']['loss'] == 17
    assert previous['metrics']['values']['loss'] != 17
    for plain_text in (False, True):
        prompt = expert_prompt(ctx, plain_text_reply=plain_text)
        assert 'Read research.json' in prompt
        assert json.dumps(ctx['history'], ensure_ascii=False, indent=2) not in prompt
        assert 'does not by itself establish its proposed mechanism' in prompt


def test_failed_gate_history_preserves_failure_without_inventing_metrics(make_project, engine_for):
    evaluate = EVALUATE + '\nif x != 3: raise SystemExit(1)\n'
    e = engine_for(make_project(evaluate=evaluate))
    e.run(max_attempts_now=2)
    ctx = json.loads((e.attempt_dir(2) / 'context.json').read_text(encoding='utf-8'))
    previous = ctx['history'][0]
    assert previous['outcome'] == Outcome.BROKEN.value
    assert previous['metrics'] is None
    assert previous['experiment']['status'] == 'failed'
    assert previous['falsifier'] == 'loss does not decrease'


def test_explicit_new_revision_starts_its_own_run(make_project):
    from opc.core.engine import Engine
    root = make_project()
    first = Engine(root, 't-toy', 'r0001', log=lambda s: None)
    first.run(max_attempts_now=1)
    second_contract = task(revision='r0002', goal='same scope, explicitly revised task')
    path = root / '.opc/tasks/t-toy/revisions/r0002/task.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(second_contract))
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'new revision')
    second = Engine(root, 't-toy', 'r0002', log=lambda s: None)
    result = second.run(max_attempts_now=0)
    assert result['revision'] == 'r0002'
    assert result['run_id'] != first.run_id
    assert result['baseline'] == git(root, 'rev-parse', 'HEAD').strip()
    assert result['baseline'] != first.summary()['champion']


def test_run_freezes_execution_values_sources_and_startpoint(make_project):
    from opc.core.engine import Engine
    root = make_project()
    local = root / '.opc/local/workers.json'
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps({'expert': {'model': 'local-model'}}))
    engine = Engine(root, 't-toy', 'r0001', log=lambda s: None)
    result = engine.run(max_attempts_now=0)
    frozen = json.loads((engine.artifact_dir() / 'frozen/baseline.json').read_text())
    assert frozen['execution']['task_digest'] == engine.task.digest
    assert frozen['execution']['worker_config']['expert']['model'] == 'local-model'
    assert frozen['execution']['budget']['max_wall_seconds'] == 600
    assert frozen['startpoint'] == {'kind': 'task_base', 'ref': 'HEAD', 'commit': result['baseline']}
    assert frozen['sources']['contract'] == '.opc/tasks/t-toy/revisions/r0001/task.json'
    assert result['startpoint'] == frozen['startpoint']


def test_frozen_contract_cannot_be_overwritten_even_for_independent_run(make_project):
    from opc.core.engine import Engine
    root = make_project()
    first = Engine(root, 't-toy', 'r0001', log=lambda s: None)
    first.run(max_attempts_now=0)
    path = root / '.opc/tasks/t-toy/revisions/r0001/task.json'
    changed = task(goal='overwrite historical execution')
    path.write_text(json.dumps(changed))
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'overwrite frozen revision')
    with pytest.raises(OPCError, match='frozen.*revision|revision.*frozen'):
        Engine(root, 't-toy', 'r0001', log=lambda s: None).run(new_run=True)
    assert len(first.ledger.runs()) == 1


def test_preparation_edits_candidate_then_allocates_after_execution(make_project):
    from opc.core.config import TaskSpec
    from opc.core.engine import Engine
    root = make_project()
    edited = task(goal='clarified candidate goal')
    candidate = TaskSpec.save_revision(root, 't-toy', 'r0001', edited)
    assert candidate.revision == 'r0001'
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'prepared candidate')
    Engine(root, 't-toy', 'r0001', log=lambda s: None).run(max_attempts_now=0)
    reserved = root / '.opc/tasks/t-toy/revisions/r0003'
    reserved.mkdir()
    next_contract = TaskSpec.save_revision(root, 't-toy', 'r0001', task(goal='new authorized goal'))
    assert next_contract.revision == 'r0004'
    assert TaskSpec.load(root, 't-toy', 'r0001').goal == 'clarified candidate goal'
    assert next_contract.goal == 'new authorized goal'


@pytest.mark.parametrize('frozen', [False, True])
def test_invalid_candidate_save_preserves_existing_contract(make_project, engine_for, frozen):
    from opc.core.config import TaskSpec
    root = make_project()
    if frozen:
        engine_for(root).run(max_attempts_now=0)
    path = root / '.opc/tasks/t-toy/revisions/r0001/task.json'
    original = path.read_bytes()
    invalid = task()
    del invalid['goal']
    with pytest.raises(OPCError, match='goal'):
        TaskSpec.save_revision(root, 't-toy', 'r0001', invalid)
    assert path.read_bytes() == original
    assert not (path.parent.parent / 'r0002').exists()


def test_no_objective_missing_tool_cannot_dispatch_formal_worker(make_project):
    from opc.core.engine import Engine
    strategy = STRATEGY.replace('def propose(self, ctx, tree):', 'def propose(self, ctx, tree):\n        raise AssertionError("formal worker must not run")')
    comp = component(gates=[{'id': 'needed-tool', 'argv': ['archa-missing-executable'], 'timeout_s': 5}])
    root = make_project(tsk=task(acceptance={'objective': None}, requirements=[]), comp=comp, strategy=strategy)
    engine = Engine(root, 't-toy', 'r0001', log=lambda s: None)
    with pytest.raises(OPCError, match='preflight|infrastructure|baseline fails'):
        engine.run()
    assert not engine.ledger.runs()


def test_independent_run_cannot_change_frozen_evaluation_contract(make_project):
    from opc.core.engine import Engine
    root = make_project()
    first = Engine(root, 't-toy', 'r0001', log=lambda s: None)
    first.run(max_attempts_now=0)
    path = root / '.opc/components/toy.json'
    changed = json.loads(path.read_text())
    changed['editable'] = ['params.json', 'new-feature.py']
    path.write_text(json.dumps(changed))
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'change frozen execution scope')
    with pytest.raises(OPCError, match='frozen.*revision|revision.*frozen'):
        Engine(root, 't-toy', 'r0001', log=lambda s: None).run(new_run=True)


def test_explicit_work_startpoint_is_checked_before_worker_dispatch(make_project):
    from opc.core.engine import Engine
    evaluate = EVALUATE + '\nraise SystemExit(75 if x == 3 else 0)\n'
    root = make_project(evaluate=evaluate, tsk=task(acceptance={}, requirements=[]))
    original = git(root, 'rev-parse', 'HEAD').strip()
    (root / 'params.json').write_text('{"x": 4}')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'available task baseline')
    engine = Engine(root, 't-toy', 'r0001', log=lambda s: None)
    with pytest.raises(OPCError, match='preflight|baseline fails'):
        engine.run(base_ref=original)
    assert not engine.ledger.runs()


def test_resume_keeps_original_run_with_unready_new_revision(make_project, engine_for, monkeypatch, capsys):
    from opc.adapters.worker import WorkerCall
    from opc.cli import main
    from opc.core.engine import Engine
    from opc.core.model import Cost
    from opc.scaffold.onboard import onboard
    root = make_project(tsk=task(profile={'name': 'development', 'version': 2}),
                        extra={'.opc/profiles/development/v2.json': json.dumps({
                            'name': 'development', 'version': 2,
                            'workers': {'expert': {'reasoning_effort': 'low'}}})})

    def preparation(self, role, prompt, tree, log, sandbox, schema):
        log.mkdir(parents=True)
        evidence = log / 'checks.txt'
        evidence.write_text('Local toy evaluator and strategy are available; no formal experiment.', encoding='utf-8')
        return WorkerCall(role, True, Cost(0, 0, None), extra={'usage_complete': True}), json.dumps({
            'state': 'ready', 'reason': 'local toy capabilities checked',
            'evidence': [evidence.relative_to(root).as_posix()]})

    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', preparation)
    ready = onboard(root, 'codex', task_id='t-toy', revision='r0001',
                    prior_tokens=0, prior_wall_seconds=0)
    assert ready['ok'] and ready['revision'] == 'r0001'
    assert not Engine(root, 't-toy', 'r0001', log=lambda _: None).ledger.runs()
    first = engine_for(root)
    paused = first.run(max_attempts_now=1)
    original_attempts = len(first.ledger.attempts(first.run_id))
    revised = task(revision='r0002', goal='unready new goal')
    write(root / '.opc/tasks/t-toy/revisions/r0002/task.json', json.dumps(revised))
    first.ledger.event(first.ledger.preparation_scope('t-toy'), 'preparation',
                       task_id='t-toy', revision='r0002', state='pending', reason='not prepared')
    # Later profile/machine defaults must not alter the original Run.
    write(root / '.opc/local/workers.json', json.dumps({'budget': {'max_wall_seconds': 1}}))
    write(root / '.opc/profiles/development/v2.json', '{invalid later profile')
    first.ledger.set_control(first.run_id, 'pause')
    assert main(['status', '-p', str(root), '--task', 't-toy', '--run-id', first.run_id]) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed[0]['run_id'] == first.run_id and observed[0]['control'] == 'pause'
    assert observed[0]['attempts'] == original_attempts
    automatic = Engine(root, 't-toy', log=lambda _: None)
    assert automatic.task.revision == 'r0001'
    resumed = Engine(root, 't-toy', run_id=first.run_id, log=lambda _: None)
    result = resumed.run()
    assert result['run_id'] == paused['run_id'] and result['revision'] == 'r0001'
    assert result['result'] == 'target_met'
    assert len(resumed.ledger.attempts(first.run_id)) > original_attempts
    assert result['spent']['wall_seconds'] >= paused['spent']['wall_seconds']
    assert resumed.task.configuration_sources['profile']['version'] == 2
    assert main(['status', '-p', str(root), '--task', 't-toy', '--run-id', first.run_id, '--details']) == 0
    detail = json.loads(capsys.readouterr().out)[0]
    assert detail['state'] == 'closed' and detail['revision'] == 'r0001'
    assert detail['execution']['configuration_sources']['profile']['version'] == 2


def test_multiple_runs_require_explicit_identity_and_resume_per_run_champion(make_project):
    from opc.core.engine import Engine
    root = make_project()
    first = Engine(root, 't-toy', 'r0001', log=lambda _: None)
    first.run(max_attempts_now=1)
    second = Engine(root, 't-toy', 'r0001', log=lambda _: None)
    second.run(new_run=True, max_attempts_now=2)
    with pytest.raises(OPCError, match='multiple Runs.*run-id'):
        Engine(root, 't-toy', 'r0001', log=lambda _: None).run()
    resumed = Engine(root, 't-toy', run_id=first.run_id, log=lambda _: None)
    result = resumed.run()
    assert result['run_id'] == first.run_id and result['result'] == 'target_met'
    assert len(resumed.ledger.attempts(second.run_id)) == 2


def test_closed_run_reports_original_result_without_reopening(make_project, engine_for):
    root = make_project()
    first = engine_for(root)
    original = first.run()
    from opc.cli import main
    original_event_count = len(first.ledger.events(first.run_id))
    assert main(['run', '-p', str(root), '--task', 't-toy', '--run-id', first.run_id, '--deliver']) == 1
    assert len(first.ledger.events(first.run_id)) == original_event_count
    first.ledger.set_control(first.run_id, 'stop')
    event_count = len(first.ledger.events(first.run_id))
    repeated = engine_for(root).run()
    assert repeated == original
    assert len(first.ledger.events(first.run_id)) == event_count
    assert first.ledger.control(first.run_id) == 'stop'


def test_status_read_preserves_pause_and_explicit_control_targets_old_run(make_project, capsys):
    from opc.cli import main
    from opc.core.engine import Engine
    root = make_project()
    first = Engine(root, 't-toy', 'r0001', log=lambda _: None)
    first.run(max_attempts_now=1)
    second = Engine(root, 't-toy', 'r0001', log=lambda _: None)
    second.run(new_run=True, max_attempts_now=1)
    assert main(['pause', '-p', str(root), '--task', 't-toy', '--run-id', first.run_id]) == 0
    capsys.readouterr()
    assert main(['status', '-p', str(root), '--task', 't-toy', '--run-id', first.run_id]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r['run_id'] for r in rows] == [first.run_id]
    assert first.ledger.control(first.run_id) == 'pause'
    assert first.ledger.control(second.run_id) == 'run'
    assert len(first.ledger.attempts(first.run_id)) == 1


def test_resume_without_frozen_execution_source_is_blocked_but_status_readable(make_project, engine_for, capsys):
    from opc.cli import main
    from opc.core.engine import Engine
    root = make_project()
    first = engine_for(root)
    first.run(max_attempts_now=1)
    snapshot = first.artifact_dir() / 'frozen/baseline.json'
    data = json.loads(snapshot.read_text())
    data.pop('execution')
    snapshot.write_text(json.dumps(data))
    with pytest.raises(OPCError, match='readable.*cannot resume.*frozen execution source'):
        Engine(root, 't-toy', run_id=first.run_id, log=lambda _: None).run()
    assert first.ledger.run(first.run_id)['state'] == 'paused'
    assert main(['status', '-p', str(root), '--task', 't-toy', '--run-id', first.run_id]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]['state'] == 'paused' and rows[0]['attempts'] == 1


def test_resume_uses_relocated_artifacts_and_workspace_bindings(make_project, engine_for, tmp_path):
    import shutil
    from opc.core.engine import Engine
    root = make_project()
    e = engine_for(root)
    first = e.run(max_attempts_now=1)
    previous = e.bindings
    artifacts = tmp_path / 'moved-artifacts'
    workspace = tmp_path / 'moved-workspaces'
    shutil.move(str(previous.artifact_root), artifacts)
    write(root / '.opc/local/bindings.json', json.dumps({
        'artifact_root': str(artifacts), 'workspace_root': str(workspace)}))
    resumed = Engine(root, 't-toy', run_id=first['run_id'], log=lambda _: None)
    result = resumed.run(max_attempts_now=0)
    assert result['run_id'] == first['run_id']
    assert (resumed.artifact_dir() / 'frozen/task.json').is_file()
    assert resumed.bindings.artifact_root == artifacts
    assert resumed.ledger.events(first['run_id'], 'binding_repaired')


def test_no_objective_resume_blocks_missing_tool_then_rechecks_drift(make_project, engine_for, tmp_path):
    marker = tmp_path / 'version.txt'
    marker.write_text('v1')
    comp = component(toolchain=[['{python}', '-c',
        'import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())', str(marker)]])
    root = make_project(comp=comp, tsk=task(acceptance={}, requirements=[{
        'id': 'REQ-001', 'text': 'working gate', 'verification': 'automated', 'gates': ['evaluate']}]))
    e = engine_for(root)
    first = e.run(max_attempts_now=0)
    marker.unlink()
    with pytest.raises(OPCError, match='toolchain.*unavailable'):
        engine_for(root).run(max_attempts_now=0)
    assert not e.ledger.attempts(first['run_id'])
    marker.write_text('v2')
    resumed = engine_for(root)
    result = resumed.run(max_attempts_now=0)
    assert result['run_id'] == first['run_id']
    records = resumed.ledger.events(first['run_id'], 'measurement_baseline')
    assert records and records[-1]['body']['cached'] is False
    assert result['compatibility']['record']['state'] == 'readable'
    assert result['compatibility']['execution']['state'] == 'resumable'
    assert result['compatibility']['measurement']['state'] == 'rechecked'


def test_status_separates_readable_legacy_execution_and_unknown_measurements(make_project, engine_for, capsys):
    from opc.cli import main
    root = make_project()
    e = engine_for(root)
    first = e.run(max_attempts_now=0)
    path = e.artifact_dir() / 'frozen/baseline.json'
    snapshot = json.loads(path.read_text())
    del snapshot['execution']
    path.write_text(json.dumps(snapshot))
    assert main(['status', '-p', str(root), '--task', 't-toy', '--run-id', first['run_id']]) == 0
    result = json.loads(capsys.readouterr().out)[0]['compatibility']
    assert result['record']['state'] == 'readable'
    assert result['execution']['state'] == 'blocked'
    assert 'legacy' in result['execution']['reason']
    assert result['measurement']['state'] == 'unknown'


def test_environment_drift_cannot_be_certified_by_champion_alone(make_project, engine_for, tmp_path):
    marker = tmp_path / 'version.txt'
    marker.write_text('v1')
    comp = component(toolchain=[['{python}', '-c',
        'import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())', str(marker)]])
    evaluate = EVALUATE.replace('x = json.loads', 'x = json.loads') + (
        '\nif Path(%r).read_text() == "v2" and x == 3: sys.exit(1)\n' % str(marker))
    root = make_project(comp=comp, evaluate=evaluate)
    e = engine_for(root)
    first = e.run(max_attempts_now=1)
    old_evidence = {p: p.read_bytes() for p in (e.artifact_dir() / 'champion').rglob('evaluation.json')}
    count = len(e.ledger.champions(first['run_id']))
    marker.write_text('v2')
    with pytest.raises(OPCError, match='changed environment baseline failed'):
        engine_for(root).run(max_attempts_now=0)
    assert len(e.ledger.champions(first['run_id'])) == count
    assert all(path.read_bytes() == raw for path, raw in old_evidence.items())
    failed_evidence = {p: p.read_bytes() for p in (e.artifact_dir() / 'environment').rglob('evaluation.json')}
    assert failed_evidence
    marker.write_text('v3')
    resumed = engine_for(root).run(max_attempts_now=0)
    assert resumed['run_id'] == first['run_id']
    assert all(path.read_bytes() == raw for path, raw in failed_evidence.items())


def test_resume_rejects_changed_frozen_permissions_without_rewriting_history(make_project, engine_for):
    root = make_project()
    e = engine_for(root)
    first = e.run(max_attempts_now=0)
    path = e.artifact_dir() / 'frozen/component.json'
    altered = json.loads(path.read_text())
    altered['editable'] = ['**/*.json']
    path.write_text(json.dumps(altered))
    with pytest.raises(OPCError, match='permissions.*new revision'):
        engine_for(root).run(max_attempts_now=0)
    assert e.ledger.run(first['run_id'])['revision'] == 'r0001'
    assert len(e.ledger.runs()) == 1
