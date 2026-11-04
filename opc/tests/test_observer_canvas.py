"""Isolated real-source records shared with the production-build browser check."""
import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from opc.observer.adapter import ObserverAdapter
from opc.observer.demo import create_demo


def source(root):
    create_demo(root)
    research = root / '.opc/research'
    topic = research / 'topics/decode-pim-mapping'
    topic.mkdir(parents=True)
    shutil.move(str(research / 'tasks'), topic / 'tasks')
    shutil.move(str(research / 'research-map.md'), topic / 'research-map.md')
    brief = topic / 'tasks/r01-dma/task-brief.md'
    value = brief.read_text(encoding='utf-8').replace('.opc/research/research-map.md', '.opc/research/topics/decode-pim-mapping/research-map.md')
    brief.write_text(value, encoding='utf-8')
    for file in (root / '.opc/tasks').glob('*/revisions/*/task.json'):
        contract = json.loads(file.read_text(encoding='utf-8'))
        contract['_source'] = dict(brief=brief.relative_to(root).as_posix(), sha256=hashlib.sha256(brief.read_bytes()).hexdigest())
        file.write_text(json.dumps(contract), encoding='utf-8')
    for file in (root / '.opc/local/artifacts').glob('**/frozen/task.json'):
        contract = json.loads(file.read_text(encoding='utf-8')); contract['_source'] = dict(brief=brief.relative_to(root).as_posix(), sha256=hashlib.sha256(brief.read_bytes()).hexdigest()); file.write_text(json.dumps(contract), encoding='utf-8')
    other = research / 'topics/other/tasks/r01'
    other.mkdir(parents=True)
    (other / 'task.md').write_text('# Other R01\n', encoding='utf-8')
    ledger = root / '.opc/local/ledger.sqlite3'
    output = root / '.opc/local/artifacts/dma-demo/dma-backpressure/run-dma-r1/attempts'
    log = output / 'a000002/live/designer-events.jsonl'
    log.parent.mkdir(parents=True)
    def now():
        return dt.datetime.now(dt.timezone.utc).isoformat()
    def event(kind, number=None, **body):
        with sqlite3.connect(ledger) as db:
            db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)', ('run-dma-r1', now(), kind, number, json.dumps(body)))
    plans = {}
    with sqlite3.connect(ledger) as db:
        for n, value in db.execute("SELECT attempt_no,plan FROM attempts WHERE run_id='run-dma-r1'").fetchall():
            plan = json.loads(value)
            plan.update(work_id='work-' + str(n), title='Mapping draft ' + str(n), deliverables=['design.md'])
            plans[n] = plan
            db.execute("UPDATE attempts SET plan=? WHERE run_id='run-dma-r1' AND attempt_no=?", (json.dumps(plan), n))
    for n in (1, 2):
        event('expert_decision', call_id='coord-' + str(n))
        event('work_selected', n, decision_call='coord-' + str(n), work_id='work-' + str(n), batch_size=1)
    first = output / 'a000001/outputs/design.md'
    first.parent.mkdir(parents=True)
    first.write_text('# First design\nCapacity boundary.\n', encoding='utf-8')
    (first.parent / 'private-log.txt').write_text('internal fixture material', encoding='utf-8')
    event('call_dispatched', 1, call_id='canvas-source', role='designer', inputs=dict(plan=plans[1]))
    event('worker_call', 1, call_id='canvas-source', role='designer', ok=True)
    event('deliverables_saved', 1, paths=['outputs/design.md', 'outputs/private-log.txt'])
    inputs = dict(plan=plans[2], context=dict(task=dict(goal='Map the boundary'), handoff=dict(purpose='Use the first design to test transfer constraints', inputs=[dict(work_id='work-1', artifact='outputs/design.md', path=str(first))])))
    event('call_dispatched', 2, call_id='canvas-live', role='designer', inputs=inputs, receipt_path=str(log.parent / 'receipt.json'), activity_log=dict(provider='codex', path=str(log)))
    log.write_text(json.dumps(dict(type='item.started', timestamp=now(), item=dict(id='canvas-tool', type='command_execution', command='cat transfer-constraints.py'))) + '\n', encoding='utf-8')
    with sqlite3.connect(ledger) as db:
        db.execute('INSERT INTO calls(call_id,run_id,attempt_no,role,state,input,receipt_path,created_at) VALUES(?,?,?,?,?,?,?,?)', ('canvas-live', 'run-dma-r1', 2, 'designer', 'started', json.dumps(inputs), str(log.parent / 'receipt.json'), now()))
    return dict(ledger=ledger, topic=topic, output=output, log=log, event=event, plans=plans, inputs=inputs)


def test_content_projection_uses_real_rounds_and_declared_artifacts(tmp_path):
    case = source(tmp_path)
    before = case['ledger'].read_bytes()
    observer = ObserverAdapter(tmp_path, topics=case['topic'].parent)
    run = observer._id('run', 'run-dma-r1')
    data = observer.workbench(run)['data']['canvas']
    assert len(data['rounds']) == 2
    assert [r['attempts'] for r in data['rounds']] == [[1], [2]]
    artifacts = [card for card in data['cards'] if card['kind'] == 'artifact']
    assert len(artifacts) == 1 and artifacts[0]['title'] == 'design.md'
    assert 'private-log' not in json.dumps(data)
    handoff = next(e for e in data['edges'] if e['label'] == '传入任务材料')
    assert handoff['source'] == artifacts[0]['id']
    assert next(c for c in data['cards'] if c['id'] == handoff['target'])['attempt_no'] == 2
    assert not any(e['label'] in ('返回', '等待') for e in data['edges'])
    assert case['ledger'].read_bytes() == before
    restored = ObserverAdapter(tmp_path, topics=case['topic'].parent)
    assert [c['id'] for c in restored.workbench(run)['data']['canvas']['cards']] == [c['id'] for c in data['cards']]


def test_legacy_missing_round_and_dispatch_does_not_infer_interaction(tmp_path):
    create_demo(tmp_path)
    with sqlite3.connect(tmp_path / '.opc/local/ledger.sqlite3') as db:
        for kind in ('expert_decision', 'work_selected'):
            db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)', ('run-dma-r1', '2026-11-02', kind, 1, '{}'))
    observer = ObserverAdapter(tmp_path)
    data = observer.workbench(observer._id('run', 'run-dma-r1'))['data']['canvas']
    assert data['cards'] and not data['rounds'] and not data['edges']
    assert all(card['round_id'] is None for card in data['cards'])


def test_preparation_canvas_without_any_run_stays_preparation(tmp_path):
    from opc.tests.test_observer_preparation import fixture
    fixture(tmp_path)
    observer = ObserverAdapter(tmp_path)
    run = observer._id('run', 'preparation:dma-backpressure')
    data = observer.workbench(run)['data']
    assert data['kind'] == 'preparation'
    assert data['canvas']['cards'][0]['kind'] == 'preparation'
    assert data['canvas']['cards'][0]['role'] == 'onboard'
    assert not data['canvas']['edges'] and not data['canvas']['rounds']
    with sqlite3.connect(tmp_path / '.opc/local/ledger.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_material_update_keeps_identity_and_latest_saved_source(tmp_path):
    case = source(tmp_path)
    observer = ObserverAdapter(tmp_path)
    run = observer._id('run', 'run-dma-r1')
    first = next(c for c in observer.workbench(run)['data']['canvas']['cards'] if c['kind'] == 'artifact')
    case['event']('deliverables_saved', 1, paths=['outputs/design.md'])
    later = next(c for c in observer.workbench(run)['data']['canvas']['cards'] if c['kind'] == 'artifact')
    assert later['id'] == first['id'] and later['sequence'] > first['sequence']
    assert not any(edge['source'] == later['id'] and edge['label'] == '传入任务材料' for edge in observer.workbench(run)['data']['canvas']['edges'])


def test_historical_brief_uses_frozen_binding_and_never_opens_changed_current_file(tmp_path):
    case = source(tmp_path)
    observer = ObserverAdapter(tmp_path)
    run = observer._id('run', 'run-dma-r1')
    first = observer.workbench(run)['data']
    assert first['run_brief']['version'] == 'matched'
    material = first['run_brief']['material']
    assert material['availability'] == 'available'
    before = observer.content(material['id'])['data']['content']
    brief = case['topic'] / 'tasks/r01-dma/task-brief.md'
    brief.write_text('UNRELATED CURRENT BRIEF', encoding='utf-8')
    later = observer.workbench(run)['data']
    assert later['run_brief']['version'] == 'unconfirmed' and later['run_brief']['material'] is None
    assert later['run_brief']['goal'] == first['run_brief']['goal']
    assert observer.content(material['id'])['data']['content'] == before
    assert 'UNRELATED' not in before


def test_evaluator_result_and_expert_feedback_have_distinct_authors_and_calls(tmp_path):
    case = source(tmp_path)
    event = case['event']
    event('call_dispatched', 2, call_id='evaluate-2', role='evaluator', inputs={})
    event('evaluation_call', 2, call_id='evaluate-2', role='evaluator', ok=True)
    event('call_dispatched', call_id='analyse-2', role='expert', inputs={})
    event('worker_call', call_id='analyse-2', role='expert', ok=True)
    event('conclusion', 2, reviewed_by_call='analyse-2', text='Expert analysis after evaluation')
    observer = ObserverAdapter(tmp_path)
    data = observer.workbench(observer._id('run', 'run-dma-r1'))['data']
    evaluation = next(c for c in data['canvas']['cards'] if c['kind'] == 'evaluation' and c['attempt_no'] == 2)
    feedback = next(c for c in data['canvas']['cards'] if c['kind'] == 'feedback' and c['attempt_no'] == 2)
    assert evaluation['role'] == 'evaluator' and feedback['role'] == 'expert'
    assert evaluation['call_id'] != feedback['call_id']
    assert next(w for w in data['workers'] if w['id'] == feedback['call_id'])['role'] == 'expert'
    assert feedback['summary'] == 'Expert analysis after evaluation'
