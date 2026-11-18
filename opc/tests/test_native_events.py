"""Native log projection through installed invocation and Observer HTTP."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from opc.observer.api import create_app
from opc.tests.test_topic_cli import cli, project
from opc.tests.test_dsh_provider import providers


def test_dsh_native_tools_reach_http_without_becoming_research(project, monkeypatch):
    cli(project, 'init', '--goal', 'Evidence')
    topic = project / '.archa/topics/research'
    (topic / 'GOAL.md').write_text('Evidence\n' + 'x' * 132000)
    providers(project, monkeypatch, 'dsh')
    binary = project / 'bin/dsh'
    source = binary.read_text()
    source = source.replace("mode = os.environ.get", '''print('plain text', flush=True)
print('{"type":"unknown","tool":"invented"}', flush=True)
print(json.dumps({'type':'tool_call','callId':'one','tool':'shell','input':{'command':'echo 中文'}}, ensure_ascii=False), flush=True)
print(json.dumps({'type':'tool_result','callId':'one','status':'completed','result':'中文'}), flush=True)
print(json.dumps({'type':'status','phase':'step_end','usage':{'inputTokens':12,'outputTokens':3}}), flush=True)
mode = os.environ.get''')
    binary.write_text(source)
    assert cli(project, 'step')['next_action'] == 'executor'
    with TestClient(create_app(project)) as client:
        trace = client.get('/api/observer/v1/topics/research/steps/1/events', params={'role':'expert'}).json()
    events = trace['events']
    assert [e['kind'] for e in events] == ['lifecycle', 'tool', 'tool', 'usage', 'lifecycle']
    assert [e['status'] for e in events[1:3]] == ['running', 'ok']
    assert 'one' in events[2]['title']
    assert '中文' in events[1]['detail']
    assert 'inputTokens' in events[3]['detail']
    assert events[-1]['title'] == 'completed'
    assert [e['seq'] for e in events] == list(range(1, 6))
    assert 'plain text' in (topic / 'steps/step-01/.expert.log').read_text()


def test_codex_live_partial_unicode_and_final_tail(project, monkeypatch):
    import subprocess
    import sys
    import time
    cli(project, 'init', '--goal', 'Evidence')
    topic = project / '.archa/topics/research'
    (topic / 'GOAL.md').write_text('Evidence\n' + 'x' * 132000)
    providers(project, monkeypatch, 'codex')
    binary = project / 'bin/codex'
    binary.write_text(binary.read_text().replace("mode = os.environ.get", '''payload = json.dumps({'type':'item.started','item':{'id':'c1','type':'command_execution','command':'echo 中文','status':'in_progress'}}, ensure_ascii=False).encode()
cut = payload.index('中'.encode()) + 1
os.write(1, payload[:cut])
time.sleep(.3)
os.write(1, payload[cut:] + b'\\n')
while not pathlib.Path('release').exists(): time.sleep(.02)
print(json.dumps({'type':'item.completed','item':{'id':'c1','type':'command_execution','command':'echo 中文','status':'completed','exit_code':0}}), flush=True)
os.write(1, json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':2,'cached_input_tokens':0}}).encode())
mode = os.environ.get'''))
    process = subprocess.Popen([sys.executable, str(project / '.archa/archa.py'), 'step', '-p', str(project), '--topic', 'research'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with TestClient(create_app(project)) as client:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                events = client.get('/api/observer/v1/topics/research/steps/1/events', params={'role':'expert'}).json().get('events', [])
                if len(events) > 1:
                    break
                time.sleep(.03)
            assert [e['kind'] for e in events] == ['lifecycle', 'tool']
            assert '中文' in events[1]['detail']
            assert process.poll() is None
            (project / 'release').touch()
            out, err = process.communicate(timeout=10)
            assert process.returncode == 0, err
            events = client.get('/api/observer/v1/topics/research/steps/1/events', params={'role':'expert'}).json()['events']
            assert [e['kind'] for e in events] == ['lifecycle', 'tool', 'tool', 'usage', 'lifecycle']
    finally:
        (project / 'release').touch()
        process.communicate(timeout=10)


def test_malformed_native_event_marks_incomplete_but_commits_probe(project, monkeypatch):
    cli(project, 'init', '--goal', 'Evidence')
    topic = project / '.archa/topics/research'
    (topic / 'GOAL.md').write_text('Evidence\n' + 'x' * 132000)
    providers(project, monkeypatch, 'dsh')
    binary = project / 'bin/dsh'
    binary.write_text(binary.read_text().replace("mode = os.environ.get", "print('{\"type\":\"tool_call\"}', flush=True)\nmode = os.environ.get"))
    assert cli(project, 'step')['next_action'] == 'executor'
    with TestClient(create_app(project)) as client:
        trace = client.get('/api/observer/v1/topics/research/steps/1/events', params={'role':'expert'}).json()
    assert 'native event extraction' in trace['diagnostic']
    assert [e['kind'] for e in trace['events']] == ['lifecycle', 'diagnostic', 'lifecycle']
    assert trace['events'][-1]['title'] == 'completed'
    assert (topic / 'steps/step-01/probe.md').is_file()


def test_unwritable_events_still_publish_native_probe(project, monkeypatch):
    cli(project, 'init', '--goal', 'Evidence')
    topic = project / '.archa/topics/research'
    (topic / 'GOAL.md').write_text('Evidence\n' + 'x' * 132000)
    providers(project, monkeypatch, 'dsh')
    step = topic / 'steps/step-01'
    step.mkdir()
    (step / '.expert.events.jsonl').mkdir()
    assert cli(project, 'step')['next_action'] == 'executor'
    with TestClient(create_app(project)) as client:
        trace = client.get('/api/observer/v1/topics/research/steps/1/events', params={'role':'expert'}).json()
    assert trace['events'] == [] and 'Telemetry incomplete' in trace['diagnostic']
    assert 'Diagnostic only' in (step / '.expert.log').read_text()
    assert (step / 'probe.md').is_file()


def test_native_tool_rows_append_in_open_browser(project, monkeypatch):
    import socket
    import subprocess
    import sys
    import threading
    import time
    import uvicorn
    playwright_api = pytest.importorskip('playwright.sync_api')
    sync_playwright, expect = playwright_api.sync_playwright, playwright_api.expect
    if not (Path(__file__).parents[1] / 'observer/static/index.html').is_file():
        pytest.skip('build web before native browser acceptance')
    cli(project, 'init', '--goal', 'Evidence')
    topic = project / '.archa/topics/research'
    (topic / 'GOAL.md').write_text('Evidence\n' + 'x' * 132000)
    providers(project, monkeypatch, 'dsh')
    binary = project / 'bin/dsh'
    binary.write_text(binary.read_text().replace("mode = os.environ.get", '''print(json.dumps({'type':'tool_call','callId':'one','tool':'shell','input':{'command':'echo browser'}}), flush=True)
while not pathlib.Path('release').exists(): time.sleep(.02)
print(json.dumps({'type':'tool_result','callId':'one','status':'completed','result':'browser output'}), flush=True)
mode = os.environ.get'''))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(project), host='127.0.0.1', port=port, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    process = subprocess.Popen([sys.executable, str(project / '.archa/archa.py'), 'step', '-p', str(project), '--topic', 'research'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline
            time.sleep(.02)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{port}/?topic=research')
            page.get_by_text('Expert · stdout / stderr', exact=True).click()
            page.get_by_text('执行 Trace', exact=True).click()
            rows = page.get_by_label('调用事件')
            expect(rows).to_contain_text('shell started')
            expect(rows.locator('li')).to_have_count(2)
            page.evaluate('window.firstTool = document.querySelectorAll("[aria-label=调用事件] li")[1]')
            assert process.poll() is None
            (project / 'release').touch()
            stdout, stderr = process.communicate(timeout=10)
            assert process.returncode == 0, stderr
            expect(rows).to_contain_text('one ended')
            expect(rows.locator('li')).to_have_count(4)
            assert page.evaluate('window.firstTool === document.querySelectorAll("[aria-label=调用事件] li")[1]')
            expect(rows).to_contain_text('exit_code=0')
            expect(page.get_by_label('Trace 原始日志')).to_contain_text('browser output')
            browser.close()
    finally:
        (project / 'release').touch()
        process.communicate(timeout=10)
        server.should_exit = True
        thread.join(5)


def test_custom_native_looking_json_stays_raw(project):
    import sys
    cli(project, 'init', '--goal', 'Evidence')
    script = project / 'custom.py'
    script.write_text('''import pathlib, sys
state, output = map(pathlib.Path, sys.argv[1:])
state.write_text(pathlib.Path('.archa/topics/research/STATE.md').read_text())
output.write_text('A valid probe')
print('{"type":"tool_call","callId":"fake","tool":"invented","input":{}}')
''')
    config = {'expert': {'provider':'custom', 'command':[sys.executable, str(script), '{state_file}', '{output_file}']}, 'executor': {'provider':'codex'}}
    (project / '.archa/workers.json').write_text(json.dumps(config))
    cli(project, 'step')
    with TestClient(create_app(project)) as client:
        trace = client.get('/api/observer/v1/topics/research/steps/1/events', params={'role':'expert'}).json()
    assert [e['kind'] for e in trace['events']] == ['lifecycle', 'lifecycle']
    assert 'invented' in (project / '.archa/topics/research/steps/step-01/.expert.log').read_text()
