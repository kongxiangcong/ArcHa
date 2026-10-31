"""Controlled Expert decisions through the Run and CLI boundaries."""
import json

from opc.tests.conftest import task
from opc.tests.test_research_loop import Sequence, plan, stop, use_sequence


def incomplete(ctx):
    return {**stop(ctx), 'finish': 'close_incomplete',
            'gaps': ['Required boundary handling is still missing'],
            'reopen_conditions': ['A boundary reproducer or a new feasible repair method becomes available']}


def request(ctx):
    return {**stop(ctx), 'exhausted': False, 'finish': 'request_acceptance',
            'stop_reason': 'Selected version is ready for contract acceptance'}


def test_incomplete_closeout_preserves_gaps_without_delivery(make_project, engine_for, monkeypatch, capsys):
    from opc.cli import main
    from opc.observer.adapter import ObserverAdapter
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([plan(1), incomplete], [4]))
    monkeypatch.setattr('opc.cli._engine', lambda *a, **k: e)
    monkeypatch.setattr('opc.core.promote.promote', lambda *a, **k: (_ for _ in ()).throw(AssertionError('unexpected delivery')))
    assert main(['run', '-p', str(root), '--task', 't-toy', '--deliver']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['state'] == 'closed' and not result['complete']
    assert result['closure']['finish'] == 'close_incomplete'
    assert result['closure']['gaps'] == incomplete({ 'pending_feedback': [] })['gaps']
    assert result['closure']['reopen_conditions']
    assert result['pending_conclusions'] == []
    assert len(e.attempt_records()) == 1
    assert not [c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']
    observer = ObserverAdapter(root)
    assert observer.run(observer._id('run', e.run_id))['data']['closure'] == result['closure']


def test_explicit_acceptance_interprets_last_feedback_and_delivers_once(make_project, engine_for, monkeypatch, capsys):
    from opc.cli import main
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    seq = Sequence([plan(1), request], [7])
    e = use_sequence(engine_for(root), seq)
    monkeypatch.setattr('opc.cli._engine', lambda *a, **k: e)
    assert main(['run', '-p', str(root), '--task', 't-toy', '--deliver']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['complete'] and result['closure']['finish'] == 'request_acceptance'
    assert result['pending_conclusions'] == []
    assert result['delivery']['selected_version'] == result['selected_version']
    assert len(seq.contexts) == 2 and len(seq.parents) == 1
    calls = len(e.ledger.calls(e.run_id))
    usage = e.spent()
    assert main(['run', '-p', str(root), '--task', 't-toy', '--deliver']) == 0
    assert json.loads(capsys.readouterr().out)['complete']
    assert len(e.ledger.calls(e.run_id)) == calls and e.spent() == usage


def test_legacy_exhaustion_is_incomplete_even_with_delivery_authorization(make_project, engine_for, monkeypatch, capsys):
    from opc.cli import main
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([stop]))
    monkeypatch.setattr('opc.cli._engine', lambda *a, **k: e)
    monkeypatch.setattr('opc.core.promote.promote', lambda *a, **k: (_ for _ in ()).throw(AssertionError('unexpected delivery')))
    assert main(['run', '-p', str(root), '--task', 't-toy', '--deliver']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['closure']['finish'] == 'close_incomplete' and not result['complete']


def test_terminal_decision_handoff_replay_does_not_repeat_selection(make_project, engine_for, monkeypatch):
    import pytest
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([request]))
    original = e.ledger.finish_decision
    def interrupt(*args, **kw):
        original(*args, **kw)
        raise RuntimeError('terminal handoff interrupted')
    monkeypatch.setattr(e.ledger, 'finish_decision', interrupt)
    with pytest.raises(RuntimeError, match='terminal handoff interrupted'):
        e.run()
    restored = use_sequence(engine_for(root), Sequence([]))
    result = restored.run()
    assert result['state'] == 'closed' and result['closure']['finish'] == 'request_acceptance'
    assert len(restored.ledger.events(restored.run_id, 'selected_version')) == 1
    assert len(restored.ledger.events(restored.run_id, 'expert_stop')) == 1
    assert len([c for c in restored.ledger.calls(restored.run_id) if c['role'] == 'expert']) == 1


def test_parallel_candidates_do_not_replace_explicit_next_work_parent(make_project, engine_for):
    from opc.tests.conftest import git
    from opc.tests.test_attempt_dag import Branches
    class Choosing(Branches):
        def propose(self, ctx, tree, log_dir):
            from opc.adapters.worker import WorkerCall
            from opc.core.model import Cost
            if not self.calls:
                return super().propose(ctx, tree, log_dir)
            self.calls += 1
            candidates = [a['candidate'] for a in ctx['history']]
            assert len(candidates) == 2
            assert ctx['working_version']['commit'] not in candidates
            return WorkerCall('expert', True, Cost(), output={**request(ctx), 'base_attempt': 1})
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    worker = Choosing([plan(1, work_id='first'), plan(2, work_id='last')])
    e = use_sequence(engine_for(root), worker)
    result = e.run()
    assert result['selected_version'] == e.attempt_records()[0]['candidate']
    assert git(root, 'rev-parse', 'HEAD').strip() == result['baseline']


def test_attempt_allowance_exhaustion_interprets_final_feedback_without_delivery(make_project, engine_for, monkeypatch, capsys):
    from opc.cli import main
    contract = task()
    contract['budget']['max_attempts'] = 1
    root = make_project(tsk=contract)
    seq = Sequence([plan(1), request], [4])
    e = use_sequence(engine_for(root), seq)
    monkeypatch.setattr('opc.cli._engine', lambda *a, **k: e)
    monkeypatch.setattr('opc.core.promote.promote', lambda *a, **k: (_ for _ in ()).throw(AssertionError('budget delivery')))
    assert main(['run', '-p', str(root), '--task', 't-toy', '--deliver']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['pending_conclusions'] == []
    assert result['stop_reason'].startswith('budget_exhausted: max_attempts')
    assert len(seq.contexts) == 2 and len(seq.parents) == 1
