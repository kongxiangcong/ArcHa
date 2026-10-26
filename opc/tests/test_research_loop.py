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
