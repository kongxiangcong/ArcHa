"""Preparation visibility over real loopback HTTP with a zero-Run isolated ledger."""
import json,sqlite3,socket,sys,tempfile,threading,time
from pathlib import Path
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright,expect
from opc.tests.test_observer_preparation import fixture
from opc.observer.api import create_app

def main():
    with tempfile.TemporaryDirectory(prefix='archa-preparation-browser-') as directory:
        root=Path(directory);log=fixture(root);app=create_app(root);a=app.state.adapter
        task=next(t for t in a.overview()['data']['tasks'] if t['research_task_id']=='R01')
        ref=a.research_task(task['id'])['data']['runs'][0]
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning'));thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:
            deadline=time.monotonic()+10
            while not server.started:
                assert time.monotonic()<deadline;time.sleep(.05)
            with sync_playwright() as driver:
                browser=driver.chromium.launch();page=browser.new_page(viewport=dict(width=1440,height=1000));errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{port}/?'+urlencode(dict(task=task['id'],run=ref['id'])))
                expect(page.get_by_label('选择运行',exact=True).locator('option:checked')).to_contain_text('准备记录')
                expect(page.locator('.research-desk')).to_contain_text('尚未启动正式运行')
                expect(page.locator('[data-module="onboard"]')).to_contain_text('结果待确认')
                worker=page.locator('.worker').filter(has_text='cat task-input.py');expect(worker).to_be_visible();worker.click()
                expect(page.get_by_label('工作详情',exact=True)).to_contain_text('cat task-input.py')
                page.keyboard.press('Escape')
                material=page.locator('.prepared-materials button').filter(has_text='task-brief.md');material.click()
                expect(page.get_by_label('任务文件阅读')).to_contain_text('Goal:')
                page.get_by_role('button',name='返回工作现场',exact=True).click();expect(material).to_be_focused()
                with log.open('a') as stream:stream.write(json.dumps(dict(type='item.completed',item=dict(id='tool',type='command_execution',command='cat task-input.py',exit_code=0)))+'\n')
                with sqlite3.connect(root/'.opc/local/ledger.sqlite3') as db:
                    for kind,body in [('worker_call',dict(call_id='assigned',role='onboard',ok=True,session_id='native-prep',log_dir=str(log.parent))),('preparation',dict(state='ready',reason='Preparation completed; formal research not started'))]:
                        db.execute('INSERT INTO events(run_id,at,kind,body) VALUES(?,?,?,?)',('preparation:dma-backpressure','2026-11-02T01:00:00Z',kind,json.dumps(body)))
                expect(page.locator('[data-module="onboard"]')).to_contain_text('调用已结束',timeout=7000)
                expect(page.locator('.research-desk')).to_contain_text('Preparation completed; formal research not started')
                page.reload();expect(page.get_by_label('选择运行',exact=True)).to_have_value(ref['id'])
                page.emulate_media(reduced_motion='reduce');page.set_viewport_size(dict(width=390,height=844));expect(page.locator('.research-desk')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors,errors
                browser.close()
            with sqlite3.connect(root/'.opc/local/ledger.sqlite3') as db:assert db.execute('SELECT count(*) FROM runs').fetchone()[0]==0
            print('PASS zero-Run preparation / module / live tools / materials / terminal / reload / reduced motion')
        finally:server.should_exit=True;thread.join(timeout=10)
if __name__=='__main__':main()
