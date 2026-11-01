"""Production workbench acceptance over loopback HTTP and ordinary local records.

No models or fake browser responses. Run after npm --prefix web run build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import expect, sync_playwright
from opc.observer.api import create_app
from opc.observer.demo import create_demo


def fingerprint(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.name.endswith(('-wal', '-shm'))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=Path('work/observer-browser'))
    parser.add_argument('--chromium', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    checks = []
    def passed(name):
        checks.append(dict(check=name, status='PASS'))
        print('PASS', name, flush=True)
    with tempfile.TemporaryDirectory(prefix='observer-workbench-') as temp:
        # Fixture utility writes ordinary files/SQLite; app is in normal read-only mode.
        root = create_demo(Path(temp))
        with sqlite3.connect(root / '.opc/local/ledger.sqlite3') as db:
            for n in range(3, 107):
                plan = dict(title='待评价工作 ' + str(n), work_id='w%d' % n, changes='保持中文任务描述、公开接口与已有行为。' * 8)
                db.execute('INSERT INTO attempts(run_id,attempt_no,state,champion_before,plan,started_at) VALUES(?,?,?,?,?,?)',
                           ('run-dma-r1', n, 'designed', 'a'*40, json.dumps(plan, ensure_ascii=False), '2026-11-01T00:00:00Z'))
            db.execute("UPDATE attempts SET outcome='worker_failed',reason='解析命令未通过' WHERE run_id='run-dma-r1' AND attempt_no=106")
            for call_id, role, no in [('parallel-1', 'designer', 3), ('parallel-2', 'designer', 3), ('run-expert', 'expert', None)]:
                log_dir = root / '.opc/local/artifacts/dma-demo/dma-backpressure/run-dma-r1/calls' / call_id
                log_dir.mkdir(parents=True)
                log_path = log_dir / (role + '-events.jsonl')
                log_path.write_text(json.dumps(dict(type='thread.started', thread_id='native-' + call_id)) + '\n' + json.dumps(dict(type='item.started', item=dict(id='read-task', type='command_execution', command='cat parser.py'))) + '\n' + json.dumps(dict(type='item.started', item=dict(id='internal-read', type='command_execution', command='cat ' + str(root / '.opc/research/tasks/r01-dma/evidence/boundary.md')))) + '\n')
                db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)', ('run-dma-r1', '2026-11-01T00:00:00Z', 'call_dispatched', no, json.dumps(dict(call_id=call_id, role=role, receipt_path=str(log_dir / 'receipt.json'), activity_log=dict(provider='codex', path=str(log_path))))))
            # A registered candidate resolves an earlier waiting event without another waiting event.
            plan = dict(title='依赖已有成果', work_id='dependent', dependencies=[dict(work_id='w4', artifact='candidate')])
            db.execute('INSERT INTO attempts(run_id,attempt_no,state,champion_before,plan,started_at) VALUES(?,?,?,?,?,?)', ('run-dma-r1', 107, 'planned', 'a'*40, json.dumps(plan), '2026-11-01T00:00:00Z'))
            for kind, no, body in [('node_waiting', 107, dict(reason='inputs', blocked_by=['w4:candidate'])), ('candidate_saved', 4, dict(commit='b'*40))]:
                db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)', ('run-dma-r1', '2026-11-01T00:00:00Z', kind, no, json.dumps(body)))
        adir = root / '.opc/local/artifacts/dma-demo/dma-backpressure/run-dma-r1/attempts/a000106'
        (adir / 'outputs').mkdir(parents=True)
        (adir / 'outputs/task-output.md').write_text('# 解析任务产出\n\n失败发生于第二行，保留换行后再解析。\n\n[内部材料](../decision.json)\n\n<script>window.__workbenchPwned=true</script>\n', encoding='utf-8')
        with sqlite3.connect(root / '.opc/local/ledger.sqlite3') as db:
            for call_id, purpose, ok in [('diagnose-first', '保留第一次调用的引号输入', False), ('diagnose-retry', '第二次调用采用不同分隔符', True)]:
                inputs = dict(plan=dict(title='解析任务', changes=purpose, deliverables=['task-output.md']), context=dict(handoff=dict(purpose=purpose, evidence='forbidden-internal-content')))
                result = dict(ok=ok, error='' if ok else '解析器返回错误：第二行未闭合', output=dict(summary='已记录本次解析结果'))
                db.execute('INSERT INTO calls(call_id,run_id,attempt_no,role,state,input,result,receipt_path,created_at) VALUES(?,?,?,?,?,?,?,?,?)', (call_id,'run-dma-r1',106,'designer','completed',json.dumps(inputs),json.dumps(result),str(adir / call_id / 'receipt.json'),'2026-11-01T00:00:00Z'))
                for kind,body in [('call_dispatched',dict(call_id=call_id,role='designer',inputs=inputs)),('worker_call',dict(call_id=call_id,role='designer',ok=ok,error=result['error']))]:
                    db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)',('run-dma-r1','2026-11-01T00:00:00Z',kind,106,json.dumps(body)))
                if not ok:
                    db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)',('run-dma-r1','2026-11-01T00:00:00Z','deliverables_saved',106,json.dumps(dict(paths=['outputs/task-output.md','outputs/internal-report.json']))))
        before = fingerprint(root)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(root), host='127.0.0.1', port=port, log_level='warning'))
        thread = threading.Thread(target=server.run, daemon=True); thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError('observer HTTP did not become ready')
            time.sleep(.05)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(args.chromium) if args.chromium else None, headless=True, args=['--no-sandbox'])
                context = browser.new_context(viewport=dict(width=1440, height=1000), locale='zh-CN', reduced_motion='reduce')
                page = context.new_page(); errors = []; requests = []; external = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: requests.append((request.method, request.url)))
                origin = f'http://127.0.0.1:{port}'
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else (external.append(route.request.url), route.abort())[1])
                page.goto(origin)
                expect(page.locator('.heading h1')).to_have_text('DMA 背压行为')
                expect(page.get_by_label('选择运行', exact=True)).to_have_value('')
                options = page.get_by_label('选择运行', exact=True).locator('option').evaluate_all('(xs)=>xs.map(x=>({value:x.value,text:x.textContent}))')
                current_task = page.get_by_label('选择任务', exact=True).input_value()
                run_refs = page.request.get(origin + '/api/observer/v1/research-tasks/' + quote(current_task, safe='')).json()['data']['runs']
                rid = next(x['id'] for x in run_refs if x['source_run_id'] == 'run-dma-r1')
                page.get_by_label('选择运行', exact=True).select_option(rid)
                expect(page.locator('.work-row')).to_have_count(100)
                assert 'run-dma-r1' not in page.get_by_label('选择运行', exact=True).inner_text()
                expect(page.locator('.worker')).to_have_count(7)
                expect(page.locator('.goal')).to_have_text('修复 DMA 满载拒绝与释放恢复')
                expect(page.locator('.worker-task').filter(has_text='运行级协调')).to_have_count(1)
                expect(page.locator('.worker-name').filter(has_text='Designer')).to_have_count(5)
                expect(page.get_by_role('button', name='暂停', exact=True)).to_be_disabled()
                passed('ordinary project / explicit run / actual work / separate parallel and run-level calls / read-only controls')
                # No attention filter/load-more preheats the target page.
                page.locator('.worker').filter(has=page.locator('.worker-task').filter(has_text='工作 106')).first.click()
                expect(page.locator('.inspector-header h2')).to_have_text('待评价工作 106')
                expect(page.locator('[data-attempt="106"]')).to_have_attribute('aria-pressed', 'true')
                target = page.locator('[data-attempt="106"]')
                assert target.evaluate('(el)=>{const r=el.getBoundingClientRect(),p=el.closest(".work-scroll").getBoundingClientRect();return r.bottom>p.top && r.top<p.bottom}')
                page.keyboard.press('Escape')
                task_value = page.get_by_label('选择任务', exact=True).input_value()
                page.goto(origin + '?task=' + quote(task_value, safe='') + '&run=' + quote(rid, safe='') + '&attempt=106')
                expect(page.locator('[data-attempt="106"]')).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('.inspector-header h2')).to_have_text('待评价工作 106')
                page.goto(origin + '?task=' + quote(task_value, safe='') + '&run=' + quote(rid, safe=''))
                expect(page.locator('.work-row')).to_have_count(100)
                page.goto(origin + '?task=history&run=' + quote(rid, safe=''))
                expect(page.get_by_label('选择运行', exact=True).locator('option:checked')).to_contain_text('显式链接')
                assert 'run-dma-r1' not in page.get_by_label('选择运行', exact=True).inner_text()
                page.goto(origin + '?task=' + quote(task_value, safe='') + '&run=' + quote(rid, safe=''))
                expect(page.locator('.work-row')).to_have_count(100)
                passed('initial-page Worker selects unloaded work / deep-link selection and stage / readable run labels / target scroll')
                expect(page.locator('.worker .tool-action').filter(has_text='cat parser.py').first).to_be_visible()
                active_worker = page.locator('.worker').filter(has_text='cat parser.py').first
                active_worker.click()
                expect(page.get_by_label('工作详情', exact=True)).to_contain_text('cat parser.py')
                expect(page.get_by_label('工作详情', exact=True)).to_contain_text('未提供动作时间')
                expect(page.locator('[data-attempt="3"]')).to_have_attribute('aria-pressed', 'true')
                page.keyboard.press('Escape')
                page.locator('[data-attempt="3"]').click()
                expect(page.locator('.worker.selected').filter(has_text='cat parser.py')).to_have_count(2)
                expect(page.get_by_label('工作详情', exact=True)).to_contain_text('cat parser.py')
                page.keyboard.press('Escape')
                passed('inflight concrete tool activity / missing event time / Worker to work and work to Worker')

                page.get_by_role('button', name='需关注', exact=True).click()
                expect(page.locator('.work-row')).to_have_count(1)
                expect(page.locator('.work-row')).to_contain_text('待评价工作 106')
                page.locator('.work-button').click()
                expect(page.get_by_label('工作详情', exact=True)).to_contain_text('解析命令未通过')
                expect(page.get_by_label('工作详情', exact=True)).to_be_focused()
                expect(page.locator('.handoff-input')).to_contain_text('第二次调用采用不同分隔符')
                options = page.get_by_label('选择工作调用', exact=True).locator('option').evaluate_all('(xs)=>xs.map(x=>({id:x.value,text:x.textContent}))')
                first = next(item['id'] for item in options if '调用失败' in item['text'])
                page.get_by_label('选择工作调用', exact=True).select_option(first)
                expect(page.locator('.handoff-input')).to_contain_text('保留第一次调用的引号输入')
                expect(page.locator('.call-error')).to_contain_text('第二行未闭合')
                detail_scroll = page.locator('.inspector-content')
                detail_scroll.evaluate('(el)=>el.scrollTop=el.scrollHeight')
                detail_top = detail_scroll.evaluate('(el)=>el.scrollTop')
                page.get_by_role('button', name='task-output.md', exact=True).click()
                reader = page.get_by_label('任务文件阅读', exact=True)
                expect(reader).to_contain_text('失败发生于第二行')
                page.screenshot(path=str(args.out / 'task-reader.png'))
                assert not reader.locator('a, img, script').count()
                assert '内部材料' not in reader.inner_text()
                assert page.evaluate('window.__workbenchPwned') is None
                expect(page.get_by_role('button', name='暂停', exact=True)).to_be_visible()
                page.get_by_role('button', name='切换深色主题', exact=True).click()
                page.get_by_role('button', name='刷新', exact=True).click()
                expect(reader).to_contain_text('失败发生于第二行')
                page.keyboard.press('Escape')
                expect(page.get_by_role('button', name='task-output.md', exact=True)).to_be_focused()
                expect(page.get_by_label('选择工作调用', exact=True)).to_have_value(first)
                assert abs(detail_scroll.evaluate('(el)=>el.scrollTop') - detail_top) < 2
                expect(page.get_by_role('button', name='需关注', exact=True)).to_have_attribute('aria-pressed','true')
                page.get_by_role('button', name='task-output.md', exact=True).click()
                page.get_by_role('button', name='返回工作现场', exact=True).click()
                expect(page.get_by_role('button', name='task-output.md', exact=True)).to_be_focused()
                page.get_by_role('button', name='切换浅色主题', exact=True).click()
                inspection_url = origin + '/api/observer/v1/runs/' + quote(rid,safe='') + '/attempts/106/inspection?call=' + quote(first,safe='')
                assert page.request.get(inspection_url).json()['data']['input']['purpose'] == '保留第一次调用的引号输入'
                assert page.request.get(inspection_url.replace('/106/','/1/')).status == 422
                passed('failed Call saved input / retry selection / declared material reader / safe links / return selection, scroll and focus')
                page.keyboard.press('Escape')
                expect(page.get_by_label('工作详情', exact=True)).to_have_count(0)
                expect(page.locator('.work-button')).to_be_focused()
                page.get_by_role('button', name='全部', exact=True).click()
                expect(page.locator('.work-row')).to_have_count(107)
                expect(page.locator('[data-attempt="107"]')).to_contain_text('等待派发')
                page.locator('.dependencies button').click()
                expect(page.get_by_label('工作详情', exact=True)).to_contain_text('待评价工作 4')
                page.keyboard.press('Escape')
                passed('server attention filter across all pages / resolved wait / dependency navigation / Escape and focus restoration')
                # Selection and local scrolling survive observation, theme switches and failed refresh.
                page.locator('[data-attempt="80"]').click()
                page.keyboard.press('Escape')
                pane = page.get_by_label('工作时间线', exact=True)
                pane.evaluate('(element)=>element.scrollTop=2300')
                top = pane.evaluate('(element)=>element.scrollTop')
                page.get_by_role('button', name='切换深色主题', exact=True).click()
                expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
                page.wait_for_timeout(1700)
                assert abs(pane.evaluate('(element)=>element.scrollTop') - top) < 2
                expect(page.locator('[data-attempt="80"]')).to_have_attribute('aria-pressed', 'true')
                context.route('**/workbench', lambda route: route.abort())
                page.get_by_role('button', name='刷新', exact=True).click()
                expect(page.get_by_role('status').filter(has_text='更新失败')).to_be_visible()
                expect(page.locator('.worker')).to_have_count(7)
                context.unroute('**/workbench')
                page.get_by_role('button', name='刷新', exact=True).click()
                passed('theme and refresh retain selection / local scroll / failed reads keep last known content')
                # Source and low-level APIs remain read-only, while UI exposes no generic internal navigation.
                visible = page.locator('body').inner_text()
                assert not any(word in visible for word in ('证据', '审计', '哈希', 'SHA-256', '内部检验'))
                assert not page.locator('details, [title], textarea').count()
                response = page.request.get(origin + '/api/observer/v1/runs/' + quote(rid, safe='') + '/work-items?scope=attention&limit=1')
                assert response.status == 200
                assert response.json()['data']['items'][0]['attempt_no'] == 106
                invalid = page.request.get(origin + '/api/observer/v1/runs/' + quote(rid, safe='') + '/work-items?scope=invalid')
                assert invalid.status == 422 and invalid.json()['error']['code'] == 'invalid_parameter'
                denied = page.request.get(origin + '/api/observer/v1/artifacts/../../etc/passwd/content')
                assert denied.status == 404
                assert page.request.post(origin + '/api/observer/v1/runs/' + quote(rid, safe='')).status == 405
                assert fingerprint(root) == before
                passed('no internal reading entries / bounded HTTP query and errors / source files unchanged')
                page.screenshot(path=str(args.out / 'desktop-dark.png'))
                page.get_by_role('button', name='切换浅色主题', exact=True).click()
                page.screenshot(path=str(args.out / 'desktop-light.png'))
                for width, height in [(1024, 768), (390, 844), (320, 740), (1280, 480)]:
                    page.set_viewport_size(dict(width=width, height=height))
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    expect(page.get_by_role('button', name='刷新', exact=True)).to_be_visible()
                    page.screenshot(path=str(args.out / f'viewport-{width}-{height}.png'))
                page.set_viewport_size(dict(width=1024, height=768))
                page.add_style_tag(content='html{font-size:200%} body{font-size:200%}')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.emulate_media(reduced_motion='reduce')
                passed('wide / narrow / short / large text / both themes / reduced motion')
                page.get_by_label('选择任务', exact=True).select_option('history')
                expect(page.get_by_label('选择运行', exact=True)).to_contain_text('准备记录')
                expect(page.locator('.work-row')).to_have_count(0)
                passed('task/run scopes and empty historical workspace')
                assert not errors, errors
                assert not external, external
                assert all(method == 'GET' for method, _ in requests), requests
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError('observer HTTP did not exit')
    (args.out / 'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
