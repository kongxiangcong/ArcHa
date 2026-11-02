"""Topic discovery and semantic live views use ordinary isolated records, no workers."""
import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from opc.observer.adapter import ObserverAdapter
from opc.observer.demo import create_demo
from opc.observer.paths import resolve_topics


def topic(root, name):
    base = root / '.opc/research/topics' / name
    task = base / 'tasks/r01'
    task.mkdir(parents=True)
    (base / 'research-map.md').write_text('- [x] R01 | [Same title](tasks/r01/task.md) | status=ready-for-onboard | depends=none\n')
    (task / 'task.md').write_text('# Same title\n')
    brief = 'Task: ' + str((task / 'task.md').relative_to(root)) + '\nGoal: topic ' + name + '\n'
    (task / 'task-brief.md').write_text(brief)
    contract = dict(task_id=name, revision='r0001', goal=name, _source=dict(brief=str((task / 'task-brief.md').relative_to(root)), sha256=hashlib.sha256(brief.encode()).hexdigest()))
    directory = root / '.opc/tasks' / name / 'revisions/r0001'
    directory.mkdir(parents=True)
    (directory / 'task.json').write_text(json.dumps(contract))
    return base


def test_topics_identity_and_incremental_discovery(tmp_path):
    root = create_demo(tmp_path)
    topic(root, 'a'); topic(root, 'b')
    observer = ObserverAdapter(root)
    first = observer.overview()['data']
    tasks = [t for t in first['tasks'] if t['research_task_id'] == 'R01']
    assert {'a', 'b', 'legacy'} <= {t['topic'] for t in tasks}
    assert len({t['id'] for t in tasks}) == len(tasks)
    assert all(t['revision_refs'] for t in tasks if t['topic'] in ('a','b'))
    previous = {t['topic']:t['id'] for t in tasks}
    topic(root, 'c')
    second = observer.overview()['data']['tasks']
    assert any(t['topic'] == 'c' for t in second)
    assert all(previous[t['topic']] == t['id'] for t in second if t['research_task_id'] == 'R01' and t['topic'] in previous)
    more = root / '.opc/research/topics/a/tasks/r02/task.md'
    more.parent.mkdir(); more.write_text('# New task')
    assert any(t['title'] == 'New task' for t in observer.overview()['data']['tasks'])


def test_explicit_single_topic_and_collection_paths(tmp_path, monkeypatch):
    root = create_demo(tmp_path); selected = topic(root, 'decode-pim-mapping'); topic(root, 'other')
    monkeypatch.chdir(root)
    assert resolve_topics('.opc/research/topics/decode-pim-mapping') == (root,selected)
    assert resolve_topics('.opc/research/topics') == (root, selected.parent)
    assert {t['topic'] for t in ObserverAdapter(root, topics=selected).overview()['data']['tasks']} == {'decode-pim-mapping'}
    for path in [selected / 'tasks', selected / 'tasks/r01/task.md', root, root / 'missing']:
        with pytest.raises(ValueError): resolve_topics(path)
    from opc.observer.__main__ import main
    pytest.importorskip('uvicorn')
    with patch('uvicorn.run') as run:
        main(['.opc/research/topics/decode-pim-mapping'])
        adapter = run.call_args.args[0].state.adapter
        assert adapter.root == root and adapter.topics == selected


def test_new_topic_run_is_discovered_without_changing_project_identity(tmp_path):
    root=create_demo(tmp_path); selected=topic(root,'a')
    observer=ObserverAdapter(root,topics=selected)
    task=observer.overview()['data']['tasks'][0]
    assert observer.research_task(task['id'])['data']['runs'] == []
    with sqlite3.connect(root/'.opc/local/ledger.sqlite3') as db:
        db.execute("INSERT INTO runs SELECT 'topic-run','a','r0001',task_digest,component,base_commit,evaluator_digest,toolchain_digest,champion_ref,direction,state,stop_reason,created_at,closed_at FROM runs LIMIT 1")
    runs=observer.research_task(task['id'])['data']['runs']
    assert [r['source_run_id'] for r in runs] == ['topic-run']


def test_history_and_handoffs_require_saved_inputs(tmp_path):
    root=create_demo(tmp_path); observer=ObserverAdapter(root)
    run=observer._id('run','run-dma-r1')
    with sqlite3.connect(root/'.opc/local/ledger.sqlite3') as db:
        for number, work in [(1,'source'),(2,'target')]:
            db.execute('UPDATE attempts SET plan=? WHERE run_id=? AND attempt_no=?',(json.dumps(dict(work_id=work,title=work)),'run-dma-r1',number))
        body=dict(role='designer',call_id='handoff',inputs=dict(context=dict(handoff=dict(inputs=[dict(work_id='source',artifact='outputs/result.md')]))))
        db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)',('run-dma-r1','2026-11-02T00:00:00Z','call_dispatched',2,json.dumps(body)))
    first=observer.workbench(run)['data']
    assert first['handoffs'][0]['source']=='source' and first['handoffs'][0]['target']=='target'
    assert len({t['id'] for t in first['timeline']})==len(first['timeline'])
    assert observer.workbench(run)['data']['timeline']==first['timeline']


def test_topic_tool_activity_keeps_internal_materials_out_of_the_surface(tmp_path):
    root = create_demo(tmp_path)
    log = root / '.opc/local/artifacts/dma-demo/dma-backpressure/run-dma-r1/attempts/a000001/designer-events.jsonl'
    log.write_text(json.dumps(dict(type='thread.started', thread_id='demo-codex-1')) + '\n' +
                   json.dumps(dict(type='item.completed', item=dict(id='internal', type='command_execution',
                       command='cat .opc/research/topics/decode-pim-mapping/tasks/r01/evidence/boundary.md'))) + '\n' +
                   json.dumps(dict(type='item.completed', item=dict(id='public', type='command_execution', command='cat public.py'))) + '\n')
    observer = ObserverAdapter(root)
    call = observer.workbench(observer._id('run', 'run-dma-r1'))['data']['workers'][0]
    actions = observer.activity(call['id'])['data']['actions']
    assert [action['object'] for action in actions] == ['cat public.py']
