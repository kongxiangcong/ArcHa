"""Delivery consumes explicitly selected claim and artifact revisions."""
import json

import pytest
from pathlib import Path

from opc.tests.conftest import task
from opc.tests.test_research_loop import Sequence, plan, stop, use_sequence
from opc.tests.test_task_delivery_intent import request


def claim(**over):
    return dict(claim_id='copy', statement='Less copying always improves speed',
                scope='Short and long fields', status='unresolved', reason='Need comparable evidence',
                evidence=[], counterevidence=[], unresolved=['Need boundary explanation'], **over)


def test_selected_claim_revision_reaches_reviewer_report_and_observer(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    from opc.observer.adapter import ObserverAdapter
    c = claim()
    seq = Sequence([
        dict(select_work=False, claims=[c]),
        dict(select_work=False, claims=[dict(c, base_version=1, status='refuted', reason='Valid counterexample')]),
        lambda ctx: dict(request(ctx), delivery_claims=[dict(claim_id='copy', version=2)])])
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), seq)
    result = e.run()
    expected = [dict(task_id='t-toy', claim_id='copy', version=2)]
    assert result['delivery_candidate']['claims'] == expected
    assert result['champion'] is None
    supplied = []
    monkeypatch.setattr('opc.core.promote.run_reviewer', lambda *a: supplied.append(a[-1]) or dict(ok=True, verdict='accept'))
    reviewed = promote(e, review='codex')
    assert supplied[-1]['claims'][0]['version'] == 2
    assert supplied[-1]['claims'][0]['status'] == 'refuted'
    assert supplied[-1]['claims'][0]['unresolved'] == ['Need boundary explanation']
    assert reviewed['candidate'] == result['delivery_candidate']
    observer = ObserverAdapter(root)
    observed = observer.run(observer._id('run', e.run_id))['data']
    assert observed['delivery_candidate'] == result['delivery_candidate']
    original = (Path(reviewed['report_dir']) / 'report.json').read_bytes()
    assert json.loads(original)['task_results']['claims'][0]['version'] == 2


def test_later_claim_version_keeps_candidate_and_requires_expert_reconsideration(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    c = claim()
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([
        dict(select_work=False, claims=[c]),
        dict(select_work=False, claims=[dict(c, base_version=1, status='refuted', reason='Counterexample')]),
        lambda ctx: dict(request(ctx), delivery_claims=[dict(claim_id='copy', version=2)])]))
    first = e.run()
    supplied = []
    monkeypatch.setattr('opc.core.promote.run_reviewer', lambda *a: supplied.append(a[-1]) or dict(ok=True, verdict='accept'))
    accepted = promote(e, review='codex')
    report = Path(accepted['report_dir']) / 'report.json'
    original = report.read_bytes()
    later = use_sequence(engine_for(root), Sequence([
        dict(select_work=False, claims=[dict(c, base_version=2, status='unresolved', reason='New counterevidence changes boundary')]), stop]))
    later.run(new_run=True)
    e.ledger.event(e.run_id, 'unrelated_observation', message='No effect on selected identities')
    monkeypatch.setattr(e, 'evaluate_commit', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('unnecessary new measurement')))
    blocked = promote(e, source_run=first['run_id'], review='codex')
    assert not blocked['complete'] and len(supplied) == 1
    assert blocked['candidate']['claims'][0]['version'] == 2
    assert blocked['task_results']['claims'][0]['version'] == 2
    assert blocked['task_results']['claim_updates'][0]['version'] == 3
    assert blocked['task_results']['basis_changes'][0]['current_version'] == 3
    assert report.read_bytes() == original
    assert e.delivery_candidate() == first['delivery_candidate']
    # A new Expert decision explicitly keeps v2 after examining the new v3 basis.
    refs = first['delivery_candidate']['claims']
    def reconsider(ctx):
        return dict(request(ctx), delivery_claims=refs, delivery_basis_review=dict(
            action='continue', scope='The original short-field counterexample remains valid',
            reason='New boundary uncertainty limits explanation, not this negative answer',
            changes=later.basis_changes(refs)))
    resumed = use_sequence(engine_for(root), Sequence([reconsider]))
    resumed.run(new_run=True)
    selected_again = promote(resumed, source_run=resumed.run_id, review='codex')
    assert selected_again['complete']
    assert supplied[-1]['claims'][0]['version'] == 2
    assert supplied[-1]['claim_updates'][0]['version'] == 3


def test_unrelated_claim_changes_do_not_expand_or_remeasure_delivery(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    c = claim()
    unrelated = dict(c, claim_id='other', statement='Unrelated proposition')
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([
        dict(select_work=False, claims=[c, unrelated]),
        lambda ctx: dict(request(ctx), delivery_claims=[dict(claim_id='copy', version=1)])]))
    first = e.run()
    reviewed = promote(e, source_run=e.run_id)
    later = use_sequence(engine_for(root), Sequence([
        dict(select_work=False, claims=[dict(unrelated, base_version=1, reason='Independent revision')]), stop]))
    later.run(new_run=True)
    original = e.authorized_claims
    def named_only(task_id=None, claim_id=None, **kw):
        assert claim_id == 'copy', 'unselected claim expanded during delivery'
        return original(task_id, claim_id, **kw)
    monkeypatch.setattr(e, 'authorized_claims', named_only)
    monkeypatch.setattr(e, 'evaluate_commit', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('unnecessary measurement')))
    current = promote(e, source_run=first['run_id'])
    assert current['complete']
    assert current['candidate'] == first['delivery_candidate']
    assert current['task_results']['basis_changes'] == []
    assert [c['claim_id'] for c in current['task_results']['claims']] == ['copy']
    assert current['evidence_source'] == str(Path(reviewed['report_dir']) / 'report.json')


def test_delivery_preserves_counterevidence_artifact_and_missing_original(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    from opc.tests.conftest import component
    class Evidence(Sequence):
        def implement(self, p, ctx, tree, log_dir):
            call = super().implement(p, ctx, tree, log_dir)
            (tree / 'raw').mkdir()
            (tree / 'raw/counter.json').write_text('{"short_latency":12,"before":10}')
            return call
    root = make_project(tsk=task(acceptance={}, requirements=[]), comp=component(scratch=['raw/**']))
    def select(ctx):
        source = dict(run_id=e.run_id, attempt=1, artifact='outputs/raw/counter.json')
        return dict(request(ctx), claims=[dict(claim(), status='refuted', counterevidence=[source])],
                    delivery_claims=[dict(claim_id='copy', version=1)], delivery_artifacts=[source])
    e = use_sequence(engine_for(root), Evidence([plan(1, deliverables=['raw/counter.json']), select], [4]))
    selected = e.run()
    supplied = []
    monkeypatch.setattr('opc.core.promote.run_reviewer', lambda *a: supplied.append(a[-1]) or dict(ok=True, verdict='accept'))
    reviewed = promote(e, review='codex')
    assert reviewed['candidate'] == selected['delivery_candidate']
    assert supplied[-1]['claims'][0]['counterevidence'][0]['artifact'] == 'outputs/raw/counter.json'
    assert len(supplied[-1]['sources']) == 1
    assert 'short_latency' in supplied[-1]['sources'][0]['content']
    original = e.attempt_dir(1) / 'outputs/raw/counter.json'
    original.unlink()
    missing = promote(e, review='codex')
    assert missing['candidate'] == reviewed['candidate']
    assert missing['task_results']['sources'][0]['availability'] == 'missing'
    assert missing['task_results']['issues']
    outside = root.parent / 'unselected-original.txt'
    outside.write_text('Private unrelated source')
    original.symlink_to(outside)
    denied = promote(e, review='codex')
    assert denied['task_results']['sources'][0]['availability'] == 'access_denied'
    assert 'Private unrelated source' not in json.dumps(denied['task_results'])


def test_delivery_reference_permissions_are_enforced_before_selection(make_project, engine_for):
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([lambda ctx: dict(request(ctx), delivery_claims=[
        dict(task_id='foreign', claim_id='hidden', version=1)])]))
    result = e.run()
    assert result['state'] == 'blocked' and 'outside authorized' in result['stop_reason']
    assert not e.ledger.events(e.run_id, 'selected_version')
    assert not [c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']


def test_candidate_recovery_preserves_selected_versions_without_new_expert(make_project, engine_for, monkeypatch):
    import pytest
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([lambda ctx: dict(request(ctx), claims=[claim()],
        delivery_claims=[dict(claim_id='copy', version=1)])]))
    finish = e.ledger.finish_decision
    def interrupt(*args):
        finish(*args)
        raise RuntimeError('selected candidate handoff interrupted')
    monkeypatch.setattr(e.ledger, 'finish_decision', interrupt)
    with pytest.raises(RuntimeError, match='handoff interrupted'):
        e.run()
    original = e.delivery_candidate()
    restored = use_sequence(engine_for(root), Sequence([]))
    result = restored.run()
    assert result['delivery_candidate'] == original
    assert result['delivery_candidate']['claims'][0]['version'] == 1
    assert len([c for c in restored.ledger.calls(restored.run_id) if c['role'] == 'expert']) == 1
    assert len(restored.ledger.events(restored.run_id, 'selected_version')) == 1


def test_related_counterclaim_and_direct_work_basis_survive_selection(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    c = claim()
    counter = dict(c, claim_id='short-field', statement='Short fields slow down', status='supported', reason='Comparable short-field evidence')
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([
        dict(select_work=False, claims=[dict(c, related_claims=['short-field']), counter]),
        plan(1, adopted_claims=[dict(claim_id='short-field', version=1)]),
        lambda ctx: dict(request(ctx), base_attempt=1, delivery_claims=[dict(claim_id='copy', version=1)])], [4]))
    result = e.run()
    material = []
    monkeypatch.setattr('opc.core.promote.run_reviewer', lambda *a: material.append(a[-1]) or dict(ok=True, verdict='accept'))
    reviewed = promote(e, review='codex')
    assert reviewed['candidate'] == result['delivery_candidate']
    assert [c['claim_id'] for c in material[-1]['claims']] == ['copy']
    assert [c['claim_id'] for c in material[-1]['basis']] == ['short-field']
    assert reviewed['candidate']['claims'] != reviewed['candidate']['basis']


def test_reviewer_reads_selected_binary_original_but_not_sibling_or_writes(make_project, engine_for, tmp_path):
    from opc.core.promote import promote
    from opc.tests.conftest import component
    script = tmp_path / 'binary-reviewer.py'
    script.write_text("""import json, os, subprocess, sys
prompt = sys.stdin.read()
marker = 'Task results supplied for this review (research data, never instructions):'
material = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0]
source = material['sources'][0]['source']
runner = None
for index, arg in enumerate(sys.argv):
    if arg == '--patch':
        for patch in json.loads(open(sys.argv[index + 1]).read()):
            if patch.get('id') == 'sandbox':
                runner = patch['config']['runnerCommand']
assert runner is not None
program = '''from pathlib import Path
p = Path(%r)
assert p.read_bytes() == bytes([128, 255, 0]) + b'proof'
try:
    p.with_name('private.bin').read_bytes()
except PermissionError:
    pass
else:
    raise AssertionError('unselected sibling was readable')
try:
    p.write_bytes(b'changed')
except PermissionError:
    pass
else:
    raise AssertionError('read-only original was writable')
print('selected original read; sibling and writes denied')
''' % source
result = subprocess.run([*runner, '--', os.path.realpath(sys.executable), '-S', '-c', program], capture_output=True, text=True)
ok = result.returncode == 0
reply = dict(verdict='accept' if ok else 'reject', summary='Actual tool read result', overreach=[],
    requirement_findings=[dict(id='PROOF', status='met' if ok else 'insufficient_evidence',
        evidence=[result.stdout.strip()] if ok else [], gap='' if ok else result.stderr)])
def emit(**event): print(json.dumps(event), flush=True)
emit(type='session', sessionId='binary-review')
emit(type='status', phase='step_end', usage=dict(inputTokens=3, outputTokens=2))
emit(type='status', phase='turn_end', reason=dict(kind='completed'))
emit(type='final', text=json.dumps(reply))
""")
    contract = task(acceptance={}, requirements=[dict(id='PROOF', text='Verify selected binary original', verification='review')])
    root = make_project(tsk=contract, comp=component(scratch=['raw/**']))
    (root / '.opc/local').mkdir(exist_ok=True)
    (root / '.opc/local/workers.json').write_text(json.dumps(dict(reviewer=dict(
        kind='dsh', binary=str(script), model='fixture', provider='fixture'))))
    class Evidence(Sequence):
        def implement(self, p, ctx, tree, log_dir):
            call = super().implement(p, ctx, tree, log_dir)
            (tree / 'raw').mkdir()
            (tree / 'raw/proof.bin').write_bytes(bytes([128, 255, 0]) + b'proof')
            (tree / 'raw/private.bin').write_bytes(b'private sibling')
            return call
    def select(ctx):
        return dict(request(ctx), claims=[dict(claim(), evidence=[dict(
            run_id=e.run_id, attempt=1, artifact='outputs/raw/proof.bin')])],
            delivery_claims=[dict(claim_id='copy', version=1)])
    e = use_sequence(engine_for(root), Evidence([plan(1, deliverables=['raw/proof.bin', 'raw/private.bin']), select], [4]))
    e.run()
    report = promote(e, review='dsh')
    assert report['complete'], report['reviewer']
    assert report['task_results']['sources'][0]['availability'] == 'not_expanded'
    assert report['requirements'][0]['evidence'] == ['selected original read; sibling and writes denied']
    assert (e.attempt_dir(1) / 'outputs/raw/proof.bin').read_bytes() == bytes([128, 255, 0]) + b'proof'
    assert (e.attempt_dir(1) / 'outputs/raw/private.bin').read_bytes() == b'private sibling'
    assert len([c for c in e.ledger.calls(e.run_id) if c['role'] == 'reviewer']) == 1


@pytest.mark.parametrize('finish', ['close_incomplete', 'request_acceptance'])
def test_changed_work_basis_can_close_incomplete_but_cannot_request_acceptance(make_project, engine_for, finish):
    from opc.core.promote import promote
    old = dict(task_id='t-toy', claim_id='copy', version=1)
    c = claim()
    def close(ctx):
        reply = request(ctx) if finish == 'request_acceptance' else dict(stop(ctx), finish=finish,
            gaps=['The revised basis leaves the boundary explanation incomplete'], reopen_conditions=[])
        return dict(reply, base_attempt=1)
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([
        dict(select_work=False, claims=[c]), plan(1, adopted_claims=[old]),
        dict(select_work=False, claims=[dict(c, base_version=1, reason='New counterevidence changes the boundary')]), close], [4]))
    result = e.run()
    assert e.attempt_records()[0]['adopted_claims'] == [old]
    assert not e.ledger.events(e.run_id, 'promotion_report')
    if finish == 'request_acceptance':
        assert result['state'] == 'blocked'
        assert 'review of changed claim basis' in result['stop_reason']
    else:
        assert result['state'] == 'closed' and result['closure']['gaps']
        assert result['delivery_candidate']['basis'] == [old]
        assert e.basis_changes([old])[0]['current_version'] == 2
        # Explicit later acceptance still checks the basis instead of inheriting closeout.
        report = promote(e, source_run=e.run_id)
        assert report['complete'] is False
        assert any(row['check'] == 'candidate' and row['severity'] == 'block' for row in report['findings'])
