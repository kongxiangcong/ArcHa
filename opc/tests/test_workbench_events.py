"""Incremental trace contract through HTTP, with file-protocol producers."""
import json
import os
from fastapi.testclient import TestClient
from opc.core.workspace import TopicWorkspace
from opc.observer.api import create_app


def publish(path, stream, count):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(''.join(json.dumps(dict(seq=n, ts=stream, kind='lifecycle', title='started' if n == 1 else 'event', status='running', detail=None)) + '\n' for n in range(1, count + 1)))
    os.replace(temporary, path)


def test_incremental_stream_pagination_replacement_and_partial_lines(tmp_path):
    workspace = TopicWorkspace(tmp_path, 'trace')
    workspace.initialize('Trace', 2)
    step = workspace.path / 'steps/step-01'
    step.mkdir()
    path = step / '.expert.events.jsonl'
    url = '/api/observer/v1/topics/trace/steps/1/events'
    with TestClient(create_app(tmp_path)) as client:
        empty = client.get(url, params=dict(role='expert', stream='old', after_seq=100)).json()
        assert empty['stream'] is None and empty['reset'] and empty['next_seq'] == 0
        for stream, count in [('short', 2), ('long', 205)]:
            publish(path, stream, count)
            first = client.get(url, params=dict(role='expert', stream='old', after_seq=100)).json()
            assert first['reset'] and first['events'][0]['seq'] == 1
            assert len(first['events']) == min(count, 200)
            assert first['more'] == (count > 200)
            rest = client.get(url, params=dict(role='expert', stream=stream, after_seq=first['next_seq'])).json()
            assert not rest['reset'] and len(rest['events']) == max(0, count - 200)
        with path.open('a') as output:
            output.write('{"seq":206')
        value = client.get(url, params=dict(role='expert', stream='long', after_seq=205)).json()
        assert value['events'] == [] and not value['more'] and not value['diagnostic']
        with path.open('a') as output:
            output.write(',"ts":"long","kind":"lifecycle","title":"completed","status":"ok","detail":null}\n')
        assert client.get(url, params=dict(role='expert', stream='long', after_seq=205)).json()['next_seq'] == 206
        assert client.get(url, params=dict(role='nope')).status_code == 422
        assert client.get(url, params=dict(role='expert', after_seq=-1)).status_code == 422
        assert client.get('/api/observer/v1/materials', params=dict(path=str(path.relative_to(tmp_path)))).status_code == 403
        path.unlink()
        outside = tmp_path.parent / 'secret-events'
        outside.write_text('{}\n')
        path.symlink_to(outside)
        assert client.get(url, params=dict(role='expert')).status_code == 403


def test_observation_failure_is_not_legacy_empty_trace(tmp_path):
    workspace = TopicWorkspace(tmp_path, 'trace')
    workspace.initialize('Trace', 2)
    step = workspace.path / 'steps/step-01'
    step.mkdir()
    (step / '.expert.events.jsonl').mkdir()
    (step / '.expert.log').write_text('Telemetry incomplete: unpublished stream: permission denied\nvalid worker output\n')
    with TestClient(create_app(tmp_path)) as client:
        value = client.get('/api/observer/v1/topics/trace/steps/1/events', params=dict(role='expert')).json()
        assert value['stream'] is None and value['events'] == []
        assert 'permission denied' in value['diagnostic']
