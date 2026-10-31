"""Delivery recovery uses fixed candidates and durable calls, without model services."""
import json
from pathlib import Path

import pytest

from opc.adapters.worker import WorkerCall
from opc.core.model import BudgetExhausted, Cost, OPCError
from opc.core.promote import promote
from opc.tests.conftest import EVALUATE, component, task
from opc.tests.test_research_loop import Sequence, plan, stop, use_sequence
from opc.tests.test_task_delivery_intent import request
from opc.tests.test_requirement_review import finding


def reviewer_reply(requirements=('R',)):
    return dict(verdict='accept', summary='Scoped requirements covered', overreach=[],
                requirement_findings=[finding(ident) for ident in requirements])


@pytest.mark.parametrize('boundary', ['evaluator', 'reviewer', 'report_registration', 'unaccounted_receipt'])
def test_promote_recovers_saved_calls_before_report_without_repeating_them(make_project, engine_for, monkeypatch, boundary):
    root = make_project(tsk=task(acceptance={}, requirements=[dict(id='R', text='Explain result', verification='review')]))
    e = use_sequence(engine_for(root), Sequence([request]))
    e.run()
    reviews = []
    def review(self, role, prompt, tree, log_dir, sandbox, schema):
        reviews.append(prompt)
        return WorkerCall(role, True, Cost(0, 7, 0), extra={'usage_complete': True}), json.dumps(reviewer_reply())
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', review)
    complete = e.complete_call
    event = e.ledger.event
    def interrupt_call(request, result):
        if boundary == 'unaccounted_receipt' and request.role == 'evaluator':
            raise RuntimeError('controller interrupted after durable receipt')
        call = complete(request, result)
        if request.role == boundary:
            raise RuntimeError('controller interrupted after durable receipt')
        return call
    def interrupt_report(run_id, kind, *args, **kwargs):
        if kind == 'promotion_report':
            raise RuntimeError('controller interrupted before report registration')
        return event(run_id, kind, *args, **kwargs)
    monkeypatch.setattr(e, 'complete_call', interrupt_call)
    if boundary == 'report_registration':
        monkeypatch.setattr(e.ledger, 'event', interrupt_report)
    with pytest.raises(RuntimeError, match='controller interrupted'):
        promote(e, review='codex')
    restored = engine_for(root)
    result = promote(restored, source_run=e.run_id, review='codex')
    assert result['complete']
    assert len(reviews) == 1
    calls = restored.ledger.calls(e.run_id)
    assert len([c for c in calls if c['role'] == 'evaluator']) == 1
    assert len([c for c in calls if c['role'] == 'reviewer']) == 1
    assert restored.ledger.totals(e.run_id)['tokens'] == 7
    assert len(restored.ledger.runs()) == 1


def test_evaluator_start_failure_retries_acceptance_without_development(make_project, engine_for, tmp_path):
    ready = tmp_path / 'evaluator-ready'
    ready.touch()
    evaluate = 'from pathlib import Path\nimport sys\nif not Path(' + repr(str(ready)) + ').exists(): raise SystemExit(75)\n' + EVALUATE
    root = make_project(tsk=task(acceptance={}, requirements=[]), evaluate=evaluate)
    e = use_sequence(engine_for(root), Sequence([request]))
    selected = e.run()
    ready.unlink()
    failed = promote(e)
    assert failed['next_step']['action'] == 'retry_evaluation'
    assert failed['complete'] is False
    original = (Path(failed['report_dir']) / 'report.json').read_bytes()
    ready.touch()
    restored = engine_for(root)
    retried = restored.repair_delivery(Path(failed['report_dir']) / 'report.json')
    assert retried['complete'] is True and retried['delivery']['selected_version'] == selected['selected_version']
    assert retried['delivery']['evaluation_mode'] == 'executed'
    assert len(restored.ledger.runs()) == 1 and not restored.attempt_records()
    assert len([c for c in restored.ledger.calls(e.run_id) if c['role'] == 'evaluator']) == 2
    assert (Path(failed['report_dir']) / 'report.json').read_bytes() == original


@pytest.mark.parametrize('reply', [dict(ok=False, error='Provider unavailable'), dict(ok=True, verdict='no_usable_verdict', requirement_findings=[])])
def test_reviewer_execution_failure_retries_review_only(make_project, engine_for, monkeypatch, capsys, reply):
    root = make_project(tsk=task(acceptance={}, requirements=[dict(id='R', text='Explain result', verification='review')]))
    e = use_sequence(engine_for(root), Sequence([request]))
    e.run()
    answers = iter([reply, dict(ok=True, **reviewer_reply())])
    reviews = []
    def review(self, role, *args):
        reviews.append(args)
        answer = next(answers)
        return WorkerCall(role, answer['ok'], Cost(0, 7, 0), error=answer.get('error', ''),
                          extra={'usage_complete': True}), json.dumps(answer)
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', review)
    failed = promote(e, review='codex')
    assert failed['next_step']['action'] == 'retry_review'
    used = e.spent()
    from opc.cli import main
    monkeypatch.setattr('opc.cli._engine', lambda *a, **k: e)
    assert main(['run', '-p', str(root), '--task', 't-toy', '--repair-promotion',
                 str(Path(failed['report_dir']) / 'report.json'), '--deliver']) == 0
    retried = json.loads(capsys.readouterr().out)
    assert retried['complete'] is True and retried['delivery']['evaluation_mode'] == 'referenced'
    assert len(reviews) == 2 and len(e.ledger.runs()) == 1
    assert len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'evaluator']) == 1
    assert len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']) == 2
    assert e.spent()['tokens'] == used['tokens'] + 7 and not e.attempt_records()


def test_development_continues_failed_work_and_recovers_one_linked_repair_run(make_project, engine_for, monkeypatch):
    from opc.core.engine import Engine
    from opc.tests.conftest import git
    evaluate = EVALUATE + '\nif x == 4 or (x == 5 and "promotion" in str(out)): raise SystemExit(1)\n'
    comp = component()
    comp['gates'].append(dict(id='regression', argv=['{python}', '-c', 'import json; assert json.load(open("params.json"))["x"] != 6'], timeout_s=10))
    root = make_project(comp=comp, tsk=task(acceptance={}, requirements=[dict(id='R', text='Working behavior', gates=['evaluate', 'regression'])]), evaluate=evaluate)
    head = git(root, 'rev-parse', 'HEAD')
    seq = Sequence([plan(1, evaluate=True), plan(2, base_attempt=1, evaluate=True),
                    lambda ctx: dict(request(ctx), base_attempt=2)], [4, 5])
    first = use_sequence(engine_for(root), seq)
    first.run(max_attempts_now=1)
    a = first.attempt_records()[0]
    assert a['outcome'] == 'broken' and a['candidate']
    selected = first.run()
    assert seq.parents[1] == a['candidate']
    failed = promote(first)
    assert failed['next_step']['action'] == 'repair_candidate'
    path = Path(failed['report_dir']) / 'report.json'
    old_bytes = path.read_bytes()
    original_stop = first.ledger.run(first.run_id)['stop_reason']
    repair = use_sequence(engine_for(root), Sequence([]))
    open_run = repair.open_run
    def interrupted(*args, **kwargs):
        open_run(*args, **kwargs)
        raise RuntimeError('repair Run created before controller interruption')
    monkeypatch.setattr(repair, 'open_run', interrupted)
    with pytest.raises(RuntimeError, match='Run created'):
        repair.repair_delivery(path)
    assert len(repair.ledger.runs()) == 2
    def choose(ctx):
        failure = ctx['delivery_repair']['failure']
        assert failure['report_path'] == str(path) and failure['complete'] is False
        assert failure['candidate'] == failed['candidate']
        assert failure['findings'] == failed['findings']
        import subprocess
        from opc.core.model import write_json
        from opc.core.tool_boundary import worker_policy, runner_argv
        policy_path = recovered.artifact_dir() / 'repair-report-policy.json'
        write_json(policy_path, worker_policy('expert', Path(ctx['knowledge']['context']).parent,
                                              recovered.artifact_dir(), ctx))
        original = subprocess.run(runner_argv(policy_path, ['/bin/cat', str(path)]),
                                  check=True, capture_output=True, text=True)
        assert json.loads(original.stdout)['candidate'] == failed['candidate']
        return plan(1)
    recovered_seq = Sequence([choose, request], [7])
    recovered = use_sequence(engine_for(root), recovered_seq)
    final = recovered.repair_delivery(path)
    assert final['baseline'] == selected['selected_version']
    assert len(recovered.ledger.runs()) == 2 and recovered.run_id != first.run_id
    accepted = promote(recovered, source_run=recovered.run_id)
    assert accepted['complete'] and accepted['evaluation_mode'] == 'executed'
    assert {g['gate_id'] for g in accepted['evaluation']['gates']} == {'evaluate', 'regression'}
    assert first.ledger.run(first.run_id)['stop_reason'] == original_stop and path.read_bytes() == old_bytes
    assert recovered.summary()['delivery']['report_path'] == str(Path(accepted['report_dir']) / 'report.json')
    assert recovered.summary()['complete'] is True
    assert recovered.spent()['wall_seconds'] >= first.spent()['wall_seconds']
    before = len(recovered.ledger.calls(recovered.run_id))
    repeated = recovered.repair_delivery(path)
    assert repeated['run_id'] == final['run_id'] and len(recovered.ledger.runs()) == 2
    assert len(recovered.ledger.calls(recovered.run_id)) == before
    assert git(root, 'rev-parse', 'HEAD') == head


@pytest.mark.parametrize('control', ['pause', 'stop', 'budget'])
def test_saved_final_acceptance_receipt_can_finish_without_new_dispatch(make_project, engine_for, monkeypatch, control):
    needs_review = control == 'budget'
    contract = task(acceptance={}, requirements=[dict(id='R', text='Explain result', verification='review')] if needs_review else [])
    if needs_review:
        contract['budget']['max_tokens'] = 7
    root = make_project(tsk=contract)
    e = use_sequence(engine_for(root), Sequence([request]))
    e.run()
    def review(self, role, *args):
        return WorkerCall(role, True, Cost(0, 7, 0), extra={'usage_complete': True}), json.dumps(reviewer_reply())
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', review)
    original = e.complete_call
    def interrupt(request, result):
        call = original(request, result)
        if request.role == ('reviewer' if needs_review else 'evaluator'):
            raise RuntimeError('final receipt saved')
        return call
    monkeypatch.setattr(e, 'complete_call', interrupt)
    with pytest.raises(RuntimeError, match='final receipt'):
        promote(e, review='codex' if needs_review else None)
    if control != 'budget':
        e.ledger.set_control(e.run_id, control)
    calls = len(e.ledger.calls(e.run_id))
    spent = e.spent()
    accepted = promote(engine_for(root), source_run=e.run_id, review='codex' if needs_review else None)
    assert accepted['complete']
    assert len(e.ledger.calls(e.run_id)) == calls and e.spent() == spent


@pytest.mark.parametrize('control', ['pause', 'stop', 'budget'])
def test_recovery_does_not_dispatch_missing_review_under_control_limits(make_project, engine_for, monkeypatch, capsys, control):
    contract = task(acceptance={}, requirements=[dict(id='R', text='Explain result', verification='review')])
    contract['budget']['max_tokens'] = 7
    root = make_project(tsk=contract)
    e = use_sequence(engine_for(root), Sequence([request]))
    e.run()
    original = e.complete_call
    def interrupt(request, result):
        call = original(request, result)
        if request.role == 'evaluator':
            raise RuntimeError('evaluation receipt saved')
        return call
    monkeypatch.setattr(e, 'complete_call', interrupt)
    with pytest.raises(RuntimeError, match='evaluation receipt'):
        promote(e, review='codex')
    if control == 'budget':
        e.ledger.charge(e.run_id, None, 'expert', Cost(0, 7, 0))
    else:
        e.ledger.set_control(e.run_id, control)
    calls = len(e.ledger.calls(e.run_id))
    with pytest.raises((OPCError, BudgetExhausted)):
        promote(engine_for(root), source_run=e.run_id, review='codex')
    assert len(e.ledger.calls(e.run_id)) == calls
    assert not [c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']
    from opc.cli import main
    assert main(['promote', '-p', str(root), '--task', 't-toy', '--source-run', e.run_id, '--review', 'codex']) == 2
    assert 'max_tokens' in capsys.readouterr().err if control == 'budget' else True
    assert len(e.ledger.calls(e.run_id)) == calls


def test_confirmed_target_defect_is_not_hidden_by_reviewer_execution_failure(make_project, engine_for, monkeypatch):
    contract = task(requirements=[dict(id='R', text='Explain performance', verification='review')])
    root = make_project(tsk=contract)
    e = use_sequence(engine_for(root), Sequence([request]))
    e.run()
    monkeypatch.setattr('opc.core.promote.run_reviewer', lambda *a: dict(ok=False, error='Reviewer unavailable'))
    failed = promote(e, review='codex')
    assert failed['target_met'] is False and failed['selected_metrics']['loss'] == 17
    assert failed['next_step']['action'] == 'repair_candidate'
    assert {f['check'] for f in failed['next_step']['gaps']} >= {'target', 'review'}


def test_exploration_repairs_explanation_on_same_code_without_remeasuring(make_project, engine_for, monkeypatch, capsys):
    from opc.core.engine import Engine
    from opc.cli import main
    from opc.observer.adapter import ObserverAdapter
    from opc.tests.test_delivery_candidates import claim
    evaluations = []
    evaluate = Engine.evaluate_commit
    def measured(self, *args, **kwargs):
        evaluations.append((self.run_id, args[1]))
        return evaluate(self, *args, **kwargs)
    monkeypatch.setattr(Engine, 'evaluate_commit', measured)
    root = make_project(tsk=task(acceptance={}, requirements=[
        dict(id='TRUTH', text='Decide universal speedup', verification='review'),
        dict(id='BOUNDARY', text='Explain boundary; core unknown blocks completion', verification='review')]))
    c = dict(claim(), status='refuted', reason='Valid short-field counterexample')
    initial = use_sequence(engine_for(root), Sequence([lambda ctx: dict(request(ctx), claims=[c],
        delivery_claims=[dict(claim_id='copy', version=1)])]))
    chosen = initial.run()
    reviews = []
    def review(self, role, prompt, *args):
        reviews.append(prompt)
        if len(reviews) == 1:
            reply = dict(verdict='accept', summary='Counterexample established but boundary unknown', overreach=[],
                requirement_findings=[finding('TRUTH'), finding('BOUNDARY', status='insufficient_evidence', evidence=[], gap='Explain the short-field boundary')])
        else:
            assert 'Copy setup dominates short fields' in prompt
            reply = reviewer_reply(('TRUTH', 'BOUNDARY'))
        return WorkerCall(role, True, Cost(0, 7, 0), extra={'usage_complete': True}), json.dumps(reply)
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', review)
    failed = promote(initial, review='codex')
    assert failed['next_step']['action'] == 'supplement_evidence'
    report_path = Path(failed['report_dir']) / 'report.json'
    original = report_path.read_bytes()
    count = len(evaluations)
    def explain(ctx):
        assert ctx['delivery_repair']['failure']['requirements'][1]['gap'] == 'Explain the short-field boundary'
        return dict(request(ctx), claims=[dict(c, base_version=1,
            reason='Copy setup dominates short fields; long fields amortize setup', unresolved=[])],
            delivery_claims=[dict(claim_id='copy', version=2)])
    repaired = use_sequence(engine_for(root), Sequence([explain]))
    result = repaired.repair_delivery(report_path)
    assert result['selected_version'] == chosen['selected_version']
    accepted = promote(repaired, source_run=repaired.run_id, review='codex')
    assert accepted['complete'] and accepted['evaluation_mode'] == 'referenced'
    assert accepted['evidence_source'] == str(report_path)
    assert len(evaluations) == count  # includes preflight: repair must not repeat it
    assert len(reviews) == 2 and len(repaired.ledger.runs()) == 2
    assert all(c['role'] != 'designer' for run in repaired.ledger.runs() for c in repaired.ledger.calls(run['run_id']))
    assert accepted['candidate']['claims'][0]['version'] == 2
    assert report_path.read_bytes() == original
    monkeypatch.setattr('opc.cli._engine', lambda *a, **k: repaired)
    assert main(['report', '-p', str(root), '--task', 't-toy', '--run-id', repaired.run_id]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['complete'] is True and output['delivery']['acceptance_revision'] == 'r0001'
    assert output['delivery_repair']['source_report'] == str(report_path)
    before = repaired.ledger.path.read_bytes()
    assert main(['status', '-p', str(root), '--task', 't-toy', '--run-id', repaired.run_id]) == 0
    status = json.loads(capsys.readouterr().out)[0]
    assert status['complete'] is True and status['delivery']['candidate'] == accepted['candidate']
    observer = ObserverAdapter(root)
    observed = observer.run(observer._id('run', repaired.run_id))['data']
    assert observed['delivery_repair']['source_report'] == str(report_path)
    assert observed['delivery_next_step']['action'] == 'complete'
    assert repaired.ledger.path.read_bytes() == before and len(evaluations) == count


def test_optimization_target_gap_can_close_incomplete_without_another_review(make_project, engine_for, monkeypatch, capsys):
    from opc.cli import main
    contract = task(requirements=[])
    contract['acceptance']['target']['value'] = 90
    evaluate = EVALUATE.replace('(x - 7) ** 2 + 1', '100 if x == 3 else 94')
    root = make_project(tsk=contract, evaluate=evaluate)
    e = use_sequence(engine_for(root), Sequence([plan(1), request], [4]))
    e.run()
    failed = promote(e)
    assert failed['target_met'] is False and failed['selected_metrics']['loss'] == 94
    assert failed['next_step']['action'] == 'repair_candidate'
    repaired = use_sequence(engine_for(root), Sequence([lambda ctx: dict(stop(ctx),
        gaps=['Target 90 remains unmet at 94; no valuable next method'], reopen_conditions=[])]))
    monkeypatch.setattr('opc.cli._engine', lambda *a, **k: repaired)
    assert main(['run', '-p', str(root), '--task', 't-toy', '--repair-promotion',
                 str(Path(failed['report_dir']) / 'report.json'), '--deliver']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['closure']['finish'] == 'close_incomplete' and result['complete'] is False
    assert result['closure']['gaps'] and not repaired.attempt_records()
    assert not repaired.ledger.events(repaired.run_id, 'promotion_report')
    assert not [c for run in repaired.ledger.runs() for c in repaired.ledger.calls(run['run_id']) if c['role'] == 'reviewer']


def test_unknown_review_is_not_replayed_as_a_completed_judgment(make_project, engine_for, monkeypatch):
    root = make_project(tsk=task(acceptance={}, requirements=[dict(id='R', text='Explain result', verification='review')]))
    e = use_sequence(engine_for(root), Sequence([request]))
    e.run()
    reviews = []
    def unknown(self, role, *args):
        reviews.append(role)
        return WorkerCall(role, False, Cost(), error='Process termination unknown',
                          extra={'execution_unknown': True, 'usage_complete': True}), ''
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', unknown)
    with pytest.raises(OPCError, match='execution unknown'):
        promote(e, review='codex')
    count = len(e.ledger.calls(e.run_id))
    with pytest.raises(OPCError, match='execution unknown'):
        promote(engine_for(root), source_run=e.run_id, review='codex')
    assert len(reviews) == 1 and len(e.ledger.calls(e.run_id)) == count


def test_reproduction_start_failure_retries_only_missing_confirmations(make_project, engine_for, tmp_path):
    ready = tmp_path / 'confirmation-ready'
    evaluate = EVALUATE + '\nif "confirm" in str(out) and "baseline-0" in str(out) and not Path(' + repr(str(ready)) + ').exists(): raise SystemExit(75)\n'
    root = make_project(tsk=task(requirements=[]), evaluate=evaluate)
    e = use_sequence(engine_for(root), Sequence([plan(1), request], [7]))
    selected = e.run()
    failed = promote(e, confirm_repeats=2)
    assert failed['next_step']['action'] == 'retry_evaluation'
    count = len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'evaluator'])
    original = (Path(failed['report_dir']) / 'report.json').read_bytes()
    ready.touch()
    result = e.repair_delivery(Path(failed['report_dir']) / 'report.json')
    assert result['complete']
    assert result['delivery']['evaluation_mode'] == 'referenced'
    assert len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'evaluator']) == count + 2
    assert [s['mode'] for s in result['delivery']['reproduction_sources']] == ['executed', 'executed', 'referenced', 'referenced']
    assert (Path(failed['report_dir']) / 'report.json').read_bytes() == original
    # A new explicit confirmation after success executes the requested samples.
    before = len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'evaluator'])
    assert promote(e, confirm_repeats=2)['complete']
    assert len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'evaluator']) == before + 5
    # The same selected commit in a different comparison range cannot borrow baseline samples.
    later = use_sequence(engine_for(root), Sequence([request]))
    later.run(new_run=True, base_ref=selected['selected_version'])
    comparison = promote(later, source_run=later.run_id, confirm_repeats=2)
    assert comparison['confirm']['samples']['baseline'] == [1, 1]
    assert comparison['confirm']['worst_case_gain'] == 0
