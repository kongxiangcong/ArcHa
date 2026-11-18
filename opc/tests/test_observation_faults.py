"""Faults observed through deployed CLI, process ownership and Observer HTTP."""
import json
import subprocess
import sys
import time

import pytest

from fastapi.testclient import TestClient
from opc.observer.api import create_app
from opc.tests.test_topic_cli import cli, project
from opc.tests.test_dsh_provider import providers

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux process and resource-limit fault acceptance")


def native_project(project, monkeypatch, payload):
    cli(project, 'init', '--goal', 'Evidence')
    topic = project / '.archa/topics/research'
    (topic / 'GOAL.md').write_text('Evidence\n' + 'x' * 132000)
    providers(project, monkeypatch, 'dsh')
    binary = project / 'bin/dsh'
    binary.write_text(binary.read_text().replace('mode = os.environ.get', payload + '\nmode = os.environ.get'))
    return topic


def test_overlong_line_diagnostic_survives_later_output_and_probe_commits(project, monkeypatch):
    topic = native_project(project, monkeypatch, '''os.write(1, b'LONG:' + b'x' * (2 * 1024 * 1024))
# Wait on the public event file before writing enough output to bury its diagnosis.
events = pathlib.Path('.archa/topics/research/steps/step-01/.expert.events.jsonl')
deadline = time.monotonic() + 10
while 'Trace incomplete' not in events.read_text():
    assert time.monotonic() < deadline
    time.sleep(.02)
os.write(2, b'\\n' + b'plain later output\\n' * 100000)''')
    assert cli(project, 'step')['next_action'] == 'executor'
    step = topic / 'steps/step-01'
    raw = (step / '.expert.log').read_bytes()
    assert b'LONG:' + b'x' * (2 * 1024 * 1024) in raw
    assert (step / 'probe.md').read_text() == 'Focused probe dsh'
    with TestClient(create_app(project)) as client:
        trace = client.get('/api/observer/v1/topics/research/steps/1/events', params={'role':'expert'}).json()
        assert '1 MiB' in (trace['diagnostic'] or '')
        assert trace['events'][-1]['title'] == 'completed'
        path = '.archa/topics/research/steps/step-01/.expert.log'
        first = client.get('/api/observer/v1/materials', params={'path':path, 'limit':4096}).json()
        second = client.get('/api/observer/v1/materials', params={'path':path, 'offset':first['next_offset'], 'limit':4096}).json()
        assert first['more'] and second['more']
        assert second['text'] == 'x' * 4096


def test_independent_results_use_native_call_id_without_retaining_calls(project, monkeypatch):
    topic = native_project(project, monkeypatch, '''print(json.dumps({'type':'tool_call','callId':'request-7','tool':'shell','input':{}}), flush=True)
print(json.dumps({'type':'tool_result','callId':'request-7','status':'completed','result':'done'}), flush=True)''')
    cli(project, 'step')
    events = [json.loads(line) for line in (topic / 'steps/step-01/.expert.events.jsonl').read_text().splitlines()]
    assert events[2]['title'] == 'request-7 ended'


def test_final_drain_is_bounded_and_valid_probe_still_commits(project, monkeypatch):
    topic = native_project(project, monkeypatch, '''event = (json.dumps({'type':'tool_call','callId':'many','tool':'shell','input':{}}) + '\\n').encode()
for _ in range(1000): os.write(1, event * 1000)''')
    started = time.monotonic()
    assert cli(project, 'step')['next_action'] == 'executor'
    assert time.monotonic() - started < 8
    assert (topic / 'steps/step-01/probe.md').is_file()
    with TestClient(create_app(project)) as client:
        trace = client.get('/api/observer/v1/topics/research/steps/1/events', params={'role':'expert'}).json()
        assert 'finalization budget' in trace['diagnostic']
    assert (topic / 'steps/step-01/.expert.log').stat().st_size > 60_000_000


FLOOD = '''import subprocess
child = subprocess.Popen([sys.executable, '-c', "import pathlib,time; p=pathlib.Path('heartbeat');\\nwhile True: p.write_text(str(time.monotonic())); time.sleep(.01)"])
pathlib.Path('child.pid').write_text(str(child.pid))
event = (json.dumps({'type':'tool_call','callId':'old','tool':'flood','input':{}}) + '\\n').encode()
while True:
    os.write(1, event * 1000)
    os.write(2, b'raw stderr\\n' * 1000)
    pathlib.Path('ready').touch()
    time.sleep(.002)
'''


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('public observable did not reach expected state before deadline')


def assert_descendant_ended(project):
    from pathlib import Path
    pid = (project / 'child.pid').read_text()
    def ended():
        stat = Path('/proc') / pid / 'stat'
        return not stat.exists() or stat.read_text().split(') ')[1].startswith('Z')
    wait_for(ended)


@pytest.mark.parametrize('control', ['stop', 'timeout'])
def test_flood_stop_timeout_reaps_descendants_and_retry_is_clean(project, monkeypatch, control):
    topic = native_project(project, monkeypatch, FLOOD)
    if control == 'timeout':
        path = project / '.archa/workers.json'
        config = json.loads(path.read_text())
        config['expert']['timeout_seconds'] = 1
        path.write_text(json.dumps(config))
    process = subprocess.Popen([sys.executable, str(project / '.archa/archa.py'), 'step', '-p', str(project), '--topic', 'research'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        wait_for(lambda: (project / 'ready').exists())
        started = time.monotonic()
        if control == 'stop':
            assert cli(project, 'stop')['activity'] == 'idle'
        _, error = process.communicate(timeout=8)
        assert process.returncode != 0
        assert time.monotonic() - started < 8
        assert ('interrupted' if control == 'stop' else 'timed out') in error.decode()
        assert_descendant_ended(project)
        assert not (topic / 'steps/step-01/probe.md').exists()
        old = (topic / 'steps/step-01/.expert.events.jsonl').read_text().splitlines()[0]
        providers(project, monkeypatch, 'dsh')
        assert cli(project, 'step')['next_action'] == 'executor'
        events = (topic / 'steps/step-01/.expert.events.jsonl').read_text().splitlines()
        assert events[0] != old
        assert [json.loads(e)['title'] for e in events] == ['started', 'completed']
        assert 'flood' not in (topic / 'steps/step-01/.expert.log').read_text()
    finally:
        if process.poll() is None:
            cli(project, 'stop')
            process.communicate(timeout=10)


def test_browser_flood_stop_and_fault_retry_preserve_reading(project, monkeypatch):
    import socket
    import threading
    import uvicorn
    from pathlib import Path
    playwright = pytest.importorskip('playwright.sync_api')
    if not (Path(__file__).parents[1] / 'observer/static/index.html').exists():
        pytest.skip('build web before browser acceptance')
    topic = native_project(project, monkeypatch, FLOOD)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(project, control=True), host='127.0.0.1', port=port, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        wait_for(lambda: server.started)
        with playwright.sync_playwright() as pw:
            browser = pw.chromium.launch(args=['--no-sandbox'])
            page = browser.new_page(viewport={'width':1920, 'height':1080})
            page.goto(f'http://127.0.0.1:{port}/?topic=research')
            page.get_by_role('button').filter(has=page.locator('.source', has_text='GOAL.md')).click()
            reader = page.get_by_label('材料阅读', exact=True)
            playwright.expect(reader).to_contain_text('Evidence')
            page.get_by_role('button', name='继续', exact=True).click()
            wait_for(lambda: (project / 'ready').exists())
            playwright.expect(page.get_by_text('运行中', exact=True)).to_be_visible()
            playwright.expect(page.get_by_label('执行 Trace 内容')).to_have_count(0)
            page.get_by_role('button', name='停止', exact=True).click()
            playwright.expect(page.get_by_text('空闲', exact=True)).to_be_visible(timeout=10000)
            assert_descendant_ended(project)
            playwright.expect(reader).to_contain_text('Evidence')
            # Retry with native parsing failure and valid file-protocol output.
            providers(project, monkeypatch, 'dsh')
            binary = project / 'bin/dsh'
            binary.write_text(binary.read_text().replace('mode = os.environ.get', "print('{\"type\":\"tool_call\"}', flush=True)\nmode = os.environ.get"))
            page.get_by_label('探针断点调试').check()
            page.get_by_role('button', name='启用调试并继续', exact=True).click()
            playwright.expect(page.get_by_text('空闲', exact=True)).to_be_visible(timeout=10000)
            wait_for(lambda: (topic / 'steps/step-01/probe.md').exists())
            playwright.expect(reader).to_contain_text('Evidence')
            playwright.expect(page.get_by_label('执行 Trace 内容')).to_have_count(0)
            page.get_by_text('Expert · stdout / stderr', exact=True).click()
            page.get_by_text('执行 Trace', exact=True).click()
            playwright.expect(page.get_by_label('执行 Trace 内容').get_by_role('alert')).to_contain_text('Trace 不完整')
            playwright.expect(page.get_by_label('调用事件')).to_contain_text('completed')
            playwright.expect(page.get_by_label('Trace 原始日志')).to_contain_text('native event extraction')
            browser.close()
    finally:
        cli(project, 'stop')
        server.should_exit = True
        thread.join(5)


def test_os_event_write_failure_does_not_discard_valid_probe(project, monkeypatch):
    topic = native_project(project, monkeypatch, '''import resource
resource.prlimit(os.getppid(), resource.RLIMIT_FSIZE, (4096, 4096))
for n in range(40):
    print(json.dumps({'type':'tool_call','callId':str(n),'tool':'shell','input':{}}), flush=True)''')
    result = subprocess.run([sys.executable, str(project / '.archa/archa.py'), 'step', '-p', str(project), '--topic', 'research'], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'File too large' in result.stderr
    assert (topic / 'steps/step-01/probe.md').exists()
    with TestClient(create_app(project)) as client:
        trace = client.get('/api/observer/v1/topics/research/steps/1/events', params={'role':'expert'}).json()
        assert 'File too large' in trace['diagnostic']


def test_unwritable_raw_diagnostic_exposes_error_without_claiming_saved(project, monkeypatch):
    topic = native_project(project, monkeypatch, '''raw = pathlib.Path('.archa/topics/research/steps/step-01/.expert.log')
raw.unlink()
raw.mkdir()
print('{"type":"tool_call"}', flush=True)''')
    result = subprocess.run([sys.executable, str(project / '.archa/archa.py'), 'step', '-p', str(project), '--topic', 'research'], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'log diagnostic failed:' in result.stderr
    assert 'Is a directory' in result.stderr
    assert (topic / 'steps/step-01/probe.md').exists()
