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
        event('run-dma-r1', 'worker_call', call_id='summary-expert', role='expert', ok=True,
              worker_progress_summary='提出释放后恢复容量的假设。\n\n下一步安排对照检查。')
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
                toggle = page.get_by_role('button', name='展开信息', exact=True)
                expect(toggle).to_be_visible()
                expect(page.locator('.canvas-info.expanded')).to_have_count(0)
                assert page.locator('.workbench-overview').count() == 0
                toggle.click()
                panel = page.locator('.canvas-info')
                expect(panel).to_contain_text('已完成容量检查')
                expect(page.locator('.info-copy')).to_have_attribute('aria-live', 'polite')
                page.get_by_role('button', name='任务介绍', exact=True).click()
                expect(panel).to_contain_text('修复 DMA')
                page.get_by_role('button', name='当前进展', exact=True).click()
                size = panel.bounding_box()
                resize = page.get_by_role('button', name='调整信息窗口大小')
                resize.focus(); page.keyboard.press('ArrowLeft'); page.keyboard.press('ArrowDown')
                assert panel.bounding_box()['width'] > size['width']
                before = panel.bounding_box()
                camera = page.locator('.cc-world').get_attribute('data-camera')
                handle = resize.bounding_box()
                page.mouse.move(handle['x']+5,handle['y']+5);page.mouse.down()
                page.mouse.move(handle['x']-25,handle['y']+25,steps=5);page.mouse.up()
                assert panel.bounding_box()['width'] > before['width']
                assert page.locator('.cc-world').get_attribute('data-camera') == camera
                stored_size = page.evaluate('localStorage.getItem("archa-info-size")')
                page.get_by_role('button', name='收起信息').click()
                page.locator('.cc-overall-track .cc-unknown-time').filter(has_text='Expert').last.click()
                details = page.get_by_label('工作详情', exact=True)
                expect(details).to_have_count(0)
                expect(page.get_by_role('button', name='Worker 摘要', exact=True)).to_have_attribute('aria-pressed', 'true')
                expect(panel).to_contain_text('提出释放后恢复容量的假设')
                expect(panel).to_contain_text('该次调用自述')
                page.reload()
                expect(page.locator('.canvas-info.expanded')).to_have_count(0)
                toggle.click()
                assert page.evaluate('localStorage.getItem("archa-info-size")') == stored_size
                page.screenshot(path=str(args.out / 'floating-info.png'), full_page=True)
                passed('tabs / resize persistence / worker click opens summary without details')

                page.get_by_role('button', name='当前进展', exact=True).click()
                event('run-dma-r1', 'expert_rejected', reason='deliverables must name files: tools', correctable=True, correction_attempt=0)
                expect(panel).to_contain_text('尚未据此启动实施', timeout=7000)
                expect(panel).to_contain_text('下一步修正方案')
                page.evaluate("""() => { window.progressMutations = 0;
                  new MutationObserver(records => window.progressMutations += records.length)
                    .observe(document.querySelector('.info-copy'), {childList:true, characterData:true, subtree:true}); }""")
                page.wait_for_timeout(4000)
                assert page.evaluate('window.progressMutations') == 0
                passed('engine rejection remains authoritative / unchanged polling does not reannounce')

                page.get_by_role('button', name='收起信息').click()
                page.locator('.cc-overall-track .cc-unknown-time').filter(has_text='Expert').last.click()
                page.get_by_role('button', name='收起信息', exact=True).click()
                expect(page.locator('.canvas-info.expanded')).to_have_count(0)
                event('run-dma-r1', 'call_dispatched', call_id='pending-summary', role='designer')
                expect(page.locator('.cc-overall-track .cc-span').filter(has_text='Designer')).to_have_count(1, timeout=7000)
                page.locator('.cc-overall-track .cc-span').filter(has_text='Designer').click()
                expect(panel).to_contain_text('暂无该次调用的摘要')
                expect(details).to_have_count(0)
                page.get_by_role('button', name='工作列表', exact=True).click()
                expect(panel).to_be_visible()
                page.get_by_role('button', name='当前进展', exact=True).click()
                expect(panel).to_contain_text('尚未据此启动实施')
                passed('close leaves info collapsed / pending result stays empty / shared desk entry')

                page.get_by_label('选择运行', exact=True).select_option(prep)
                expect(page.locator('.canvas-info.expanded')).to_have_count(0)
                toggle.click()
                expect(panel).to_contain_text('尚未启动正式研究')
                page.get_by_label('选择运行', exact=True).select_option(other)
                toggle.click()
                expect(panel).to_contain_text('暂无已记录的进展说明')
                expect(panel).not_to_contain_text('修正方案')
                passed('preparation without formal Run / scope switching clears old selection')

                page.get_by_role('button', name='画布', exact=True).click()
                page.set_viewport_size(dict(width=390, height=520))
                page.screenshot(path=str(args.out / 'narrow-floating.png'), full_page=True)
                size = panel.bounding_box()
                assert size['width'] <= 390
                page.get_by_role('button', name='收起信息').click()
                main = page.locator('.main')
                main.evaluate('e=>e.scrollTop=0')
                page.locator('.cc-viewport').hover(position=dict(x=20,y=30))
                page.mouse.wheel(0,650);page.wait_for_timeout(500)
                assert main.evaluate('e=>e.scrollTop') > 0
                page.locator('.cc-timeline').scroll_into_view_if_needed()
                box = page.locator('.cc-timeline').bounding_box()
                assert box['y'] >= 0 and box['y'] + box['height'] <= 520
                assert not errors, errors
                passed('narrow info stays in bounds / short window can scroll to timeline / no browser errors')
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=5)
        (args.out / 'result.json').write_text(json.dumps(dict(checks=checks), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
