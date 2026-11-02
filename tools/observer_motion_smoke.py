"""Real-browser acceptance of live topics/motion over loopback and isolated records.
Run after web build: .venv/bin/python tools/observer_motion_smoke.py --out /tmp/archa-motion
No worker/model is started; only this fixture writes its own temporary data.
"""
import argparse
import asyncio
import datetime as dt
import hashlib
import json
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright, expect
from opc.observer.api import create_app
from opc.observer.demo import create_demo


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--out',type=Path,default=Path('/tmp/archa-motion')); args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    checks=[]
    def passed(name):
        checks.append(name); print('PASS',name,flush=True)
    def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix='archa-motion-') as temporary:
        root=create_demo(Path(temporary)); research=root/'.opc/research'; topic=research/'topics/decode-pim-mapping';topic.mkdir(parents=True)
        shutil.move(str(research/'tasks'),topic/'tasks');shutil.move(str(research/'research-map.md'),topic/'research-map.md')
        brief=topic/'tasks/r01-dma/task-brief.md'; text=brief.read_text().replace('.opc/research/research-map.md','.opc/research/topics/decode-pim-mapping/research-map.md');brief.write_text(text)
        (root/'.opc/context/DECISIONS.md').write_text('')
        for file in (root/'.opc/tasks').glob('*/revisions/*/task.json'):
            contract=json.loads(file.read_text());contract['_source']=dict(brief=str(brief.relative_to(root)),sha256=hashlib.sha256(text.encode()).hexdigest());file.write_text(json.dumps(contract))
        other=research/'topics/other/tasks/r01';other.mkdir(parents=True);(other/'task.md').write_text('# Another R01')
        ledger=root/'.opc/local/ledger.sqlite3'
        adir=root/'.opc/local/artifacts/dma-demo/dma-backpressure/run-dma-r1/attempts'
        log=adir/'a000002/live/designer-events.jsonl';log.parent.mkdir(parents=True)
        output=adir/'a000002/outputs/live.txt';output.parent.mkdir(parents=True);output.write_text('first live content')
        def event(kind,no=None,**body):
            with sqlite3.connect(ledger) as db: db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)',('run-dma-r1',now(),kind,no,json.dumps(body)))
        inputs=dict(plan=dict(title='Live implementation',deliverables=['live.txt']),context=dict(handoff=dict(purpose='Read current task',inputs=[dict(work_id='source',artifact='outputs/result.md')])))
        with sqlite3.connect(ledger) as db:
            db.execute('UPDATE attempts SET plan=? WHERE run_id=? AND attempt_no=1',(json.dumps(dict(work_id='source',title='Source work')),'run-dma-r1'))
            db.execute('UPDATE attempts SET plan=? WHERE run_id=? AND attempt_no=2',(json.dumps(dict(work_id='target',title='Live target',dependencies=[dict(work_id='source',artifact='outputs/result.md')])),'run-dma-r1'))
            db.execute('INSERT INTO calls(call_id,run_id,attempt_no,role,state,input,receipt_path,created_at) VALUES(?,?,?,?,?,?,?,?)',('live-call','run-dma-r1',2,'designer','dispatched',json.dumps(inputs),str(log.parent/'receipt.json'),now()))
        log.write_text(json.dumps(dict(type='thread.started',thread_id='live-session'))+'\n'+json.dumps(dict(type='item.started',timestamp=now(),item=dict(id='live-tool',type='command_execution',command='cat visible-task.py')))+'\n')
        event('call_dispatched',2,call_id='live-call',role='designer',inputs=inputs,receipt_path=str(log.parent/'receipt.json'),activity_log=dict(provider='codex',path=str(log)))
        event('deliverables_saved',2,paths=['outputs/live.txt'])
        app=create_app(root,topics=topic);adapter=app.state.adapter
        stall=threading.Event()
        @app.middleware('http')
        async def slow_fixture(request,call_next):
            if stall.is_set() and request.url.path.endswith('/workbench'):
                await asyncio.sleep(9.5)
            return await call_next(request)
        task=next(t for t in adapter.overview()['data']['tasks'] if t['research_task_id']=='R01');run=adapter._id('run','run-dma-r1')
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning'));thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:
            deadline=time.monotonic()+10
            while not server.started:
                assert time.monotonic()<deadline;time.sleep(.05)
            origin=f'http://127.0.0.1:{port}'
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch();context=browser.new_context(viewport=dict(width=1440,height=1000));page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin+'/?'+urlencode(dict(topic='decode-pim-mapping',task=task['id'],run=run)))
                expect(page.get_by_label('选择专题',exact=True)).to_have_value('decode-pim-mapping')
                expect(page.get_by_label('选择专题',exact=True).locator('option')).to_have_count(1)
                expect(page.locator('[data-module="designer"]')).to_contain_text('结果待确认')
                live=page.locator('.worker').filter(has_text='cat visible-task.py').first
                expect(live).to_be_visible();expect(live.locator('canvas')).to_have_count(1)
                passed('single topic / actual module dispatch / bounded real-activity orb')
                page.wait_for_timeout(800);page.screenshot(path=str(args.out/'research-stage-live.png'),full_page=True)
                live.click();expect(page.get_by_label('工作详情',exact=True)).to_contain_text('cat visible-task.py')
                page.get_by_role('button',name='live.txt',exact=True).click();expect(page.get_by_label('任务文件阅读')).to_contain_text('first live content')
                output.write_text('changed during the same call')
                expect(page.get_by_label('任务文件阅读')).to_contain_text('changed during the same call',timeout=7000)
                page.get_by_role('button',name='返回工作现场',exact=True).click()
                passed('same-call material refresh / reader return preserves selected work')
                result=dict(ok=True,output=dict(summary='Live output arrived'),error='')
                with sqlite3.connect(ledger) as db:db.execute('UPDATE calls SET result=?,state=? WHERE call_id=?',(json.dumps(result),'completed','live-call'))
                with log.open('a') as stream:
                    for i in range(2500):stream.write(json.dumps(dict(type='future.event',padding='x'*70))+'\n')
                    stream.write(json.dumps(dict(type='item.completed',timestamp=now(),item=dict(id='tail-proof',type='command_execution',command='echo terminal-tail-proof',exit_code=0)))+'\n')
                event('worker_call',2,call_id='live-call',role='designer',ok=True,log_dir=str(log.parent))
                expect(page.get_by_label('工作详情',exact=True)).to_contain_text('Live output arrived',timeout=7000)
                expect(page.get_by_label('工作详情',exact=True)).to_contain_text('terminal-tail-proof',timeout=7000)
                expect(page.locator('.worker canvas')).to_have_count(0)
                passed('terminal log tail beyond 64KiB drains / result refresh / orb stops')
                page.keyboard.press('Escape');page.get_by_role('button',name='回看演进',exact=True).click();expect(page.get_by_label('研究演进记录')).to_contain_text('调用已返回')
                page.get_by_role('button',name='返回当前现场',exact=True).click()
                # A newly saved handoff activates once, then settles without replay on polling.
                event('call_dispatched',2,call_id='handoff-new',role='evaluator',inputs=inputs)
                expect(page.locator('.handoff-card.activated')).to_have_count(1,timeout=5000)
                page.wait_for_timeout(800);expect(page.locator('.handoff-card.activated')).to_have_count(0)
                page.wait_for_timeout(1800);expect(page.locator('.handoff-card.activated')).to_have_count(0)
                passed('semantic history / real saved handoff activates once then settles')
                context.set_offline(True);expect(page.locator('.notice').filter(has_text='更新失败').first).to_be_visible(timeout=10000)
                context.set_offline(False);expect(page.locator('.notice').filter(has_text='更新失败')).to_have_count(0,timeout=10000)
                passed('network disconnect / stale data / online recovery')
                stall.set()
                expect(page.locator('.notice').filter(has_text='更新失败').first).to_be_visible(timeout=12000)
                stall.clear()
                expect(page.locator('.notice').filter(has_text='更新失败')).to_have_count(0,timeout=12000)
                passed('hung GET times out and subsequent polling recovers')
                # A new run is offered, never silently steals historical browsing.
                with sqlite3.connect(ledger) as db:
                    db.execute("UPDATE runs SET state='closed' WHERE run_id='run-dma-r1'")
                    db.execute("INSERT INTO runs SELECT 'fresh-run',task_id,revision,task_digest,component,base_commit,evaluator_digest,toolchain_digest,champion_ref,direction,'active',NULL,?,NULL FROM runs WHERE run_id='run-dma-r1'",(now(),))
                expect(page.get_by_role('button',name='有当前运行 · 前往查看')).to_be_visible(timeout=10000)
                assert page.get_by_label('选择运行',exact=True).input_value()==run
                page.get_by_role('checkbox',name='跟随此任务的当前运行').check()
                expect(page.get_by_label('选择运行',exact=True)).to_have_value(adapter._id('run','fresh-run'),timeout=7000)
                passed('new run hint does not hijack history / explicit follow selects unique active run')
                page.goto(origin+'/?'+urlencode(dict(topic='decode-pim-mapping',task=task['id'],run=run)))
                page.wait_for_timeout(800); page.screenshot(path=str(args.out/'research-stage-desktop.png'),full_page=True)
                page.emulate_media(reduced_motion='reduce');page.set_viewport_size(dict(width=390,height=844))
                expect(page.get_by_label('议题研究桌')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.get_by_role('button',name='回看演进').click()
                assert page.locator('.evolution').evaluate('(e)=>getComputedStyle(e).animationName')=='none'
                page.keyboard.press('Tab');assert page.evaluate('document.activeElement !== document.body')
                page.screenshot(path=str(args.out/'research-stage-mobile.png'),full_page=True)
                assert not errors,errors
                passed('narrow viewport / reduced motion / keyboard / no browser exceptions')
                # Broaden only this isolated service's discovery selection to exercise topic switching.
                adapter.topics = research / 'topics'
                page.set_viewport_size(dict(width=1440,height=1000))
                expect(page.get_by_label('选择专题',exact=True).locator('option')).to_have_count(2,timeout=10000)
                selected_run=page.get_by_label('选择运行',exact=True).input_value()
                page.get_by_label('选择专题',exact=True).select_option('other')
                expect(page.get_by_label('选择任务',exact=True)).to_contain_text('Another R01')
                page.get_by_label('选择专题',exact=True).select_option('decode-pim-mapping')
                expect(page.get_by_label('选择运行',exact=True)).to_have_value(selected_run)
                passed('collection discovery / duplicate R01 / per-topic selection continuity')
                browser.close()
        finally:
            server.should_exit=True;thread.join(timeout=10)
        (args.out/'checks.json').write_text(json.dumps(dict(checks=checks),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
