"""A Reviewer covers requirement identities, never an implicit whole-task accept."""
from pathlib import Path

import pytest

from opc.tests.conftest import task
from opc.tests.test_research_loop import Sequence, stop, use_sequence


def finding(ident, status='met', evidence=None, gap=''):
    return dict(id=ident, status=status,
                evidence=['Selected candidate and scoped evidence'] if evidence is None else evidence, gap=gap)


def test_reviewer_can_read_selected_formal_originals_and_their_cached_origin(make_project, engine_for, monkeypatch):
    import json
    from opc.adapters.worker import WorkerCall
    from opc.core.model import Cost
    from opc.core.promote import promote
    root = make_project(tsk=task(acceptance={}, requirements=[dict(id='R', text='Inspect actual checks', verification='review')]))
    engine = use_sequence(engine_for(root), Sequence([stop]))
    engine.run()
    originals = []
    def review(self, role, prompt, tree, log_dir, sandbox, schema):
        assert role == 'reviewer'
        directories = [Path(p) for p in self.tool_scope['tool_policy']['read']
                       if (Path(p) / 'evaluation.json').is_file()]
        assert len(directories) == 1
        directory = directories[0]
        assert json.loads((directory / 'evaluation.json').read_text())['commit'] == engine.selected_commit()
        assert (directory / 'receipt.json').is_file()
        assert self.tool_scope['tool_policy']['write'] == []
        originals.append(directory)
        return WorkerCall(role, True, Cost(), extra={'usage_complete':True}), json.dumps({
            'verdict':'accept','summary':'Read selected execution originals','overreach':[],
            'requirement_findings':[finding('R')]})
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', review)
    first = promote(engine, review='codex')
    def no_repeat(*args, **kwargs):
        raise AssertionError('review retry must use the actual saved execution')
    monkeypatch.setattr(engine, 'evaluate_commit', no_repeat)
    second = promote(engine, review='codex')
    assert first['complete'] and second['complete']
    assert originals[0] == originals[1]
    assert first['task_results']['formal_evaluation'] == second['task_results']['formal_evaluation']


def test_overall_accept_cannot_cover_omitted_required_item(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    from opc.observer.adapter import ObserverAdapter
    root = make_project(tsk=task(acceptance={}, requirements=[
        dict(id='REQ-1', text='Decide whether universal speedup holds', verification='review'),
        dict(id='REQ-2', text='Explain the boundary', verification='review')]))
    e = use_sequence(engine_for(root), Sequence([stop]))
    e.run()
    calls = []
    def reviewer(*args):
        calls.append(args)
        return dict(ok=True, verdict='accept', requirement_findings=[finding('REQ-1')])
    monkeypatch.setattr('opc.core.promote.run_reviewer', reviewer)
    report = promote(e, review='codex')
    assert not report['complete'] and len(calls) == 1
    rows = {r['id']: r for r in report['requirements']}
    assert rows['REQ-1']['status'] == 'met_by_review'
    assert rows['REQ-2']['status'] == 'not_covered'
    assert rows['REQ-2']['gap']
    assert {r['id'] for r in calls[0][-2]} == {'REQ-1', 'REQ-2'}
    observer = ObserverAdapter(root)
    observed = observer.run(observer._id('run', e.run_id))['data']['requirements']
    assert {r['id']: r['result'] for r in observed} == {'REQ-1': 'met', 'REQ-2': 'not_covered'}
    assert rows['REQ-2']['gap'] in (Path(report['report_dir']) / 'PROMOTION.md').read_text()


def test_optional_missing_and_empty_evidence_do_not_gain_required_coverage(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    root = make_project(tsk=task(acceptance={}, requirements=[
        dict(id='R', text='Core explanation', verification='review'),
        dict(id='O', text='Optional discussion', verification='review', required=False)]))
    e = use_sequence(engine_for(root), Sequence([stop]))
    e.run()
    answers = iter([
        dict(ok=True, verdict='accept', requirement_findings=[finding('R', evidence=[])]),
        dict(ok=True, verdict='accept', requirement_findings=[finding('R')])])
    monkeypatch.setattr('opc.core.promote.run_reviewer', lambda *a: next(answers))
    first = promote(e, review='codex')
    assert not first['complete']
    assert first['requirements'][0]['status'] == 'insufficient_evidence'
    assert first['requirements'][1]['status'] == 'not_covered'
    second = promote(e, review='codex')
    assert second['complete']
    assert second['requirements'][1]['status'] == 'not_covered'


@pytest.mark.parametrize('bound, judgment', [(1, 'met'), (20, 'not_met')])
def test_review_judgments_cannot_replace_program_checks_or_hide_blockers(make_project, engine_for, monkeypatch, bound, judgment):
    from opc.core.promote import promote
    root = make_project(tsk=task(acceptance={}, requirements=[
        dict(id='AUTO', text='Measured loss bound', verification='automated',
             check=dict(metric='loss', op='<=', value=bound)),
        dict(id='BOTH', text='Measured bound and explanation', verification='review',
             check=dict(metric='loss', op='<=', value=bound))]))
    e = use_sequence(engine_for(root), Sequence([stop]))
    e.run()
    monkeypatch.setattr('opc.core.promote.run_reviewer', lambda *a: dict(ok=True, verdict='accept',
        requirement_findings=[finding('AUTO', status=judgment, gap='Semantic blocker' if judgment != 'met' else ''), finding('BOTH')]))
    report = promote(e, review='codex')
    assert not report['complete']
    if bound == 1:
        assert all(r['status'].startswith('not_met') for r in report['requirements'])
    else:
        assert report['requirements'][0]['status'] == 'not_met'
        assert report['requirements'][0]['automated_status'] == 'met'
        assert report['requirements'][1]['status'] == 'met_by_review'


def test_negative_answer_can_pass_only_after_required_boundary_is_covered(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    from opc.tests.test_delivery_candidates import claim
    from opc.tests.test_task_delivery_intent import request
    root = make_project(tsk=task(acceptance={}, requirements=[
        dict(id='TRUTH', text='Determine whether copying universally helps', verification='review'),
        dict(id='BOUNDARY', text='Explain short-field boundary; core uncertainty blocks delivery', verification='review')]))
    e = use_sequence(engine_for(root), Sequence([lambda ctx: dict(request(ctx),
        claims=[dict(claim(), status='refuted', reason='Valid short-field counterexample')],
        delivery_claims=[dict(claim_id='copy', version=1)])]))
    e.run()
    captured = []
    def reviewer(*args):
        captured.append(args[-1])
        return dict(ok=True, verdict='accept', requirement_findings=[
            finding('TRUTH', evidence=['copy v1 is refuted by valid counterexample']),
            finding('BOUNDARY', status='insufficient_evidence', evidence=[], gap='Boundary explanation is missing')])
    monkeypatch.setattr('opc.core.promote.run_reviewer', reviewer)
    missing = promote(e, review='codex')
    assert not missing['complete']
    assert captured[-1]['claims'][0]['status'] == 'refuted'
    # Explicit claim revision supplies the missing explanation, retaining the negative answer.
    later = use_sequence(engine_for(root), Sequence([lambda ctx: dict(request(ctx),
        claims=[dict(claim(), base_version=1, status='refuted', reason='Copy setup dominates short fields; long fields amortize setup', unresolved=[])],
        delivery_claims=[dict(claim_id='copy', version=2)])]))
    later.run(new_run=True)
    def complete(*args):
        assert args[-1]['claims'][0]['version'] == 2
        assert args[-1]['claims'][0]['unresolved'] == []
        return dict(ok=True, verdict='accept', requirement_findings=[finding('TRUTH'), finding('BOUNDARY')])
    monkeypatch.setattr('opc.core.promote.run_reviewer', complete)
    accepted = promote(later, source_run=later.run_id, review='codex')
    assert accepted['complete']
    assert all(r['status'] == 'met_by_review' for r in accepted['requirements'])


def test_call_failures_and_completed_negative_judgments_keep_distinct_facts(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    root = make_project(tsk=task(acceptance={}, requirements=[
        dict(id='R', text='Required explanation', verification='review')]))
    e = use_sequence(engine_for(root), Sequence([stop]))
    e.run()
    answers = iter([
        dict(ok=False, error='Provider unavailable'),
        dict(ok=True, verdict='accept', requirement_findings=['unstructured old response']),
        dict(ok=True, verdict='accept', requirement_findings=[finding('R', status='not_met', gap='Explanation contradicts evidence')]),
        dict(ok=True, verdict='accept', requirement_findings=[finding('R', status='insufficient_evidence', evidence=[], gap='Original measurement is missing')]),
        dict(ok=True, verdict='accept', requirement_findings=[finding('R', status='not_covered', evidence=[], gap='')])])
    monkeypatch.setattr('opc.core.promote.run_reviewer', lambda *a: next(answers))
    reports = [promote(e, review='codex') for _ in range(5)]
    assert all(not r['complete'] for r in reports)
    assert [r['requirements'][0]['status'] for r in reports] == ['not_covered', 'not_covered', 'not_met', 'insufficient_evidence', 'not_covered']
    assert [r['reviewer']['ok'] for r in reports] == [False, False, True, True, False]
    assert 'invalid reviewer output' in reports[1]['reviewer']['error']
    assert len({r['report_dir'] for r in reports}) == 5
    assert 'evidence or a concrete gap' in reports[-1]['reviewer']['error']
    assert all(r['candidate'] == reports[0]['candidate'] for r in reports)
    assert e.attempt_records() == []
    assert len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'evaluator']) == 1


def test_dsh_review_receives_json_shape_and_covers_multiple_items_once(make_project, engine_for, tmp_path):
    import json
    from opc.core.promote import promote, run_reviewer
    script = tmp_path / 'reviewer.py'
    script.write_text('''import json, os, sys
prompt = sys.stdin.read()
assert os.environ['DSH_PERMISSION_MODE'] == 'read-only'
assert 'Return only JSON' in prompt
assert all(field in prompt for field in ('requirement_findings', 'insufficient_evidence', 'not_covered', '"evidence"', '"gap"'))
reply = dict(verdict='accept', summary='Both scoped requirements covered', overreach=[],
    requirement_findings=[dict(id=ident, status='met', evidence=['Selected commit and supplied observations'], gap='') for ident in ('R1','R2')])
def emit(**data): print(json.dumps(data), flush=True)
emit(type='session', sessionId='fresh-review-context')
emit(type='status', phase='step_end', usage=dict(inputTokens=5, outputTokens=2))
emit(type='status', phase='turn_end', reason=dict(kind='completed'))
emit(type='final', text=json.dumps(reply))
''')
    contract = task(acceptance={}, requirements=[
        dict(id='R1', text='One requirement', verification='review'),
        dict(id='R2', text='Another requirement', verification='review')])
    root = make_project(tsk=contract)
    (root / '.opc/local').mkdir(exist_ok=True)
    (root / '.opc/local/workers.json').write_text(json.dumps(dict(
        reviewer=dict(kind='dsh', binary=str(script), model='fixture', provider='fixture'))))
    e = use_sequence(engine_for(root), Sequence([stop]))
    e.run()
    report = promote(e, review='dsh')
    assert report['complete']
    calls = [c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']
    assert len(calls) == 1 and calls[0]['session_id'] == 'fresh-review-context'
    assert calls[0]['input']['candidate'] == report['candidate']
    assert calls[0]['result']['cost']['tokens'] == 7
    used = e.ledger.totals(e.run_id)
    selected = dict(commit_sha=report['selected_version'], metrics=dict(values=report['selected_metrics']))
    replay = run_reviewer(e, 'dsh', Path(report['report_dir']), '', selected, selected, report['requirements'], report['task_results'])
    assert replay['call_id'] == calls[0]['call_id']
    assert len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']) == 1
    assert e.ledger.totals(e.run_id) == used


def test_requirement_ids_must_identify_unambiguous_review_scope(make_project, engine_for):
    import json
    import pytest
    from opc.core.model import OPCError
    root = make_project(tsk=task(acceptance={}, requirements=[dict(text='Missing identity', verification='review')]))
    with pytest.raises(OPCError, match='unique nonempty IDs'):
        engine_for(root)
    path = root / '.opc/tasks/t-toy/revisions/r0001/task.json'
    raw = json.loads(path.read_text())
    raw['requirements'] = [dict(id='R', text='First'), dict(id='R', text='Ambiguous second')]
    path.write_text(json.dumps(raw))
    with pytest.raises(OPCError, match='unique nonempty IDs'):
        engine_for(root)


@pytest.mark.parametrize('availability', ['missing', 'truncated'])
def test_missing_or_truncated_necessary_originals_remain_insufficient(make_project, engine_for, monkeypatch, availability):
    from opc.core.promote import promote
    from opc.tests.conftest import component
    from opc.tests.test_research_loop import plan
    from opc.tests.test_delivery_candidates import claim
    from opc.tests.test_task_delivery_intent import request
    class Evidence(Sequence):
        def implement(self, p, ctx, tree, log_dir):
            call = super().implement(p, ctx, tree, log_dir)
            (tree / 'raw').mkdir()
            (tree / 'raw/proof.txt').write_text('Observed proof: ' + 'x' * 9000)
            return call
    root = make_project(tsk=task(acceptance={}, requirements=[dict(
        id='PROOF', text='Necessary proof must be available in full', verification='review')]),
        comp=component(scratch=['raw/**']))
    def select(ctx):
        return dict(request(ctx), claims=[dict(claim(), evidence=[dict(
            run_id=e.run_id, attempt=1, artifact='outputs/raw/proof.txt')])],
            delivery_claims=[dict(claim_id='copy', version=1)])
    e = use_sequence(engine_for(root), Evidence([plan(1, deliverables=['raw/proof.txt']), select], [4]))
    e.run()
    if availability == 'missing':
        (e.attempt_dir(1) / 'outputs/raw/proof.txt').unlink()
    seen = []
    def reviewer(*args):
        supplied = args[-1]
        seen.append(supplied)
        assert supplied['issues']
        source = supplied['sources'][0]
        assert source['availability'] == 'missing' if availability == 'missing' else source['omitted']
        return dict(ok=True, verdict='accept', requirement_findings=[finding(
            'PROOF', status='insufficient_evidence', evidence=[], gap='Necessary original is ' + availability)])
    monkeypatch.setattr('opc.core.promote.run_reviewer', reviewer)
    report = promote(e, review='codex')
    assert not report['complete'] and len(seen) == 1
    assert report['requirements'][0]['status'] == 'insufficient_evidence'
