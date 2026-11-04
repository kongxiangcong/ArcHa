import json
import sqlite3
from opc.observer.demo import create_demo
from opc.observer.adapter import ObserverAdapter


def fixture(root):
    create_demo(root)
    path=root/'.opc/local/onboard/assigned/onboard-events.jsonl';path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(type='thread.started',thread_id='native-prep'))+'\n'+json.dumps(dict(type='item.started',item=dict(id='tool',type='command_execution',command='cat task-input.py')))+'\n')
    with sqlite3.connect(root/'.opc/local/ledger.sqlite3') as db:
        for table in ('runs','events','calls','attempts','charges'):db.execute('DELETE FROM '+table)
        body=dict(call_id='assigned',role='onboard',inputs=dict(brief_input=dict(brief='.opc/research/tasks/r01-dma/task-brief.md')),activity_log=dict(provider='codex',path=str(path)))
        db.execute('INSERT INTO events(run_id,at,kind,body) VALUES(?,?,?,?)',('preparation:dma-backpressure','2026-11-02T00:00:00Z','call_dispatched',json.dumps(body)))
    return path


def test_preparation_without_runs_or_contract_and_live_terminal_tail(tmp_path):
    path=fixture(tmp_path)
    import shutil
    shutil.rmtree(tmp_path/'.opc/tasks')
    adapter=ObserverAdapter(tmp_path)
    task=next(t for t in adapter.overview()['data']['tasks'] if t['research_task_id']=='R01')
    refs=adapter.research_task(task['id'])['data']['runs'];assert len(refs)==1 and refs[0]['kind']=='preparation'
    ident=refs[0]['id'];scene=adapter.workbench(ident)['data'];assert scene['kind']=='preparation'
    assert not scene['control']['resume']['enabled']
    assert scene['workers'][0]['role']=='onboard' and scene['workers'][0]['state']=='pending'
    call=scene['workers'][0]['id'];first=adapter.activity(call);assert first['data']['actions'][0]['object']=='cat task-input.py'
    with path.open('a') as stream:
        for i in range(2000):stream.write(json.dumps(dict(type='future',padding='x'*60))+'\n')
        stream.write(json.dumps(dict(type='item.completed',item=dict(id='tail',type='command_execution',command='echo preparation-tail',exit_code=0)))+'\n')
    with sqlite3.connect(tmp_path/'.opc/local/ledger.sqlite3') as db:
        for kind,body in [('worker_call',dict(call_id='assigned',role='onboard',ok=True,log_dir=str(path.parent),session_id='native-prep')),('preparation',dict(task_id='dma-backpressure',revision='r0001',state='ready',reason='checks prepared'))]:
            db.execute('INSERT INTO events(run_id,at,kind,body) VALUES(?,?,?,?)',('preparation:dma-backpressure','2026-11-02T00:01:00Z',kind,json.dumps(body)))
    page=adapter.activity(call,first['next_cursor'])
    while page['data']['has_more']:page=adapter.activity(call,page['next_cursor'])
    assert any(a['object']=='echo preparation-tail' for a in page['data']['actions'])
    assert adapter.workbench(ident)['data']['execution']=='ready'
    with sqlite3.connect(tmp_path/'.opc/local/ledger.sqlite3') as db:assert db.execute('SELECT count(*) FROM runs').fetchone()[0]==0
    restored=ObserverAdapter(tmp_path);assert restored.research_task(task['id'])['data']['runs'][0]['id']==ident


def test_preparation_and_execution_are_separate_and_not_attached_by_title(tmp_path):
    fixture(tmp_path);a=ObserverAdapter(tmp_path);task=next(t for t in a.overview()['data']['tasks'] if t['research_task_id']=='R01')
    other=next(t for t in a.overview()['data']['tasks'] if t['research_task_id']=='R02')
    assert a.research_task(other['id'])['data']['runs']==[]
    with sqlite3.connect(tmp_path/'.opc/local/ledger.sqlite3') as db:
        db.execute("INSERT INTO runs VALUES('formal','dma-backpressure','r0001','digest','dma','base','eval','tool','','','active',NULL,'2026-11-02',NULL)")
    refs=a.research_task(task['id'])['data']['runs'];assert {r['kind'] for r in refs}=={'preparation','execution'}


def test_same_r01_in_separate_topics_does_not_share_preparation(tmp_path):
    fixture(tmp_path)
    from opc.tests.test_observer_topics import topic
    a=topic(tmp_path,'a');topic(tmp_path,'b')
    with sqlite3.connect(tmp_path/'.opc/local/ledger.sqlite3') as db:
        body=dict(role='onboard',call_id='a-only',inputs=dict(brief_input=dict(brief=str((a/'tasks/r01/task-brief.md').relative_to(tmp_path)))))
        db.execute('INSERT INTO events(run_id,at,kind,body) VALUES(?,?,?,?)',('preparation:a','2026-11-02','call_dispatched',json.dumps(body)))
    observer=ObserverAdapter(tmp_path,topics=a.parent)
    tasks=observer.overview()['data']['tasks']
    task_a=next(t for t in tasks if t['topic']=='a');task_b=next(t for t in tasks if t['topic']=='b')
    assert len(observer.research_task(task_a['id'])['data']['runs'])==1
    assert observer.research_task(task_b['id'])['data']['runs']==[]



def test_legacy_preparation_receipt_is_visible_without_new_dispatch(tmp_path):
    fixture(tmp_path)
    with sqlite3.connect(tmp_path/'.opc/local/ledger.sqlite3') as db:
        db.execute('DELETE FROM events')
        body=dict(state='pending',reason='existing preparation',brief_input=dict(brief='.opc/research/tasks/r01-dma/task-brief.md'))
        db.execute('INSERT INTO events(run_id,at,kind,body) VALUES(?,?,?,?)',('preparation:dma-backpressure','2026-11-02','preparation',json.dumps(body)))
    observer=ObserverAdapter(tmp_path)
    task=next(t for t in observer.overview()['data']['tasks'] if t['research_task_id']=='R01')
    ref=observer.research_task(task['id'])['data']['runs'][0]
    scene=observer.workbench(ref['id'])['data']
    assert scene['kind']=='preparation' and scene['execution']=='pending' and scene['workers']==[]
    assert scene['preparation_materials']


def test_shared_preparation_scope_with_two_brief_origins_is_quarantined(tmp_path):
    fixture(tmp_path)
    from opc.tests.test_observer_topics import topic
    a=topic(tmp_path,'a');b=topic(tmp_path,'b')
    with sqlite3.connect(tmp_path/'.opc/local/ledger.sqlite3') as db:
        for index,base in enumerate((a,b)):
            body=dict(role='onboard',call_id='shared-'+str(index),inputs=dict(brief_input=dict(brief=str((base/'tasks/r01/task-brief.md').relative_to(tmp_path)))))
            db.execute('INSERT INTO events(run_id,at,kind,body) VALUES(?,?,?,?)',('preparation:shared','2026-11-02','call_dispatched',json.dumps(body)))
    for scope in (a,b,a.parent):
        observer=ObserverAdapter(tmp_path,topics=scope)
        tasks=observer.overview()['data']['tasks']
        assert all(not observer.research_task(t['id'])['data']['runs'] for t in tasks)
        assert any(i['code']=='preparation_owner_ambiguous' for i in observer.issues)
    observer=ObserverAdapter(tmp_path)
    assert any(r['source_run_id']=='preparation:shared' for r in observer.overview()['data']['unlinked_runs'])
