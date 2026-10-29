"""Task results acceptance: shared questions, independent executions and fixed review input."""
import json
from pathlib import Path

import pytest

from opc.core.model import OPCError
from opc.core.results import register, external_batch, snapshot, split, entry_path
from opc.core.config import TaskSpec
from opc.tests.conftest import task
from opc.tests.test_research_loop import Sequence, plan, stop, use_sequence

ENTRY = 'research/results/README.md'


def test_external_batch_idempotence_preserves_judgments_and_originals(tmp_path):
    root = tmp_path
    raw = root / 'research/raw'
    raw.mkdir(parents=True)
    (raw / 'plan.md').write_text('A predicts 4, B predicts 2; same conditions')
    (raw / 'index.json').write_text('{"observed": 3}')
    register(root, ENTRY, [])
    entry = root / ENTRY
    entry.write_text(entry.read_text().replace('待分析；独立审核待完成。', 'C1: 尚不能判定；条件为 X。'))
    kwargs = dict(root=root, artifact_root=root / 'artifacts', value=ENTRY, batch='batch-1',
                  experiment_id='E001', question='distinguish A/B', status='completed',
                  refs={'plan':'../raw/plan.md', 'evidence':'../raw/index.json'})
    external_batch(**kwargs)
    first = entry.read_bytes()
    external_batch(**kwargs)
    assert entry.read_bytes() == first
    assert 'C1: 尚不能判定' in first.decode()
    assert (raw / 'index.json').read_text() == '{"observed": 3}'
    rows = split(first.decode())[1]
    assert len(rows) == 1 and rows[0]['key'] == 'external/batch-1'
    assert rows[0]['issues'] == ['analysis: 未提供', 'review: 未提供']
    with pytest.raises(OPCError, match='original plan'):
        external_batch(**{**kwargs, 'refs': {'plan': '../raw/new-plan.md'}})
    with pytest.raises(OPCError, match='already belongs'):
        external_batch(**{**kwargs, 'experiment_id': 'E002'})
    assert entry.read_bytes() == first


def test_two_runs_external_batch_and_current_conclusion(make_project, engine_for):
    root = make_project(tsk=task(results_path=ENTRY), extra={
        'research/spec.md': 'C1: provisional support; condition X; review pending',
        'research/raw.json': '{"values":[4,4]}',
        ENTRY: '# Task\n\n[conclusions](../spec.md)\n[original](../raw.json)\n'})
    e = use_sequence(engine_for(root), Sequence([plan(1, experiment_id='E001'), stop], [4]))
    e.run()
    first_run = e.run_id
    old_context = (e.attempt_dir(1) / 'context.json').read_bytes()
    original = (root / 'research/raw.json').read_bytes()
    external_batch(root, e.bindings.artifact_root, ENTRY, 'control-1', 'E001', 'control', 'failed',
                   {'evidence': '../raw.json'})
    (root / 'research/spec.md').write_text('C1: refuted by control; condition X; old review does not cover revision')
    seq = Sequence([plan(1, experiment_id='E001'), stop], [5])
    e2 = use_sequence(engine_for(root), seq)
    e2.run(new_run=True)
    assert e2.run_id != first_run
    assert seq.contexts[0]['history'] == []
    assert 'refuted by control' in json.dumps(seq.contexts[0]['task_results'])
    rows = split((root / ENTRY).read_text())[1]
    questions = [r for r in rows if r.get('experiment_id') == 'E001']
    assert len(questions) == 3
    assert {r['key'].split('/')[0] for r in questions} == {first_run, e2.run_id, 'external'}
    assert (e.attempt_dir(1) / 'context.json').read_bytes() == old_context
    assert (root / 'research/raw.json').read_bytes() == original
    before = (root / ENTRY).read_bytes()
    e2.write_views()
    assert (root / ENTRY).read_bytes() == before


def test_registration_failure_retries_without_running_experiment(make_project, engine_for, monkeypatch):
    root = make_project(tsk=task(results_path=ENTRY))
    seq = Sequence([plan(1, experiment_id='E1'), stop], [4])
    e = use_sequence(engine_for(root), seq)
    import opc.core.results as results
    real = results.write_text
    monkeypatch.setattr(results, 'write_text', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    result = e.run()
    assert result['state'] == 'closed'
    assert e.attempt_records()[0]['candidate']
    report = json.loads((e.artifact_dir() / 'views/report.json').read_text())
    assert report['results_registration_error'] == 'disk full'
    cost = e.ledger.totals(e.run_id)
    monkeypatch.setattr(results, 'write_text', real)
    e.write_views()
    assert len(split((root / ENTRY).read_text())[1]) == 2
    assert e.ledger.totals(e.run_id) == cost
    assert len(seq.contexts) == 2


def test_missing_sources_bounds_and_path_boundary(tmp_path):
    register(tmp_path, ENTRY, [])
    path = tmp_path / ENTRY
    path.write_text('# Current\n[missing](../missing.md)\n[escape](../../../../etc/passwd)\n'
                    '[secret](../../.env)\n' + 'unknown; ' * 3000)
    result = snapshot(tmp_path, tmp_path / 'artifacts', ENTRY, budget=120)
    assert sum(len(s['excerpt']) for s in result['sources']) <= 120
    assert result['sources'][0]['truncated']
    assert any('source missing' in i for i in result['issues'])
    assert any('outside' in i for i in result['issues'])
    assert any('protected' in i for i in result['issues'])
    for bad in ('../outside.md', '.opc/runtime/README.md', '/tmp/out.md'):
        with pytest.raises(OPCError):
            entry_path(tmp_path, bad)


def test_review_keeps_consumed_version_and_does_not_remeasure_on_text_change(make_project, engine_for, monkeypatch):
    from opc.core.promote import promote
    root = make_project(tsk=task(results_path=ENTRY), extra={
        ENTRY: '# Findings\n[C1](../spec.md)\n', 'research/spec.md': 'C1 v1: support under X'})
    e = use_sequence(engine_for(root), Sequence([plan(1, experiment_id='E1'), stop], [6]))
    e.run()
    supplied = []
    def reviewer(*args):
        supplied.append(args[-1])
        return {'ok': True, 'verdict': 'accept', 'summary': 'C1 v1 only'}
    monkeypatch.setattr('opc.core.promote.run_reviewer', reviewer)
    first = promote(e, review='codex')
    old = Path(first['report_dir']) / 'report.json'
    old_bytes = old.read_bytes()
    assert 'C1 v1: support' in json.dumps(supplied[0])
    assert not any('older source versions' in i for i in e.results_context()['issues'])
    (root / 'research/spec.md').write_text('C1 v2: refuted; review pending')
    def no_measurements(*a, **kw):
        raise AssertionError('text revision should reuse unchanged delivery measurements')
    monkeypatch.setattr(e, 'evaluate_commit', no_measurements)
    second = promote(e, review='codex')
    assert first['evidence_key'] == second['evidence_key']
    assert second['evidence_source'] == str(old)
    assert 'C1 v2: refuted' in json.dumps(supplied[-1])
    assert old.read_bytes() == old_bytes
    assert first['task_results'] != second['task_results']
    assert any('older source versions' in s for s in supplied[-1]['issues'])


def test_old_contract_and_new_revision_binding(make_project):
    root = make_project()
    original = TaskSpec.load(root, 't-toy')
    assert 'results_path' not in original.raw
    new = {**original.raw, 'revision': 'r0002', 'results_path': ENTRY}
    p = original.path.parent.parent / 'r0002/task.json'
    p.parent.mkdir()
    p.write_text(json.dumps(new))
    assert TaskSpec.load(root, 't-toy').raw['results_path'] == ENTRY
    assert TaskSpec.load(root, 't-toy', 'r0001').digest == original.digest


def test_external_cli_works_without_engine_run(make_project, capsys):
    from opc.cli import main
    root = make_project(tsk=task(results_path=ENTRY))
    args = ['results', '-p', str(root), '--task', 't-toy']
    assert main(args + ['--initialize']) == 0
    assert main(args + ['--batch', 'b1', '--experiment-id', 'E1', '--status', 'aborted']) == 0
    assert not (root / '.opc/local/ledger.sqlite3').exists()
    assert split((root / ENTRY).read_text())[1][0]['status'] == 'aborted'
    assert 'aborted' in capsys.readouterr().out


def test_observer_reads_results_and_explicit_links_without_writes(make_project):
    from opc.observer.adapter import ObserverAdapter
    root = make_project(tsk=task(results_path=ENTRY), extra={
        ENTRY: '# Task\n[spec](../spec.md)\n[missing](../absent.md)\n',
        'research/spec.md': '# C1\n[observation](raw.json)\n[secret](../.env)',
        'research/raw.json': '{"observation":4}', '.env': 'PRIVATE'})
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}
    adapter = ObserverAdapter(root)
    adapter._discover()
    revision = next(iter(adapter.revisions.values()))
    detail = adapter.task_revision(revision['id'])['data']
    assert any(a['title'] == '任务成果' for a in detail['artifacts'])
    assert any(a['meta']['availability'] == 'missing' for a in detail['artifacts'])
    spec = root / 'research/spec.md'
    resolved = adapter._markdown_links(spec, spec.read_text())
    assert 'raw.json' in resolved and '../.env' not in resolved
    after = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}
    assert before == after


def test_interrupted_and_cached_batches_are_not_new_measurements(make_project, engine_for):
    root = make_project(tsk=task(results_path=ENTRY, acceptance={'objective': None}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([plan(1, experiment_id='E1')], ['interrupt']))
    result = e.run()
    assert result['state'] == 'paused'
    rows = split((root / ENTRY).read_text())[1]
    assert rows[0]['run_state'] == 'paused'
    assert not rows[0]['refs'].get('evidence')
    assert e.task.acceptance.objective_metric is None
    external_batch(root, e.bindings.artifact_root, ENTRY, 'old-data', 'E1', 'reuse', 'cached',
                   {'evidence': '../missing-index.json#repeat-2'})
    text = (root / ENTRY).read_text()
    assert '历史缓存，非新实测' in text
    assert split(text)[1][0]['refs']['evidence'].endswith('#repeat-2')


def test_invalid_worker_plan_cannot_corrupt_results(make_project, engine_for):
    root = make_project(tsk=task(results_path=ENTRY))
    e = use_sequence(engine_for(root), Sequence([plan(1, experiment_id=['not', 'an', 'ID']), stop]))
    e.run()
    row = e.attempt_records()[0]
    assert row['outcome'] == 'worker_failed'
    assert split((root / ENTRY).read_text())[1][0]['experiment_id'] is None


def test_missing_entry_is_visible_and_symlinks_cannot_expose_secrets(make_project):
    from opc.observer.adapter import ObserverAdapter
    root = make_project(tsk=task(results_path=ENTRY), extra={'.env': 'PRIVATE'})
    adapter = ObserverAdapter(root)
    adapter._discover()
    revision = next(iter(adapter.revisions.values()))
    detail = adapter.task_revision(revision['id'])['data']
    assert any(a['title'] == '任务成果' and a['availability'] == 'missing' for a in detail['artifacts'])
    entry = root / ENTRY
    entry.parent.mkdir(parents=True)
    try:
        entry.symlink_to(root / '.env')
    except OSError as exc:
        pytest.skip('symlink unavailable: ' + str(exc))
    with pytest.raises(OPCError, match='symlinks'):
        register(root, ENTRY, [])
    # A file registered earlier is rechecked at read time, even within project root.
    assert not adapter._allowed(entry)
    assert (root / '.env').read_text() == 'PRIVATE'


def test_malformed_registration_keeps_existing_text(tmp_path):
    path = tmp_path / ENTRY
    path.parent.mkdir(parents=True)
    path.write_text('# Conclusion\n<!-- archa-results:start -->\nbroken')
    before = path.read_bytes()
    with pytest.raises(OPCError, match='markers'):
        register(tmp_path, ENTRY, [])
    assert path.read_bytes() == before


def test_results_http_entry_uses_existing_file_list_and_links(make_project, observer_test_client):
    from opc.observer.api import create_app
    from urllib.parse import quote
    root = make_project(tsk=task(results_path=ENTRY), extra={
        ENTRY: '# Task result\n[claim](../claim.md)\n', 'research/claim.md': 'C1 pending independent review'})
    app = create_app(root)
    app.state.adapter._discover()
    revision = next(iter(app.state.adapter.revisions))
    base = '/api/observer/v1'
    with observer_test_client(app) as client:
        detail = client.get(base + '/task-revisions/' + quote(revision, safe=''))
        assert detail.status_code == 200
        art = next(a for a in detail.json()['data']['artifacts'] if a['title'] == '任务成果')
        assert art['label'] == '任务成果'  # Existing FileList consumes label, not title.
        path = base + '/artifacts/' + quote(art['id'], safe='')
        metadata = client.get(path)
        assert metadata.status_code == 200
        target = metadata.json()['data']['link_targets']['../claim.md']['id']
        body = client.get(base + '/artifacts/' + quote(target, safe='') + '/content')
        assert body.status_code == 200 and 'C1 pending' in body.json()['data']['content']
        assert client.post(path).status_code == 405


def test_external_cli_respects_controller_lock(make_project):
    from opc.core.results import writer
    from opc.cli import main
    root = make_project(tsk=task(results_path=ENTRY))
    with writer(root):
        assert main(['results', '-p', str(root), '--task', 't-toy', '--initialize']) == 2
    assert not (root / ENTRY).exists()
