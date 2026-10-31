import json
import subprocess
import sys

import pytest

from opc.tests.conftest import EVALUATE, STRATEGY, component, git, task

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
