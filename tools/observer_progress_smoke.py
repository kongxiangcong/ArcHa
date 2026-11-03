"""Browser regression over the production build and real Observer/ledger, no model calls."""
import argparse
import json
import socket
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import expect, sync_playwright
from opc.core.ledger import Ledger
from opc.observer.api import create_app
from opc.observer.demo import create_demo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=Path('work/progress-browser'))
    parser.add_argument('--chromium', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='archa-progress-') as temporary:
        root = create_demo(Path(temporary))
        path = root / '.opc/local/ledger.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute("DELETE FROM runs WHERE revision='preparation'")
            db.execute("DELETE FROM events WHERE run_id='prepare-dma'")
        def event(scope, kind, attempt=None, **body):
            ledger = Ledger(path)
            ledger.event(scope, kind, attempt, **body)
            ledger.db.close()
        event('run-dma-r1', 'execution', 1, call_id='implementation',
              progress_summary='已完成容量检查，并确认满载时会拒绝新写入。下一步补充释放后的恢复验证。')
        event('run-dma-r1', 'candidate_saved', 1, commit='c' * 40)
        event('preparation:dma-backpressure', 'preparation', state='ready',
              brief_input=dict(brief='.opc/research/tasks/r01-dma/task-brief.md'))
        app = create_app(root)
        adapter = app.state.adapter
        task = next(t for t in adapter.overview()['data']['tasks'] if t['research_task_id'] == 'R01')
        run = adapter._id('run', 'run-dma-r1')
        other = adapter._id('run', 'run-dma-r2')
        prep = adapter._id('run', 'preparation:dma-backpressure')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline
            time.sleep(.05)
        origin = f'http://127.0.0.1:{port}'
        checks = []
        def passed(name):
            checks.append(name)
            print('PASS', name, flush=True)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(args.chromium) if args.chromium else None,
                                                       headless=True, args=['--no-sandbox'])
                page = browser.new_page(viewport=dict(width=1440, height=1050), locale='zh-CN')
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin + '/?' + urlencode(dict(task=task['id'], run=run)))
                panel = page.locator('.current-progress')
                expect(panel).to_be_visible()
                expect(panel).to_contain_text('已完成容量检查')
                expect(panel).to_contain_text('最近已完成进展 · 实施')
                expect(page.locator('.current-progress-copy')).to_have_attribute('aria-live', 'polite')
                page.screenshot(path=str(args.out / 'canvas.png'), full_page=True)
                page.get_by_role('button', name='工作列表', exact=True).click()
                expect(panel).to_contain_text('已完成容量检查')
                page.screenshot(path=str(args.out / 'desk.png'), full_page=True)
                passed('shared window in canvas and desk / role / timestamp / polite live region')

                page.get_by_role('button', name='工作列表', exact=True).focus()
                focus = page.evaluate('document.activeElement.textContent')
                event('run-dma-r1', 'expert_rejected', reason='deliverables must name files: tools', correctable=True, correction_attempt=0)
                expect(panel).to_contain_text('尚未据此启动实施', timeout=7000)
                expect(panel).to_contain_text('下一步修正方案')
                assert page.evaluate('document.activeElement.textContent') == focus
                assert 'tools' not in panel.inner_text()
                passed('real polling update / rejection overrides worker intent / focus retained')

                page.evaluate("""() => { window.progressMutations = 0;
                  new MutationObserver(records => window.progressMutations += records.length)
                    .observe(document.querySelector('.current-progress-copy'), {childList:true, characterData:true, subtree:true}); }""")
                event('run-dma-r1', 'call_dispatched', call_id='pending-progress', role='expert')
                expect(panel).to_contain_text('已有调用派发', timeout=7000)
                event('run-dma-r1', 'worker_call', call_id='pending-progress', role='expert', ok=True)
                expect(panel).not_to_contain_text('已有调用派发', timeout=7000)
                page.wait_for_timeout(3300)
                assert page.evaluate('window.progressMutations') == 0
                expect(panel).to_contain_text('下一步修正方案')
                passed('new call retains last completed result / generic completion never overwrites / unchanged polls do not announce')

                page.reload()
                expect(panel).to_contain_text('下一步修正方案')
                page.get_by_label('选择运行', exact=True).select_option(other)
                expect(panel).to_contain_text('暂无已记录的进展说明')
                expect(panel).not_to_contain_text('修正方案')
                page.get_by_label('选择运行', exact=True).select_option(prep)
                expect(panel).to_contain_text('研究准备')
                expect(panel).to_contain_text('尚未启动正式研究')
                expect(panel).not_to_contain_text('正式运行')
                passed('refresh / switch Run without stale narration / preparation scope before formal Run')

                event('run-dma-r1', 'execution', 1, call_id='long-copy',
                      progress_summary=('已经完成容量检查，但目前尚未验证释放后的恢复行为。' * 12) + '下一步补充恢复验证。')
                event('run-dma-r1', 'candidate_saved', 1, commit='d' * 40)
                page.get_by_label('选择运行', exact=True).select_option(run)
                expect(panel).to_contain_text('已经完成容量检查')
                page.set_viewport_size(dict(width=390, height=844))
                for layout in ('画布', '工作列表'):
                    page.get_by_role('button', name=layout, exact=True).click()
                    panel.scroll_into_view_if_needed()
                    size = panel.bounding_box()
                    assert size and size['width'] <= 390
                    assert page.locator('.current-progress-copy p').evaluate('(p) => p.scrollWidth <= p.clientWidth')
                    page.screenshot(path=str(args.out / ('narrow-canvas.png' if layout == '画布' else 'narrow-desk.png')), full_page=True)
                passed('long Chinese paragraphs wrap at 390px in both layouts')
                other_task = next(t for t in adapter.overview()['data']['tasks'] if t['research_task_id'] == 'R02')
                page.get_by_label('选择任务', exact=True).select_option(other_task['id'])
                expect(panel).to_contain_text('暂无已记录的进展说明')
                expect(panel).not_to_contain_text('容量检查')
                assert not errors, errors
                passed('task switch clears old result / no browser errors')
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=5)
        (args.out / 'result.json').write_text(json.dumps(dict(checks=checks), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
