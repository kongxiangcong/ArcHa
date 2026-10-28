"""Offline loop contracts: no model service, onboard run or benchmark."""
import json

import pytest

from opc.adapters.worker import WorkerCall, validate_plan
from opc.core.model import Cost, Outcome
from opc.tests.conftest import EVALUATE, component, git, task


def plan(n, **extra):
    return dict(title=f'experiment {n}', hypothesis='test a capability',
                changes='implement or measure the method', expected='observable capability',
                falsifier='measurement disagrees', **extra)


class Sequence:
    def __init__(self, proposals, actions=None):
        self.proposals = iter(proposals)
        self.actions = iter(actions or [])
        self.contexts = []
        self.parents = []

    def propose(self, ctx, tree, log_dir):
        assert sorted(p.name for p in tree.iterdir()) == ['research.json']
        assert not (tree / '.git').exists()
        self.contexts.append(ctx)
        output = next(self.proposals)
        if callable(output):
            output = output(ctx)
        return WorkerCall('expert', True, Cost(), output=output,
                          exhausted=output.get('exhausted', False))

    def implement(self, p, ctx, tree, log_dir):
        self.parents.append(git(tree, 'rev-parse', 'HEAD').strip())
        action = next(self.actions, None)
        if action == 'interrupt':
            raise KeyboardInterrupt()
        if action is not None:
            (tree / 'params.json').write_text(json.dumps({'x': action}), encoding='utf-8')
        return WorkerCall('designer', True, Cost(), output={
            'summary': 'Actual method executed; capability added; deviation: no speedup yet'})


def stop(ctx):
    return {'exhausted': True, 'stop_reason': 'No worthwhile work remains for this task',
            'conclusions': [{'attempt': a['attempt'], 'conclusion': f"a{a['attempt']}: evidence supports capability; objective still uncertain"}
                            for a in ctx['history'] if a['conclusion'] is None]}


def use_sequence(e, seq):
    e._workers = (seq, seq)
    return e


def test_expert_material_and_full_history_are_research_only(make_project, engine_for):
    evaluate = EVALUATE.replace('{"metrics": {"loss": (x - 7) ** 2 + 1, "correct": 1}}',
        '{"metrics": {"loss": (x - 7) ** 2 + 1, "correct": 1}, "verdict": "PRIVATE_VERDICT", "stdout": "PRIVATE_LOG", "conditions": {"seed": 9}, "cases": [{"id": "a", "latency": 17}]}')
    root = make_project(evaluate=evaluate, comp=component(context_files=['params.json']),
                        extra={'.opc/context/PROJECT.md': 'Task background: existing scalar capability'})
    seq = Sequence([plan(1), stop], [4])
    e = use_sequence(engine_for(root), seq)
    s = e.run()
    ctx = seq.contexts[1]
    text = json.dumps(ctx)
    assert 'existing scalar capability' in text
    assert 'context_files' not in text and 'gates' not in text and 'log_dir' not in text
    assert 'objective gain' not in text and 'designer left' not in text
    assert 'PRIVATE_VERDICT' not in text and 'PRIVATE_LOG' not in text
    row = ctx['history'][0]
    assert row['changes'] == plan(1)['changes']
    assert row['execution']['summary'].startswith('Actual method executed')
    assert row['experiment']['data'][0]['data']['conditions'] == {'seed': 9}
    assert row['experiment']['data'][0]['data']['cases'][0]['latency'] == 17
    assert e.attempt_records()[0]['conclusion'].startswith('a1: evidence')
    assert s['pending_conclusions'] == []
    assert s['result'] == 'exploration_stopped' and s['target_met'] is False
    assert 'No worthwhile work' in s['stop_reason']
    report = json.loads((e.artifact_dir() / 'views/report.json').read_text(encoding='utf-8'))
    assert report['attempts'][0]['conclusion'] == e.attempt_records()[0]['conclusion']


def test_no_gain_candidate_survives_pause_and_restores_actual_parent(make_project, engine_for):
    root = make_project()
    e = use_sequence(engine_for(root), Sequence([plan(1)], [0]))
    first = e.run(max_attempts_now=1)
    a1 = e.attempt_records()[0]
    assert a1['outcome'] == Outcome.NO_GAIN.value
    assert a1['candidate'] != first['champion']
    assert first['pending_conclusions'] == [1]
    # A new controller and fresh worktrees must recover the saved non-champion.
    seq = Sequence([plan(2, base_attempt=1), stop], [7])
    e2 = use_sequence(engine_for(root), seq)
    result = e2.run()
    a2 = e2.attempt_records()[1]
    assert seq.parents[0] == a1['candidate'] == a2['parent']
    assert a2['champion_before'] == first['champion']
    assert a2['outcome'] == Outcome.IMPROVEMENT.value
    assert git(root, 'rev-parse', a2['candidate'] + '^').strip() == a1['candidate']
    assert result['champion'] == a2['candidate'] and result['champion_metrics']['loss'] == 1
    assert json.loads((root / 'params.json').read_text()) == {'x': 3}


def test_threshold_and_stagnation_are_expert_inputs(make_project, engine_for):
    t = task()
    t['acceptance']['target']['value'] = 17
    t['budget']['max_stagnation'] = 1
    seq = Sequence([plan(1), plan(2, base_attempt=1), stop], [0, 1])
    e = use_sequence(engine_for(make_project(tsk=t)), seq)
    s = e.run()
    assert len(seq.contexts) == 3
    assert seq.contexts[0]['progress']['target_met']
    assert seq.contexts[1]['progress']['no_gain_streak'] == 1
    assert seq.contexts[2]['progress']['no_gain_streak'] == 2
    assert s['result'] == 'target_met' and s['champion'] == s['baseline']


def test_no_patch_measurements_are_fresh_and_different_from_not_executed(make_project, engine_for):
    t = task()
    t['budget']['max_attempts'] = 3
    seq = Sequence([plan(1), plan(2), plan(3, base_attempt=99), stop])
    e = use_sequence(engine_for(make_project(comp=component(deterministic=True), tsk=t)), seq)
    e.run()
    rows = e.attempt_records()
    for row in rows[:2]:
        assert row['outcome'] == Outcome.NO_GAIN.value
        assert row['experiment']['status'] == 'completed'
        assert row['experiment']['cached'] is False
        assert row['experiment']['data'][0]['data']['metrics']['loss'] == 17
    assert rows[2]['outcome'] == Outcome.WORKER_FAILED.value
    assert rows[2]['experiment'] is None and rows[2]['execution'] is None
    assert e.summary()['pending_conclusions'] == [1, 2, 3]  # resource cap: no extra call
    assert len(seq.contexts) == 3


def test_interruption_preserves_pending_review_without_extra_call(make_project, engine_for):
    seq = Sequence([plan(1), plan(2)], [0, 'interrupt'])
    e = use_sequence(engine_for(make_project()), seq)
    s = e.run()
    assert s['state'] == 'paused' and len(seq.contexts) == 2
    assert s['pending_conclusions'] == [1, 2]
    assert e.attempt_records()[1]['outcome'] == Outcome.ABANDONED.value


def test_conclusions_cannot_be_attached_to_a_different_attempt(make_project, engine_for):
    seq = Sequence([plan(1), {'exhausted': True, 'stop_reason': 'done',
        'conclusions': [{'attempt': 99, 'conclusion': 'wrong association'}]}], [0])
    e = use_sequence(engine_for(make_project()), seq)
    e.run(max_attempts_now=2)
    assert e.attempt_records()[0]['conclusion'] is None
    assert e.attempt_records()[1]['outcome'] == Outcome.WORKER_FAILED.value
    assert not e.ledger.events(e.run_id, 'conclusion')


def test_plan_does_not_require_file_guesses():
    assert validate_plan(plan(1)) is None
    assert validate_plan(plan(1, files=[])) is None
    assert validate_plan(plan(1, base_attempt=True))

def test_legacy_base_patch_and_final_reply_are_reused_without_measurement(make_project, engine_for):
    root = make_project()
    e = use_sequence(engine_for(root), Sequence([plan(1)], [0]))
    e.run(max_attempts_now=1)
    # Simulate an existing run made by the old engine, which had patch + final reply
    # and measurement artifacts but none of the new connecting events.
    e.ledger.db.execute("DELETE FROM events WHERE run_id=? AND kind IN "
                        "('candidate_saved','development_parent','execution','experiment')", (e.run_id,))
    from opc.core.model import write_text
    write_text(e.attempt_dir(1) / 'designer/designer-last.txt', 'Historical actual behavior; no speedup')
    seq = Sequence([plan(2, base_attempt=1), stop], [7])
    e2 = use_sequence(engine_for(root), seq)
    result = e2.run()
    a1, a2 = e2.attempt_records()[:2]
    assert seq.contexts[0]['history'][0]['execution']['summary'].startswith('Historical actual')
    assert seq.contexts[0]['history'][0]['experiment']['data'][0]['data']['metrics']['loss'] == 50
    assert a2['parent'] == a1['candidate'] == seq.parents[0]
    assert result['champion_metrics']['loss'] == 1


def test_gate_verdict_and_log_text_stay_out_of_next_expert(make_project, engine_for):
    evaluate = EVALUATE + '\nif x != 3:\n    print("RAW_LOG_SECRET evaluator-internal-detail")\n    raise SystemExit(1)\n'
    seq = Sequence([plan(1), stop], [0])
    e = use_sequence(engine_for(make_project(evaluate=evaluate)), seq)
    e.run()
    assert 'RAW_LOG_SECRET' in e.ledger.attempts(e.run_id)[0]['reason']
    assert 'RAW_LOG_SECRET' not in json.dumps(seq.contexts[1])
    assert seq.contexts[1]['history'][0]['metrics'] is None
    assert seq.contexts[1]['history'][0]['experiment']['status'] == 'failed'

def test_selected_parent_and_advanced_champion_stay_distinct(make_project, engine_for):
    seq = Sequence([plan(1), plan(2), plan(3, base_attempt=1), stop], [0, 4, 5])
    e = use_sequence(engine_for(make_project()), seq)
    e.run()
    a1, a2, a3 = e.attempt_records()[:3]
    assert a1['outcome'] == Outcome.NO_GAIN.value
    assert a2['outcome'] == a3['outcome'] == Outcome.IMPROVEMENT.value
    assert a3['parent'] == a1['candidate'] != a3['champion_before'] == a2['candidate']
    assert a3['gain'] == pytest.approx(0.5)  # loss 10 -> 5, not comparison to parent loss 50
    assert seq.contexts[3]['history'][2]['champion_before']['values']['loss'] == 10


def test_builtin_parameter_search_uses_context_across_resume(make_project, engine_for):
    t = task()
    t['workers'] = {'expert': {'kind': 'scripted', 'strategy': 'builtin:param_search',
                             'options': {'file': 'params.json', 'space': {'x': [3, 4, 5, 6, 7]}}}}
    root = make_project(tsk=t)
    e = engine_for(root)
    e.run(max_attempts_now=1)
    s = engine_for(root).run()
    assert s['champion_metrics']['loss'] == 1
    assert s['result'] == 'target_met'

def test_measurement_only_gain_keeps_original_control_with_same_commit(make_project, engine_for):
    # A changing measurement can update champion metrics without changing its SHA.
    evaluate = EVALUATE.replace('(x - 7) ** 2 + 1', '(17 if "champion" in str(out) else 9)')
    seq = Sequence([plan(1), stop])
    e = use_sequence(engine_for(make_project(evaluate=evaluate)), seq)
    e.run()
    row = seq.contexts[1]['history'][0]
    assert e.attempt_records()[0]['outcome'] == Outcome.IMPROVEMENT.value
    assert row['candidate'] == row['parent']
    assert row['champion_before']['values']['loss'] == 17
    assert row['metrics']['values']['loss'] == 9


def test_work_versions_resume_and_select(make_project, engine_for):
    from opc.tests.conftest import task, STRATEGY, EVALUATE, git
    t = task(acceptance={"objective": None}, requirements=[])
    strategy = STRATEGY.replace('x = int(7 - (ctx["champion"]["values"]["loss"] - 1) ** 0.5)', 'x = ctx["attempt"] + 2').replace('if ctx["progress"]["target_met"]:', 'if ctx["attempt"] > 2:').replace('"task target reached"}', '"done", "base_attempt": 1}')
    root = make_project(tsk=t, strategy=strategy, evaluate=EVALUATE+'\nraise SystemExit(1)\n')
    e = engine_for(root)
    assert e.preflight()["ok"]
    first = e.run(max_attempts_now=1)
    assert first['champion'] is None
    ctx = json.loads((e.attempt_dir(1) / 'context.json').read_text())
    assert ctx['champion'] is None and ctx['task']['acceptance']['objective'] is None
    first_commit = first['working_version']
    e = engine_for(root)
    second = e.run(max_attempts_now=1)
    assert second['working_version'] != first_commit
    rows = e.attempt_records()
    assert rows[1]['parent'] == first_commit
    stopped = e.run()
    assert stopped['selected_version'] == first_commit
    assert not e.ledger.champions(e.run_id)
    assert '"x": 4' in git(root, 'show', first_commit+':params.json')


def test_no_objective_rejects_relative_ranking(make_project):
    from opc.tests.conftest import task
    from opc.core.config import TaskSpec
    from opc.core.model import OPCError
    import pytest
    root = make_project(tsk=task(acceptance={"constraints": [
        {"metric": "loss", "op": "<=", "relative_to_champion": 1}]}))
    with pytest.raises(OPCError, match='require an objective'):
        TaskSpec.load(root, 't-toy')


@pytest.mark.parametrize('failure', ['worker', 'sandbox'])
def test_failed_work_does_not_advance(make_project, engine_for, failure):
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    class Failed(Sequence):
        def implement(self, p, ctx, tree, log_dir):
            if failure == 'sandbox':
                (tree / '.opc/strategy.py').write_text('unauthorized')
                return WorkerCall('designer', True, Cost(), output={})
            return WorkerCall('designer', False, Cost(), error='implementation failed')
    e = use_sequence(engine_for(root), Failed([plan(1), stop]))
    s = e.run()
    assert s['working_version'] == s['baseline'] == s['selected_version']
    assert not any(a['candidate'] for a in e.attempt_records())


def test_selected_delivery_and_review_reuses_exact_evidence(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    from opc.core.engine import Engine
    root = make_project(tsk=task(acceptance={}, requirements=[
        {'id': 'R1', 'text': 'usable', 'verification': 'review'}]))
    e = use_sequence(engine_for(root), Sequence([plan(1), {'exhausted': True, 'base_attempt': 1}], [4]))
    s = e.run()
    count = []
    original = Engine.evaluate_commit
    def evaluate(self, *args, **kwargs):
        count.append(args[1])
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Engine, 'evaluate_commit', evaluate)
    first = promote(e)
    assert not first['complete'] and first['selected_version'] == s['selected_version']
    monkeypatch.setattr('opc.core.promote.run_reviewer', lambda *a: {'ok': True, 'verdict': 'accept'})
    second = promote(e, review='codex')
    assert second['complete'] and second['evidence_source']
    assert len(count) == 1
    assert second['champion'] is None
    assert len(e.attempt_records()) == 2
    # A different selected version cannot borrow that receipt.
    e.ledger.event(e.run_id, 'selected_version', None, commit=s['baseline'])
    promote(e, review='codex')
    assert len(count) == 2


def test_context_bounds_machine_data_and_history(make_project, engine_for):
    from opc.adapters.prompts import expert_prompt
    payload = {'metrics': {'loss': 17, 'correct': 1, **{f'machine_{i}': i for i in range(2156)}},
               'conditions': {'seed': 17}, 'cases': [{'id': i, 'latency': i+3} for i in range(1000)]}
    evaluate = EVALUATE[:EVALUATE.index('(out / "metrics.json")')] + '(out / "metrics.json").write_text('+repr(json.dumps(payload))+')\n'
    seq = Sequence([plan(i) for i in range(15)] + [lambda ctx: {**stop(ctx), "base_attempt": 1}], [4]*15)
    e = use_sequence(engine_for(make_project(evaluate=evaluate)), seq)
    e.run()
    ctx = seq.contexts[-1]
    assert len(ctx['history']) == 12 and len(ctx['candidates']) <= 12
    assert e.summary()['selected_version'] == e.attempt_records()[0]['candidate']
    assert '"machine_' not in json.dumps(ctx)
    data = ctx['history'][-1]['experiment']['data'][0]['data']
    assert data['conditions']['seed'] == 17 and data['cases']['count'] == 1000
    assert data['cases']['last'][-1]['latency'] == 1002
    raw = json.loads((e.attempt_dir(15) / 'eval/evaluation.json').read_text())
    assert len(raw['metrics']['values']) == 2158 and len(raw['data'][0]['data']['cases']) == 1000
    assert len(expert_prompt(ctx)) < 2000
    assert e.save_conclusions({'conclusions': []}, ctx, 17) is None


def test_development_local_steps_and_explicit_measurement(make_project, engine_for):
    seq = Sequence([{'title': 'build', 'changes': 'implement'},
                    {'title': 'build', 'changes': 'implement', 'evaluate': True}, stop], [4, 7])
    e = use_sequence(engine_for(make_project(tsk=task(acceptance={}, requirements=[]))), seq)
    e.run()
    rows = e.attempt_records()
    assert rows[0]['experiment'] is None and rows[0]['metrics'] is None
    assert rows[1]['experiment']['status'] == 'completed'
    assert rows[1]['parent'] == rows[0]['candidate']
    assert not e.ledger.champions(e.run_id)


def test_direct_task_to_delivery_and_environment_invalidation(make_project, engine_for, monkeypatch):
    from opc.tests.test_brief import brief_project
    from opc.scaffold.brief import load_brief
    from opc.core.promote import promote
    root = make_project(tsk=task(acceptance={}, requirements=[
        {'id': 'R1', 'text': 'public contract', 'verification': 'automated', 'gates': ['evaluate']}]))
    body = brief_project(root)
    (root / 'TASK.md').write_text('Implement the confirmed task', encoding='utf-8')
    (root / 'task-brief.md').write_text(body.replace('Map: map.md', 'Task: TASK.md'), encoding='utf-8')
    assert load_brief(root, 'task-brief.md')[0]['ok']
    git(root, 'add', '-A'); git(root, 'commit', '-qm', 'confirmed direct task')
    e = use_sequence(engine_for(root), Sequence([plan(1)], [4]))
    e.run(max_attempts_now=1)
    seq = Sequence([plan(2), {'exhausted': True, 'base_attempt': 2}], [7])
    resumed = use_sequence(engine_for(root), seq)
    s = resumed.run()
    assert resumed.attempt_records()[1]['parent'] == resumed.attempt_records()[0]['candidate']
    assert all(not a['experiment'] for a in resumed.attempt_records())
    result = promote(resumed)
    assert result['complete'] and result['selected_version'] == s['selected_version']
    assert result['requirements'][0]['status'] == 'met_by_gates'
    assert promote(resumed)['evidence_source']
    monkeypatch.setenv('ARCHA_TEST_TOOL_ENV', 'changed')
    assert promote(resumed)['evidence_source'] is None


def test_selected_nonchampion_reports_its_own_measurement(make_project, engine_for):
    from opc.core.promote import promote
    e = use_sequence(engine_for(make_project()), Sequence([
        plan(1), plan(2), {'exhausted': True, 'base_attempt': 2}], [7, 6]))
    e.run()
    r = promote(e)
    assert r['selected_metrics']['loss'] == 2
    assert r['champion_metrics']['loss'] == 1
    assert r['selected_version'] != r['champion']
    assert not r['complete']  # original loss<=1 completion requirement still applies


@pytest.mark.parametrize('case', ['gates', 'metrics', 'review', 'conditions'])
def test_delivery_missing_evidence_blocks(make_project, engine_for, monkeypatch, case):
    from opc.core.promote import promote
    requirements = ([{'id': 'R1', 'text': 'reviewed', 'verification': 'review'}]
                    if case in ('review', 'conditions') else [])
    acc = {'constraints': [{'metric': 'missing', 'op': '==', 'value': 1}]} if case == 'metrics' else {}
    ev = EVALUATE+'\nraise SystemExit(1)\n' if case == 'gates' else EVALUATE
    e = use_sequence(engine_for(make_project(evaluate=ev, tsk=task(acceptance=acc, requirements=requirements))),
                     Sequence([plan(1), {'exhausted': True, 'base_attempt': 0}], [4]))
    s = e.run()
    assert s['selected_version'] == s['baseline']
    monkeypatch.setattr('opc.core.promote.run_reviewer', lambda *a: {
        'ok': True, 'verdict': 'accept_with_conditions', 'summary': 'required docs missing'})
    r = promote(e, review='codex' if case == 'conditions' else None)
    assert not r['complete'] and not r['promotable']


def test_no_numeric_output_is_required_for_gate_only_completion(make_project, engine_for):
    from opc.core.promote import promote
    comp = component()
    comp['gates'][0].pop('metrics')
    root = make_project(comp=comp, tsk=task(acceptance={}, requirements=[
        {'id': 'R1', 'verification': 'automated', 'gates': ['evaluate']}]))
    e = use_sequence(engine_for(root), Sequence([plan(1), stop], [4]))
    assert e.preflight()['ok']
    e.run()
    assert promote(e)['complete']


def test_numeric_contract_still_requires_metric_output(make_project, engine_for):
    comp = component()
    comp['gates'][0].pop('metrics')
    e = engine_for(make_project(comp=comp))
    assert not e.static_check()['ok']


@pytest.mark.parametrize('case', ['ready', 'device', 'budget', 'unknown'])
def test_metered_preparation_to_formal_execution(make_project, engine_for, monkeypatch, case):
    from opc.scaffold.onboard import onboard
    from opc.adapters.codex import CodexWorker
    from opc.tests.conftest import EVALUATE
    import subprocess, sys
    root = make_project(tsk=task(acceptance={}, requirements=[], preparation_review=True))
    evaluator = root / '.opc/eval/evaluate.py'
    evaluator.unlink()
    git(root, 'add', '-A'); git(root, 'commit', '-qm', 'missing evaluator')
    calls = []
    def run(self, role, prompt, tree, log, sandbox, schema):
        calls.append(role)
        log.mkdir(parents=True, exist_ok=True)
        if role == 'onboard':
            assert 'No nested model dispatch' in prompt and 'bounded' in prompt
            if case == 'device':
                # Portable denial fixture: exercises a failed probe receipt, not real hardware.
                probe = subprocess.run([sys.executable, '-c',
                    "raise PermissionError('device permission denied by fixture')"], capture_output=True, text=True)
                assert probe.returncode != 0
                (log / 'probe.txt').write_text(probe.stderr)
                response = {'state':'external_blocked', 'reason':'observed device read permission denied; owner must grant access',
                            'evidence':[(log / 'probe.txt').relative_to(root).as_posix()]}
            else:
                # Fake worker executes real positive and negative controls of the new evaluator.
                code = EVALUATE+'\nraise SystemExit(0 if x == 7 else 1)\n'
                evaluator.write_text(code)
                scratch = log / 'control'; scratch.mkdir()
                outcomes = []
                for x in (7,3):
                    (scratch / 'params.json').write_text(json.dumps({'x':x}))
                    outcomes.append(subprocess.run([sys.executable,str(evaluator),'--out',str(scratch/'out')], cwd=scratch).returncode)
                assert outcomes == [0,1]
                (log / 'controls.json').write_text(json.dumps(outcomes))
                response={'state':'ready','reason':'tooling controls verified','evidence':[(log / 'controls.json').relative_to(root).as_posix()]}
        else:
            assert sandbox == 'read-only'
            assert json.loads((log.parent / 'controls.json').read_text()) == [0,1]
            response={'verdict':'accept', 'reason':'controls reject incorrect product, no device experiment'}
        return WorkerCall(role,True,Cost(1,80 if role=='onboard' else 20,None),
                          extra={'usage_complete':case!='unknown' or len(calls)>1}),json.dumps(response)
    monkeypatch.setattr(CodexWorker,'_run',run)
    kw=dict(prepare=True,task_id='t-toy',max_tokens=90 if case=='budget' else 1000,
            max_wall_seconds=600,prior_tokens=10,prior_wall_seconds=0)
    r=onboard(root,'codex',**kw)
    if case!='ready':
        assert r['preparation']=={'device':'external_blocked','budget':'budget_exhausted','unknown':'accounting_unknown'}[case]
        assert calls==['onboard'] and not engine_for(root).static_check()['ok']
        if case=='budget':
            assert evaluator.exists()
            assert not onboard(root,'codex',**kw)['ok'] and calls==['onboard']
        if case == 'unknown':
            from opc.core.ledger import Ledger
            ledger = Ledger(root / '.opc/local/ledger.sqlite3')
            rid = ledger.runs()[-1]['run_id']
            seq = ledger.unresolved_accounting(rid)[0]['seq']
            evidence = root / '.opc/local/usage-evidence.json'
            evidence.write_text('{"actual_tokens": 80, "already_charged": 80}')
            receipt = root / '.opc/local/reconciliation.json'
            receipt.write_text(json.dumps({'entries': [{'event_seq': seq,
                'additional_tokens': 0, 'additional_wall_seconds': 0,
                'evidence': evidence.relative_to(root).as_posix(),
                'reason': 'receipt confirms the existing charge is complete'}]}))
            assert onboard(root, 'codex', reconcile_usage=receipt, **kw)['preparation'] == 'pending'
            assert calls == ['onboard']
            assert onboard(root, 'codex', **kw)['ok']
            git(root,'add','.opc/eval'); git(root,'commit','-qm','recovered preparation')
            e = engine_for(root)
            assert e.static_check()['ok']
            e.hard_check()
            assert ledger.task_totals('t-toy')['tokens'] == 190
        return
    assert r['ok'] and calls==['onboard','reviewer']
    kw['prior_tokens'] = 12
    assert onboard(root,'codex',record_usage_only=True,**kw)['ok']
    assert calls == ['onboard','reviewer']
    git(root,'add','.opc/eval'); git(root,'commit','-qm','reviewed acceptance frozen')
    e=use_sequence(engine_for(root),Sequence([plan(1),stop],[7]))
    assert e.static_check()['ok'] and e.preflight()['ok']
    result=e.run()
    assert result['champion'] is None and result['spent']['tokens']==112
    assert result['budget_left']['tokens']==888
    evaluator.write_text(EVALUATE)
    git(root,'add','.opc/eval'); git(root,'commit','-qm','changed standard')
    assert not engine_for(root).static_check()['ok']
