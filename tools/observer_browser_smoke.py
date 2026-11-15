"""Real HTTP/browser acceptance for topic observation. Build web first."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from opc.observer.api import create_app
from opc.observer.demo import create_demo


def main():
    with tempfile.TemporaryDirectory(prefix='archa-observer-') as temporary:
        root = Path(temporary)
        subprocess.run([sys.executable, '-m', 'opc', 'init', '-p', str(root), '--topic', 'research', '--goal', 'Check evidence', '--max-rounds', '1'], check=True, capture_output=True)
        with socket.socket() as socket_:
            socket_.bind(('127.0.0.1', 0))
            port = socket_.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(root, control=True), host='127.0.0.1', port=port, log_level='warning'))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert time.monotonic() < deadline
                time.sleep(.02)
            origin = f'http://127.0.0.1:{port}'
            with urlopen(origin + '/api/observer/v1/topics') as response:
                data = json.load(response)
            assert data['topics'][0]['topic'] == 'research', data
            print('PASS topic HTTP discovery')
            create_demo(root)
            with urlopen(origin + '/api/observer/v1/topics') as response:
                demo_topics = json.load(response)['topics']
            assert any(item['topic'] == 'evidence-demo' for item in demo_topics), demo_topics
            with urlopen(origin + '/api/observer/v1/topics/evidence-demo') as response:
                demo = json.load(response)
            assert demo['status'] == 'BUDGET_EXHAUSTED' and demo['activity'] == 'idle'
            assert demo['rounds'][0]['completed']
            print('PASS new-format offline demo through same HTTP')
            worker = root / 'worker.py'
            worker.write_text(r"""import pathlib, sys, time
role, state, output, root = sys.argv[1:]
state, output, root = map(pathlib.Path, (state, output, root))
if state == output: role = 'expert_finalize'
print('x' * 270000, flush=True)
print(role + ' live stdout', flush=True)
print(role + ' live stderr', file=sys.stderr, flush=True)
while not (root / ('release-' + role)).exists(): time.sleep(.05)
if role == 'expert_finalize': sys.exit(9)
if role == 'expert':
    state.write_text((root / '.archa/topics/research/STATE.md').read_text() + '\nCurrent evidence remains uncertain.\n')
output.write_text('# ' + role + ' material\n\n[Original](../../../../../evidence.md)')
""")
            config = {'roles': {role: {'command': [sys.executable, str(worker), role, '{state_file}', '{output_file}', str(root)], 'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 60} for role in ('expert', 'executor')}}
            (root / '.archa/workers.json').write_text(json.dumps(config))
            process = subprocess.Popen([sys.executable, '-m', 'opc', 'run', '-p', str(root), '--topic', 'research'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            from playwright.sync_api import sync_playwright, expect
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
                page = browser.new_page()
                page.goto(origin + '?topic=research')
                expect(page.get_by_label('选择专题')).to_have_value('research')
                expect(page.get_by_text('输入与认知状态', exact=True)).to_be_visible()
                expect(page.get_by_text('IN_PROGRESS', exact=True)).to_be_visible()
                expect(page.get_by_text('运行中', exact=True)).to_be_visible()
                page.get_by_text('轮次历史与日志', exact=True).click()
                page.get_by_text('Expert · stdout / stderr', exact=True).click()
                expect(page.locator('pre').filter(has_text='expert live stdout')).to_contain_text('expert live stderr')
                assert process.poll() is None, 'must observe stdout while worker is alive'
                (root / 'release-expert').touch()
                page.get_by_text('Executor · stdout / stderr', exact=True).click()
                expect(page.locator('pre').filter(has_text='executor live stdout')).to_contain_text('executor live stderr', timeout=10000)
                expect(page.get_by_label('当前探针', exact=True)).to_contain_text('expert material')
                (root / 'release-executor').touch()
                page.get_by_text('Expert · 收尾消化 · stdout / stderr', exact=True).click()
                expect(page.locator('pre').filter(has_text='expert_finalize live stdout')).to_contain_text('expert_finalize live stderr', timeout=10000)
                expect(page.get_by_text('Expert · 收尾消化 · stdout / stderr', exact=True)).to_be_visible()
                (root / 'release-expert_finalize').touch()
                assert process.wait(timeout=10) != 0
                expect(page.get_by_text('空闲', exact=True)).to_be_visible()
                expect(page.get_by_role('alert')).to_contain_text('exited with code 9')
                expect(page.locator('pre').filter(has_text='expert live stdout')).to_be_visible()
                expect(page.locator('pre').filter(has_text='expert_finalize live stdout')).to_be_visible()
                # A new invocation can be interrupted; retained logs remain readable.
                (root / 'release-expert_finalize').unlink()
                process = subprocess.Popen([sys.executable, '-m', 'opc', 'run', '-p', str(root), '--topic', 'research'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                expect(page.get_by_text('运行中', exact=True)).to_be_visible()
                expect(page.locator('pre').filter(has_text='expert_finalize live stdout')).to_be_visible()
                stopped = subprocess.run([sys.executable, '-m', 'opc', 'stop', '-p', str(root), '--topic', 'research'], capture_output=True, text=True, timeout=15)
                assert stopped.returncode == 0, stopped.stderr
                assert process.wait(timeout=10) != 0
                expect(page.get_by_text('空闲', exact=True)).to_be_visible()
                expect(page.get_by_role('alert')).to_contain_text('interrupted')
                # Original project material, HTML safety, navigation and path boundaries.
                (root / 'evidence.md').write_text('# Original evidence\n\n<script>window.__pwned = true</script>\n\n[Raw HTML](raw.html)')
                (root / 'raw.html').write_text('<script>window.__pwned = true</script>')
                (root / 'escape').symlink_to('/etc/passwd')
                page.get_by_role('button', name='result.md', exact=True).click()
                page.get_by_role('button', name='Original', exact=True).click()
                expect(page.get_by_role('heading', name='Original evidence')).to_be_visible()
                page.get_by_role('button', name='Raw HTML', exact=True).click()
                expect(page.locator('#material-reader pre')).to_contain_text('<script>')
                assert page.evaluate('window.__pwned') is None
                from urllib.parse import urlencode
                for denied in ('../outside', '/etc/passwd', 'escape', '.archa/workers.json', '.git/config', '.archa/topics/research/steps/step-01/.staging.expert/STATE.md'):
                    response = page.request.get(origin + '/api/observer/v1/materials?' + urlencode({'path': denied}))
                    assert response.status == 403, (denied, response.status)
                staging = root / '.archa/topics/research/steps/step-01/.staging.expert'
                staging.mkdir(exist_ok=True)
                (staging / 'untouched').write_text('Keep failed staging')
                for _ in range(3):
                    assert page.request.get(origin + '/api/observer/v1/topics/research').ok
                assert (staging / 'untouched').read_text() == 'Keep failed staging'
                assert not (root / '.archa/topics/research/steps/step-01/.expert_finalize.prompt.md').exists()
                page.get_by_label('主题', exact=True).select_option('dark')
                assert page.locator('html').get_attribute('data-theme') == 'dark'
                page.reload()
                expect(page.get_by_label('主题', exact=True)).to_have_value('dark')
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.keyboard.press('Tab')
                assert page.evaluate('document.activeElement.tagName') == 'A'
                assert page.get_by_role('button', name='暂停').count() == 0
                # A second topic exercises actual controls and Worker subprocesses.
                subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'skills/archa-discuss/scripts/initialize.py'), '--project', str(root)], check=True, capture_output=True)
                launcher = root / '.archa/archa.py'
                subprocess.run([sys.executable, str(launcher), 'init', '-p', str(root), '--topic', 'debug', '--goal', 'Inspect hypothesis evidence', '--max-rounds', '3'], check=True, capture_output=True)
                worker.write_text(r"""import pathlib, sys, time
role, state, output, topic = sys.argv[1:]
state, output, topic = map(pathlib.Path, (state, output, topic))
text = sys.stdin.read()
print(role + ' diagnostic output', flush=True)
if 'Role: expert_revise' in text:
    assert 'CURRENT PROBE' in text and 'Measure the exact integer sum.' in text
    assert 'USER DIRECTION' in text and 'Focus on negative integers' in text
    time.sleep(2)
    state.write_text((topic / 'STATE.md').read_text())
    output.write_text('# Revised probe\n\nMeasure negative integer sums.')
    sys.exit(0)
if role == 'expert':
    state.write_text((topic / 'STATE.md').read_text())
    output.write_text('# Hypothesis and evidence\n\nHypothesis: float conversion loses integer precision.\n\nEvidence: baseline input 9007199254740993 produced 9007199254740992.\n\n## Probe design\n\nMeasure the exact integer sum.')
else:
    expected = 'Measure negative integer sums.' if 'step-01' in output.parts else 'Measure the exact integer sum.'
    assert expected in text
    output.write_text('Observed negative integer mismatch from revised probe.')
""")
                (root / '.archa/workers.json').write_text(json.dumps({'roles': {role: {
                    'command': [sys.executable, str(worker), role, '{state_file}', '{output_file}', '{topic_dir}'],
                    'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 10,
                } for role in ('expert', 'executor')}}))
                page.goto(origin + '?topic=debug')
                page.get_by_label('探针断点调试', exact=True).check()
                page.get_by_role('button', name='启用调试并继续', exact=True).click()
                expect(page.get_by_text('探针断点等待', exact=True)).to_be_visible(timeout=10000)
                expect(page.get_by_role('heading', name='Hypothesis and evidence')).to_be_visible()
                expect(page.get_by_role('heading', name='Probe design')).to_be_visible()
                expect(page.get_by_label('当前探针', exact=True)).to_contain_text('Hypothesis: float conversion loses integer precision.')
                expect(page.get_by_label('当前探针', exact=True)).to_contain_text('Evidence: baseline input 9007199254740993 produced 9007199254740992.')
                endpoint = origin + '/api/observer/v1/topics/debug'
                assert page.request.get(endpoint).json()['completed_rounds'] == 0
                page.reload()
                expect(page.get_by_text('探针断点等待', exact=True)).to_be_visible()
                assert page.request.get(endpoint).json()['completed_rounds'] == 0
                page.get_by_text('轮次历史与日志', exact=True).click()
                page.get_by_text('Expert · stdout / stderr', exact=True).click()
                expect(page.locator('pre').filter(has_text='expert diagnostic output')).to_be_visible()
                page.get_by_text('输入与认知状态', exact=True).click()
                page.get_by_role('button', name='GOAL.md', exact=True).click()
                expect(page.locator('#material-reader')).to_contain_text('Inspect hypothesis evidence')
                page.get_by_label('当前探针方向意见', exact=True).fill('Focus on negative integers')
                page.get_by_role('button', name='提交意见并重拟', exact=True).click()
                expect(page.get_by_label('专题与执行状态')).to_contain_text('Expert · 调整探针')
                expect(page.get_by_role('heading', name='Revised probe')).to_be_visible(timeout=10000)
                expect(page.get_by_text('探针断点等待', exact=True)).to_be_visible()
                revised = page.request.get(endpoint).json()
                assert revised['completed_rounds'] == 0 and revised['max_rounds'] == 3
                page.get_by_role('button', name='feedback.md', exact=True).click()
                expect(page.locator('#material-reader')).to_contain_text('Focus on negative integers')
                page.get_by_label('当前探针方向意见', exact=True).fill('Unsent direction for round one')
                page.get_by_role('button', name='执行当前探针并继续', exact=True).click()
                expect(page.get_by_text('第 2 轮 · 待执行探针', exact=True)).to_be_visible(timeout=10000)
                expect(page.get_by_label('当前探针方向意见', exact=True)).to_have_value('')
                detail = page.request.get(endpoint).json()
                assert detail['completed_rounds'] == 1 and detail['probe_breakpoint'] and detail['error'] is None
                assert detail['execution'] is None
                result = next(item for item in detail['rounds'][0]['materials'] if item['name'] == 'result.md')
                assert 'Observed negative integer mismatch' in page.request.get(origin + '/api/observer/v1/materials', params={'path': result['path']}).json()['text']
                page.get_by_label('当前探针方向意见', exact=True).fill('Unsent direction for round two')
                subprocess.run([sys.executable, str(launcher), 'resume', '-p', str(root), '--topic', 'debug'], check=True, capture_output=True, timeout=15)
                expect(page.get_by_text('第 3 轮 · 待执行探针', exact=True)).to_be_visible(timeout=10000)
                expect(page.get_by_label('当前探针方向意见', exact=True)).to_have_value('')
                browser.close()
                print('PASS browser debug: enable, refresh, diagnostics, submit direction, revise without budget use, execute revised probe, clear unsent direction after browser and CLI advance')
            print('PASS browser: live role logs, finalize failure, interruption, safe materials, read-only polling, theme, mobile and keyboard')
        finally:
            if 'process' in locals() and process.poll() is None:
                subprocess.run([sys.executable, '-m', 'opc', 'stop', '-p', str(root), '--topic', 'research'], capture_output=True, timeout=15)
                process.wait(timeout=10)
            if (root / '.archa/topics/debug').exists():
                subprocess.run([sys.executable, '-m', 'opc', 'stop', '-p', str(root), '--topic', 'debug'], capture_output=True, timeout=15)
            server.should_exit = True
            thread.join(10)


if __name__ == '__main__':
    main()
