import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opc.log import read, update, pending, target
from opc.core.ledger import Ledger
from opc.observer.api import create_app
from opc.tests.test_observer_canvas import source


def prose(root, run, units):
    return [dict(key=u['key'], summary='本轮检查容量边界，已有局部检查结果，释放后的恢复行为尚未验证。', problem='需要确认容量边界。', hypothesis='满载后应拒绝新增写入。',
        experiment='执行容量检查。', result='已有记录表明完成局部检查，尚未验证释放后的恢复行为。',
        next_step='下一步由研究协调分析结果并确定方案。') for u in units]


def test_append_deduplicate_supplement_and_cli_read(tmp_path):
    case = source(tmp_path)
    path = case['topic'] / 'tasks/r01-dma/PROGRESS_LOG.md'
    old = '# 用户已有记录\n\n原记录必须逐字保留。\n\n## 第0轮\n\n### 当时的问题\n旧五段日志原文。\n'
    path.write_text(old)
    before = case['ledger'].read_bytes()
    first = update(tmp_path, 'run-dma-r1', timezone='Asia/Shanghai', generator=prose)
    assert first['added'] > 0 and first['content'].startswith(old)
    assert 'CST' in first['content']
    appended = first['content'][len(old):]
    summary = prose(tmp_path, {}, [dict(key='a1')])[0]['summary']
    positions = [appended.index(text) for text in (summary, '### 当前问题', '### 假设', '### 实验', '### 结论', '### 下一步')]
    assert positions == sorted(positions)
    assert '### 当时的问题' not in appended
    visible = appended.split('<!-- archa-log ')[0]
    assert 'run-dma-r1' not in visible
    assert case['ledger'].read_bytes() == before
    def forbidden(*args):
        pytest.fail('没有新事实时不得调用模型')
    assert update(tmp_path, 'run-dma-r1', generator=forbidden)['added'] == 0
    case['event']('conclusion', 1, text='恢复行为仍需验证')
    value = update(tmp_path, 'run-dma-r1', generator=prose)
    assert value['added'] == 1 and value['content'].startswith(first['content'])
    assert '第1轮补充' in value['content']
    result = subprocess.run([sys.executable, '-m', 'opc.log', '-p', str(tmp_path), '--run-id', 'run-dma-r1', '--read'], capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)['content'] == value['content']


def test_failure_and_user_edit_preserve_old_log(tmp_path):
    source(tmp_path)
    path = tmp_path / 'research/log.md'
    path.parent.mkdir();path.write_text('history\n')
    with pytest.raises(ValueError, match='轮次'):
        update(tmp_path, 'run-dma-r1', 'research/log.md', generator=lambda *a: [])
    assert path.read_text() == 'history\n'
    def edits(root, run, units):
        path.write_text('user edit\n')
        return prose(root, run, units)
    with pytest.raises(ValueError, match='被修改'):
        update(tmp_path, 'run-dma-r1', 'research/log.md', generator=edits)
    assert path.read_text() == 'user edit\n'


def test_lock_and_paused_next_step(tmp_path):
    case = source(tmp_path)
    ledger = Ledger(case['ledger'])
    ledger.set_run_state('run-dma-r1', 'paused', 'user paused')
    ledger.close()
    def nested(root, run, units):
        with pytest.raises(ValueError, match='正在更新'):
            update(root, run['run_id'], generator=prose)
        return prose(root, run, units)
    value = update(tmp_path, 'run-dma-r1', generator=nested)
    assert '下一步等待用户恢复' in value['content']


def test_output_boundaries_and_missing_source(tmp_path):
    source(tmp_path)
    for output in ('../elsewhere.md', '.opc/local/artifacts/log.md'):
        with pytest.raises(ValueError):
            read(tmp_path, 'run-dma-r1', output)
    assert not (tmp_path.parent / 'elsewhere.md').exists()


@pytest.mark.parametrize('control', [False, True])
def test_observer_reads_and_launches_only_explicit_write(tmp_path, monkeypatch, control):
    case = source(tmp_path)
    app = create_app(tmp_path, control=control, topics=case['topic'])
    ident = app.state.adapter._id('run', 'run-dma-r1')
    called = []
    def launch(argv, **kwargs):
        called.append(argv)
        assert argv[1:3] == ['-m', 'opc.log']
        return subprocess.CompletedProcess(argv, 0, json.dumps(update(tmp_path, 'run-dma-r1', generator=prose)), '')
    monkeypatch.setattr(subprocess, 'run', launch)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        data = client.get('/api/observer/v1/runs/' + ident + '/research-log').json()['data']
        assert data['content'] == '' and data['can_update']
        assert app.state.adapter.control_enabled == control
        assert not called
        url = '/api/control/v1/runs/' + ident + '/research-log'
        assert client.post(url, json={}).status_code == 403
        response = client.post(url, json={}, headers={'Origin': 'http://127.0.0.1'})
        assert response.status_code == 200 and response.json()['data']['added'] > 0
        assert len(called) == 1
    app = create_app(tmp_path, demo=True, topics=case['topic'])
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert not client.get('/api/observer/v1/runs/' + ident + '/research-log').json()['data']['can_update']
        assert client.post(url, json={}, headers={'Origin': 'http://127.0.0.1'}).status_code == 403
        assert len(called) == 1


@pytest.mark.parametrize('invalid', ['missing_summary', 'summary_structure'])
def test_invalid_summary_preserves_history(tmp_path, invalid):
    case = source(tmp_path)
    path = case['topic'] / 'tasks/r01-dma/PROGRESS_LOG.md'
    path.write_bytes('旧五段日志保持不变。\n'.encode())
    before = path.read_bytes()
    def malformed(root, run, units):
        entries = prose(root, run, units)
        if invalid == 'missing_summary':
            del entries[0]['summary']
        else:
            entries[0]['summary'] = '<!-- injected -->'
        return entries
    with pytest.raises(ValueError, match='未追加'):
        update(tmp_path, 'run-dma-r1', generator=malformed)
    assert path.read_bytes() == before


def test_generation_requires_summary_and_uses_new_schema(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from opc.log import generate
    from opc.adapters import worker
    captured = {}
    class Transport:
        def _run(self, role, prompt, tree, transport, mode, schema):
            captured.update(prompt=prompt, schema=schema)
            return SimpleNamespace(ok=True), json.dumps(dict(entries=prose(tmp_path, {}, [dict(key='a1')])))
    monkeypatch.setattr(worker, 'make_worker', lambda *args: Transport())
    source(tmp_path)
    entries = generate(tmp_path, dict(state='active'), [dict(key='a1')])
    assert entries[0]['summary']
    item = captured['schema']['properties']['entries']['items']
    assert set(item['required']) == {'key', 'summary', 'problem', 'hypothesis', 'experiment', 'result', 'next_step'}
    assert item['additionalProperties'] is False
