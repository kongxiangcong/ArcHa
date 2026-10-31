"""Offline loop contracts: no model service, onboard run or benchmark."""
import json
from pathlib import Path

import pytest

from opc.adapters.worker import WorkerCall, validate_plan
from opc.core.model import Cost, OPCError, Outcome
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
                            for a in ctx['pending_feedback']]}


def use_sequence(e, seq):
    e.workers = lambda tree: (seq, seq)
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
    assert len(rows) == 2  # invalid input selection is a Run decision failure, not work
    assert e.summary()['state'] == 'blocked'
    assert e.summary()['pending_conclusions'] == [1, 2]
    assert len(seq.contexts) == 3


def test_interruption_preserves_pending_review_without_extra_call(make_project, engine_for):
    seq = Sequence([plan(1), plan(2)], [0, 'interrupt'])
    e = use_sequence(engine_for(make_project()), seq)
    s = e.run()
    assert s['state'] == 'paused' and len(seq.contexts) == 2
    assert s['pending_conclusions'] == [1]
    assert e.attempt_records()[1]['outcome'] is None
    assert e.ledger.calls(e.run_id)[-1]['state'] == 'dispatched'


def test_conclusions_cannot_be_attached_to_a_different_attempt(make_project, engine_for):
    seq = Sequence([plan(1), {'exhausted': True, 'stop_reason': 'done',
        'conclusions': [{'attempt': 99, 'conclusion': 'wrong association'}]}], [0])
    e = use_sequence(engine_for(make_project()), seq)
    e.run(max_attempts_now=2)
    assert e.attempt_records()[0]['conclusion'] is None
    assert len(e.attempt_records()) == 1
    assert e.summary()['state'] == 'blocked'
    assert e.ledger.events(e.run_id, 'expert_rejected')
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
    e = use_sequence(engine_for(root), Sequence([plan(1), lambda ctx: {**stop(ctx), 'base_attempt': 1}], [4]))
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
    assert len(e.attempt_records()) == 1  # stop decision creates no execution node
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
    assert len(expert_prompt(ctx)) < 2600
    assert len(ctx['pending_feedback']) == 15
    assert len(e.ledger.events(e.run_id, 'conclusion')) == 15


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
    seq = Sequence([plan(2), lambda ctx: {**stop(ctx), 'base_attempt': 2}], [7])
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
        plan(1), plan(2), lambda ctx: {**stop(ctx), 'base_attempt': 2}], [7, 6]))
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
                     Sequence([plan(1), lambda ctx: {**stop(ctx), 'base_attempt': 0}], [4]))
    if case == 'metrics':
        with pytest.raises(OPCError, match='required metrics: missing'):
            e.run()
        assert not e.ledger.runs()
        return
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
            rid = ledger.preparation_scope('t-toy')
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


def test_delivery_repair_selected_candidate_preserves_failure(make_project, engine_for):
    from opc.core.promote import promote
    root = make_project(tsk=task(acceptance={}, requirements=[
        {'id': 'R', 'text': 'loss one', 'check': {'metric': 'loss', 'op': '<=', 'value': 1}}]))
    e = use_sequence(engine_for(root), Sequence([plan(1), stop], [4]))
    first_run = e.run()
    failure = promote(e, source_run=first_run['run_id'])
    assert not failure['complete']
    original = e.ledger.run(first_run['run_id'])['stop_reason']
    e = use_sequence(engine_for(root), Sequence([plan(1), stop], [7]))
    repaired = e.repair_delivery(Path(failure['report_dir']) / 'report.json')
    assert repaired['baseline'] == first_run['selected_version']
    assert e.ledger.run(first_run['run_id'])['stop_reason'] == original
    assert promote(e, source_run=repaired['run_id'])['complete']
    assert not json.loads((Path(failure['report_dir']) / 'report.json').read_text())['complete']


def test_delivery_repair_respects_stop(make_project, engine_for):
    from opc.core.promote import promote
    from opc.core.model import OPCError
    root = make_project(tsk=task(acceptance={}, requirements=[{'id':'R','text':'review','verification':'review'}]))
    e = use_sequence(engine_for(root), Sequence([stop]))
    s = e.run()
    report = promote(e, source_run=s['run_id'])
    e.ledger.set_control(s['run_id'], 'stop')
    with pytest.raises(OPCError, match='pause/stop'):
        e.repair_delivery(Path(report['report_dir']) / 'report.json')


def test_confirmed_revision_reuses_measurements_without_rewriting_failure(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    from opc.core.model import OPCError
    root = make_project(tsk=task(acceptance={}, requirements=[
        {'id':'R','text':'loss threshold','check':{'metric':'loss','op':'<=','value':1}}]))
    e = use_sequence(engine_for(root), Sequence([plan(1), stop], [4]))
    s = e.run()
    failed = promote(e, source_run=s['run_id'])
    old_report = Path(failed['report_dir']) / 'report.json'
    original = old_report.read_bytes()
    new = dict(e.task.raw, revision='r0002', requirements=[
        {'id':'R','text':'diagnostic loss','check':{'metric':'loss','op':'<=','value':1}, 'required':False}])
    path = root / '.opc/tasks/t-toy/revisions/r0002/task.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(new))
    from opc.core.engine import Engine
    revised = Engine(root, 't-toy', 'r0002')
    with pytest.raises(OPCError, match='confirmation'):
        promote(revised, source_run=s['run_id'])
    receipt = root / 'confirmation.json'
    receipt.write_text(json.dumps(dict(confirmed_by='user', source_run=s['run_id'],
        from_revision='r0001', to_revision='r0002', changes={
            'requirements':{'old':e.task.raw['requirements'], 'new':new['requirements']}})))
    monkeypatch.setattr(revised, 'evaluate_commit', lambda *a, **k: pytest.fail('unnecessary measurement'))
    passed = promote(revised, source_run=s['run_id'], standards_confirmation=receipt)
    assert passed['complete'] and passed['reassessed']
    assert passed['selected_version'] == s['selected_version']
    assert passed['evidence_source'] == str(old_report)
    assert passed['requirements'][0]['status'].startswith('not_met')
    assert old_report.read_bytes() == original
    assert len([r for r in revised.ledger.runs() if r['revision'] != 'preparation']) == 1
    new['budget']['max_tokens'] = 999999
    path.write_text(json.dumps(new))
    with pytest.raises(OPCError, match='cannot change execution'):
        promote(Engine(root, 't-toy', 'r0002'), source_run=s['run_id'], standards_confirmation=receipt)


def test_cli_delivery_consumes_selected_run_and_never_applies(make_project, engine_for, monkeypatch, capsys):
    from opc.cli import main
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([plan(1), stop], [7]))
    monkeypatch.setattr('opc.cli._engine', lambda *a, **k: e)
    before = git(root, 'rev-parse', 'HEAD')
    assert main(['run','-p',str(root),'--task','t-toy','--deliver']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['complete']
    assert result['delivery']['run_id'] == result['run_id']
    assert result['delivery']['selected_version'] == result['selected_version']
    assert not result['delivery']['applied']
    assert git(root, 'rev-parse', 'HEAD') == before


def test_cli_paused_delivery_makes_no_evaluation(make_project, engine_for, monkeypatch, capsys):
    from opc.cli import main
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([plan(1), stop], [7]))
    monkeypatch.setattr('opc.cli._engine', lambda *a, **k: e)
    monkeypatch.setattr('opc.core.promote.promote', lambda *a, **k: pytest.fail('paused delivery'))
    assert main(['run','-p',str(root),'--task','t-toy','--max-now','0','--deliver']) == 1
    assert not json.loads(capsys.readouterr().out)['complete']


@pytest.mark.parametrize("required", [True, False])
def test_diagnostic_gate_does_not_mask_hard_requirement(make_project, engine_for, required):
    from opc.core.promote import promote
    root = make_project(tsk=task(acceptance={}, requirements=[
        {'id':'D','text':'diagnostic','gates':['evaluate'],'required':required}]))
    (root / '.opc/eval/evaluate.py').write_text(EVALUATE + '\nraise SystemExit(1)\n')
    git(root, 'add', '.opc/eval/evaluate.py'); git(root, 'commit', '-qm', 'failing measurement gate')
    e = use_sequence(engine_for(root), Sequence([stop]))
    s = e.run()
    assert promote(e, source_run=s['run_id'])['complete'] is (not required)


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('hard_exit', [0, 1])
def test_delivery_checks_hard_gates_after_diagnostic_failure(make_project, engine_for, bound, hard_exit):
    from opc.core.promote import promote
    comp = component()
    comp['gates'].insert(0, {'id': 'diagnostic', 'argv': ['{python}', '-c', 'exit(1)']})
    comp['gates'].append({'id': 'hard', 'argv': ['{python}', '-c', f'exit({hard_exit})']})
    requirements = [{'id': 'D', 'text': 'diagnostic', 'gates': ['diagnostic'], 'required': False}]
    if bound:
        requirements.append({'id': 'H', 'text': 'hard check', 'gates': ['hard']})
    root = make_project(comp=comp, tsk=task(acceptance={}, requirements=requirements))
    e = use_sequence(engine_for(root), Sequence([stop]))
    s = e.run()
    report = promote(e, source_run=s['run_id'])
    assert report['complete'] is (hard_exit == 0)
    assert {g['gate_id'] for g in report['evaluation']['gates']} == {'diagnostic', 'evaluate', 'hard'}
    if hard_exit == 0:
        assert report['selected_metrics']['loss'] == 17


def test_confirmed_revision_can_repair_remaining_findings(make_project, engine_for):
    from opc.core.engine import Engine
    from opc.core.promote import promote
    from opc.core.model import OPCError
    root = make_project(tsk=task(acceptance={}, requirements=[
        {'id': 'R', 'text': 'loss', 'check': {'metric': 'loss', 'op': '<=', 'value': 1}}]))
    e = use_sequence(engine_for(root), Sequence([plan(1), stop], [4]))
    first = e.run()
    e.ledger.charge(first['run_id'], None, 'expert', Cost(0, 123, 0.0))
    original = promote(e, source_run=first['run_id'])
    old_bytes = (Path(original['report_dir']) / 'report.json').read_bytes()
    new = dict(e.task.raw, revision='r0002', requirements=[
        {'id': 'R', 'text': 'relaxed loss', 'check': {'metric': 'loss', 'op': '<=', 'value': 2}}])
    path = root / '.opc/tasks/t-toy/revisions/r0002/task.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(new))
    git(root, 'add', str(path)); git(root, 'commit', '-qm', 'confirmed standards')
    receipt = root / 'confirmation.json'
    receipt.write_text(json.dumps(dict(confirmed_by='user', source_run=first['run_id'],
        from_revision='r0001', to_revision='r0002', changes={
            'requirements': {'old': e.task.raw['requirements'], 'new': new['requirements']}})))
    revised = Engine(root, 't-toy', 'r0002')
    failed = promote(revised, source_run=first['run_id'], standards_confirmation=receipt)
    assert not failed['complete']
    failed_path = Path(failed['report_dir']) / 'report.json'
    failed_bytes = failed_path.read_bytes()
    with pytest.raises(OPCError, match='acceptance contract'):
        e.repair_delivery(failed_path)
    receipt.unlink()  # registered report preserves the approved standards
    # A later budget edit cannot reuse this confirmation.
    altered = dict(new, budget=dict(new['budget'], max_tokens=999999))
    path.write_text(json.dumps(altered))
    with pytest.raises(OPCError):
        Engine(root, 't-toy', 'r0002').repair_delivery(failed_path)
    path.write_text(json.dumps(new))
    repair = use_sequence(Engine(root, 't-toy', 'r0002'), Sequence([plan(1), stop], [7]))
    repaired = repair.repair_delivery(failed_path)
    assert repaired['baseline'] == first['selected_version']
    assert repair.ledger.run(repaired['run_id'])['revision'] == 'r0002'
    assert repaired['spent']['tokens'] == 123
    assert promote(repair, source_run=repaired['run_id'])['complete']
    assert failed_path.read_bytes() == failed_bytes
    assert (Path(original['report_dir']) / 'report.json').read_bytes() == old_bytes


@pytest.mark.parametrize('entry', ['hard_check', 'admit', 'run'])
@pytest.mark.parametrize('marker', ['delivery_repair', 'promotion_report', 'delivery'])
def test_delivery_accounting_survives_engine_recreation(make_project, engine_for, entry, marker):
    from opc.core.model import OPCError
    spec = task(acceptance={}, requirements=[])
    spec["budget"]["max_tokens"] = 1000
    root = make_project(tsk=spec)
    e = engine_for(root)
    rid = e.open_run()
    if marker == 'delivery':
        e.enable_delivery()
    else:
        e.ledger.event(rid, marker, source_run='earlier', source_promotion='p')
    e.ledger.event(rid, 'accounting_unknown', reason='missing worker receipt')
    fresh = engine_for(root)
    fresh.open_run()
    with pytest.raises(OPCError, match='accounting incomplete'):
        getattr(fresh, entry)()


def test_delivery_confirmation_repeats_allow_diagnostic_failure(make_project, engine_for):
    from opc.core.promote import promote
    comp = component()
    comp['gates'].insert(0, {'id': 'diagnostic', 'argv': ['{python}', '-c',
        'import json; exit(1 if json.load(open("params.json"))["x"] == 7 else 0)']})
    root = make_project(comp=comp, tsk=task(requirements=[
        {'id': 'D', 'text': 'diagnostic', 'gates': ['diagnostic'], 'required': False}]))
    e = use_sequence(engine_for(root), Sequence([plan(1), lambda ctx: {**stop(ctx), 'base_attempt': 1}], [7]))
    s = e.run()
    report = promote(e, source_run=s['run_id'], confirm_repeats=2)
    assert report['complete'], report['findings']
    assert len(report['confirm']['samples']['champion']) == 2


@pytest.mark.parametrize('repeats', [1, 2])
def test_delivery_rejects_incomplete_hard_gate_receipts(make_project, engine_for, monkeypatch, repeats):
    from opc.core.promote import promote
    comp = component()
    comp['gates'][0]['repeat'] = True
    root = make_project(comp=comp, tsk=task(acceptance={'repeats': repeats}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([stop]))
    s = e.run()
    dom = e.domain(root)
    original = dom.evaluate
    def incomplete(*args, **kwargs):
        ev = original(*args, **kwargs)
        ev.gates.pop()  # Adapter claims success with a missing required receipt.
        return ev
    monkeypatch.setattr(dom, 'evaluate', incomplete)
    report = promote(e, source_run=s['run_id'])
    assert not report['complete']
    assert any(f['check'] == 'gates' and 'not passed' in f['text'] for f in report['findings'])


def test_run_expert_stop_does_not_create_attempt(make_project, engine_for):
    e = use_sequence(engine_for(make_project()), Sequence([stop]))
    result = e.run()
    assert result['state'] == 'closed'
    assert e.ledger.attempts(e.run_id) == []
    expert_calls = [c for c in e.ledger.calls(e.run_id) if c['role'] == 'expert']
    assert len(expert_calls) == 1 and expert_calls[0]['attempt_no'] is None


def test_measurement_can_skip_designer_and_last_result_is_interpreted(make_project, engine_for):
    seq = Sequence([plan(1, designer=False, evaluate=True), stop])
    e = use_sequence(engine_for(make_project()), seq)
    result = e.run()
    assert result['state'] == 'closed' and result['pending_conclusions'] == []
    assert len(e.ledger.attempts(e.run_id)) == 1
    assert not [c for c in e.ledger.calls(e.run_id) if c['role'] == 'designer']
    assert e.attempt_records()[0]['experiment']['cached'] is False
    assert len({str(c['input']['tree']) for c in e.ledger.calls(e.run_id) if c['role'] == 'expert'}) == 1


@pytest.mark.parametrize('handoff', ['receipt', 'decision', 'selection'])
def test_run_decision_recovery_does_not_repeat_expert_or_selected_work(make_project, engine_for, monkeypatch, handoff):
    root = make_project()
    seq = Sequence([plan(1, evaluate=False)], [4])
    e = use_sequence(engine_for(root), seq)
    target = 'record_decision' if handoff == 'receipt' else 'begin_selected_attempt'
    original = getattr(e.ledger, target)
    def interrupt(*args, **kwargs):
        if handoff == 'selection':
            original(*args, **kwargs)
        raise RuntimeError('handoff interrupted')
    monkeypatch.setattr(e.ledger, target, interrupt)
    with pytest.raises(RuntimeError, match='handoff interrupted'):
        e.run(max_attempts_now=1)
    assert len(seq.contexts) == 1
    assert len(e.ledger.attempts(e.run_id)) == (1 if handoff == 'selection' else 0)
    seq2 = Sequence([stop], [4])
    resumed = use_sequence(engine_for(root), seq2)
    result = resumed.run(max_attempts_now=1)
    assert result['state'] == 'paused' and len(resumed.ledger.attempts(resumed.run_id)) == 1
    assert seq2.contexts == []
    assert len([c for c in resumed.ledger.calls(resumed.run_id) if c['role'] == 'expert']) == 1
    assert len(resumed.ledger.events(resumed.run_id, 'expert_decision')) == 1
    result = resumed.run(max_attempts_now=0)
    assert len(resumed.ledger.attempts(resumed.run_id)) == 1


def test_read_acknowledgment_does_not_clear_pending_feedback(make_project, engine_for):
    seq = Sequence([plan(1, evaluate=False), {'exhausted': True,
        'conclusions': [{'attempt': 1, 'conclusion': '已读。'}]}], [4])
    e = use_sequence(engine_for(make_project()), seq)
    result = e.run()
    assert result['state'] == 'blocked' and result['pending_conclusions'] == [1]
    assert len(e.ledger.attempts(e.run_id)) == 1
    assert len(e.ledger.events(e.run_id, 'expert_decision')) == 1


def test_review_only_decision_can_interpret_multiple_results_without_work(make_project, engine_for):
    e = use_sequence(engine_for(make_project()), Sequence([plan(1, evaluate=False), plan(2, evaluate=False)], [4, 5]))
    first = e.run(max_attempts_now=2)
    assert first['pending_conclusions'] == [1, 2]
    seq = Sequence([lambda ctx: {**stop(ctx), 'exhausted': False, 'select_work': False}, stop])
    e.workers = lambda tree: (seq, seq)
    result = e.run()
    assert result['state'] == 'closed' and result['pending_conclusions'] == []
    assert len(e.ledger.attempts(e.run_id)) == 2
    conclusions = e.ledger.events(e.run_id, 'conclusion')
    assert len(conclusions) == 2 and len({c['body']['reviewed_by_call'] for c in conclusions}) == 1
    from opc.observer.adapter import ObserverAdapter
    observer = ObserverAdapter(e.root)
    ref = next(r for r in observer.overview()['data']['unlinked_runs'] if r['source_run_id'] == e.run_id)
    run = observer.run(ref['id'])['data']
    assert run['pending_feedback'] == []
    assert len(run['decisions']) == 4


def test_failed_run_expert_is_charged_without_creating_attempt(make_project, engine_for):
    class FailedExpert:
        def propose(self, ctx, tree, log_dir):
            return WorkerCall('expert', False, Cost(1, 3, None), error='provider unavailable',
                              extra={'infra': True, 'usage_complete': True})
    failed = FailedExpert()
    e = use_sequence(engine_for(make_project()), failed)
    result = e.run()
    assert result['state'] == 'blocked' and result['spent']['tokens'] == 3
    assert e.ledger.attempts(e.run_id) == []
    assert e.ledger.calls(e.run_id)[-1]['attempt_no'] is None


def test_expert_session_loss_rebuilds_from_materials_in_new_call(make_project, engine_for):
    class Sessions(Sequence):
        def propose(self, ctx, tree, log_dir):
            self.contexts.append(ctx)
            if len(self.contexts) == 1:
                assert 'session_id' not in ctx
                return WorkerCall('expert', True, Cost(0, 2), call_id='native-session', output=plan(1))
            if len(self.contexts) == 2:
                assert ctx['session_id'] == 'native-session'
                return WorkerCall('expert', False, Cost(0, 0), error='session not found',
                    extra={'session_unavailable': True, 'not_started': True, 'usage_complete': True})
            assert 'session_id' not in ctx and ctx['pending_feedback']
            return WorkerCall('expert', True, Cost(0, 3), call_id='rebuilt-session',
                              output=stop(ctx), exhausted=True)
    root = make_project()
    worker = Sessions([], [4])
    e = use_sequence(engine_for(root), worker)
    result = e.run()
    assert result['state'] == 'closed' and len(e.ledger.attempts(e.run_id)) == 1
    calls = [c for c in e.ledger.calls(e.run_id) if c['role'] == 'expert']
    assert len({c['call_id'] for c in calls}) == 3
    assert calls[1]['state'] == 'not_started'
    assert calls[0]['session_id'] == 'native-session' and calls[2]['session_id'] == 'rebuilt-session'
    assert e.ledger.events(e.run_id, 'expert_session_rebuilt')[0]['body']['reason'] == 'session not found'
    assert not result['pending_conclusions']


REVIEW_CLI = """import json,os,sys,time
from pathlib import Path
sys.stdin.read()
print(json.dumps({'type':'thread.started','thread_id':'review-session'}),flush=True)
Path(os.environ['REVIEW_READY']).touch()
while not Path(os.environ['REVIEW_RELEASE']).exists():
    time.sleep(.01)
reply = {'verdict':'accept','summary':'review completed','overreach':[],'requirement_findings':[]}
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(reply)}}),flush=True)
if os.environ.get('REVIEW_UNKNOWN') != '1':
    print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':2}}),flush=True)
"""


def reviewer_case(make_project, engine_for, tmp_path, monkeypatch):
    from opc.tests.conftest import write
    cli = tmp_path / 'reviewer.py'
    cli.write_text(REVIEW_CLI)
    ready, release = tmp_path / 'review-ready', tmp_path / 'review-release'
    monkeypatch.setenv('REVIEW_READY', str(ready))
    monkeypatch.setenv('REVIEW_RELEASE', str(release))
    root = make_project()
    write(root / '.opc/local/workers.json', json.dumps({'reviewer': {'kind':'codex','binary':str(cli)}}))
    e = engine_for(root)
    e.run(max_attempts_now=0)
    commit, measurements = e.ledger.champion(e.run_id)
    selected = {'commit_sha':commit,'metrics':measurements.as_dict()}
    return e, selected, e.artifact_dir() / 'promotion/test-review', ready, release


def test_reviewer_stop_uses_call_receipt_and_finite_cancellation(make_project, engine_for, tmp_path, monkeypatch):
    import threading
    import time
    from opc.core.ledger import Ledger
    from opc.core.model import DispatchStopped
    from opc.core.promote import run_reviewer
    e, selected, out, ready, release = reviewer_case(make_project, engine_for, tmp_path, monkeypatch)
    def stop():
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        other = Ledger(e.ledger.path)
        other.set_control(e.run_id, 'stop')
        other.db.close()
    requester = threading.Thread(target=stop)
    requester.start()
    fallback = threading.Timer(2, release.touch)
    fallback.start()
    started = time.monotonic()
    try:
        with pytest.raises(DispatchStopped, match='stopped by user'):
            run_reviewer(e, 'codex', out, '', selected, selected, [])
    finally:
        fallback.cancel()
        release.touch()
        requester.join(timeout=5)
    assert time.monotonic() - started < 1.5
    calls = [c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']
    assert len(calls) == 1 and calls[0]['state'] == 'cancelled'
    assert calls[0]['session_id'] == 'review-session'
    assert Path(calls[0]['receipt_path']).is_file()
    assert not calls[0]['result']['ok']
    assert len(e.ledger.events(e.run_id, 'worker_call')) == 1



def test_reviewer_replays_saved_reply_without_new_call_or_charge(make_project, engine_for, tmp_path, monkeypatch):
    from opc.core.promote import run_reviewer
    e, selected, out, ready, release = reviewer_case(make_project, engine_for, tmp_path, monkeypatch)
    release.touch()
    first = run_reviewer(e, 'codex', out, '', selected, selected, [])
    assert first['ok'] and first['verdict'] == 'accept'
    calls = [c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']
    assert len(calls) == 1 and calls[0]['call_id'] == first['call_id']
    assert calls[0]['session_id'] == 'review-session'
    used = e.ledger.totals(e.run_id)
    ready.unlink()
    release.unlink()
    replay = run_reviewer(e, 'codex', out, '', selected, selected, [])
    assert replay == first
    assert not ready.exists()  # no subprocess was started again
    assert e.ledger.totals(e.run_id) == used
    assert not Path(calls[0]['input']['tree']).exists()


def test_unknown_reviewer_keeps_selected_checkout_and_blocks_redispatch(make_project, engine_for, tmp_path, monkeypatch):
    from opc.core.promote import run_reviewer
    e, selected, out, ready, release = reviewer_case(make_project, engine_for, tmp_path, monkeypatch)
    monkeypatch.setenv('REVIEW_UNKNOWN', '1')
    release.touch()
    with pytest.raises(OPCError, match='execution unknown'):
        run_reviewer(e, 'codex', out, '', selected, selected, [])
    calls = [c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']
    assert len(calls) == 1 and calls[0]['state'] == 'unknown'
    assert (Path(calls[0]['input']['tree']) / 'params.json').is_file()
    with pytest.raises(OPCError, match='execution unknown'):
        run_reviewer(e, 'codex', out.parent / 'another-review', '', selected, selected, [])
    assert len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']) == 1


def test_delivery_requires_project_writer_before_any_execution(make_project, engine_for):
    from opc.core.ledger import Ledger
    from opc.core.promote import promote
    e = engine_for(make_project())
    e.run(max_attempts_now=0)
    events = e.ledger.events(e.run_id)
    calls = e.ledger.calls(e.run_id)
    other = Ledger(e.ledger.path)
    try:
        with other.writer():
            with pytest.raises(OPCError, match='another controller'):
                promote(e)
    finally:
        other.db.close()
    assert e.ledger.events(e.run_id) == events
    assert e.ledger.calls(e.run_id) == calls
    assert not (e.artifact_dir() / 'promotion').exists()



def test_delivery_unknown_evaluation_retains_workspace_and_is_not_repeated(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    from opc.domains.command import CommandDomain
    e = engine_for(make_project())
    e.run(max_attempts_now=0)
    original = CommandDomain.evaluate
    evaluations = []
    def lost_terminal(self, tree, out, repeats, **kwargs):
        original(self, tree, out, repeats, **kwargs)
        evaluations.append(str(tree))
        raise RuntimeError('controller lost evaluator terminal before receipt')
    monkeypatch.setattr(CommandDomain, 'evaluate', lost_terminal)
    with pytest.raises(RuntimeError, match='lost evaluator terminal'):
        promote(e)
    pending = [c for c in e.ledger.calls(e.run_id) if c['result'] is None]
    assert len(pending) == 1 and pending[0]['role'] == 'evaluator'
    assert pending[0]['state'] == 'dispatched'
    tree = Path(pending[0]['input']['tree'])
    assert (tree / 'params.json').is_file()
    assert not Path(pending[0]['receipt_path']).exists()
    calls = e.ledger.calls(e.run_id)
    with pytest.raises(OPCError, match='execution unknown'):
        promote(e)
    assert e.ledger.calls(e.run_id) == calls
    assert evaluations == [str(tree)]
    assert (tree / 'params.json').is_file()


def test_delivery_completed_evaluation_releases_its_workspace(make_project, engine_for):
    from opc.core.promote import promote
    e = engine_for(make_project())
    e.run(max_attempts_now=0)
    report = promote(e)
    assert report['evaluation']['failure'] is None
    calls = [c for c in e.ledger.calls(e.run_id)
             if c['role'] == 'evaluator' and c['input'].get('delivery')]
    assert len(calls) == 1 and calls[0]['state'] == 'completed'
    assert not Path(calls[0]['input']['tree']).exists()


@pytest.mark.parametrize('not_started', [True, False])
def test_known_designer_infrastructure_failure_retries_original_attempt_in_new_call(make_project, engine_for, not_started):
    class RetryDesigner(Sequence):
        def __init__(self):
            super().__init__([plan(1)], [4])
            self.design_calls = 0
        def implement(self, p, ctx, tree, log_dir):
            self.design_calls += 1
            if self.design_calls == 1:
                return WorkerCall('designer', False, Cost(1, 0 if not_started else 3), error='configured tool unavailable',
                                  extra={'infra': True, 'not_started': not_started, 'usage_complete': True})
            call = super().implement(p, ctx, tree, log_dir)
            call.cost = Cost(2, 5)
            return call
    root = make_project()
    worker = RetryDesigner()
    first = use_sequence(engine_for(root), worker)
    summary = first.run()
    assert summary['state'] == 'blocked' and worker.design_calls == 1
    original = first.ledger.attempts(first.run_id)[0]
    assert original['outcome'] is None and original['state'] == 'planned'
    calls = [c for c in first.ledger.calls(first.run_id) if c['role'] == 'designer']
    assert len(calls) == 1 and calls[0]['state'] == ('not_started' if not_started else 'completed')
    resumed = use_sequence(engine_for(root), worker)
    resumed.run(max_attempts_now=0)
    attempts = resumed.ledger.attempts(resumed.run_id)
    assert len(attempts) == 1 and attempts[0]['plan'] == original['plan']
    assert attempts[0]['outcome'] == Outcome.IMPROVEMENT.value
    assert worker.design_calls == 2 and len(worker.contexts) == 1
    designers = [c for c in resumed.ledger.calls(resumed.run_id) if c['role'] == 'designer']
    assert len(designers) == 2 and designers[0]['call_id'] != designers[1]['call_id']
    assert designers[0]['receipt_path'] != designers[1]['receipt_path']
    assert attempts[0]['cost']['tokens'] == (5 if not_started else 8)
    assert attempts[0]['cost']['wall_seconds'] == sum(c['result']['cost']['wall_seconds']
            for c in resumed.ledger.calls(resumed.run_id) if c['attempt_no'] == 1)


def test_claim_registration_is_separate_from_pending_feedback(make_project, engine_for):
    def interpret(ctx):
        return dict(select_work=False,
                    conclusions=[dict(attempt=1, conclusion='Inconclusive: further comparable evidence needed')],
                    claims=[dict(claim_id='copy-speed', statement='Reducing copying always improves speed',
                                 scope='Comparable short and long fields', status='unresolved',
                                 reason='One observation is insufficient',
                                 evidence=[dict(run_id=e.run_id, attempt=1, artifact='eval/evaluation.json')],
                                 counterevidence=[], unresolved=['Short fields not measured'])])
    root = make_project()
    seq = Sequence([plan(1), interpret, plan(2)], [0, 1])
    e = use_sequence(engine_for(root), seq)
    e.run(max_attempts_now=2)
    claim = seq.contexts[2]['claims'][0]
    assert claim['claim_id'] == 'copy-speed' and claim['version'] == 1
    assert claim['status'] == 'unresolved'
    assert claim['scope'] == 'Comparable short and long fields'
    assert claim['evidence'][0]['artifact'] == 'eval/evaluation.json'
    assert e.summary()['claims'][0]['status'] == 'unresolved'
    assert e.summary()['pending_conclusions'] == [2]
    seq2 = Sequence([stop])
    restored = use_sequence(engine_for(root), seq2)
    restored.run()
    assert seq2.contexts[0]['claims'][0]['claim_id'] == 'copy-speed'
    assert seq2.contexts[0]['pending_feedback'][0]['attempt'] == 2
    report = json.loads((restored.artifact_dir() / 'views/report.json').read_text())
    assert report['claims'][0]['status'] == 'unresolved'
    assert 'copy-speed' in (restored.artifact_dir() / 'views/STATE.md').read_text()


@pytest.mark.parametrize('change,reason', [
    ({'related_claims': ['unknown']}, 'unknown related claim'),
    ({'status': 'verified'}, 'status'),
    ({'claim_id': '../escape'}, 'claim_id'),
    ({'task_id': 'other-task'}, 'outside current task'),
    ({'evidence': [{'run_id': 'absent', 'attempt': 1, 'artifact': 'eval/evaluation.json'}]}, 'unknown'),
    ({'evidence': [{'run_id': 'absent', 'attempt': 1, 'artifact': '../private'}]}, 'relative artifact'),
])
def test_invalid_claim_rejects_feedback_and_next_work(make_project, engine_for, change, reason):
    claim = dict(claim_id='claim', statement='Copying affects speed', scope='fixed inputs',
                 status='unresolved', reason='More evidence needed', evidence=[])
    seq = Sequence([plan(1), dict(plan(2), claims=[dict(claim, **change)],
                       conclusions=[dict(attempt=1, conclusion='More comparable measurements needed')])], [0])
    e = use_sequence(engine_for(make_project()), seq)
    result = e.run()
    assert result['state'] == 'blocked' and reason in result['stop_reason']
    assert result['claims'] == [] and result['pending_conclusions'] == [1]
    assert len(e.attempt_records()) == 1


def test_multiple_claims_share_observation_and_observer_is_read_only(make_project, engine_for):
    from opc.observer.adapter import ObserverAdapter
    def interpret(ctx):
        reference = dict(run_id=e.run_id, attempt=1, artifact='eval/evaluation.json')
        return dict(stop(ctx), claims=[
            dict(claim_id='general', statement='Copying affects speed', scope='fixed inputs',
                 status='unresolved', reason='Need short field measurement', evidence=[reference],
                 unresolved=['Short fields unknown']),
            dict(claim_id='long', statement='Reducing copying helps long fields', scope='long fields only',
                 status='supported', reason='Long fields improved', evidence=[reference],
                 counterevidence=[reference], unresolved=['Independent repeats needed'])])
    root = make_project()
    e = use_sequence(engine_for(root), Sequence([plan(1), interpret], [4]))
    result = e.run()
    assert [c['claim_id'] for c in result['claims']] == ['general', 'long']
    ledger_path = e.ledger.path
    before = ledger_path.read_bytes()
    observer = ObserverAdapter(root)
    observed = observer.run(observer._id('run', e.run_id))['data']
    assert [(c['claim_id'], c['status']) for c in observed['claims']] == [
        ('general', 'unresolved'), ('long', 'supported')]
    assert observed['claims'][1]['counterevidence'][0]['attempt'] == 1
    assert ledger_path.read_bytes() == before
