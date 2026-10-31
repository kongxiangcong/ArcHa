import json
import pytest

from opc.scaffold.onboard import onboard
from opc.core.ledger import Ledger
from opc.core.model import Cost


def test_onboard_reconciles_without_dispatch(make_project, monkeypatch):
    root = make_project()
    kw = dict(task_id='t-toy', max_tokens=1000, max_wall_seconds=600,
              prior_tokens=10, prior_wall_seconds=0, record_usage_only=True)
    onboard(root, 'codex', **kw)
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    rid = ledger.preparation_scope('t-toy')
    ledger.charge(rid, None, 'onboard', Cost(2, 20, None))
    ledger.event(rid, 'accounting_unknown', reason='worker usage missing')
    seq = ledger.events(rid, 'accounting_unknown')[0]['seq']
    assert onboard(root, 'codex', **kw)['preparation'] == 'accounting_unknown'
    evidence = root / 'usage.json'
    evidence.write_text('{"actual_tokens": 50}', encoding="utf-8")
    receipt = root / 'reconcile.json'
    receipt.write_text(json.dumps({'entries': [{'event_seq': seq, 'additional_tokens': 30,
        'additional_wall_seconds': 0, 'evidence': 'usage.json',
        'reason': 'actual 50 minus already charged 20; elapsed time already charged'}]}), encoding="utf-8")
    def forbidden(*a, **k):
        raise AssertionError('reconciliation must not dispatch')
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', forbidden)
    result = onboard(root, 'codex', reconcile_usage=receipt, **kw)
    assert result['preparation'] == 'pending'
    assert not ledger.unresolved_accounting(rid)
    assert ledger.totals(rid)['tokens'] == 60
    onboard(root, 'codex', reconcile_usage=receipt, **kw)
    assert ledger.totals(rid)['tokens'] == 60
    assert ledger.events(rid, 'accounting_unknown')  # audit history survives
    ledger.event(rid, 'accounting_unknown', reason='another call')
    assert onboard(root, 'codex', **kw)['preparation'] == 'accounting_unknown'


def test_codex_home_override_reaches_child(tmp_path, monkeypatch):
    from opc.adapters.codex import CodexWorker
    home = tmp_path / 'worker-home'
    home.mkdir()
    script = tmp_path / 'worker.py'
    script.write_text('import os, pathlib, json\n'
                      'pathlib.Path(os.environ["CODEX_HOME"], "started").touch()\n'
                      'print(json.dumps({"type":"turn.completed", "usage":{"input_tokens":0,"output_tokens":0}}))\n', encoding="utf-8")
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'unusable-parent'))
    call, _ = CodexWorker({'binary': str(script), 'codex_home': str(home)})._run(
        'onboard', 'test', tmp_path, tmp_path / 'logs', 'workspace-write', None)
    assert call.ok and (home / 'started').exists()


def test_reconciliation_validation_and_budget(make_project, monkeypatch):
    import pytest
    from opc.core.model import OPCError
    root = make_project()
    kw = dict(task_id='t-toy', max_tokens=100, max_wall_seconds=600,
              prior_tokens=10, prior_wall_seconds=0, record_usage_only=True)
    onboard(root, 'codex', **kw)
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    rid = ledger.preparation_scope('t-toy')
    ledger.event(rid, 'accounting_unknown', reason='first')
    ledger.event(rid, 'accounting_unknown', reason='second')
    events = ledger.unresolved_accounting(rid)
    (root / 'evidence.txt').write_text('test accounting evidence', encoding="utf-8")
    entry = dict(event_seq=events[0]['seq'], additional_tokens=90,
                 additional_wall_seconds=0, evidence='evidence.txt', reason='missing tokens')
    for invalid in ({'additional_tokens': -1}, {'additional_tokens': True},
                    {'additional_wall_seconds': float('nan')}, {'event_seq': 99999},
                    {'evidence': '../outside'}, {'reason': ''}):
        with pytest.raises(OPCError):
            with ledger.writer():
                ledger.reconcile_accounting(rid, [entry, {**entry, 'event_seq': events[1]['seq'], **invalid}], root)
        assert ledger.totals(rid)['tokens'] == 10
        assert len(ledger.unresolved_accounting(rid)) == 2
    with ledger.writer():
        ledger.reconcile_accounting(rid, [entry], root)
    assert len(ledger.unresolved_accounting(rid)) == 1
    with pytest.raises(OPCError, match='different receipt'):
        with ledger.writer():
            ledger.reconcile_accounting(rid, [{**entry, 'additional_tokens': 1}], root)
    receipt = root / 'reconcile.json'
    receipt.write_text(json.dumps({'entries': [{**entry, 'event_seq': events[1]['seq'], 'additional_tokens': 0}]}), encoding="utf-8")
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', lambda *a: pytest.fail('dispatched'))
    assert onboard(root, 'codex', reconcile_usage=receipt, **kw)['preparation'] == 'budget_exhausted'
    assert ledger.totals(rid)['tokens'] == 100
    # An explicit new cap updates configuration without resetting consumed usage.
    onboard(root, 'codex', **{**kw, 'max_tokens': 200})
    assert ledger.totals(rid)['tokens'] == 100
    assert [v['body']['tokens'] for v in ledger.events(rid, 'preparation_budget')] == [100, 200]


def test_codex_readonly_error_and_spawn_failure(tmp_path):
    from opc.adapters.codex import CodexWorker
    script = tmp_path / 'readonly.py'
    script.write_text('import sys\nprint("Read-only file system", file=sys.stderr)\nsys.exit(1)\n', encoding="utf-8")
    log = tmp_path / 'logs'
    log.mkdir()
    (log / 'onboard-last.txt').write_text('stale success', encoding="utf-8")
    call, reply = CodexWorker({'binary': str(script)})._run(
        'onboard', 'test', tmp_path, log, 'workspace-write', None)
    assert not call.ok and not reply
    assert 'OPC_CODEX_HOME' in call.error
    assert not call.extra['usage_complete']  # no receipt is not proof of zero usage
    call, _ = CodexWorker({'binary': str(tmp_path / 'absent')})._run(
        'onboard', 'test', tmp_path, log, 'workspace-write', None)
    assert not call.ok and call.extra['not_started'] and call.extra['usage_complete']
    assert call.cost.tokens == 0


def test_cli_reconcile_and_role_home_config(make_project, capsys):
    from opc.cli import main
    from opc.core.worker_config import load_worker_config, worker_options
    from opc.adapters.codex import CodexWorker
    root = make_project()
    kw = dict(task_id='t-toy', max_tokens=100, max_wall_seconds=600,
              prior_tokens=0, prior_wall_seconds=0, record_usage_only=True)
    onboard(root, 'codex', **kw)
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    rid = ledger.preparation_scope('t-toy')
    ledger.event(rid, 'accounting_unknown', reason='unknown startup')
    seq = ledger.unresolved_accounting(rid)[0]['seq']
    (root / 'evidence.txt').write_text('fixture verifies zero model usage', encoding="utf-8")
    (root / 'receipt.json').write_text(json.dumps({'entries': [dict(event_seq=seq,
        additional_tokens=0, additional_wall_seconds=0, evidence='evidence.txt', reason='no model request')]}), encoding="utf-8")
    status = main(['onboard', '-p', str(root), '--task', 't-toy', '--max-tokens', '100',
                   '--max-wall-seconds', '600', '--prior-tokens', '0', '--prior-wall-seconds', '0',
                   '--reconcile-usage', 'receipt.json'])
    assert status == 1  # accounting is resolved, readiness is not certified
    assert json.loads(capsys.readouterr().out)['preparation'] == 'pending'
    assert not ledger.unresolved_accounting(rid)
    home = root / '.opc/local/codex-home'
    home.mkdir()
    (root / '.opc/local/workers.json').write_text(json.dumps({'onboard': {'codex_home': str(home)}}), encoding="utf-8")
    worker = CodexWorker(worker_options(load_worker_config(root), 'onboard'))
    assert worker.codex_home == str(home)


def test_direct_reconciliation_invalidates_stale_ready(make_project, monkeypatch):
    """A later unknown call may have no intervening preparation state receipt."""
    import pytest
    root = make_project()
    kw = dict(task_id='t-toy', max_tokens=100, max_wall_seconds=600,
              prior_tokens=0, prior_wall_seconds=0, record_usage_only=True)
    onboard(root, 'codex', **kw)
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    rid = ledger.preparation_scope('t-toy')
    ledger.event(rid, 'preparation', state='ready', reason='previous review')
    ledger.event(rid, 'accounting_unknown', reason='subsequent worker receipt missing')
    seq = ledger.unresolved_accounting(rid)[0]['seq']
    (root / 'usage.txt').write_text('verified additional usage', encoding="utf-8")
    receipt = root / 'reconcile.json'
    receipt.write_text(json.dumps({'entries': [dict(event_seq=seq,
        additional_tokens=2, additional_wall_seconds=0, evidence='usage.txt', reason='measured missing usage')]}), encoding="utf-8")
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', lambda *a: pytest.fail('dispatched'))
    result = onboard(root, 'codex', reconcile_usage=receipt, **kw)
    assert result['preparation'] == 'pending'
    assert not result['ok']
    assert ledger.events(rid, 'preparation')[-1]['body']['state'] == 'pending'
    assert not ledger.unresolved_accounting(rid)


def test_reconciliation_requires_preparation_lock_and_immutable_evidence(make_project):
    import pytest
    from opc.core.model import OPCError
    root = make_project()
    onboard(root, 'codex', task_id='t-toy', max_tokens=100, max_wall_seconds=600,
            prior_tokens=0, prior_wall_seconds=0, record_usage_only=True)
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    rid = ledger.preparation_scope('t-toy')
    ledger.event(rid, 'accounting_unknown', reason='missing')
    evidence = root / 'usage.txt'
    evidence.write_text('original evidence', encoding="utf-8")
    entry = dict(event_seq=ledger.unresolved_accounting(rid)[0]['seq'],
                 additional_tokens=2, additional_wall_seconds=0, evidence='usage.txt', reason='measured')
    with pytest.raises(OPCError, match='writer lock'):
        ledger.reconcile_accounting(rid, [entry], root)
    with ledger.writer():
        ledger.reconcile_accounting(rid, [entry], root)
        evidence.write_text('changed evidence', encoding="utf-8")
        with pytest.raises(OPCError, match='different receipt'):
            ledger.reconcile_accounting(rid, [entry], root)
    assert ledger.totals(rid)['tokens'] == 2
    assert len(ledger.events(rid, 'accounting_reconciled')) == 1
    rid = ledger.create_run(task_id="t-toy", revision="r0001", task_digest="x",
        component="toy", base_commit="x", evaluator_digest="x", toolchain_digest="x",
        champion_ref="", direction="")
    with ledger.writer():
        with pytest.raises(OPCError, match='preparation run'):
            ledger.reconcile_accounting(rid, [entry], root)


def test_codex_home_precedence_and_parent_environment(tmp_path, monkeypatch):
    from opc.adapters.codex import CodexWorker
    from opc.core.model import OPCError
    import pytest
    homes = [tmp_path / name for name in ('role', 'override', 'inherited')]
    for home in homes:
        home.mkdir()
    script = tmp_path / 'worker.py'
    script.write_text('import os,json\nprint(json.dumps({"type":"turn.completed",'
                      '"usage":{"input_tokens":0,"output_tokens":0}}))\n', encoding="utf-8")
    monkeypatch.setenv('CODEX_HOME', str(homes[2]))
    monkeypatch.setenv('OPC_CODEX_HOME', str(homes[1]))
    options = dict(binary=str(script))
    for index in range(3):
        if index == 2:
            monkeypatch.delenv('OPC_CODEX_HOME')
        worker = CodexWorker({**options, **({'codex_home': str(homes[0])} if index == 0 else {})})
        log = tmp_path / f'log-{index}'
        call, _ = worker._run('onboard', 'test', tmp_path, log, 'workspace-write', None)
        assert call.ok
        assert json.loads((log / 'onboard-request.json').read_text(encoding="utf-8"))['codex_home'] == str(homes[index])
        import os
        assert os.environ['CODEX_HOME'] == str(homes[2])
    with pytest.raises(OPCError, match='existing absolute directory'):
        CodexWorker({**options, 'codex_home': 'relative'})._run(
            'onboard', 'test', tmp_path, tmp_path / 'invalid-log', 'workspace-write', None)


def test_preparation_retry_preserves_call_logs_and_diagnostics(make_project, monkeypatch):
    from opc.adapters.worker import WorkerCall
    root = make_project()
    logs = []
    def worker(self, role, prompt, tree, log, sandbox, schema):
        log.mkdir(parents=True, exist_ok=True)
        (log / 'startup.txt').write_text('startup error ' + str(len(logs)), encoding="utf-8")
        logs.append(log)
        return WorkerCall(role, False, Cost(0, 0, None), call_id='startup-call',
                          error='Read-only file system', extra={'usage_complete': len(logs) > 1}), ''
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', worker)
    kw = dict(task_id='t-toy', max_tokens=100, max_wall_seconds=600,
              prior_tokens=0, prior_wall_seconds=0)
    result = onboard(root, 'codex', **kw)
    assert result['worker_error'] == 'Read-only file system'
    unknown = result['unresolved_accounting'][0]
    assert unknown['body']['call_id'] == 'startup-call'
    assert unknown['body']['log_dir'] == str(logs[0])
    assert unknown['body']['charged']['tokens'] == 0
    assert unknown['body']['error'] == 'Read-only file system'
    receipt = root / 'reconcile.json'
    receipt.write_text(json.dumps({'entries': [dict(event_seq=unknown['seq'],
        additional_tokens=0, additional_wall_seconds=0,
        evidence=(logs[0] / 'startup.txt').relative_to(root).as_posix(),
        reason='fixture confirms no model request')]}), encoding="utf-8")
    assert onboard(root, 'codex', reconcile_usage=receipt, **kw)['preparation'] == 'pending'
    assert len(logs) == 1
    assert onboard(root, 'codex', **kw)['preparation'] == 'pending'
    assert len(logs) == 2 and logs[0] != logs[1]
    assert (logs[0] / 'startup.txt').read_text(encoding="utf-8") == 'startup error 0'


@pytest.mark.parametrize('binary', [False, True])
def test_reviewed_preparation_survives_git_newline_conversion(make_project, engine_for, monkeypatch, binary):
    from opc.adapters.worker import WorkerCall
    from opc.tests.conftest import task, git
    root = make_project(tsk=task(preparation_review=True))
    git(root, 'config', 'core.autocrlf', 'true')
    if binary:
        (root / '.gitattributes').write_text('.opc/eval/*.py -text\n', encoding='utf-8')
        git(root, 'add', '.gitattributes')
        git(root, 'commit', '-qm', 'preserve evaluator bytes')
    evaluator = root / '.opc/eval/evaluate.py'

    def worker(self, role, prompt, tree, log, sandbox, schema):
        log.mkdir(parents=True)
        if role == 'onboard':
            # A Windows editor writes CRLF, which Git stores as LF on commit.
            evaluator.write_bytes(evaluator.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
            (log / 'checks.txt').write_text('verified evaluator', encoding='utf-8')
            reply = dict(state='ready', evidence=[(log / 'checks.txt').relative_to(root).as_posix()])
        else:
            reply = dict(verdict='accept')
        return WorkerCall(role, True, Cost(0, 0, None), extra={'usage_complete': True}), json.dumps(reply)

    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', worker)
    assert onboard(root, 'codex', task_id='t-toy', prior_tokens=0, prior_wall_seconds=0)['ok']
    git(root, 'add', '.opc')
    git(root, 'commit', '--allow-empty', '-qm', 'commit reviewed acceptance')
    check = engine_for(root).static_check()
    assert check['ok'], check['problems']
    evaluator.write_bytes(evaluator.read_bytes() + b'\r\n# changed after review\r\n')
    git(root, 'add', '.opc')
    git(root, 'commit', '-qm', 'unreviewed evaluator change')
    check = engine_for(root).static_check()
    assert not check['ok']
    assert any('prepared acceptance changed' in problem for problem in check['problems'])


def test_legacy_preparation_sha256_receipt_still_checked(make_project, engine_for):
    import hashlib
    from opc.core.workspace import git as repo_git
    root = make_project()
    relative = '.opc/eval/evaluate.py'
    digest = hashlib.sha256(repo_git('show', 'HEAD:' + relative, cwd=root, binary=True)).hexdigest()
    ledger = Ledger(root / '.opc/local/ledger.sqlite3')
    rid = ledger.create_run(task_id='t-toy', revision='preparation', task_digest='preparation',
                            component='preparation', base_commit='HEAD', evaluator_digest='',
                            toolchain_digest='', champion_ref='', direction='legacy receipt')
    ledger.event(rid, 'preparation', state='ready', files={relative: digest})
    assert engine_for(root).static_check()['ok']
    ledger.event(rid, 'preparation', state='ready', files={relative: '0' * 64})
    check = engine_for(root).static_check()
    assert not check['ok']
    assert any('prepared acceptance changed' in problem for problem in check['problems'])


def test_default_preparation_has_no_reviewer_and_scoped_files(make_project, monkeypatch):
    from opc.adapters.worker import WorkerCall
    from opc.scaffold.onboard import preparation_files
    root = make_project()
    calls = []
    def worker(self, role, prompt, tree, log, sandbox, schema):
        calls.append(role)
        log.mkdir(parents=True)
        (log / 'check.txt').write_text('integration checked', encoding="utf-8")
        return WorkerCall(role, True, Cost(0, 0, None), extra={'usage_complete': True}), json.dumps(
            dict(state='ready', evidence=[(log / 'check.txt').relative_to(root).as_posix()]))
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', worker)
    assert onboard(root, 'codex', task_id='t-toy', max_tokens=100, max_wall_seconds=600,
                   prior_tokens=0, prior_wall_seconds=0)['ok']
    assert calls == ['onboard']
    before = preparation_files(root, 't-toy')
    other = root / '.opc/tasks/unrelated/revisions/r0001/task.json'
    other.parent.mkdir(parents=True)
    other.write_text('{}', encoding="utf-8")
    assert preparation_files(root, 't-toy') == before
    (root / '.opc/eval/evaluate.py').write_text('changed shared evaluator', encoding="utf-8")
    assert preparation_files(root, 't-toy') != before


def test_preparation_review_retry_does_not_repeat_development(make_project, monkeypatch):
    from opc.adapters.worker import WorkerCall
    from opc.tests.conftest import task
    root = make_project(tsk=task(preparation_review=True))
    calls = []
    def worker(self, role, prompt, tree, log, sandbox, schema):
        calls.append(role)
        log.mkdir(parents=True)
        if role == 'onboard':
            (log / 'checks.txt').write_text('necessary checks', encoding="utf-8")
            reply = dict(state='ready', evidence=[(log / 'checks.txt').relative_to(root).as_posix()])
        else:
            reply = dict(verdict='reject' if len(calls) == 2 else 'accept')
        return WorkerCall(role, True, Cost(0, 0, None), extra={'usage_complete':True}), json.dumps(reply)
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', worker)
    kw = dict(task_id='t-toy', max_tokens=100, max_wall_seconds=600, prior_tokens=0, prior_wall_seconds=0)
    assert onboard(root, 'codex', **kw)['preparation'] == 'pending'
    assert onboard(root, 'codex', **kw)['ok']
    assert calls == ['onboard', 'reviewer', 'reviewer']


def test_preparation_candidate_is_not_reused_for_changed_brief(make_project, monkeypatch):
    from opc.adapters.worker import WorkerCall
    from opc.tests.conftest import task
    from opc.tests.test_brief import brief_project
    root = make_project(tsk=task(preparation_review=True))
    brief_project(root)
    brief = root / 'task-brief.md'
    calls = []
    def worker(self, role, prompt, tree, log, sandbox, schema):
        calls.append(role)
        log.mkdir(parents=True)
        if role == 'onboard':
            assert 'Target task ID: t-toy.' in prompt
            assert brief.read_text(encoding="utf-8") in prompt
            (log / 'checks.txt').write_text('focused checks', encoding="utf-8")
            reply = dict(state='ready', evidence=[(log / 'checks.txt').relative_to(root).as_posix()])
        else:
            reply = dict(verdict='reject')
        return WorkerCall(role, True, Cost(0, 0, None), extra={'usage_complete': True}), json.dumps(reply)
    monkeypatch.setattr('opc.adapters.codex.CodexWorker._run', worker)
    kw = dict(task_id='t-toy', brief=brief, prior_tokens=0, prior_wall_seconds=0)
    assert onboard(root, 'codex', **kw)['preparation'] == 'pending'
    brief.write_text(brief.read_text(encoding="utf-8") + '\nNew evidence changes the brief.\n', encoding="utf-8")
    assert onboard(root, 'codex', **kw)['preparation'] == 'pending'
    assert calls == ['onboard', 'reviewer', 'onboard', 'reviewer']
