"""Standards-only reassessment and read-only acceptance history; no model service."""
import json
from pathlib import Path

import pytest

from opc.core.engine import Engine
from opc.core.model import OPCError
from opc.core.promote import promote
from opc.observer.adapter import ObserverAdapter
from opc.tests.conftest import EVALUATE, task, write
from opc.tests.test_research_loop import Sequence, plan, stop, use_sequence


def test_target_reassessment_records_revision_history_without_repeating_work(make_project, engine_for):
    t = task(requirements=[])
    t['acceptance']['target']['value'] = 90
    evaluate = EVALUATE.replace('(x - 7) ** 2 + 1', '100 if x == 3 else 94')
    root = make_project(tsk=t, evaluate=evaluate)
    e = use_sequence(engine_for(root), Sequence([plan(1), stop], [4]))
    result = e.run()
    first = promote(e)
    assert first['complete'] is False and first['selected_metrics']['loss'] == 94
    old_report = Path(first['report_dir']) / 'report.json'
    original = old_report.read_bytes()
    original_markdown = (old_report.parent / 'PROMOTION.md').read_bytes()
    calls = len(e.ledger.calls(e.run_id))
    runs = len(e.ledger.runs())
    spent = e.spent()

    new = json.loads(json.dumps(t))
    new['revision'] = 'r0002'
    new['acceptance']['target']['value'] = 95
    write(root / '.opc/tasks/t-toy/revisions/r0002/task.json', json.dumps(new))
    later = dict(new, revision='r0003')
    write(root / '.opc/tasks/t-toy/revisions/r0003/task.json', json.dumps(later))
    observer = ObserverAdapter(root)
    before = e.ledger.path.read_bytes()
    pending = observer.run(observer._id('run', e.run_id))['data']['acceptance_history']
    assert [(r['revision'], r['status']) for r in pending] == [
        ('r0001', 'failed'), ('r0002', 'not_evaluated'), ('r0003', 'not_evaluated')]
    assert e.ledger.path.read_bytes() == before
    revised = Engine(root, 't-toy', 'r0002', log=lambda _: None)
    with pytest.raises(OPCError, match='confirmation'):
        promote(revised, source_run=e.run_id)
    receipt = root / 'confirmation.json'
    receipt.write_text(json.dumps(dict(confirmed_by='user', source_run=e.run_id,
        from_revision='r0001', to_revision='r0002', changes={
            'acceptance': {'old': t['acceptance'], 'new': new['acceptance']}})))
    passed = promote(revised, source_run=e.run_id, standards_confirmation=receipt)
    assert passed['complete'] is True and passed['reassessed'] is True
    assert passed['evidence_source'] == str(old_report)
    assert passed['execution_revision'] == 'r0001' and passed['acceptance_revision'] == 'r0002'
    history = passed['acceptance_history']
    assert [(r['revision'], r['status']) for r in history] == [
        ('r0001', 'failed'), ('r0002', 'passed'), ('r0003', 'not_evaluated')]
    assert history[1]['selected_version'] == result['selected_version']
    document = (Path(passed['report_dir']) / 'PROMOTION.md').read_text()
    assert '## Acceptance revision history' in document and '| r0003 |' in document
    assert 'not_evaluated' in document and 'report.json' in document
    assert len(e.ledger.calls(e.run_id)) == calls and len(e.ledger.runs()) == runs
    assert e.spent() == spent
    assert old_report.read_bytes() == original
    assert (old_report.parent / 'PROMOTION.md').read_bytes() == original_markdown

    # Another report for the same standard replaces only the table's latest link.
    again = promote(revised, source_run=e.run_id, standards_confirmation=receipt)
    assert again['acceptance_history'][1]['report_path'] == str(Path(again['report_dir']) / 'report.json')
    assert Path(passed['report_dir']).is_dir()
    before = e.ledger.path.read_bytes()
    observed = observer.run(observer._id('run', e.run_id))['data']['acceptance_history']
    assert observed[1]['report_path'] == again['acceptance_history'][1]['report_path']
    assert e.ledger.path.read_bytes() == before
    assert len(e.ledger.calls(e.run_id)) == calls

    # The same Task's different selected candidate cannot inherit 94 ms evidence.
    e.ledger.event(e.run_id, 'selected_version', commit=result['baseline'])
    changed = promote(revised, source_run=e.run_id, standards_confirmation=receipt)
    assert changed['complete'] is False and changed['selected_metrics']['loss'] == 100
    assert changed['evidence_source'] is None
    assert changed['acceptance_history'][1]['selected_version'] == result['baseline']
    assert len(e.ledger.calls(e.run_id)) == calls + 1


def test_reassessed_revision_cannot_be_overwritten_or_inherit_old_acceptance(make_project, engine_for):
    from opc.core.config import TaskSpec
    t = task(requirements=[])
    root = make_project(tsk=t)
    e = use_sequence(engine_for(root), Sequence([stop]))
    e.run()
    promote(e)
    new = json.loads(json.dumps(t))
    new['revision'] = 'r0002'
    new['acceptance']['target']['value'] = 17
    path = root / '.opc/tasks/t-toy/revisions/r0002/task.json'
    write(path, json.dumps(new))
    receipt = root / 'confirmation.json'
    confirmation = dict(confirmed_by='user', source_run=e.run_id, from_revision='r0001', to_revision='r0002',
                        changes={'acceptance': {'old': t['acceptance'], 'new': new['acceptance']}})
    receipt.write_text(json.dumps(confirmation))
    passed = promote(Engine(root, 't-toy', 'r0002'), source_run=e.run_id, standards_confirmation=receipt)
    assert passed['complete']
    original = path.read_bytes()
    calls = len(e.ledger.calls(e.run_id))
    changed = json.loads(json.dumps(new))
    changed['acceptance']['target']['value'] = 18
    path.write_text(json.dumps(changed))
    confirmation['changes']['acceptance']['new'] = changed['acceptance']
    receipt.write_text(json.dumps(confirmation))
    observed = ObserverAdapter(root)
    history = observed.run(observed._id('run', e.run_id))['data']['acceptance_history']
    assert history[1]['status'] == 'not_evaluated'
    assert 'differs' in history[1]['reason']
    with pytest.raises(OPCError, match='frozen acceptance revision.*new revision'):
        promote(Engine(root, 't-toy', 'r0002'), source_run=e.run_id, standards_confirmation=receipt)
    path.write_bytes(original)
    saved = TaskSpec.save_revision(root, 't-toy', 'r0002', changed)
    assert saved.revision == 'r0003' and path.read_bytes() == original
    assert len(e.ledger.calls(e.run_id)) == calls
    assert len(e.ledger.runs()) == 1


@pytest.mark.parametrize('change', ['goal', 'objective', 'input', 'evaluator'])
def test_standards_reassessment_rejects_execution_changes_before_dispatch(make_project, engine_for, change):
    t = task(requirements=[])
    root = make_project(tsk=t)
    e = use_sequence(engine_for(root), Sequence([stop]))
    e.run()
    promote(e)
    calls = len(e.ledger.calls(e.run_id))
    new = json.loads(json.dumps(t))
    new['revision'] = 'r0002'
    new['acceptance']['target']['value'] = 17
    if change == 'goal':
        new['goal'] = 'different work'
    elif change == 'objective':
        new['acceptance']['objective']['direction'] = 'maximize'
    else:
        comp_path = root / '.opc/components/toy.json'
        comp = json.loads(comp_path.read_text())
        if change == 'input':
            comp['gates'][0]['env'] = {'EXPERIMENT_INPUT': 'different'}
        else:
            comp['gates'][0]['argv'].append('--different-evaluator-mode')
        comp_path.write_text(json.dumps(comp))
    write(root / '.opc/tasks/t-toy/revisions/r0002/task.json', json.dumps(new))
    receipt = root / 'confirmation.json'
    receipt.write_text(json.dumps(dict(confirmed_by='user', source_run=e.run_id,
        from_revision='r0001', to_revision='r0002', changes={
            'acceptance': {'old': t['acceptance'], 'new': new['acceptance']}})))
    with pytest.raises(OPCError, match='cannot change execution'):
        promote(Engine(root, 't-toy', 'r0002'), source_run=e.run_id, standards_confirmation=receipt)
    assert len(e.ledger.calls(e.run_id)) == calls and len(e.ledger.runs()) == 1


def test_history_distinguishes_claim_versions_with_the_same_code_commit(make_project, engine_for):
    from opc.tests.test_delivery_candidates import claim
    from opc.tests.test_task_delivery_intent import request

    c = claim()
    root = make_project(tsk=task(acceptance={}, requirements=[]))
    first = use_sequence(engine_for(root), Sequence([
        dict(select_work=False, claims=[c]),
        dict(select_work=False, claims=[dict(c, base_version=1, status='refuted', reason='Valid counterexample')]),
        lambda ctx: dict(request(ctx), delivery_claims=[dict(claim_id='copy', version=2)])]))
    selected_v2 = first.run()
    report_v2 = promote(first)
    path_v2 = Path(report_v2['report_dir']) / 'report.json'
    original = path_v2.read_bytes()
    assert report_v2['acceptance_history'][0]['candidate'] == selected_v2['delivery_candidate']

    second = use_sequence(engine_for(root), Sequence([
        dict(select_work=False, claims=[dict(c, base_version=2, status='refuted', reason='Boundary explanation clarified')]),
        lambda ctx: dict(request(ctx), delivery_claims=[dict(claim_id='copy', version=3)])]))
    selected_v3 = second.run(new_run=True)
    report_v3 = promote(second, source_run=second.run_id)
    assert selected_v2['selected_version'] == selected_v3['selected_version']
    history = report_v3['acceptance_history'][0]
    assert history['candidate'] == selected_v3['delivery_candidate']
    assert history['candidate']['claims'][0]['version'] == 3
    assert history['report_path'] == str(Path(report_v3['report_dir']) / 'report.json')
    document_v2 = (path_v2.parent / 'PROMOTION.md').read_text().split('## Acceptance revision history')[1]
    document_v3 = (Path(report_v3['report_dir']) / 'PROMOTION.md').read_text().split('## Acceptance revision history')[1]
    assert 't-toy/copy/v2' in document_v2 and 't-toy/copy/v3' in document_v3
    assert path_v2.read_bytes() == original
    calls = len(second.ledger.calls(second.run_id))
    before = second.ledger.path.read_bytes()
    observer = ObserverAdapter(root)
    observed = observer.run(observer._id('run', second.run_id))['data']['acceptance_history'][0]
    assert observed['candidate'] == history['candidate']
    assert second.ledger.path.read_bytes() == before and len(second.ledger.calls(second.run_id)) == calls


def test_same_acceptance_source_allows_new_run_with_different_local_budget(make_project, engine_for):
    contract = task(requirements=[])
    root = make_project(tsk=contract)
    source_path = root / '.opc/tasks/t-toy/revisions/r0001/task.json'
    original_contract = source_path.read_bytes()
    settings = root / '.opc/local/workers.json'
    write(settings, json.dumps(dict(budget=dict(max_wall_seconds=300))))
    first = use_sequence(engine_for(root), Sequence([plan(1), stop], [7]))
    first.run()
    accepted = promote(first, source_run=first.run_id)
    assert accepted['complete'] and accepted['selected_metrics']['loss'] == 1
    old_report = Path(accepted['report_dir']) / 'report.json'
    old_bytes = old_report.read_bytes()
    old_markdown = (old_report.parent / 'PROMOTION.md').read_bytes()
    write(settings, json.dumps(dict(budget=dict(max_wall_seconds=400))))
    later = use_sequence(engine_for(root), Sequence([stop]))
    result = later.run(new_run=True)
    assert result['run_id'] != first.run_id
    assert later.task.digest != first.task.digest
    assert source_path.read_bytes() == original_contract
    assert later.ledger.events(later.run_id, 'promotion_report') == []
    failed = promote(later, source_run=later.run_id)
    assert not failed['complete'] and failed['selected_metrics']['loss'] == 17
    assert failed['evidence_source'] is None
    assert failed['acceptance_source_digest'] == accepted['acceptance_source_digest']
    assert failed['acceptance_task_digest'] != accepted['acceptance_task_digest']
    assert old_report.read_bytes() == old_bytes
    assert (old_report.parent / 'PROMOTION.md').read_bytes() == old_markdown
    # An actual edit of the source standards still requires a new revision.
    changed = json.loads(original_contract)
    changed['acceptance']['target']['value'] = 18
    source_path.write_text(json.dumps(changed))
    with pytest.raises(OPCError, match='frozen revision.*new revision'):
        use_sequence(engine_for(root), Sequence([])).run(new_run=True)
    assert len(later.ledger.runs()) == 2
