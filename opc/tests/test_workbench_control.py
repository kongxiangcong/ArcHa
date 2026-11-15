import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient
from opc.core.workspace import TopicWorkspace
from opc.observer.api import create_app

PREFIX = '/api/observer/v1/topics/research'

def setup(root):
    w = TopicWorkspace(root, 'research')
    w.initialize('Check evidence', 1)
    config = {'roles': {'expert': {'command': [sys.executable, '-c', 'import time; print("live",flush=True); time.sleep(30)'], 'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 40}, 'executor': {'preset': 'scripted'}}}
    (root / '.archa/workers.json').write_text(json.dumps(config))
    return w

def test_two_pages_resume_once_and_stale_stop_preserves_new_execution(tmp_path):
    setup(tmp_path)
    with TestClient(create_app(tmp_path, control=True)) as client:
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(lambda _: client.post(PREFIX + '/resume', json={}), range(2)))
        assert sorted(r.status_code for r in replies) == [202, 409]
        first = client.get(PREFIX).json()['execution']['id']
        assert client.post(PREFIX + '/stop', json={'execution_id': first}).json()['activity'] == 'idle'
        assert client.post(PREFIX + '/resume', json={}).status_code == 202
        second = client.get(PREFIX).json()['execution']['id']
        assert second != first
        assert client.post(PREFIX + '/stop', json={'execution_id': first}).json()['execution']['id'] == second
        assert client.post(PREFIX + '/stop', json={'execution_id': second}).json()['activity'] == 'idle'

def wait_idle(client):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        detail = client.get(PREFIX).json()
        if detail['activity'] == 'idle':
            return detail
        time.sleep(.02)
    raise AssertionError('execution did not finish')


def test_resume_budget_blocked_completed_and_failure(tmp_path):
    w = setup(tmp_path)
    config = {'roles': {role: {'preset': 'scripted'} for role in ('expert', 'executor')}}
    (tmp_path / '.archa/workers.json').write_text(json.dumps(config))
    state = w.path / 'STATE.md'
    state.write_text(state.read_text().replace('IN_PROGRESS', 'BLOCKED'))
    with TestClient(create_app(tmp_path, control=True)) as client:
        assert client.post(PREFIX + '/resume', json={}).status_code == 202
        detail = wait_idle(client)
        assert (detail['status'], detail['completed_rounds']) == ('BUDGET_EXHAUSTED', 1)
        assert client.post(PREFIX + '/resume', json={}).status_code == 409
        assert client.post(PREFIX + '/resume', json={'add_rounds': 1}).status_code == 202
        detail = wait_idle(client)
        assert (detail['max_rounds'], detail['completed_rounds']) == (2, 2)
        state.write_text(state.read_text().replace('BUDGET_EXHAUSTED', 'COMPLETED'))
        assert client.post(PREFIX + '/resume', json={'add_rounds': 1}).status_code == 409
        assert client.get(PREFIX).json()['max_rounds'] == 2
        for invalid in (0, -1, True, '1'):
            assert client.post(PREFIX + '/resume', json={'add_rounds': invalid}).status_code == 422
        state.write_text(state.read_text().replace('COMPLETED', 'IN_PROGRESS'))
        config['roles']['expert'] = {'command': [sys.executable, '-c', 'import sys; print("failed evidence",flush=True); sys.exit(9)'], 'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 10}
        (tmp_path / '.archa/workers.json').write_text(json.dumps(config))
        assert client.post(PREFIX + '/resume', json={}).status_code == 202
        detail = wait_idle(client)
        assert detail['error'] and detail['status'] == 'IN_PROGRESS'
        path = detail['rounds'][-1]['logs'][-1]['path']
        assert 'failed evidence' in client.get('/api/observer/v1/materials', params={'path': path}).json()['text']


def test_control_disabled_and_unknown_owner_are_explicit(tmp_path):
    w = setup(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(PREFIX + '/resume', json={}).status_code == 403
    record = {'id': 'abandoned', 'topic': 'research', 'controller': None, 'worker': 'starting', 'role': 'expert', 'round': 1, 'started_at': '2026-01-01T00:00:00Z'}
    (w.control / '.execution.json').write_text(json.dumps(record))
    with TestClient(create_app(tmp_path, control=True)) as client:
        assert client.get(PREFIX).json()['activity'] == 'unknown'
        assert client.post(PREFIX + '/resume', json={}).status_code == 409
        assert client.post(PREFIX + '/stop', json={'execution_id': 'abandoned'}).status_code == 409
        assert client.get(PREFIX).json()['activity'] == 'unknown'


def test_probe_breakpoint_http_continue_and_read_only_materials(tmp_path):
    w = setup(tmp_path)
    with w.writer():
        w.resume(1)
    (tmp_path / '.archa/workers.json').write_text(json.dumps({
        'roles': {role: {'preset': 'scripted'} for role in ('expert', 'executor')}}))
    with TestClient(create_app(tmp_path, control=True)) as client:
        assert client.post(PREFIX + '/resume', json={'debug_probes': True}).status_code == 202
        detail = wait_idle(client)
        assert detail['probe_breakpoint'] and detail['completed_rounds'] == 0
        probe = detail['current_probe']
        assert probe['name'] == 'probe.md'
        assert client.get('/api/observer/v1/materials', params={'path': probe['path']}).json()['text']
        assert client.get(PREFIX).json()['completed_rounds'] == 0
        assert client.post(PREFIX + '/resume', json={}).status_code == 202
        detail = wait_idle(client)
        assert detail['probe_breakpoint'] and detail['completed_rounds'] == 1
        assert detail['current_round'] == 2 and detail['error'] is None
        assert client.post(PREFIX + '/resume', json={'debug_probes': False}).status_code == 202
        detail = wait_idle(client)
        assert detail['status'] == 'BUDGET_EXHAUSTED' and not detail['debug_probes']
        assert detail['current_probe'] is None
        assert client.post(PREFIX + '/resume', json={'debug_probes': 'true'}).status_code == 422
