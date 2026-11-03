"""Production UI + real-source fixtures over loopback; no models or research records."""
import argparse
import datetime as dt
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
from playwright.sync_api import sync_playwright, expect
from opc.observer.api import create_app
from opc.tests.test_observer_canvas import source


def serve(app):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline; time.sleep(.05)
    return server, thread, 'http://127.0.0.1:' + str(port)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', type=Path, default=Path('/tmp/archa-canvas-qa')); args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='archa-canvas-qa-') as temporary, sync_playwright() as p:
        root = Path(temporary); case = source(root); app = create_app(root, topics=case['topic'].parent)
        server, thread, origin = serve(app)
        browser = p.chromium.launch(); context = browser.new_context(viewport=dict(width=1440, height=1000)); page = context.new_page(); errors = []; offline = [False]
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' and not (offline[0] and 'ERR_INTERNET_DISCONNECTED' in message.text) else None)
        observer = app.state.adapter; task = next(t for t in observer.overview()['data']['tasks'] if t['topic'] == 'decode-pim-mapping' and t['research_task_id'] == 'R01'); run = observer._id('run', 'run-dma-r1')
        try:
            page.goto(origin + '/?' + urlencode(dict(topic='decode-pim-mapping', task=task['id'], run=run)))
            canvas = page.get_by_label('研究画布', exact=True); expect(canvas).to_be_visible()
            expect(page.locator('.brand-logo')).to_be_visible(); assert 'archa-aha-orange' in page.locator('.brand-logo').get_attribute('src')
            assert not any(text in page.locator('body').inner_text() for text in ['同一条研究，另一种读法', 'CONVERSATION CANVAS', '问题留下来，方向展开'])
            expect(page.locator('[data-card-kind="direction"]')).to_have_count(2)
            expect(page.locator('[data-card-kind="artifact"]')).to_have_count(1)
            expect(page.locator('[data-card-kind="artifact"]')).not_to_contain_text('private-log')
            expect(page.locator('.cc-edge.flash')).to_have_count(0)
            page.get_by_role('button', name='全图', exact=True).click()
            brief = case['topic'] / 'tasks/r01-dma/task-brief.md'; original_brief = brief.read_bytes()
            page.locator('[data-card-kind="brief"]').click()
            expect(page.get_by_label('任务文件阅读')).to_contain_text(original_brief.decode('utf-8').splitlines()[0].lstrip('# '))
            page.keyboard.press('Escape'); expect(canvas).to_be_visible()
            assert page.evaluate('document.activeElement.dataset.cardKind') == 'brief'
            brief.write_text('UNRELATED CURRENT BRIEF', encoding='utf-8'); page.reload()
            page.get_by_role('button', name='全图', exact=True).click(); page.locator('[data-card-kind="brief"]').click()
            expect(page.get_by_label('内容详情', exact=True)).to_contain_text('简报历史版本无法确认')
            expect(page.get_by_label('内容详情', exact=True)).not_to_contain_text('UNRELATED CURRENT BRIEF')
            page.keyboard.press('Escape'); assert page.evaluate('document.activeElement.dataset.cardKind') == 'brief'
            brief.write_bytes(original_brief); page.reload(); page.get_by_role('button', name='全图', exact=True).click()
            print('PASS frozen brief version / changed current file rejected / keyboard focus restoration', flush=True)
            page.get_by_role('button', name='协调 1 · 折叠', exact=True).click()
            expect(page.locator('.cc-round-summary')).to_have_count(1)
            page.locator('.cc-round-summary').click(); expect(page.locator('.cc-round-summary')).to_have_count(0)
            expect(page.get_by_role('button', name='Agent 时间轴', exact=False)).to_have_attribute('aria-expanded', 'true')
            expect(page.locator('.cc-tracks')).to_be_visible()
            page.locator('.cc-span').filter(has_text='工作 2').last.click()
            expect(page.get_by_label('工作详情', exact=True)).to_have_count(0)
            expect(page.locator('.canvas-info.expanded')).to_be_visible()
            card = page.locator('[data-card-kind="implementation"][aria-pressed="true"]')
            page.wait_for_timeout(800)
            box, view = card.bounding_box(), page.locator('.cc-viewport').bounding_box()
            assert box['y'] >= view['y'] and box['y'] + box['height'] <= view['y'] + view['height']
            assert page.locator('.main').evaluate('e=>e.scrollTop') == 0
            expect(page.get_by_label('工作详情', exact=True)).to_have_count(0)
            expect(page.locator('.canvas-info.expanded')).to_be_visible()
            expect(page.locator('.canvas-info')).not_to_contain_text('cat transfer-constraints.py')
            expect(page.get_by_role('button', name='Worker 摘要', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('.cc-card.selected')).to_have_count(1)
            page.get_by_role('button', name='收起信息', exact=True).click()
            page.get_by_role('button', name='全图', exact=True).click()
            page.locator('[data-card-kind="artifact"]').click()
            expect(page.get_by_label('任务文件阅读')).to_have_count(0)
            expect(page.get_by_label('工作详情', exact=True)).to_have_count(0)
            expect(page.locator('.canvas-info.expanded')).to_be_visible()
            page.get_by_role('button', name='收起信息', exact=True).click()
            expect(canvas).to_be_visible()
            expect(page.locator('.cc-span.selected').first).to_have_attribute('aria-label', 'Designer 工作 1 调用已结束')
            print('PASS approved canvas / real round fold / shared timeline selection / declared artifact and focus return', flush=True)

            viewport = page.get_by_label('研究画布视口', exact=True); box = viewport.bounding_box()
            page.mouse.move(box['x'] + box['width'] - 25, box['y'] + box['height'] - 90); page.mouse.down(); page.mouse.move(box['x'] + box['width'] - 95, box['y'] + box['height'] - 35, steps=5); page.mouse.up()
            camera = page.locator('.cc-world').get_attribute('data-camera')
            expect(page.get_by_role('button', name='跟随最新', exact=True)).to_have_attribute('aria-pressed', 'false')
            output = case['output'] / 'a000002/outputs/design.md'; output.parent.mkdir(parents=True, exist_ok=True); output.write_text('# Second design\nTransfer constraint rejected.\n', encoding='utf-8')
            case['event']('deliverables_saved', 2, paths=['outputs/design.md'])
            case['event']('execution', 2, completed=True, summary='Second design saved; evaluation rejected transfer constraint')
            case['event']('call_dispatched', 2, call_id='canvas-evaluation', role='evaluator', inputs={})
            case['event']('evaluation_call', 2, call_id='canvas-evaluation', role='evaluator', ok=True)
            case['event']('call_dispatched', call_id='canvas-analysis', role='expert', inputs={})
            case['event']('worker_call', call_id='canvas-analysis', role='expert', ok=True)
            case['event']('conclusion', 2, reviewed_by_call='canvas-analysis', text='Transfer constraint rejected; keep the failure and revise the boundary')
            with sqlite3.connect(case['ledger']) as db: db.execute("UPDATE attempts SET outcome='broken',state='decided' WHERE run_id='run-dma-r1' AND attempt_no=2")
            expect(page.locator('[data-card-kind="artifact"]')).to_have_count(2, timeout=7000)
            expect(canvas).to_contain_text('Transfer constraint rejected')
            assert page.locator('.cc-world').get_attribute('data-camera') == camera
            page.locator('[data-card-kind="feedback"]').filter(has_text='Transfer constraint rejected').click()
            expect(page.get_by_label('工作详情', exact=True)).to_have_count(0)
            expect(page.locator('.canvas-info.expanded')).to_be_visible()
            page.keyboard.press('Escape')
            page.wait_for_timeout(1600); expect(page.locator('.cc-edge.flash')).to_have_count(0)
            page.wait_for_timeout(1700); expect(page.locator('.cc-edge.flash')).to_have_count(0)
            page.get_by_role('button', name='跟随最新', exact=True).click()
            expect(page.get_by_role('button', name='跟随最新', exact=True)).to_have_attribute('aria-pressed', 'true')
            page.get_by_role('button', name='全图', exact=True).click(); page.wait_for_timeout(800)
            page.screenshot(path=str(args.out / 'canvas-desktop.png'), full_page=True)
            print('PASS real content arrival / failure feedback / manual pan survives polling / one-shot semantic motion', flush=True)

            offline[0] = True; context.set_offline(True); expect(page.locator('.notice').filter(has_text='更新失败').first).to_be_visible(timeout=12000)
            context.set_offline(False); expect(page.locator('.notice').filter(has_text='更新失败')).to_have_count(0, timeout=12000); offline[0] = False
            page.get_by_label('选择专题', exact=True).select_option('other'); expect(page.get_by_label('选择任务', exact=True)).to_contain_text('Other R01')
            expect(page.locator('[data-card-kind="artifact"]')).to_have_count(0)
            page.get_by_label('选择专题', exact=True).select_option('decode-pim-mapping'); expect(page.locator('[data-card-kind="artifact"]')).to_have_count(2)
            print('PASS network loss/recovery / topic isolation with another R01 / scope restoration', flush=True)
            page.goto(origin + '/?' + urlencode(dict(topic='decode-pim-mapping', task=task['id'], run=run, attempt=2)))
            expect(page.get_by_label('工作详情', exact=True)).to_contain_text('Mapping draft 2')
            page.get_by_role('button', name='关闭详情', exact=True).click()
            with sqlite3.connect(case['ledger']) as db: db.execute("UPDATE runs SET state='closed' WHERE run_id='run-dma-r1'")
            page.reload(); expect(canvas).to_be_visible(); expect(page.locator('[data-card-kind="artifact"]')).to_have_count(2)
            expect(page.locator('.cc-edge.flash,.cc-card.arrived')).to_have_count(0)
            page.emulate_media(reduced_motion='reduce'); page.set_viewport_size(dict(width=390, height=844));
            if page.get_by_role('button', name='关闭详情', exact=True).is_visible(): page.get_by_role('button', name='关闭详情', exact=True).click()
            page.get_by_role('button', name='跟随最新', exact=True).click()
            expect(page.get_by_role('button', name='减少动态效果', exact=True)).to_have_attribute('aria-pressed', 'true')
            assert page.locator('.cc-world').evaluate('el=>getComputedStyle(el).transitionDuration') == '0s'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert viewport.bounding_box()['height'] > 300
            page.keyboard.press('Tab'); assert page.evaluate('document.activeElement.tagName') != 'BODY'
            page.screenshot(path=str(args.out / 'canvas-mobile.png'), full_page=True)
            assert not errors, errors
            print('PASS historical reload without live replay / reduced motion / narrow screen / keyboard / no console errors', flush=True)
        finally:
            context.close(); server.should_exit = True; thread.join(timeout=10)

        from opc.tests.test_observer_preparation import fixture
        prep = root / 'preparation-only'; prep.mkdir(); log = fixture(prep)
        app = create_app(prep); server, thread, origin = serve(app); context = browser.new_context(viewport=dict(width=1440, height=1000)); page = context.new_page()
        try:
            observer = app.state.adapter; task = next(t for t in observer.overview()['data']['tasks'] if t['research_task_id'] == 'R01')
            # No explicit Run selection: the sole preparation view is discovered automatically.
            page.goto(origin + '/?' + urlencode(dict(task=task['id'])))
            expect(page.locator('[data-card-kind="preparation"]')).to_have_count(1)
            expect(page.get_by_label('研究画布', exact=True)).to_contain_text('非正式 Run')
            with log.open('a', encoding='utf-8') as stream:
                for i in range(2200): stream.write(json.dumps(dict(type='future.event', padding='x'*70)) + '\n')
                stream.write(json.dumps(dict(type='item.completed', item=dict(id='tail', type='command_execution', command='echo preparation-canvas-tail', exit_code=0))) + '\n')
            with sqlite3.connect(prep / '.opc/local/ledger.sqlite3') as db:
                db.execute('INSERT INTO events(run_id,at,kind,body) VALUES(?,?,?,?)', ('preparation:dma-backpressure', dt.datetime.now(dt.timezone.utc).isoformat(), 'worker_call', json.dumps(dict(call_id='assigned', role='onboard', ok=True, log_dir=str(log.parent)))))
            page.locator('.cc-span,.cc-unknown-time').first.click()
            expect(page.locator('.canvas-info')).not_to_contain_text('preparation-canvas-tail')
            expect(page.get_by_role('button', name='Worker 摘要', exact=True)).to_have_attribute('aria-pressed', 'true')
            with sqlite3.connect(prep / '.opc/local/ledger.sqlite3') as db: assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0
            expect(page.locator('[data-card-kind="preparation"]')).to_have_count(1)
            page.get_by_role('button', name='收起信息', exact=True).click(); page.screenshot(path=str(args.out / 'canvas-preparation.png'), full_page=True)
            print('PASS zero-Run preparation / discover on open / internal tool log omitted / no fabricated Run', flush=True)
            old_scope = page.get_by_label('选择运行', exact=True).input_value()
            with sqlite3.connect(prep / '.opc/local/ledger.sqlite3') as db:
                db.execute("INSERT INTO runs VALUES('formal-one','dma-backpressure','r0001','digest','dma','base','eval','tool','','','active',NULL,?,NULL)", (dt.datetime.now(dt.timezone.utc).isoformat(),))
            expect(page.get_by_role('button', name='有当前运行 · 前往查看', exact=True)).to_be_visible(timeout=12000)
            assert page.get_by_label('选择运行', exact=True).input_value() == old_scope
            page.get_by_role('button', name='有当前运行 · 前往查看', exact=True).click()
            expect(page.locator('[data-card-kind="preparation"]')).to_have_count(0)
            expect(page.locator('[data-card-kind="brief"]')).to_have_count(1)
            print('PASS preparation to formal Run / explicit new-run navigation / separate scope', flush=True)
        finally:
            context.close(); browser.close(); server.should_exit = True; thread.join(timeout=10)


if __name__ == '__main__': main()
