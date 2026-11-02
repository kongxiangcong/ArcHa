"""Control acceptance at the real loopback HTTP → Engine boundary."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from opc.core.engine import Engine
from opc.tests.test_engine import CONTROLLED_DESIGN


@contextmanager
def observer(root, *, control=True):
    pytest.importorskip('fastapi')
    uvicorn = pytest.importorskip('uvicorn')
    from opc.observer.api import create_app
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    origin = 'http://127.0.0.1:%d' % port
    server = uvicorn.Server(uvicorn.Config(create_app(root, control=control), host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        until = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= until:
                raise RuntimeError('HTTP service did not become ready')
            time.sleep(.02)
        yield origin
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError('HTTP service did not exit')


def request(origin, path, body=None, headers=None):
    headers = {'Content-Type': 'application/json', 'Origin': origin, **(headers or {})}
    req = urllib.request.Request(origin + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def until(predicate, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError('bounded wait expired')


def run_path(origin, rid):
    from urllib.parse import quote
    _, overview = request(origin, '/api/observer/v1/overview')
    # Stable IDs are presentation identities, resolved through the public workbench.
    candidates = overview['data']['unlinked_runs']
    for task in overview['data']['tasks']:
        _, detail = request(origin, '/api/observer/v1/research-tasks/' + quote(task['id'], safe=''))
        candidates += detail['data']['runs']
    for candidate in candidates:
        encoded = quote(candidate['id'], safe='')
        _, workbench = request(origin, '/api/observer/v1/runs/' + encoded + '/workbench')
        if workbench['data']['source_run_id'] == rid:
            return encoded
    raise AssertionError('run not exposed')


def test_pause_http_is_received_before_engine_drains_designer(make_project, tmp_path):
    root = make_project(strategy=CONTROLLED_DESIGN)
    initial = Engine(root, 't-toy', log=lambda _: None)
    rid = initial.run(max_attempts_now=0)['run_id']
    ready, release = tmp_path / 'ready', tmp_path / 'release'
    env = {**os.environ, 'CONTROL_READY': str(ready), 'CONTROL_RELEASE': str(release)}
    child = subprocess.Popen([sys.executable, '-c',
        'from opc.core.engine import Engine; from pathlib import Path; import sys; Engine(Path(sys.argv[1]), "t-toy", run_id=sys.argv[2], log=lambda _: None).run(max_attempts_now=1)', str(root), rid], env=env)
    try:
        until(ready.exists)
        with observer(root) as origin:
            ident = run_path(origin, rid)
            path = '/api/control/v1/runs/' + ident + '/requests'
            code, accepted = request(origin, path, {'request_id': 'pause-one', 'action': 'pause'})
            assert code == 202
            assert accepted['data']['status'] == 'accepted'
            assert accepted['data']['run']['state'] == 'active'
            code, replay = request(origin, path, {'request_id': 'pause-one', 'action': 'pause'})
            assert code == 200 and replay['data'] == accepted['data']
            code, conflict = request(origin, path, {'request_id': 'pause-one', 'action': 'stop'})
            assert code == 409 and conflict['error']['code'] == 'request_conflict'
            release.touch()
            value = until(lambda: (lambda r: r if r[1]['data']['status'] == 'applied' else None)(request(origin, path + '/pause-one')))
            assert value[1]['data']['run']['state'] == 'paused'
            _, paused_scene = request(origin, '/api/observer/v1/runs/' + ident + '/workbench')
            assert '暂停' in paused_scene['data']['stop_reason'] and '结束' not in paused_scene['data']['stop_reason']
            _, works = request(origin, '/api/observer/v1/runs/' + ident + '/work-items')
            assert works['data']['items'][0]['stage'] == 'pending_evaluation'
        child.wait(timeout=10)
        assert child.returncode == 0
        roles = [c['role'] for c in initial.ledger.calls(rid)]
        assert roles.count('designer') == 1 and roles.count('evaluator') == 1
    finally:
        release.touch()
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)
        initial.ledger.close()


def test_control_readonly_security_replay_and_stale_pause_are_honest(make_project):
    root = make_project()
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    with observer(root, control=False) as origin:
        ident = run_path(origin, rid)
        path = '/api/control/v1/runs/' + ident + '/requests'
        assert request(origin, path, {'request_id': 'readonly', 'action': 'pause'})[0] == 403
        assert request(origin, path + '/readonly')[0] == 403
    with observer(root) as origin:
        ident = run_path(origin, rid)
        path = '/api/control/v1/runs/' + ident + '/requests'
        body = {'request_id': 'once', 'action': 'pause'}
        assert request(origin, path, body, {'Origin': 'https://other.example'})[0] == 403
        assert request(origin, path, body, {'Host': 'evil.example'})[0] == 403
        assert request(origin, path, body, {'Content-Type': 'text/plain'})[0] == 415
        assert request(origin, path, {**body, 'command': 'arbitrary'})[0] == 422
        assert request(origin, path, {**body, 'project': '/another/path'})[0] == 422
        assert request(origin, '/api/control/v1/runs/no-such-run/requests', body)[0] == 404
        code, result = request(origin, path, body)
        assert code == 202 and result['data']['status'] == 'applied'
        assert request(origin, path, body)[0] == 200
        second = Engine(root, 't-toy', log=lambda _: None).run(new_run=True, max_attempts_now=0)['run_id']
        second_path = '/api/control/v1/runs/' + run_path(origin, second) + '/requests'
        assert request(origin, second_path, body)[0] == 409
        # An old run_paused event is not application of a new pause request.
        engine.ledger.set_run_state(rid, 'active')
        code, stale = request(origin, path, {'request_id': 'not-consumed', 'action': 'pause'})
        assert code == 202 and stale['data']['status'] == 'unknown'
        assert stale['data']['run']['state'] == 'active'
    with observer(root) as restarted:
        ident = run_path(restarted, rid)
        _, preserved = request(restarted, '/api/control/v1/runs/' + ident + '/requests/not-consumed')
        assert preserved['data']['status'] == 'unknown'
    engine.ledger.close()


def test_control_get_does_not_initialize_execution_data(make_project):
    root = make_project()
    database = root / '.opc/local/ledger.sqlite3'
    assert not database.exists()
    with observer(root) as origin:
        assert request(origin, '/api/observer/v1/overview')[0] == 200
        assert request(origin, '/api/control/v1/runs/missing/requests/missing')[0] == 404
    assert not database.exists()


def test_pause_concurrent_pages_and_persistence_failure_keep_request_identity(make_project):
    from concurrent.futures import ThreadPoolExecutor
    import sqlite3
    root = make_project()
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    with observer(root) as first, observer(root) as second:
        ident = run_path(first, rid)
        path = '/api/control/v1/runs/' + ident + '/requests'
        body = {'request_id': 'two-pages', 'action': 'pause'}
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda origin: request(origin, path, body), [first, second, first, second]))
        assert sorted(code for code, _ in results) == [200, 200, 200, 202]
        assert {data['data']['sequence'] for _, data in results} == {results[0][1]['data']['sequence']}
        assert all(data['data']['status'] == 'applied' for _, data in results)
        with sqlite3.connect(root / '.opc/local/ledger.sqlite3', isolation_level=None) as blocked:
            blocked.execute('BEGIN IMMEDIATE')
            code, failure = request(first, path, {'request_id': 'write-failure', 'action': 'pause'})
            assert code == 503 and failure['error']['code'] == 'control_write_failed'
            blocked.execute('ROLLBACK')
        assert request(second, path + '/write-failure')[0] == 404
        assert len(engine.ledger.calls(rid)) == 1  # Baseline only, control never dispatches.
    engine.ledger.close()


PARALLEL_WORKER = '''
import json, os, time
from pathlib import Path
class Step:
    def __init__(self, options): pass
    def propose(self, ctx, tree):
        return {"works": [dict(work_id="branch-"+str(n), title="Parallel work "+str(n),
                hypothesis="Independent change", changes="Set parameter", expected="Lower loss",
                falsifier="Loss rises", evaluate=True, params={"x":4}) for n in range(4)]}
    def implement(self, plan, tree):
        ready = Path(os.environ['CONTROL_READY']); ready.mkdir(exist_ok=True)
        (ready / plan['work_id']).touch()
        while not Path(os.environ['CONTROL_RELEASE']).exists(): time.sleep(.02)
        (tree / 'params.json').write_text(json.dumps(plan['params']))
'''


@pytest.mark.parametrize('case', ['evaluation', 'parallel'])
def test_pause_http_drains_evaluation_and_parallel_calls_without_followup(make_project, tmp_path, case):
    from opc.tests.test_engine import CONTROLLED_EVALUATE
    root = make_project(**({'evaluate': CONTROLLED_EVALUATE} if case == 'evaluation' else {'strategy': PARALLEL_WORKER}))
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    ready, release = tmp_path / 'ready', tmp_path / 'release'
    env = {**os.environ, 'CONTROL_READY': str(ready), 'CONTROL_RELEASE': str(release)}
    child = subprocess.Popen([sys.executable, '-c',
        'from opc.core.engine import Engine; from pathlib import Path; import sys; Engine(Path(sys.argv[1]), "t-toy", run_id=sys.argv[2], log=lambda _: None).run()', str(root), rid], env=env)
    try:
        until(lambda: len(list(ready.iterdir())) == 3 if case == 'parallel' and ready.is_dir() else ready.is_file() if case == 'evaluation' else False)
        with observer(root) as origin:
            ident = run_path(origin, rid)
            path = '/api/control/v1/runs/' + ident + '/requests'
            code, accepted = request(origin, path, {'request_id': 'drain-' + case, 'action': 'pause'})
            assert code == 202 and accepted['data']['status'] == 'accepted'
            assert accepted['data']['run']['state'] == 'active'
            release.touch()
            _, finished = until(lambda: (lambda result: result if result[1]['data']['status'] == 'applied' else None)(request(origin, path + '/drain-' + case)))
            assert finished['data']['run'] == {'state': 'paused', 'execution_unknown': False}
        child.wait(timeout=10)
        assert child.returncode == 0
        calls = engine.ledger.calls(rid)
        assert sum(c['role'] == 'designer' for c in calls) == (3 if case == 'parallel' else 1)
        assert sum(c['role'] == 'evaluator' for c in calls) == (1 if case == 'parallel' else 2)
        assert sum(c['role'] == 'expert' for c in calls) == 1
        assert all(c['result'] is not None for c in calls)
    finally:
        release.touch()
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)
        engine.ledger.close()


def test_pause_browser_keeps_request_and_actual_state_separate(make_project, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    if not (Path(__file__).parents[1] / 'observer/static/index.html').is_file():
        pytest.skip('production frontend must be built for browser acceptance')
    root = make_project(strategy=CONTROLLED_DESIGN)
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    ready, release = tmp_path / 'ready', tmp_path / 'release'
    env = {**os.environ, 'CONTROL_READY': str(ready), 'CONTROL_RELEASE': str(release)}
    child = subprocess.Popen([sys.executable, '-c',
        'from opc.core.engine import Engine; from pathlib import Path; import sys; Engine(Path(sys.argv[1]), "t-toy", run_id=sys.argv[2], log=lambda _: None).run(max_attempts_now=1)', str(root), rid], env=env)
    try:
        until(ready.exists)
        with observer(root) as origin, playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport=dict(width=1440, height=1000), reduced_motion='reduce')
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(origin)
            page.get_by_role("button", name="工作列表", exact=True).click()
            ident = run_path(origin, rid)
            from urllib.parse import unquote
            page.get_by_label('选择运行', exact=True).select_option(unquote(ident))
            assert rid not in page.get_by_label('选择运行', exact=True).inner_text()
            playwright.expect(page.get_by_label('选择运行', exact=True).locator('option:checked')).to_contain_text('运行')
            pause = page.get_by_role('button', name='暂停', exact=True)
            playwright.expect(pause).to_be_enabled()
            page.locator('.work-button').first.click()
            playwright.expect(page.locator('.inspector')).to_be_visible()
            submitted = []
            def lose_response(route):
                accepted = route.fetch()
                assert accepted.status == 202
                submitted.append(json.loads(route.request.post_data))
                route.abort()  # The server accepted it; only the browser response is lost.
            page.route('**/api/control/v1/runs/*/requests', lose_response)
            pause.click()
            playwright.expect(page.locator('.run-status')).to_contain_text('请求已收到')
            playwright.expect(page.locator('.run-status strong')).to_have_text('运行记录中')
            playwright.expect(page.get_by_role('button', name='等待暂停', exact=True)).to_be_disabled()
            page.reload()
            playwright.expect(page.locator('.run-status')).to_contain_text('请求已收到')
            release.touch()
            playwright.expect(page.locator('.run-status strong')).to_have_text('已暂停', timeout=10000)
            playwright.expect(page.locator('.run-status')).to_contain_text('当前调用已收尾')
            playwright.expect(page.locator('.heading')).to_contain_text('暂停说明')
            playwright.expect(page.locator('.heading')).not_to_contain_text('结束原因')
            assert len(submitted) == 1  # Lost reply is queried with the same identity, never reposted.
            assert not errors
            out = Path(os.environ.get('ARCHA_CONTROL_BROWSER_OUT', str(tmp_path)))
            out.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out / 'pause-applied.png'))
            browser.close()
        child.wait(timeout=10)
        assert child.returncode == 0
    finally:
        release.touch()
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)
        engine.ledger.close()


def test_paused_run_with_unknown_execution_does_not_claim_all_calls_ended(make_project):
    root = make_project()
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    call = engine.ledger.begin_call(rid, None, 'designer', {}, str(root / '.opc/local/unconfirmed/receipt.json'))
    engine.ledger.db.execute("UPDATE calls SET state='unknown' WHERE call_id=?", (call,))
    with observer(root) as origin:
        ident = run_path(origin, rid)
        path = '/api/control/v1/runs/' + ident + '/requests'
        code, result = request(origin, path, {'request_id': 'paused-unknown', 'action': 'pause'})
        assert code == 202 and result['data']['status'] == 'unknown'
        assert result['data']['run'] == {'state': 'paused', 'execution_unknown': True}
        assert '待确认' in result['data']['reason']
        _, scene = request(origin, '/api/observer/v1/runs/' + ident + '/workbench')
        assert scene['data']['control_request']['status'] == 'unknown'
        assert not scene['data']['control']['resume']['enabled']
    engine.ledger.close()


def test_resume_http_uses_independent_process_and_reuses_same_run_results(make_project, tmp_path, monkeypatch):
    from opc.tests.test_engine import CONTROLLED_EVALUATE
    root = make_project(evaluate=CONTROLLED_EVALUATE)
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    calls_before = engine.ledger.calls(rid)
    spent_before = engine.ledger.totals(rid)
    ready, release = tmp_path / 'resume-ready', tmp_path / 'resume-release'
    monkeypatch.setenv('CONTROL_READY', str(ready))
    monkeypatch.setenv('CONTROL_RELEASE', str(release))
    with observer(root) as origin:
        ident = run_path(origin, rid)
        path = '/api/control/v1/runs/' + ident + '/requests'
        code, accepted = request(origin, path, {'request_id': 'resume-one', 'action': 'resume'})
        assert code == 202 and accepted['data']['status'] in ('accepted', 'processing', 'applied')
        until(ready.exists)
        assert request(origin, path, {'request_id': 'resume-one', 'action': 'resume'})[0] == 200
        _, restoring = request(origin, path + '/resume-one')
        assert restoring['data']['status'] == 'applied'
        assert restoring['data']['run']['state'] == 'active'
        # Pause must survive a late resume entrance and allow this evaluation to drain.
        assert request(origin, path, {'request_id': 'pause-resumed', 'action': 'pause'})[0] == 202
        release.touch()
        until(lambda: request(origin, path + '/pause-resumed')[1]['data']['status'] == 'applied')
        assert request(origin, path + '/resume-one')[1]['data']['status'] == 'applied'
        assert engine.ledger.run(rid)['state'] == 'paused'
        assert len(engine.ledger.runs()) == 1
        calls = engine.ledger.calls(rid)
        assert [c['call_id'] for c in calls[:len(calls_before)]] == [c['call_id'] for c in calls_before]
        assert sum(c['role'] == 'designer' for c in calls) == 1
        assert sum(c['role'] == 'evaluator' for c in calls) == 2
        assert engine.ledger.totals(rid)['wall_seconds'] >= spent_before['wall_seconds']
    engine.ledger.close()


def test_resume_failure_is_durable_and_same_identity_never_launches_again(make_project, monkeypatch):
    root = make_project()
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    import opc.observer.control as boundary
    starts = []
    def unavailable(*args, **kwargs):
        starts.append(args)
        raise OSError('controlled process creation failure')
    monkeypatch.setattr(boundary.subprocess, 'Popen', unavailable)
    with observer(root) as origin:
        ident = run_path(origin, rid)
        path = '/api/control/v1/runs/' + ident + '/requests'
        code, failed = request(origin, path, {'request_id': 'launch-failed', 'action': 'resume'})
        assert code == 202 and failed['data']['status'] == 'failed'
        assert failed['data']['run']['state'] == 'paused'
        assert '未能启动' in failed['data']['reason']
        assert request(origin, path, {'request_id': 'launch-failed', 'action': 'resume'})[0] == 200
        assert len(starts) == 1
        failure = engine.ledger.events(rid, 'control_execution_failed')[-1]['body']
        assert failure['request_id'] == 'launch-failed' and failure['action'] == 'resume'
        assert failure['error_type'] == 'OSError'
        assert failure['error'] == 'controlled process creation failure'
        assert failure['error'] not in failed['data']['reason']
    with observer(root) as restarted:
        ident = run_path(restarted, rid)
        assert request(restarted, '/api/control/v1/runs/' + ident + '/requests/launch-failed')[1]['data']['status'] == 'failed'
    engine.ledger.close()


def test_resume_restore_failure_and_project_lock_report_real_failure(make_project):
    root = make_project()
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    with observer(root) as origin:
        ident = run_path(origin, rid)
        path = '/api/control/v1/runs/' + ident + '/requests'
        with engine.ledger.writer():
            assert request(origin, path, {'request_id': 'locked-resume', 'action': 'resume'})[0] == 202
            result = until(lambda: (lambda value: value if value['data']['status'] == 'failed' else None)(request(origin, path + '/locked-resume')[1]))
            assert '已有运行端占用' in result['data']['reason']
            assert result['data']['run']['state'] == 'paused'
        frozen = engine.artifact_dir() / 'frozen/baseline.json'
        original = frozen.read_text()
        saved = json.loads(original)
        saved['execution']['task_digest'] = 'unavailable historical execution'
        frozen.write_text(json.dumps(saved))
        assert request(origin, path, {'request_id': 'restore-failed', 'action': 'resume'})[0] == 202
        result = until(lambda: (lambda value: value if value['data']['status'] == 'failed' else None)(request(origin, path + '/restore-failed')[1]))
        assert result['data']['run']['state'] == 'paused'
        assert len(engine.ledger.calls(rid)) == 1
        frozen.write_text(original)
    engine.ledger.close()


def test_resume_preparation_pause_is_not_overwritten_and_disconnected_service_can_query(make_project, tmp_path, monkeypatch):
    from opc.tests.conftest import component
    command = 'import os,time; from pathlib import Path; r=os.environ.get("RESUME_PREPARING"); exec("if r:\\n Path(r).touch()\\n while not Path(os.environ[\'RESUME_RELEASE\']).exists(): time.sleep(.02)"); print("stable tool")'
    root = make_project(comp=component(toolchain=[[sys.executable, '-c', command]]))
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    ready, release = tmp_path / 'preparing', tmp_path / 'release'
    monkeypatch.setenv('RESUME_PREPARING', str(ready))
    monkeypatch.setenv('RESUME_RELEASE', str(release))
    try:
        with observer(root) as origin:
            ident = run_path(origin, rid)
            path = '/api/control/v1/runs/' + ident + '/requests'
            assert request(origin, path, {'request_id': 'preparing', 'action': 'resume'})[0] == 202
            until(ready.exists)
            assert request(origin, path + '/preparing')[1]['data']['status'] == 'processing'
            assert request(origin, path, {'request_id': 'another-preparation', 'action': 'resume'})[0] == 409
        # The HTTP service exits while the separate execution process still holds the project.
        with observer(root) as restarted:
            ident = run_path(restarted, rid)
            path = '/api/control/v1/runs/' + ident + '/requests'
            assert request(restarted, path + '/preparing')[1]['data']['status'] == 'processing'
            assert request(restarted, path, {'request_id': 'later-pause', 'action': 'pause'})[0] == 202
            release.touch()
            result = until(lambda: request(restarted, path + '/later-pause')[1]['data']['status'] == 'applied')
            assert result
            assert request(restarted, path + '/preparing')[1]['data']['status'] == 'superseded'
            assert len(engine.ledger.calls(rid)) == 1  # No new work passed the later pause.
    finally:
        release.touch()
        engine.ledger.close()


def test_resume_concurrent_services_and_already_running_do_not_duplicate_execution(make_project, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from opc.tests.test_engine import CONTROLLED_EVALUATE
    root = make_project(evaluate=CONTROLLED_EVALUATE)
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    ready, release = tmp_path / 'ready', tmp_path / 'release'
    monkeypatch.setenv('CONTROL_READY', str(ready))
    monkeypatch.setenv('CONTROL_RELEASE', str(release))
    try:
        with observer(root) as first, observer(root) as second:
            ident = run_path(first, rid)
            path = '/api/control/v1/runs/' + ident + '/requests'
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(lambda origin: request(origin, path, {'request_id': 'shared-resume', 'action': 'resume'}), [first, second]))
            assert sorted(code for code, _ in replies) == [200, 202]
            until(ready.exists)
            code, already = request(second, path, {'request_id': 'already-running', 'action': 'resume'})
            assert code == 202 and already['data']['status'] == 'applied'
            assert '未重复启动' in already['data']['reason']
            assert request(first, path, {'request_id': 'finish-pause', 'action': 'pause'})[0] == 202
            release.touch()
            until(lambda: request(second, path + '/finish-pause')[1]['data']['status'] == 'applied')
            assert sum(c['role'] == 'designer' for c in engine.ledger.calls(rid)) == 1
            assert sum(c['role'] == 'evaluator' for c in engine.ledger.calls(rid)) == 2
    finally:
        release.touch()
        engine.ledger.close()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX abrupt execution loss injection')
def test_resume_lost_execution_is_unknown_after_service_restart_and_never_relaunched(make_project, tmp_path, monkeypatch):
    import signal
    from opc.tests.conftest import component
    command = 'import os,time; from pathlib import Path; r=os.environ.get("RESUME_PREPARING"); exec("if r:\\n Path(r).touch()\\n while not Path(os.environ[\'RESUME_RELEASE\']).exists(): time.sleep(.02)"); print("stable tool")'
    root = make_project(comp=component(toolchain=[[sys.executable, '-c', command]]))
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    ready, release = tmp_path / 'preparing', tmp_path / 'release'
    monkeypatch.setenv('RESUME_PREPARING', str(ready))
    monkeypatch.setenv('RESUME_RELEASE', str(release))
    other_child = None
    other_release = tmp_path / 'other-release'
    try:
        with observer(root) as origin:
            ident = run_path(origin, rid)
            path = '/api/control/v1/runs/' + ident + '/requests'
            assert request(origin, path, {'request_id': 'lost-resume', 'action': 'resume'})[0] == 202
            until(ready.exists)
            started = engine.ledger.events(rid, 'control_execution_started')
            assert len(started) == 1
            os.kill(started[0]['body']['owner_pid'], signal.SIGKILL)
            until(lambda: request(origin, path + '/lost-resume')[1]['data']['status'] == 'unknown')
        release.touch()
        monkeypatch.delenv('RESUME_PREPARING')
        other = Engine(root, 't-toy', log=lambda _: None)
        other_rid = other.run(new_run=True, max_attempts_now=0)['run_id']
        other.ledger.close()
        other_ready = tmp_path / 'other-ready'
        other_env = {**os.environ, 'RESUME_PREPARING': str(other_ready), 'RESUME_RELEASE': str(other_release)}
        other_child = subprocess.Popen([sys.executable, '-c', 'from pathlib import Path; import sys; from opc.core.engine import Engine; Engine(Path(sys.argv[1]), "t-toy", run_id=sys.argv[2], log=lambda _: None).run(max_attempts_now=0)', str(root), other_rid], env=other_env)
        until(other_ready.exists)
        with observer(root) as restarted:
            ident = run_path(restarted, rid)
            path = '/api/control/v1/runs/' + ident + '/requests'
            result = until(lambda: (lambda reply: reply if reply['data']['status'] == 'unknown' else None)(request(restarted, path + '/lost-resume')[1]))
            assert '不会自动' in result['data']['reason']
            assert request(restarted, path, {'request_id': 'lost-resume', 'action': 'resume'})[1]['data']['status'] == 'unknown'
            assert request(restarted, path, {'request_id': 'new-unsafe-retry', 'action': 'resume'})[0] == 409
            _, scene = request(restarted, '/api/observer/v1/runs/' + ident + '/workbench')
            assert scene['data']['control_request']['status'] == 'unknown'
            assert not scene['data']['control']['resume']['enabled']
            assert len(engine.ledger.events(rid, 'control_execution_started')) == 1
    finally:
        release.touch()
        other_release.touch()
        if other_child:
            other_child.wait(timeout=10)
        engine.ledger.close()


def test_resume_browser_preserves_scene_through_pause_continue_and_failure(make_project, tmp_path, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    from opc.tests.test_engine import CONTROLLED_EVALUATE
    root = make_project(strategy=CONTROLLED_DESIGN, evaluate=CONTROLLED_EVALUATE)
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    ready, release = tmp_path / 'design-ready', tmp_path / 'design-release'
    env = {**os.environ, 'CONTROL_READY': str(ready), 'CONTROL_RELEASE': str(release)}
    child = subprocess.Popen([sys.executable, '-c', 'from opc.core.engine import Engine; from pathlib import Path; import sys; Engine(Path(sys.argv[1]), "t-toy", run_id=sys.argv[2], log=lambda _: None).run(max_attempts_now=1)', str(root), rid], env=env)
    resumed_release = tmp_path / 'evaluation-release'
    try:
        until(ready.exists)
        with observer(root) as origin, playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport=dict(width=1440, height=1000), reduced_motion='reduce')
            page.goto(origin)
            page.get_by_role("button", name="工作列表", exact=True).click()
            ident = run_path(origin, rid)
            from urllib.parse import unquote
            page.get_by_label('选择运行', exact=True).select_option(unquote(ident))
            page.locator('.work-button').first.click()
            playwright.expect(page.locator('.inspector')).to_be_visible()
            page.get_by_role('button', name='暂停', exact=True).click()
            playwright.expect(page.get_by_role('button', name='等待暂停', exact=True)).to_be_disabled()
            release.touch()
            playwright.expect(page.get_by_role('button', name='继续', exact=True)).to_be_enabled(timeout=10000)
            child.wait(timeout=10)
            saved_url = page.url
            resumed_ready = tmp_path / 'evaluation-ready'
            monkeypatch.setenv('CONTROL_READY', str(resumed_ready))
            monkeypatch.setenv('CONTROL_RELEASE', str(resumed_release))
            page.get_by_role('button', name='继续', exact=True).click()
            until(resumed_ready.exists)
            playwright.expect(page.locator('.run-status')).to_contain_text('已恢复原运行')
            playwright.expect(page.locator('.inspector')).to_be_visible()
            assert page.url == saved_url
            page.get_by_role('button', name='暂停', exact=True).click()
            playwright.expect(page.get_by_role('button', name='等待暂停', exact=True)).to_be_disabled()
            playwright.expect(page.locator('.run-status')).to_contain_text('请求已收到')
            resumed_release.touch()
            playwright.expect(page.get_by_role('button', name='继续', exact=True)).to_be_enabled(timeout=10000)
            assert sum(c['role'] == 'designer' for c in engine.ledger.calls(rid)) == 1
            assert sum(c['role'] == 'evaluator' for c in engine.ledger.calls(rid)) == 2
            frozen = engine.artifact_dir() / 'frozen/baseline.json'
            saved = json.loads(frozen.read_text())
            saved['execution']['task_digest'] = 'controlled unavailable source'
            frozen.write_text(json.dumps(saved))
            page.get_by_role('button', name='继续', exact=True).click()
            playwright.expect(page.locator('.run-status')).to_contain_text('恢复失败', timeout=10000)
            playwright.expect(page.locator('.run-status strong')).to_have_text('已暂停')
            playwright.expect(page.locator('.inspector')).to_be_visible()
            assert page.url == saved_url
            playwright.expect(page.get_by_label('选择工作调用')).not_to_contain_text('已派发，结果待确认')
            playwright.expect(page.locator('.run-status')).not_to_contain_text('identity')
            out = Path(os.environ.get('ARCHA_CONTROL_BROWSER_OUT', str(tmp_path)))
            out.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out / 'resume-failure-scene.png'))
            browser.close()
    finally:
        release.touch()
        resumed_release.touch()
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)
        engine.ledger.close()


def test_resume_immediate_completion_returns_actual_closed_run_without_new_run(make_project):
    root = make_project(x=7)
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    frozen = (engine.artifact_dir() / 'frozen/baseline.json').read_bytes()
    original = engine.ledger.calls(rid)[0]
    with observer(root) as origin:
        ident = run_path(origin, rid)
        path = '/api/control/v1/runs/' + ident + '/requests'
        assert request(origin, path, {'request_id': 'finish-immediately', 'action': 'resume'})[0] == 202
        result = until(lambda: (lambda value: value if value['data']['run']['state'] == 'closed' else None)(request(origin, path + '/finish-immediately')[1]))
        assert result['data']['status'] == 'applied'
        assert '已结束' in result['data']['reason']
        assert request(origin, path, {'request_id': 'finish-immediately', 'action': 'resume'})[0] == 200
        assert request(origin, path, {'request_id': 'not-a-new-run', 'action': 'resume'})[0] == 409
        assert len(engine.ledger.runs()) == 1
        assert engine.ledger.calls(rid)[0] == original
        assert (engine.artifact_dir() / 'frozen/baseline.json').read_bytes() == frozen
    engine.ledger.close()


def test_stop_paused_run_closes_without_resuming_or_dispatching_and_replays_closed(make_project):
    root = make_project()
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    before = engine.ledger.calls(rid)
    usage = engine.ledger.totals(rid)
    with observer(root) as origin:
        ident = run_path(origin, rid)
        path = '/api/control/v1/runs/' + ident + '/requests'
        with engine.ledger.writer():
            code, occupied = request(origin, path, {'request_id': 'stop-occupied', 'action': 'stop'})
            assert code == 202 and occupied['data']['status'] == 'failed'
            assert engine.ledger.calls(rid) == before and engine.ledger.run(rid)['state'] == 'paused'
        code, received = request(origin, path, {'request_id': 'stop-paused', 'action': 'stop'})
        assert code == 202
        _, result = until(lambda: (lambda value: value if value[1]['data']['status'] == 'applied' else None)(request(origin, path + '/stop-paused')))
        assert result['data']['run'] == {'state': 'closed', 'execution_unknown': False}
        assert engine.ledger.calls(rid) == before
        assert engine.ledger.totals(rid) == usage
        assert len(engine.ledger.runs()) == 1
        assert request(origin, path, {'request_id': 'stop-paused', 'action': 'stop'})[0] == 200
        code, repeated = request(origin, path, {'request_id': 'stop-closed', 'action': 'stop'})
        assert code == 202 and repeated['data']['status'] == 'applied'
        assert repeated['data']['run']['state'] == 'closed'
        assert request(origin, path, {'request_id': 'resume-closed', 'action': 'resume'})[0] == 409
    engine.ledger.close()


def test_stop_active_call_cancels_without_followup_dispatch(make_project, tmp_path):
    root = make_project(strategy=CONTROLLED_DESIGN)
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    ready, release = tmp_path / 'ready', tmp_path / 'release'
    env = {**os.environ, 'CONTROL_READY': str(ready), 'CONTROL_RELEASE': str(release)}
    child = subprocess.Popen([sys.executable, '-c', 'from opc.core.engine import Engine; from pathlib import Path; import sys; Engine(Path(sys.argv[1]), "t-toy", run_id=sys.argv[2], log=lambda _: None).run()', str(root), rid], env=env)
    try:
        until(ready.exists)
        with observer(root) as origin:
            ident = run_path(origin, rid)
            path = '/api/control/v1/runs/' + ident + '/requests'
            code, received = request(origin, path, {'request_id': 'stop-active', 'action': 'stop'})
            assert code == 202
            _, stopped = until(lambda: (lambda result: result if result[1]['data']['status'] == 'applied' else None)(request(origin, path + '/stop-active')))
            assert stopped['data']['run'] == {'state': 'closed', 'execution_unknown': False}
            assert '完成' in stopped['data']['reason']  # Explicitly says stopping is not task completion.
        child.wait(timeout=10)
        assert child.returncode == 0
        calls = engine.ledger.calls(rid)
        assert sum(c['role'] == 'designer' for c in calls) == 1
        assert sum(c['role'] == 'evaluator' for c in calls) == 1
        assert all(c['result'] is not None for c in calls)
    finally:
        release.touch()
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)
        engine.ledger.close()


def test_stop_during_restore_supersedes_resume_without_dispatch(make_project, tmp_path, monkeypatch):
    from opc.tests.conftest import component
    command = 'import os,time; from pathlib import Path; r=os.environ.get("RESUME_PREPARING"); exec("if r:\\n Path(r).touch()\\n while not Path(os.environ[\'RESUME_RELEASE\']).exists(): time.sleep(.02)"); print("stable tool")'
    root = make_project(comp=component(toolchain=[[sys.executable, '-c', command]]))
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    before = engine.ledger.calls(rid)
    ready, release = tmp_path / 'preparing', tmp_path / 'release'
    monkeypatch.setenv('RESUME_PREPARING', str(ready))
    monkeypatch.setenv('RESUME_RELEASE', str(release))
    try:
        with observer(root) as origin:
            ident = run_path(origin, rid)
            path = '/api/control/v1/runs/' + ident + '/requests'
            assert request(origin, path, {'request_id': 'restore-to-stop', 'action': 'resume'})[0] == 202
            until(ready.exists)
            assert request(origin, path, {'request_id': 'later-stop', 'action': 'stop'})[0] == 202
            assert request(origin, path + '/restore-to-stop')[1]['data']['status'] == 'superseded'
            release.touch()
            _, stopped = until(lambda: (lambda value: value if value[1]['data']['status'] == 'applied' else None)(request(origin, path + '/later-stop')))
            assert stopped['data']['run']['state'] == 'closed'
            assert engine.ledger.calls(rid) == before
    finally:
        release.touch()
        engine.ledger.close()


def test_stop_unconfirmed_execution_retains_saved_workspace_and_feedback(make_project, tmp_path):
    root = make_project()
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    tree = root / '.opc/local/unknown-work'
    tree.mkdir()
    (tree / 'work.txt').write_text('saved task progress')
    call = engine.ledger.begin_call(rid, None, 'designer', {'tree': str(tree)}, str(tree / 'receipt.json'))
    engine.ledger.db.execute("UPDATE calls SET state='unknown' WHERE call_id=?", (call,))
    with observer(root) as origin:
        ident = run_path(origin, rid)
        path = '/api/control/v1/runs/' + ident + '/requests'
        assert request(origin, path, {'request_id': 'stop-unconfirmed', 'action': 'stop'})[0] == 202
        _, result = until(lambda: (lambda value: value if value[1]['data']['status'] == 'unknown' and value[1]['data']['run']['execution_unknown'] else None)(request(origin, path + '/stop-unconfirmed')))
        assert result['data']['run'] == {'state': 'blocked', 'execution_unknown': True}
        assert '待确认' in result['data']['reason']
        assert (tree / 'work.txt').read_text() == 'saved task progress'
        assert engine.ledger.calls(rid)[-1]['result'] is None
        assert request(origin, path, {'request_id': 'unsafe-resume', 'action': 'resume'})[0] == 409
    engine.ledger.close()


@pytest.mark.parametrize('unconfirmed', [False, True])
def test_stop_browser_confirmation_focus_and_actual_or_unknown_result(make_project, tmp_path, unconfirmed):
    playwright = pytest.importorskip('playwright.sync_api')
    if not (Path(__file__).parents[1] / 'observer/static/index.html').is_file():
        pytest.skip('production frontend must be built for browser acceptance')
    root = make_project()
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=1)['run_id']
    before = len(engine.ledger.calls(rid))
    if unconfirmed:
        tree = root / '.opc/local/unconfirmed-work'
        tree.mkdir()
        (tree / 'task.txt').write_text('keep task work')
        call = engine.ledger.begin_call(rid, 1, 'designer', {'tree': str(tree)}, str(tree / 'receipt.json'))
        engine.ledger.db.execute("UPDATE calls SET state='unknown' WHERE call_id=?", (call,))
        before += 1
    try:
        with observer(root) as origin, playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport=dict(width=1440, height=1000), reduced_motion='reduce')
            page = context.new_page()
            errors, posts = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.set_default_timeout(5000)
            page.on('request', lambda req: posts.append(json.loads(req.post_data)) if req.method == 'POST' else None)
            page.goto(origin)
            page.get_by_role("button", name="工作列表", exact=True).click()
            ident = run_path(origin, rid)
            from urllib.parse import unquote
            page.get_by_label('选择运行', exact=True).select_option(unquote(ident))
            page.locator('.work-button').first.click()
            playwright.expect(page.locator('.inspector')).to_be_visible()
            stop = page.get_by_role('button', name='停止', exact=True)
            playwright.expect(stop).to_be_enabled()
            stop.click()
            dialog = page.get_by_role('dialog', name='停止当前运行？')
            playwright.expect(dialog).to_be_visible()
            playwright.expect(dialog.get_by_role('button', name='取消', exact=True)).to_be_focused()
            page.keyboard.press('Tab')
            playwright.expect(dialog.get_by_role('button', name='确认停止', exact=True)).to_be_focused()
            page.keyboard.press('Tab')
            assert page.evaluate('document.querySelector("dialog").contains(document.activeElement)')
            page.keyboard.press('Escape')
            playwright.expect(dialog).not_to_be_visible()
            playwright.expect(stop).to_be_focused()
            playwright.expect(page.locator('.inspector')).to_be_visible()
            assert not posts
            stop.click()
            dialog.get_by_role('button', name='取消', exact=True).click()
            assert not posts
            playwright.expect(stop).to_be_focused()
            page.set_viewport_size(dict(width=390, height=844))
            stop.click()
            assert page.evaluate('document.querySelector("dialog").getBoundingClientRect().right <= innerWidth')
            page.set_viewport_size(dict(width=1440, height=1000))
            dialog.get_by_role('button', name='确认停止', exact=True).click()
            expected = '需要处理' if unconfirmed else '已结束'
            playwright.expect(page.locator('.run-status strong')).to_have_text(expected, timeout=10000)
            playwright.expect(page.locator('.run-status')).to_contain_text('待确认' if unconfirmed else '停止不代表任务已完成')
            assert len(posts) == 1 and posts[0]['action'] == 'stop'
            assert len(engine.ledger.calls(rid)) == before
            if unconfirmed:
                playwright.expect(page.locator('.notice').filter(has_text='仍有执行结果')).not_to_contain_text('暂停')
                assert (tree / 'task.txt').read_text() == 'keep task work'
                playwright.expect(page.get_by_role('button', name='继续', exact=True)).to_be_disabled()
            assert not errors
            text = page.locator('body').inner_text()
            assert 'sha256' not in text and 'audit' not in text and 'evidence_refs' not in text
            out = Path(os.environ.get('ARCHA_CONTROL_BROWSER_OUT', str(tmp_path)))
            out.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out / ('stop-unknown.png' if unconfirmed else 'stop-applied.png')))
            browser.close()
    finally:
        engine.ledger.close()


def test_active_stop_cannot_confirm_termination_retains_call_and_workspace(make_project, tmp_path):
    if os.name == 'nt':
        pytest.skip('POSIX cancellation failure injection; shared stop behavior is covered above')
    resistant = CONTROLLED_DESIGN.replace('import time; from pathlib',
        'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); from pathlib')
    root = make_project(strategy=resistant)
    engine = Engine(root, 't-toy', log=lambda _: None)
    rid = engine.run(max_attempts_now=0)['run_id']
    ready, release = tmp_path / 'ready', tmp_path / 'release'
    env = {**os.environ, 'CONTROL_READY': str(ready), 'CONTROL_RELEASE': str(release)}
    code = '''import os,signal,sys
from pathlib import Path
from opc.core.engine import Engine
original=os.killpg
def deny(pid,sig):
    if sig == signal.SIGKILL and Path(os.environ["CONTROL_READY"]).exists(): raise PermissionError("controlled cancellation unconfirmed")
    original(pid,sig)
os.killpg=deny
Engine(Path(sys.argv[1]),"t-toy",run_id=sys.argv[2],log=lambda _:None).run()
'''
    child = subprocess.Popen([sys.executable, '-c', code, str(root), rid], env=env)
    try:
        until(ready.exists)
        with observer(root) as origin:
            ident = run_path(origin, rid)
            path = '/api/control/v1/runs/' + ident + '/requests'
            assert request(origin, path, {'request_id': 'unconfirmed-active-stop', 'action': 'stop'})[0] == 202
            _, result = until(lambda: (lambda value: value if value[1]['data']['status'] == 'unknown' and value[1]['data']['run']['execution_unknown'] else None)(request(origin, path + '/unconfirmed-active-stop')), seconds=15)
            assert result['data']['run'] == {'state': 'blocked', 'execution_unknown': True}
            designer = next(c for c in engine.ledger.calls(rid) if c['role'] == 'designer')
            assert designer['result'] is None and Path(designer['input']['tree']).is_dir()
            assert sum(c['role'] == 'evaluator' for c in engine.ledger.calls(rid)) == 1
        child.wait(timeout=10)
    finally:
        release.touch()
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)
        import signal
        for record in engine.ledger.calls(rid):
            if record['role'] == 'designer':
                process = Path(record['receipt_path']).parent / 'process.json'
                if process.exists():
                    try:
                        os.killpg(json.loads(process.read_text())['pid'], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        engine.ledger.close()
