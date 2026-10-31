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
    (raw / 'plan.md').write_text('A predicts 4, B predicts 2; same conditions', encoding="utf-8")
    (raw / 'index.json').write_text('{"observed": 3}', encoding="utf-8")
    register(root, ENTRY, [])
    entry = root / ENTRY
    entry.write_text(entry.read_text(encoding="utf-8").replace('待分析；独立审核待完成。', 'C1: 尚不能判定；条件为 X。'), encoding="utf-8")
    kwargs = dict(root=root, artifact_root=root / 'artifacts', value=ENTRY, batch='batch-1',
                  experiment_id='E001', question='distinguish A/B', status='completed',
                  refs={'plan':'../raw/plan.md', 'evidence':'../raw/index.json'})
    external_batch(**kwargs)
    first = entry.read_bytes()
    external_batch(**kwargs)
    assert entry.read_bytes() == first
    assert 'C1: 尚不能判定' in first.decode()
    assert (raw / 'index.json').read_text(encoding="utf-8") == '{"observed": 3}'
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
    (root / 'research/spec.md').write_text('C1: refuted by control; condition X; old review does not cover revision', encoding="utf-8")
    seq = Sequence([plan(1, experiment_id='E001'), stop], [5])
    e2 = use_sequence(engine_for(root), seq)
    e2.run(new_run=True)
    assert e2.run_id != first_run
    assert seq.contexts[0]['history'] == []
    assert 'refuted by control' in json.dumps(seq.contexts[0]['task_results'])
    rows = split((root / ENTRY).read_text(encoding="utf-8"))[1]
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
    report = json.loads((e.artifact_dir() / 'views/report.json').read_text(encoding="utf-8"))
    assert report['results_registration_error'] == 'disk full'
    cost = e.ledger.totals(e.run_id)
    calls = [c['call_id'] for c in e.ledger.calls(e.run_id)]
    candidate = e.attempt_records()[0]['candidate']
    monkeypatch.setattr(results, 'write_text', real)
    e.write_views()
    rows = split((root / ENTRY).read_text(encoding="utf-8"))[1]
    assert len(rows) == 1  # Stop is a Run decision, not a second execution.
    assert rows[0]['key'] == e.run_id + '/a1' and rows[0]['experiment_id'] == 'E1'
    assert rows[0]['status'] == e.attempt_records()[0]['outcome']
    evidence = ((root / ENTRY).parent / rows[0]['refs']['evidence']).resolve()
    assert evidence == e.attempt_dir(1) / 'eval/evaluation.json'
    assert json.loads(evidence.read_text())['commit'] == candidate
    assert e.ledger.totals(e.run_id) == cost
    assert [c['call_id'] for c in e.ledger.calls(e.run_id)] == calls
    assert len(seq.contexts) == 2


def test_missing_sources_bounds_and_path_boundary(tmp_path):
    register(tmp_path, ENTRY, [])
    path = tmp_path / ENTRY
    path.write_text('# Current\n[missing](../missing.md)\n[escape](../../../../etc/passwd)\n'
                    '[secret](../../.env)\n' + 'unknown; ' * 3000, encoding="utf-8")
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
    (root / 'research/spec.md').write_text('C1 v2: refuted; review pending', encoding="utf-8")
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
    p.write_text(json.dumps(new), encoding="utf-8")
    assert TaskSpec.load(root, 't-toy').raw['results_path'] == ENTRY
    assert TaskSpec.load(root, 't-toy', 'r0001').digest == original.digest


def test_external_cli_works_without_engine_run(make_project, capsys):
    from opc.cli import main
    root = make_project(tsk=task(results_path=ENTRY))
    args = ['results', '-p', str(root), '--task', 't-toy']
    assert main(args + ['--initialize']) == 0
    assert main(args + ['--batch', 'b1', '--experiment-id', 'E1', '--status', 'aborted']) == 0
    assert not (root / '.opc/local/ledger.sqlite3').exists()
    assert split((root / ENTRY).read_text(encoding="utf-8"))[1][0]['status'] == 'aborted'
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
    resolved = adapter._markdown_links(spec, spec.read_text(encoding="utf-8"))
    assert 'raw.json' in resolved and '../.env' not in resolved
    after = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}
    assert before == after


def test_interrupted_and_cached_batches_are_not_new_measurements(make_project, engine_for):
    root = make_project(tsk=task(results_path=ENTRY, acceptance={'objective': None}, requirements=[]))
    e = use_sequence(engine_for(root), Sequence([plan(1, experiment_id='E1')], ['interrupt']))
    result = e.run()
    assert result['state'] == 'paused'
    rows = split((root / ENTRY).read_text(encoding="utf-8"))[1]
    assert rows[0]['run_state'] == 'paused'
    assert not rows[0]['refs'].get('evidence')
    assert e.task.acceptance.objective_metric is None
    external_batch(root, e.bindings.artifact_root, ENTRY, 'old-data', 'E1', 'reuse', 'cached',
                   {'evidence': '../missing-index.json#repeat-2'})
    text = (root / ENTRY).read_text(encoding="utf-8")
    assert '历史缓存，非新实测' in text
    assert split(text)[1][0]['refs']['evidence'].endswith('#repeat-2')


def test_invalid_worker_plan_cannot_corrupt_results(make_project, engine_for):
    root = make_project(tsk=task(results_path=ENTRY))
    register(root, ENTRY, [dict(key='external/control', experiment_id='E0', question='existing control',
                                status='completed', refs={}, issues=[])])
    previous = split((root / ENTRY).read_text(encoding="utf-8"))[1]
    e = use_sequence(engine_for(root), Sequence([plan(1, experiment_id=['not', 'an', 'ID']), stop]))
    result = e.run()
    assert result['state'] == 'blocked' and e.attempt_records() == []
    call = next(c for c in e.ledger.calls(e.run_id) if c['role'] == 'expert')
    assert call['attempt_no'] is None and call['result']['output']['experiment_id'] == ['not', 'an', 'ID']
    rejection = e.ledger.events(e.run_id, 'expert_rejected')[-1]['body']
    assert rejection['call_id'] == call['call_id'] and 'experiment_id' in rejection['reason']
    assert split((root / ENTRY).read_text(encoding="utf-8"))[1] == previous


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
    assert (root / '.env').read_text(encoding="utf-8") == 'PRIVATE'


def test_malformed_registration_keeps_existing_text(tmp_path):
    path = tmp_path / ENTRY
    path.parent.mkdir(parents=True)
    path.write_text('# Conclusion\n<!-- archa-results:start -->\nbroken', encoding="utf-8")
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


def test_worker_claim_query_preserves_counterevidence_and_reads_scoped_sources(make_project, engine_for):
    import subprocess
    from opc.core.tool_boundary import worker_policy, runner_argv
    received = []
    class QueryWorker(Sequence):
        def implement(self, p, ctx, tree, log_dir):
            if received:
                material = ctx['knowledge']
                assert 'history' not in ctx and 'task_results' not in ctx
                policy = worker_policy('designer', tree, log_dir, ctx)
                policy_path = log_dir / 'query-policy.json'
                policy_path.parent.mkdir(parents=True, exist_ok=True)
                policy_path.write_text(json.dumps(policy))
                def query(*args):
                    result = subprocess.run(runner_argv(policy_path, material['command'] + list(args)),
                                            cwd=tree, text=True, capture_output=True)
                    assert result.returncode == 0, result.stderr
                    return json.loads(result.stdout)
                found = query('--status', 'supported', '--text', 'long')
                assert found['scope']['task_ids'] == ['t-toy']
                assert found['as_of'] == 'fixed_call_input'
                assert len(found['claims']) == 1
                claim = found['claims'][0]
                assert claim['scope'] == 'long fields only'
                assert claim['counterevidence'][0]['availability'] == 'not_expanded'
                assert claim['unresolved'] == ['Repeat measurement needed']
                assert found['omitted'] == 1
                expanded = query('--claim-id', 'long', '--source', '0')
                assert expanded['source']['availability'] == 'read'
                assert 'metrics' in expanded['source']['content']
                denied = subprocess.run(runner_argv(policy_path, material['command'] + ['--task-id', 'other-task']),
                                        cwd=tree, text=True, capture_output=True)
                assert denied.returncode != 0 and 'authorized' in denied.stderr
            received.append(ctx)
            return super().implement(p, ctx, tree, log_dir)
    def register_claims(ctx):
        source = dict(run_id=e.run_id, attempt=1, artifact='eval/evaluation.json')
        return dict(plan(2), claims=[
            dict(claim_id='general', statement='Less copying always helps', scope='all fields',
                 status='unresolved', reason='Short fields unknown', evidence=[source]),
            dict(claim_id='long', statement='Less copying helps long fields', scope='long fields only',
                 status='supported', reason='Controlled long field observation', evidence=[source],
                 counterevidence=[source], unresolved=['Repeat measurement needed'])])
    e = use_sequence(engine_for(make_project()), QueryWorker([plan(1), register_claims, stop], [4, 5]))
    assert e.run()['state'] == 'closed'
    assert len(received) == 2
    from opc.observer.adapter import ObserverAdapter
    before = e.ledger.path.read_bytes()
    observer = ObserverAdapter(e.root)
    observed = observer.run(observer._id('run', e.run_id))['data']
    source = observed['claims'][1]['counterevidence'][0]
    assert source['availability'] == 'not_expanded'
    assert 'metrics' in observer.content(source['artifact_id'])['data']['content']
    assert e.ledger.path.read_bytes() == before


def test_cross_task_claim_query_requires_named_material_dependency(make_project, engine_for):
    from opc.tests.conftest import task
    from opc.core.results import query_claims
    def register_claims(ctx):
        return dict(stop(ctx), claims=[
            dict(claim_id=name, statement=name + ' proposition', scope='fixed inputs',
                 status='supported', reason='Measurement supports scoped claim',
                 evidence=[dict(run_id=origin.run_id, attempt=1, artifact='eval/evaluation.json')])
            for name in ('shared', 'private')])
    root = make_project()
    origin = use_sequence(engine_for(root), Sequence([plan(1), register_claims], [4]))
    origin.run()
    def add_task(ident, dependencies):
        path = root / '.opc/tasks' / ident / 'revisions/r0001/task.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(task(task_id=ident, knowledge_dependencies=dependencies)))
        from opc.tests.conftest import git
        git(root, 'add', str(path.relative_to(root)))
        git(root, 'commit', '-qm', 'add dependent task')
        return engine_for(root, task_id=ident)
    authorized = add_task('t-dependent', [{'task_id': 't-toy', 'claim_id': 'shared'}])
    seq = Sequence([stop])
    use_sequence(authorized, seq).run()
    context = seq.contexts[0]
    found = query_claims(context, task_id='t-toy')
    assert [c['claim_id'] for c in found['claims']] == ['shared']
    assert query_claims(context, claim_id='private')['claims'] == []
    assert query_claims(context, claim_id='shared', source=0)['source']['availability'] == 'read'
    denied = add_task('t-isolated', [])
    seq2 = Sequence([stop])
    use_sequence(denied, seq2).run()
    with pytest.raises(ValueError, match='authorized'):
        query_claims(seq2.contexts[0], task_id='t-toy')


def test_claim_source_expansion_distinguishes_missing_and_access_denied(make_project, engine_for):
    from opc.core.results import query_claims
    def register_claim(ctx):
        return dict(plan(2), claims=[dict(claim_id='copy', statement='Copying affects speed', scope='fixed inputs',
                    status='supported', reason='Observation supports claim',
                    evidence=[dict(run_id=e.run_id, attempt=1, artifact='eval/evaluation.json')])])
    root = make_project()
    seq = Sequence([plan(1), register_claim, stop], [4, 5])
    e = use_sequence(engine_for(root), seq)
    e.run()
    context = seq.contexts[2]
    ref = context['claims'][0]['evidence'][0]
    source = Path(ref['source'])
    source.unlink()
    missing = query_claims(context, claim_id='copy', source=0)
    assert missing['source']['availability'] == 'missing'
    assert missing['claims'][0]['status'] == 'supported'
    private = root / 'private.txt'
    private.write_text('private sibling data')
    source.symlink_to(private)
    denied = query_claims(context, claim_id='copy', source=0)
    assert denied['source']['availability'] == 'access_denied'
    assert 'content' not in denied['source']


@pytest.mark.parametrize('worker_ok', [True, False])
def test_designer_discovered_originals_survive_cleanup_and_candidate_rejection(make_project, engine_for, worker_ok):
    from opc.core.results import query_claims
    from opc.tests.conftest import component
    trees = []
    class EvidenceWorker(Sequence):
        def implement(self, p, ctx, tree, log_dir):
            trees.append(tree)
            raw = tree / 'measurements/long.json'
            raw.parent.mkdir(parents=True)
            raw.write_text('{"field":"long","latency":17}')
            (raw.parent / 'trace.bin').write_bytes(b'\x00\xffnative-trace')
            call = super().implement(p, ctx, tree, log_dir)
            call.output['evidence_files'] = ['measurements/long.json', 'measurements/trace.bin']
            call.ok = worker_ok
            call.error = '' if worker_ok else 'Work incomplete; observations retained'
            return call
    def register_claim(ctx):
        saved = ctx['history'][0]['execution']['saved_files']
        assert saved == ['outputs/measurements/long.json', 'outputs/measurements/trace.bin']
        return dict(stop(ctx), claims=[dict(claim_id='long', statement='Less copying helps long fields',
                    scope='long fields only', status='supported', reason='Controlled long field observation',
                    evidence=[dict(run_id=e.run_id, attempt=1, artifact=path) for path in saved])])
    root = make_project(comp=component(scratch=['measurements/**']))
    e = use_sequence(engine_for(root), EvidenceWorker([
        plan(1, deliverables=['measurements/long.json']), register_claim], [0]))
    result = e.run()
    assert result['state'] == 'closed'
    assert e.attempt_records()[0]['outcome'] == ('no_gain' if worker_ok else 'worker_failed')
    assert json.loads((root / 'params.json').read_text()) == {'x': 3}
    assert not trees[0].exists()
    original = e.attempt_dir(1) / 'outputs/measurements/long.json'
    trace = e.attempt_dir(1) / 'outputs/measurements/trace.bin'
    assert original.read_text() == '{"field":"long","latency":17}'
    assert trace.read_bytes() == b'\x00\xffnative-trace'
    assert sorted(p.name for p in original.parent.iterdir()) == ['long.json', 'trace.bin']
    old_stat = original.stat().st_mtime_ns
    seq = Sequence([stop])
    restored = use_sequence(engine_for(root), seq)
    restored.run(new_run=True)
    expanded = query_claims(seq.contexts[0], claim_id='long', source=0)
    assert expanded['source']['availability'] == 'read'
    assert json.loads(expanded['source']['content'])['latency'] == 17
    assert original.stat().st_mtime_ns == old_stat


def test_missing_claim_original_is_preserved_as_gap_after_fresh_observation(make_project, engine_for):
    from opc.core.results import query_claims
    from opc.tests.conftest import component
    from opc.adapters.worker import WorkerCall
    from opc.core.model import Cost
    claim = dict(claim_id='long', statement='Less copying helps long fields', scope='long fields only',
                 status='supported', reason='First controlled observation')
    class EvidenceWorker(Sequence):
        def implement(self, p, ctx, tree, log_dir):
            raw = tree / 'measurements/long.json'
            raw.parent.mkdir(parents=True)
            raw.write_text('{"observation":"fresh measurement","latency":22}')
            return WorkerCall('designer', True, Cost(), output=dict(
                summary='New controlled long-field observation; does not recover old execution',
                evidence_files=['measurements/long.json']))
    def register_claim(ctx):
        return dict(stop(ctx), claims=[dict(claim, evidence=[dict(
                    run_id=first.run_id, attempt=1, artifact='outputs/measurements/long.json')])])
    root = make_project(comp=component(scratch=['measurements/**']))
    first = use_sequence(engine_for(root), EvidenceWorker([plan(1), register_claim]))
    first.run()
    missing = first.attempt_dir(1) / 'outputs/measurements/long.json'
    missing.unlink()
    original_run = first.run_id
    old_ref = dict(run_id=original_run, attempt=1, artifact='outputs/measurements/long.json')
    def recover(ctx):
        found = query_claims(ctx, claim_id='long', source=0)
        assert found['source']['availability'] == 'missing'
        assert found['claims'][0]['status'] == 'supported'
        return dict(plan(1), changes='Obtain a new long-field observation; original execution remains missing')
    def reconsider(ctx):
        assert ctx['pending_feedback'][0]['attempt'] == 1
        return dict(stop(ctx), claims=[dict(claim, base_version=1,
                    reason='Fresh observation supports scope; original historical execution remains missing',
                    evidence=[old_ref, dict(run_id=second.run_id, attempt=1,
                                           artifact='outputs/measurements/long.json')],
                    unresolved=['Original historical execution could not be recovered'])])
    seq = EvidenceWorker([recover, reconsider])
    second = use_sequence(engine_for(root), seq)
    assert second.run(new_run=True)['state'] == 'closed'
    assert second.run_id != original_run
    final_seq = Sequence([stop])
    final = use_sequence(engine_for(root), final_seq)
    final.run(new_run=True)
    ctx = final_seq.contexts[0]
    current = query_claims(ctx, claim_id='long')
    assert current['claims'][0]['version'] == 2
    assert current['claims'][0]['unresolved'] == ['Original historical execution could not be recovered']
    assert query_claims(ctx, claim_id='long', source=0)['source']['availability'] == 'missing'
    assert query_claims(ctx, claim_id='long', source=1)['source']['availability'] == 'read'
    old = query_claims(ctx, claim_id='long', version=1, source=0)
    assert old['source']['availability'] == 'missing'
    assert old['claims'][0]['reason'] == 'First controlled observation'
    assert not missing.exists()
    from opc.observer.adapter import ObserverAdapter
    before = final.ledger.path.read_bytes()
    observer = ObserverAdapter(root)
    observed = observer.run(observer._id('run', second.run_id))['data']
    assert observed['claims'][0]['version'] == 2
    assert observed['claims'][0]['evidence'][0]['availability'] == 'missing'
    assert observed['claim_history'][0]['reason'] == 'First controlled observation'
    assert final.ledger.path.read_bytes() == before


@pytest.mark.parametrize('evidence_files', [
    '../outside.txt', ['../outside.txt'], ['.opc/eval/evaluate.py'],
])
def test_discovered_evidence_rejects_invalid_or_unauthorized_paths(make_project, engine_for, evidence_files):
    from opc.adapters.worker import WorkerCall
    from opc.core.model import Cost
    class EvidenceWorker(Sequence):
        def implement(self, p, ctx, tree, log_dir):
            return WorkerCall('designer', True, Cost(), output=dict(
                summary='Attempted evidence declaration', evidence_files=evidence_files))
    e = use_sequence(engine_for(make_project()), EvidenceWorker([plan(1), stop]))
    e.run()
    result = e.attempt_records()[0]
    assert result['outcome'] == 'worker_failed'
    assert 'evidence_files' in result['reason']
    assert not (e.attempt_dir(1) / 'outputs').exists()


def test_discovered_evidence_cannot_archive_protected_file_through_scratch_link(make_project, engine_for):
    from opc.adapters.worker import WorkerCall
    from opc.core.model import Cost
    from opc.tests.conftest import component
    class EvidenceWorker(Sequence):
        def implement(self, p, ctx, tree, log_dir):
            raw = tree / 'measurements/linked.py'
            raw.parent.mkdir()
            raw.symlink_to(tree / '.opc/eval/evaluate.py')
            return WorkerCall('designer', True, Cost(), output=dict(
                summary='Attempted protected source alias', evidence_files=['measurements/linked.py']))
    e = use_sequence(engine_for(make_project(comp=component(scratch=['measurements/**']))),
                     EvidenceWorker([plan(1), stop]))
    e.run()
    assert e.attempt_records()[0]['outcome'] == 'worker_failed'
    assert not (e.attempt_dir(1) / 'outputs/measurements/linked.py').exists()


@pytest.mark.parametrize('has_results', [False, True])
def test_claim_review_keeps_exact_revision_after_later_run_updates(make_project, engine_for, monkeypatch, has_results):
    from opc.core.promote import promote
    claim = dict(claim_id='copy-all', statement='Reducing copying always improves speed',
                 scope='Comparable long and short fields', status='unresolved', reason='Need evidence', evidence=[])
    e = use_sequence(engine_for(make_project(tsk=task(results_path=ENTRY) if has_results else task())),
                     Sequence([plan(1), lambda ctx: dict(stop(ctx), claims=[claim])], [4]))
    e.run()
    supplied = []
    def reviewer(*args):
        supplied.append(args[-1])
        return dict(ok=True, verdict='accept', summary='Only supplied version and scope')
    monkeypatch.setattr('opc.core.promote.run_reviewer', reviewer)
    reviewed = promote(e, review='codex')
    assert supplied[0]['claims'][0]['version'] == 1
    review_path = Path(reviewed['report_dir']) / 'report.json'
    old_review = review_path.read_bytes()
    seq = Sequence([dict(select_work=False, claims=[dict(claim, base_version=1,
                        status='refuted', reason='Comparable short field counterexample')]), stop])
    later = use_sequence(engine_for(e.root), seq)
    later.run(new_run=True)
    assert later.claims('copy-all')[0]['version'] == 2
    assert later.summary()['claims'][0]['status'] == 'refuted'
    assert review_path.read_bytes() == old_review
    assert json.loads(old_review)['task_results']['claims'][0]['version'] == 1
    assert not later.ledger.events(later.run_id, 'promotion_report')


def test_fixed_claim_query_expands_explicit_historical_revision(make_project, engine_for):
    from opc.core.results import query_claims
    claim = dict(claim_id='copy', statement='Less copying always helps', scope='fixed fields',
                 status='unresolved', reason='Need comparable evidence', evidence=[])
    e = use_sequence(engine_for(make_project()), Sequence([
        plan(1), dict(select_work=False, claims=[claim]),
        dict(select_work=False, claims=[dict(claim, base_version=1, status='refuted', reason='Valid counterexample')]),
        stop], [4]))
    e.run()
    context = [c['input']['context'] for c in e.ledger.calls(e.run_id) if c['role'] == 'expert'][-1]
    current = query_claims(context, claim_id='copy')
    assert current['claims'][0]['version'] == 2 and current['claims'][0]['status'] == 'refuted'
    historical = query_claims(context, claim_id='copy', version=1)
    assert historical['claims'][0]['status'] == 'unresolved'
    assert historical['claims'][0]['reason'] == 'Need comparable evidence'
