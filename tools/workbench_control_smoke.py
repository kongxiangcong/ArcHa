"""Browser acceptance against real HTTP and Worker processes; build web first."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from opc.core.topic_workspace import TopicWorkspace
from opc.observer.api import create_app


def main():
    from playwright.sync_api import sync_playwright, expect
    with tempfile.TemporaryDirectory(prefix='archa-control-') as temporary:
        root = Path(temporary)
        w = TopicWorkspace(root, 'research')
        w.initialize('Read original evidence', 1)
        worker = root / 'worker.py'
        worker.write_text('''import pathlib,sys,time
state, output, root = map(pathlib.Path,sys.argv[1:])
print('Worker live output',flush=True)
while not (root/'release').exists(): time.sleep(.05)
if (root/'fail').exists(): sys.exit(9)
if state != output: output.write_text('Original evidence')
''')
        config = {'roles': {role: {'command': [sys.executable, str(worker), '{state_file}', '{output_file}', str(root)], 'input_mode': 'stdin', 'output_mode': 'file', 'timeout_seconds': 30} for role in ('expert', 'executor')}}
        (root / '.archa/workers.json').write_text(json.dumps(config))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(root, control=True), host='127.0.0.1', port=port, log_level='warning'))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert time.monotonic() < deadline
                time.sleep(.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(args=['--no-sandbox'])
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{port}/?topic=research')
                page.get_by_role('button', name='GOAL.md', exact=True).click()
                reader = page.get_by_label('材料阅读', exact=True)
                expect(reader).to_contain_text('Read original evidence')
                page.get_by_role('button', name='继续', exact=True).click()
                expect(page.get_by_text('运行中', exact=True)).to_be_visible()
                expect(page.locator('pre').filter(has_text='Worker live output')).to_be_visible()
                execution_id = page.request.get(f'http://127.0.0.1:{port}/api/observer/v1/topics/research').json()['execution']['id']
                other = browser.new_page()
                other.goto(page.url)
                expect(other.get_by_role('button', name='继续', exact=True)).to_be_disabled()
                other.reload()
                assert other.request.get(f'http://127.0.0.1:{port}/api/observer/v1/topics/research').json()['execution']['id'] == execution_id
                page.get_by_role('button', name='停止', exact=True).click()
                expect(page.get_by_text('空闲', exact=True)).to_be_visible(timeout=15000)
                expect(reader).to_contain_text('Read original evidence')
                # Explicit BLOCKED recovery through browser.
                state = w.path / 'STATE.md'
                state.write_text(state.read_text().replace('IN_PROGRESS', 'BLOCKED'))
                (root / 'release').touch()
                page.get_by_role('button', name='条件已补齐，继续', exact=True).click()
                expect(page.get_by_text('BUDGET_EXHAUSTED', exact=True)).to_be_visible(timeout=10000)
                expect(page.get_by_role('button', name='继续', exact=True)).to_be_disabled()
                page.get_by_label('追加轮数', exact=True).fill('1')
                page.get_by_role('button', name='追加并继续', exact=True).click()
                expect(page.get_by_label('专题与执行状态')).to_contain_text('2 / 2')
                expect(page.get_by_text('空闲', exact=True)).to_be_visible()
                # Worker failure preserves current reader and shared diagnostics.
                (root / 'fail').touch()
                page.get_by_role('button', name='追加并继续', exact=True).click()
                expect(page.get_by_label('专题与执行状态').get_by_role('alert')).to_be_visible()
                expect(reader).to_contain_text('Read original evidence')
                expect(other.get_by_label('专题与执行状态').get_by_role('alert')).to_be_visible()
                # Unknown ownership is visible and failed control keeps the reader.
                record = dict(id='unknown', topic='research', controller=None, worker='starting', role='expert', round=3, started_at='2026-01-01T00:00:00Z')
                (w.control / '.execution.json').write_text(json.dumps(record))
                expect(page.get_by_text('未知执行', exact=True)).to_be_visible()
                page.get_by_role('button', name='停止', exact=True).click()
                expect(page.get_by_label('专题控制').get_by_role('alert')).to_contain_text('unknown execution')
                expect(reader).to_contain_text('Read original evidence')
                (w.control / '.execution.json').unlink()
                state.write_text(state.read_text().replace('IN_PROGRESS', 'COMPLETED'))
                expect(page.get_by_text('研究已完成，不能自动重开。', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='追加并继续', exact=True)).to_have_count(0)
                browser.close()
                print('PASS browser run/stop/resume, two pages, blocked, budget, failure, unknown, completed; reader retained')
        finally:
            server.should_exit = True
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
