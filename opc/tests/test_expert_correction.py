"""Malformed work is corrected before it can create Attempts or execute candidates."""
import json
from pathlib import Path

import pytest

from opc.core.model import Cost
from opc.tests.conftest import component, task
from opc.tests.test_research_loop import Sequence, plan, use_sequence


@pytest.mark.parametrize('batch', [False, True])
def test_directory_manifest_is_corrected_in_same_run_with_original_receipt(make_project, engine_for, batch):
    root = make_project(comp=component(editable=['params.json', 'tools/**', 'manifests/**']),
                        extra={'tools/check.py': '# tool', 'manifests/run.json': '{}'})
    bad = plan(1, deliverables=['tools', 'manifests'])
    bad['claims'] = [dict(claim_id='unapplied', statement='Proposed claim', scope='Fixed inputs',
                          status='unresolved', reason='Need evidence')]
    rejected = {'works': [bad]} if batch else bad
    engine = engine_for(root)

    def correct(ctx):
        feedback = ctx['decision_correction']
        assert feedback['rejected_output'] == rejected
        assert 'tools' in feedback['reason'] and 'concrete' in feedback['reason']
        assert feedback['attempt'] == 1 and feedback['max_attempts'] == 2
        assert engine.attempt_records() == []
        assert engine.ledger.claims(engine.task.task_id) == []
        assert not engine.ledger.events(engine.run_id, 'expert_decision')
        assert not any(c['role'] == 'designer' for c in engine.ledger.calls(engine.run_id))
        good = plan(1, deliverables=['tools/check.py', 'manifests/run.json'])
        return {'works': [good]} if batch else good

    worker = Sequence([rejected, correct], [4])
    result = use_sequence(engine, worker).run(max_attempts_now=1)
    assert result['state'] == 'paused' and len(engine.attempt_records()) == 1
    calls = engine.ledger.calls(engine.run_id)
    assert [c['role'] for c in calls] == ['evaluator', 'expert', 'expert', 'designer', 'evaluator']
    assert json.loads(Path(calls[1]['receipt_path']).read_text())['output'] == rejected
    assert calls[1]['run_id'] == calls[2]['run_id'] == engine.run_id
    assert len(engine.ledger.events(engine.run_id, 'expert_rejected')) == 1
    assert len(engine.ledger.events(engine.run_id, 'expert_decision')) == 1
    assert (engine.attempt_dir(1) / 'outputs/tools/check.py').is_file()
    assert (engine.attempt_dir(1) / 'outputs/manifests/run.json').is_file()


@pytest.mark.parametrize('path', ['tools', 'tools/', 'tools/*', 'tools/?.py', 'tools/[ab].py', '../tools/x.py'])
def test_deliverables_reject_directories_and_patterns_even_with_broad_editable_scope(make_project, engine_for, path):
    root = make_project(comp=component(editable=['**']), extra={'tools/check.py': '# tool'})
    engine = engine_for(root)
    assert engine.validate_work_batch([plan(1, deliverables=[path])], source_tree=root)
    assert engine.validate_work_batch([plan(1, deliverables=['tools/new.py', 'LICENSE'])], source_tree=root) is None


def test_repeated_invalid_work_blocks_after_two_corrections_and_accounts_calls(make_project, engine_for):
    class Invalid(Sequence):
        def propose(self, ctx, tree, log_dir):
            call = super().propose(ctx, tree, log_dir)
            call.cost = Cost(.01, 7, 0.0)
            return call

    worker = Invalid([plan(1, deliverables=['tools']) for _ in range(3)])
    engine = use_sequence(engine_for(make_project()), worker)
    result = engine.run()
    assert result['state'] == 'blocked' and 'tools' in result['stop_reason']
    assert result['spent']['tokens'] == 21
    assert engine.attempt_records() == []
    assert [c['role'] for c in engine.ledger.calls(engine.run_id)] == ['evaluator'] + ['expert'] * 3
    assert [ctx.get('decision_correction', {}).get('attempt', 0) for ctx in worker.contexts] == [0, 1, 2]
    assert len(engine.ledger.events(engine.run_id, 'expert_rejected')) == 3


def test_correction_obeys_budget_before_dispatch(make_project, engine_for):
    class Expensive(Sequence):
        def propose(self, ctx, tree, log_dir):
            call = super().propose(ctx, tree, log_dir)
            call.cost = Cost(.01, 7, 0.0)
            return call

    spec = task()
    spec['budget']['max_tokens'] = 7
    engine = use_sequence(engine_for(make_project(tsk=spec)), Expensive([plan(1, deliverables=['tools'])]))
    result = engine.run()
    assert result['state'] == 'closed' and 'budget_exhausted' in result['stop_reason']
    assert len(engine.ledger.calls(engine.run_id)) == 2  # baseline and first Expert only
    assert len(engine.ledger.events(engine.run_id, 'expert_rejected')) == 1
    assert engine.attempt_records() == []


@pytest.mark.parametrize('interruption', ['after_rejection', 'after_receipt'])
def test_resume_keeps_correction_count_and_receipt(make_project, engine_for, monkeypatch, interruption):
    root = make_project()
    engine = use_sequence(engine_for(root), Sequence([plan(1, deliverables=['tools'])]))
    hard_check = engine.hard_check

    def interrupt():
        if engine.run_id and engine.ledger.events(engine.run_id, 'expert_rejected'):
            raise KeyboardInterrupt()
        hard_check()

    if interruption == 'after_rejection':
        monkeypatch.setattr(engine, 'hard_check', interrupt)
    else:
        dispatch = engine.dispatch_call

        def interrupted_dispatch(role, *args, **kwargs):
            call = dispatch(role, *args, **kwargs)
            if role == 'expert':
                raise KeyboardInterrupt()
            return call

        monkeypatch.setattr(engine, 'dispatch_call', interrupted_dispatch)
    assert engine.run()['state'] == 'paused'
    call = engine.ledger.calls(engine.run_id)[1]
    original = Path(call['receipt_path']).read_bytes()
    worker = Sequence([plan(1, deliverables=['tools']) for _ in range(2)])
    resumed = use_sequence(engine_for(root), worker)
    result = resumed.run()
    assert resumed.run_id == engine.run_id and result['state'] == 'blocked'
    assert [ctx['decision_correction']['attempt'] for ctx in worker.contexts] == [1, 2]
    assert len(resumed.ledger.calls(resumed.run_id)) == 4  # baseline and three Expert calls
    assert Path(call['receipt_path']).read_bytes() == original
