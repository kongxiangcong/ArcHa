"""Exercise the production observer with ordinary source fixtures, no models.

Run after npm --prefix web run build. Requires optional Playwright + Chromium.
Evidence is written to --out (default work/observer-browser).
"""
from __future__ import annotations
import argparse
import hashlib
import json
import socket
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright, expect
from opc.observer.api import create_app
from opc.observer.demo import create_demo


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=Path('work/observer-browser'))
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    checks=[]
    def passed(name):
        checks.append({'check':name,'status':'PASS'})
        print('PASS',name,flush=True)
    with tempfile.TemporaryDirectory(prefix='observer-browser-') as temp:
        root=create_demo(Path(temp)); dbpath=root/'.opc/local/ledger.sqlite3'
        # Source-owned Markdown includes hostile active content and one explicitly linked evidence file.
        evidence=root/'.opc/research/tasks/r01-dma/evidence/boundary.md'
        evidence.parent.mkdir(parents=True,exist_ok=True)
        evidence.write_text('# 证据边界\n\n这是一份来源证据，原文可查看。',encoding='utf-8')
        large=root/'.opc/local/artifacts/dma-demo/dma-backpressure/run-dma-r1/attempts/a000001/large.txt'
        large.write_text('头部\n'+'分页验证\n'*30000+'尾部',encoding='utf-8')
        map_path=root/'.opc/research/research-map.md'
        with map_path.open('a',encoding='utf-8') as stream:
            stream.write('\n[分页产物](../local/artifacts/dma-demo/dma-backpressure/run-dma-r1/attempts/a000001/large.txt)\n[证据边界](tasks/r01-dma/evidence/boundary.md)\n\n<script>window.__observerPwned=true</script>\n\n![远程图片](https://invalid.example/image.png)\n\n[恶意链接](javascript:alert(1))\n')
        before={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(create_app(root,demo=True),host='127.0.0.1',port=port,log_level='warning'))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        deadline=time.monotonic()+10
        while not server.started:
            if time.monotonic()>deadline:raise RuntimeError('service failed to start')
            time.sleep(.05)
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
                context=browser.new_context(viewport={'width':1440,'height':900},locale='zh-CN',timezone_id='Asia/Shanghai',reduced_motion='reduce')
                errors=[];requests=[];external=[]
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda request:requests.append((request.method,request.url)))
                context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(f'http://127.0.0.1:{port}') else (external.append(route.request.url),route.abort())[1])
                page.goto(f'http://127.0.0.1:{port}')
                expect(page.locator('.heading h1')).to_have_text('DMA 背压行为')
                expect(page.locator('.read-time')).to_contain_text('run-dma-r1')
                page.wait_for_function("() => new URLSearchParams(location.search).has('run') && new URLSearchParams(location.search).has('attempt')")
                assert not page.locator('textarea').count()
                assert not page.get_by_role('button',name='停止',exact=True).count()
                expect(page.locator('.mode')).to_contain_text('演示数据')
                expect(page.locator('.usage').first).to_contain_text('USD 未知')
                passed('task-map + honest states + persistent default selection')
                page.locator('.map-body').get_by_role('button',name='证据边界',exact=True).click()
                expect(page.locator('.inspector h2')).to_have_text('boundary.md')
                expect(page.locator('.inspector .source-content')).to_contain_text('这是一份来源证据')
                assert page.evaluate('window.__observerPwned') is None
                assert not external
                page.locator('.map-body').get_by_role('button',name='分页产物',exact=True).click()
                expect(page.locator('.inspector h2')).to_have_text('large.txt')
                page.get_by_role('button',name='查看原文',exact=True).click()
                expect(page.get_by_label('产物原文')).to_contain_text('头部')
                page.get_by_role('button',name='继续读取原文',exact=True).click()
                expect(page.get_by_label('产物原文')).to_contain_text('尾部')
                large.write_text('替换后的短内容',encoding='utf-8')
                expect(page.get_by_label('产物原文')).to_have_text('替换后的短内容',timeout=6000)
                passed('large artifact pagination + truncation resets old offset and content')
                page.locator('.map-body').get_by_role('button',name='调度边界',exact=True).click()
                expect(page.locator('.heading h1')).to_have_text('调度边界')
                page.locator('.task-list button').first.click()
                passed('relative task/evidence links + Markdown script/image safety')
                # Equivalent task list and actual graph link.
                page.locator('.task-list button').nth(1).click()
                expect(page.locator('.heading h1')).to_have_text('调度边界')
                page.locator('.task-list button').first.click()
                expect(page.locator('.heading h1')).to_have_text('DMA 背压行为')
                page.get_by_role('button',name='4 迭代执行').click()
                expect(page.locator('.rounds button')).to_have_count(2)
                expect(page.locator('.facts')).to_contain_text('容量检查已实现')
                page.locator('.call-list button').first.click()
                expect(page.locator('.inspector .message')).to_have_count(4)
                page.locator('.tool summary').first.click()
                expect(page.locator('.tool').first).to_contain_text('pytest')
                page.locator('.tool summary').first.click()
                page.locator('.rounds button').nth(1).click()
                expect(page.locator('.facts')).to_contain_text('未记录')
                page.locator('.call-list button').first.click()
                expect(page.locator('.inspector')).to_contain_text('dsh')
                expect(page.locator('.inspector .message')).to_have_count(4)
                expect(page.locator('.inspector')).not_to_contain_text('保存候选')
                page.locator('.tool summary').first.click()
                expect(page.locator('.tool').first).to_contain_text('read_file')
                passed('Codex/DSH independent readonly assistant-ui + tool disclosure')
                page.locator('.rounds button').first.click()
                patch=page.locator('.file-list .file').filter(has_text='candidate.patch').first
                patch.click()
                expect(page.locator('.inspector h2')).to_contain_text('candidate.patch')
                page.get_by_role('button',name='查看原文',exact=True).click()
                expect(page.get_by_label('产物原文')).to_contain_text('REJECTED')
                deep=page.url;page.reload()
                expect(page.get_by_role('button',name='查看原文',exact=True)).to_be_visible()
                expect(page.locator('.inspector h2')).to_contain_text('candidate.patch')
                assert page.url==deep
                passed('artifact source + original + URL reload restores task/run/phase/attempt/artifact')
                page.get_by_role('button',name='5 交付验收').click()
                expect(page.locator('table tbody')).to_contain_text('未验证')
                page.get_by_placeholder('输入关键词').first.fill('释放')
                expect(page.locator('tbody tr')).to_have_count(1)
                page.get_by_placeholder('输入关键词').first.fill('')
                page.locator('th button').first.click()
                expect(page.locator('tbody tr')).to_have_count(3)
                passed('requirements filtering/sorting + validation method separate from result')
                # Mismatched explicit contract/run deep link must retain historical run goal.
                qs=page.evaluate('Object.fromEntries(new URLSearchParams(location.search))')
                overview=page.request.get(f'http://127.0.0.1:{port}/api/observer/v1/overview').json()['data']
                task=page.request.get(f'http://127.0.0.1:{port}/api/observer/v1/research-tasks/'+qs['task']).json()['data']
                r2=next(x['id'] for x in task['revisions'] if x['revision']=='r0002')
                page.goto(f'http://127.0.0.1:{port}/?task={qs["task"]}&revision={r2}&run={qs["run"]}&phase=loop&attempt=1')
                expect(page.locator('.goal')).to_have_text('修复 DMA 满载拒绝与释放恢复')
                expect(page.get_by_label('选择运行',exact=True)).to_have_value(qs['run'])
                expect(page.locator('.facts')).to_contain_text('容量检查已实现')
                passed('historical run goal remains frozen when selected revision differs')
                page.locator('.rounds button').nth(1).click()
                # No forced jump while a writer updates an older attempt's conclusion.
                with sqlite3.connect(dbpath) as db:
                    db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)',('run-dma-r1','2026-10-28T00:00:00Z','conclusion',1,json.dumps({'text':'浏览器验证：旧轮次结论追加'},ensure_ascii=False)))
                page.wait_for_timeout(2400)
                expect(page.locator('.rounds button').nth(1)).to_have_attribute('aria-pressed','true')
                page.locator('.rounds button').first.click()
                expect(page.locator('.facts')).to_contain_text('浏览器验证：旧轮次结论追加')
                passed('source writer append + background refresh keeps viewed attempt')
                # Failed HTTP poll retains reading data and selection, then recovers.
                page.route('**/api/observer/v1/runs/*',lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'schema_version':'1.0','error':{'code':'source_unreadable','message':'浏览器模拟读取失败'}})))
                expect(page.locator('.alert').filter(has_text='数据可能滞后').first).to_be_visible(timeout=6000)
                expect(page.locator('.facts')).to_contain_text('浏览器验证：旧轮次结论追加')
                page.unroute('**/api/observer/v1/runs/*')
                expect(page.locator('.alert').filter(has_text='浏览器模拟读取失败')).to_have_count(0,timeout=6000)
                passed('HTTP read failure preserves last success and recovers without selection loss')
                page.locator('.call-list button').first.click()
                expect(page.locator('.inspector .message')).to_have_count(4)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out/'desktop-1440x900.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.wait_for_timeout(250)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out/'mobile-390x844.png'),full_page=True)
                # Keyboard visible focus and Enter changes phase, reduced motion is active.
                page.get_by_role('button',name='2 任务目标').focus()
                page.keyboard.press('Tab')
                page.keyboard.press('Shift+Tab')
                assert page.evaluate("getComputedStyle(document.activeElement).outlineStyle !== 'none'")
                page.keyboard.press('Enter')
                expect(page.get_by_role('button',name='2 任务目标')).to_have_attribute('aria-pressed','true')
                assert page.evaluate("matchMedia('(prefers-reduced-motion:reduce)').matches")
                page.set_viewport_size({'width':1440,'height':900})
                page.evaluate("document.documentElement.style.fontSize='200%'")
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                passed('1440x900 + 390x844 + keyboard focus/Enter + reduced motion + enlarged text')
                assert not errors,errors
                assert not external,external
                assert all(method=='GET' for method,_ in requests),requests
                passed('no JS errors, external requests, write requests or tool executions from browsing')
                browser_version=browser.version;browser.close()
            # Only the explicit writer above may have changed source data.
            after={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            assert set(before)==set(after)
            assert all(v==after[k] for k,v in before.items() if k not in {'.opc/local/ledger.sqlite3',str(large.relative_to(root))})
            passed('browsing created no source files and changed no ordinary source content')
            (args.out/'results.json').write_text(json.dumps({'browser':browser_version,'checks':checks,'source_mode':'synthetic source-format fixture','real_user_run':'NOT_RUN'},ensure_ascii=False,indent=2))
        finally:
            server.should_exit=True;thread.join(timeout=5)

if __name__=='__main__':main()
