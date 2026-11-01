"""Read-only observer acceptance against ordinary ArcHa files and SQLite rows.

These tests never construct the Engine/Ledger or launch a worker. The fixture
writer owns all source writes, including concurrent append/update scenarios.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

import pytest

from opc.core.ledger import SCHEMA
from opc.core.model import canonical_json

BASE = '/api/observer/v1'
AT = '2026-10-27T15:00:00+00:00'


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def event(db, run, kind, attempt=None, **body):
    db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)',
               (run, AT, kind, attempt, json.dumps(body, ensure_ascii=False)))


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    put(root / '.opc/project.json', {'project_id': 'test', 'display_name': 'DMA 观察验收', 'components': ['dma']})
    research = root / '.opc/research'
    research.mkdir()
    (research / 'research-map.md').write_text(
        '# DMA 输入背压\n\n- [x] R01 | [满载拒绝](tasks/r01/task.md) | status=ready-for-onboard | depends=none\n'
        '- [ ] R02 | [释放恢复](tasks/r02/task.md) | status=todo | depends=R01\n', encoding='utf-8')
    for task in ['r01', 'r02', 'direct']:
        p = research / 'tasks' / task / 'task.md'
        p.parent.mkdir(parents=True)
        p.write_text('# ' + task + '\n\n一项已有研究讨论。', encoding='utf-8')
    brief = research / 'tasks/r01/task-brief.md'
    brief.write_text('# DMA brief\n\n## Source\nMap: .opc/research/research-map.md\nStatus: ready-for-onboard\n'
                     '\n## Goal\nGoal: 处理满载拒绝\nDone when: 三项验证完成\nDirection: FIFO\n'
                     '\n## Scope and deliverables\n- D1: 补丁\n- R1: 满载拒绝 | verification=automated\n'
                     '- R2: 释放恢复 | verification=review\nObjective: none: 行为修复\n', encoding='utf-8')
    requirements = [{'id': 'R1', 'text': '满载拒绝', 'verification': 'automated', 'gates': ['unit']},
                    {'id': 'R2', 'text': '释放恢复', 'verification': 'review'}]
    contracts = {}
    for revision, goal in [('r0001', '修复满载拒绝'), ('r0002', '新增调度公平性')]:
        contract = {'task_id': 'dma', 'revision': revision, 'component': 'dma', 'goal': goal,
                    'direction': 'FIFO', 'requirements': requirements,
                    'acceptance': {}, 'budget': {'max_tokens': 10000}}
        contracts[revision] = contract
        put(root / '.opc/tasks/dma/revisions' / revision / 'task.json', contract)
    local = root / '.opc/local'
    local.mkdir()
    db = sqlite3.connect(local / 'ledger.sqlite3')
    db.executescript(SCHEMA)
    for run, revision, state in [('old-run', 'r0001', 'closed'), ('new-run', 'r0002', 'active'),
                                 ('prepare-run', 'preparation', 'closed')]:
        digest = hashlib.sha256(canonical_json(contracts[revision]).encode()).hexdigest() if revision in contracts else 'preparation'
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (run, 'dma', revision, digest, 'dma', 'a'*40, 'eval1', 'tool1', '', 'FIFO', state,
                    'budget' if state == 'closed' else None, AT, AT if state == 'closed' else None))
        event(db, run, 'run_created', task='dma', revision=revision)
        if revision in contracts:
            run_dir = local / 'artifacts/test/dma' / run
            put(run_dir / 'frozen/task.json', contracts[revision])
            put(run_dir / 'frozen/baseline.json', {'commit_sha': 'a'*40, 'metrics': {'values': {}}})
    event(db, 'prepare-run', 'preparation', state='ready', reason='已有验收凭据')
    for no in [1, 2]:
        db.execute('INSERT INTO attempts(run_id,attempt_no,state,champion_before,plan,outcome,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?)',
                   ('old-run', no, 'decided' if no == 1 else 'started', 'a'*40,
                    json.dumps({'title': '预期拒绝满载写入', 'changes': ['检查容量后返回']}),
                    'work' if no == 1 else None, AT, AT if no == 1 else None))
    event(db, 'old-run', 'candidate_saved', 1, commit='b'*40, parent='a'*40)
    event(db, 'old-run', 'selected_version', 1, commit='b'*40)
    event(db, 'old-run', 'execution', 1, completed=True, summary='加入容量检查')
    event(db, 'old-run', 'experiment', 1, summary='局部测试通过，未验证恢复')
    event(db, 'old-run', 'conclusion', 1, text='R2 仍未验证', reviewed_by_attempt=2)
    log = local / 'artifacts/test/dma/old-run/attempts/a000001'
    log.mkdir(parents=True, exist_ok=True)
    (log / 'candidate.patch').write_text('diff --git a/dma.py b/dma.py\n+capacity_check()\n', encoding='utf-8')
    codex_events = [ {'type': 'thread.started', 'thread_id': 'codex-one'},
                     {'type': 'item.completed', 'item': {'id': 'm1', 'type': 'agent_message', 'text': '只属于第一次调用'}},
                     {'type': 'item.completed', 'item': {'id': 't1', 'type': 'command_execution', 'command': 'pytest', 'aggregated_output': '1 passed', 'exit_code': 0}},
                     {'type': 'future.provider.event', 'value': '新增事件原文'}]
    (log / 'designer-events.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in codex_events), encoding='utf-8')
    event(db, 'old-run', 'worker_call', 1, role='designer', call_id='codex-one', ok=True, tokens=30, seconds=1, error='', log_dir=str(log))
    dsh_log = local / 'artifacts/test/dma/old-run/attempts/a000002'
    dsh_log.mkdir(parents=True, exist_ok=True)
    (dsh_log / 'expert-events.jsonl').write_text(json.dumps({'type':'session','sessionId':'dsh-two'})+'\n'+json.dumps({'type':'final','text':'只属于第二次调用'}, ensure_ascii=False)+'\n', encoding='utf-8')
    event(db, 'old-run', 'worker_call', 2, role='expert', call_id='dsh-two', ok=True, tokens=15, seconds=1, error='', log_dir=str(dsh_log))
    report = {'promotion_id':'p1', 'run_id':'old-run', 'task':'dma', 'selected_version':'b'*40,
              'baseline':'a'*40,'champion':None,'complete':False,'promotable':False,
              'evidence_key':{'commit':'b'*40, 'task':hashlib.sha256(canonical_json(contracts['r0001']).encode()).hexdigest(),
                              'evaluator':'eval1','toolchain':'tool1','environment':'env1'},
              'requirements':[dict(requirements[0], status='met_by_gates'),dict(requirements[1],status='needs_review')],
              'findings':[{'severity':'block','check':'requirements','text':'R2 needs independent review'}],
              'baseline_metrics':{}, 'selected_metrics':{}, 'champion_metrics':None}
    put(local / 'artifacts/test/dma/old-run/promotion/p1/report.json', report)
    db.commit()
    db.close()
    return root


@pytest.fixture
def client(project, observer_test_client):
    from opc.observer.api import create_app
    with observer_test_client(create_app(project)) as client:
        yield client


def get(client, path):
    response = client.get(BASE + path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['schema_version'] == '1.0'
    assert 'snapshot_at' in body and 'issues' in body and 'next_cursor' in body
    return body


def ident(value):
    return quote(value, safe='')


def runs(client):
    overview = get(client, '/overview')['data']
    refs = {r['id']:r for r in overview['unlinked_runs']}
    for task in overview['tasks']:
        detail = get(client, '/research-tasks/' + ident(task['id']))['data']
        for r in detail['runs']:
            refs[r['id']] = r
    for revision in overview['unlinked_revisions']:
        detail = get(client, '/task-revisions/' + ident(revision['id']))['data']
        for r in detail['runs']:
            refs[r['id']] = r
    return {get(client, '/runs/' + ident(rid))['data']['source_run_id']:rid for rid in refs}


def run(client, name='old-run'):
    return get(client, '/runs/' + ident(runs(client)[name]))['data']


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.name.endswith(('-wal', '-shm'))}


def test_all_entry_kinds_and_stable_ids(client, project):
    first = get(client, '/overview')['data']
    assert first['project']['source_mode'] == 'live'
    assert first['maps'] and len(first['tasks']) >= 3
    assert set(runs(client)) == {'old-run','new-run','prepare-run'}
    from opc.observer.adapter import ObserverAdapter
    second = ObserverAdapter(project).overview()['data']
    assert sorted(t['id'] for t in first['tasks']) == sorted(t['id'] for t in second['tasks'])


def test_history_uses_frozen_contract_not_new_goal(client):
    old = run(client)
    new = run(client, 'new-run')
    assert old['task_revision_id'] != new['task_revision_id']
    revision = get(client, '/task-revisions/' + ident(old['task_revision_id']))['data']['revision']
    assert revision['goal'] == '修复满载拒绝'
    assert revision['revision'] == 'r0001'
    assert old['preparation']['value'] in {'unknown','not_applicable'}
    assert run(client, 'prepare-run')['kind'] == 'preparation'
    assert old['acceptance']['value'] != 'passed'
    assert old['execution']['value'] != 'running'


def test_requirements_are_verification_results_not_methods(client):
    old = run(client)
    rows = {r['id']:r for r in old['requirements']}
    assert rows['R1']['verification'] == 'automated'
    assert rows['R1']['result'] == 'met'
    assert rows['R2']['verification'] == 'review'
    assert rows['R2']['result'] in {'pending_review','unverified'}
    assert rows['R1']['tested_commit'] == 'b'*40
    assert old['versions']['selected'] == 'b'*40
    assert old['metrics'] == []
    assert all(r['result'] == 'unverified' for r in run(client,'new-run')['requirements'])


def test_expected_plan_never_becomes_actual_execution_and_late_conclusion(client):
    rid = runs(client)['old-run']
    first = get(client, f'/runs/{ident(rid)}/attempts/1')['data']
    second = get(client, f'/runs/{ident(rid)}/attempts/2')['data']
    assert first['intent'] is not None
    assert first['execution_summary'] is not None
    assert first['conclusion']['text'] == 'R2 仍未验证'
    assert second['execution_summary'] is None
    assert second['conclusion'] is None
    assert first['candidate_commit'] == 'b'*40


def test_usage_unknown_not_zero_and_live_activity_unconfirmed(client):
    current = run(client,'new-run')
    assert current['execution']['value'] == 'running'
    assert current['execution']['basis'] == 'recorded'
    assert current['usage']['recorded_tokens'] is None
    assert current['usage']['recorded_usd'] is None
    assert current['last_activity_at'] is not None
    call = get(client,'/calls/'+ident(run(client)['calls'][0]['id']))['data']
    assert call['started_at'] is None
    assert call['usage'] is None or call['usage']['recorded_usd'] is None


def test_calls_are_independent_and_unknown_events_preserved(client):
    calls = run(client)['calls']
    assert len({r['id'] for r in calls}) == 2
    texts=[]
    kinds=[]
    for ref in calls:
        data=get(client,'/calls/'+ident(ref['id'])+'/messages')['data']
        texts.append(json.dumps(data, ensure_ascii=False))
        kinds.extend(i['kind'] for i in data['items'])
        assert all(i['call_id']==ref['id'] for i in data['items'])
    assert any('只属于第一次调用' in text for text in texts)
    assert any('只属于第二次调用' in text for text in texts)
    assert all(not('只属于第一次调用' in text and '只属于第二次调用' in text) for text in texts)
    assert 'unknown' in kinds


def test_no_source_business_writes_or_execution_entrypoints(client,project,monkeypatch):
    bind_brief(project)
    import subprocess
    def forbidden(*args,**kwargs):
        pytest.fail('Observer attempted process execution')
    monkeypatch.setattr(subprocess,'Popen',forbidden)
    before=snapshot(project)
    overview=get(client,'/overview')['data']
    for task in overview['tasks']:
        get(client,'/research-tasks/'+ident(task['id']))
    for rid in runs(client).values():
        data=get(client,'/runs/'+ident(rid))['data']
        for no, a in enumerate(data['attempts'], 1):
            detail=get(client,f'/runs/{ident(rid)}/attempts/{no}')['data']
            assert detail['run_id']==rid
        for ref in data['calls']:
            get(client,'/calls/'+ident(ref['id']))
            get(client,'/calls/'+ident(ref['id'])+'/messages')
        for ref in data['artifacts']:
            artifact=get(client,'/artifacts/'+ident(ref['id']))['data']
            if artifact['can_preview']:
                get(client,'/artifacts/'+ident(ref['id'])+'/content')
    assert snapshot(project)==before
    for method in ['post','put','patch','delete']:
        response=getattr(client,method)(BASE+'/overview')
        assert response.status_code==405
        assert response.json()['schema_version']=='1.0'
    assert client.get(BASE+'/control').status_code==404


def test_missing_source_is_empty_and_does_not_initialize(tmp_path):
    from opc.observer.adapter import ObserverAdapter
    empty=tmp_path/'empty'
    empty.mkdir()
    data=ObserverAdapter(empty).overview()
    assert data['data']['tasks']==[]
    assert not (empty/'.opc').exists()


def test_utf8_chunks_respect_byte_boundaries(client,project):
    artifact=next(a for a in run(client)['artifacts'] if 'candidate.patch' in a['label'])
    content=get(client,'/artifacts/'+ident(artifact['id'])+'/content?limit=5')['data']
    assert content['byte_offset']==0
    assert content['next_offset']>0
    assert content['truncated'] and not content['eof']
    assert content['content_version']


def test_unknown_artifact_and_invalid_params_have_uniform_errors(client):
    for path,status in [('/artifacts/not-an-id/content',404),('/overview/../../etc/passwd',404),
                        ('/artifacts/not-an-id/content?offset=-1',422)]:
        response=client.get(BASE+path)
        assert response.status_code==status
        assert response.json()['schema_version']=='1.0'
        assert 'error' in response.json()
    for limit in [0,201]:
        cid=run(client)['calls'][0]['id']
        assert client.get(BASE+'/calls/'+ident(cid)+f'/messages?limit={limit}').status_code==422


def test_sqlite_writer_can_append_between_requests(client,project):
    rid=runs(client)['old-run']
    with sqlite3.connect(project/'.opc/local/ledger.sqlite3',timeout=0.2) as db:
        event(db,'old-run','conclusion',2,text='第二轮补充结论',reviewed_by_attempt=3)
    result=get(client,f'/runs/{ident(rid)}/attempts/2')['data']
    assert result['conclusion']['text']=='第二轮补充结论'


def test_half_line_waits_then_complete_append_appears_without_duplicates(client,project):
    call=next(c for c in run(client)['calls'] if get(client,'/calls/'+ident(c['id']))['data']['provider_call_id']=='codex-one')
    url='/calls/'+ident(call['id'])+'/messages'
    original=get(client,url)
    path=project/'.opc/local/artifacts/test/dma/old-run/attempts/a000001/designer-events.jsonl'
    extra=json.dumps({'type':'item.completed','item':{'id':'m2','type':'agent_message','text':'追加完整消息'}},ensure_ascii=False).encode()
    with path.open('ab') as out:
        out.write(extra[:20])
    half=get(client,url)
    assert len(half['data']['items'])==len(original['data']['items'])
    with path.open('ab') as out:
        out.write(extra[20:]+b'\n')
    complete=get(client,url)
    assert '追加完整消息' in json.dumps(complete,ensure_ascii=False)
    assert len({i['id'] for i in complete['data']['items']})==len(complete['data']['items'])


def test_reused_log_never_backfills_old_call(client,project):
    calls=run(client)['calls']
    cid=next(c['id'] for c in calls if get(client,'/calls/'+ident(c['id']))['data']['provider_call_id']=='codex-one')
    url='/calls/'+ident(cid)+'/messages'
    get(client,url)
    path=project/'.opc/local/artifacts/test/dma/old-run/attempts/a000001/designer-events.jsonl'
    path.write_text(json.dumps({'type':'thread.started','thread_id':'someone-else'})+'\n'+json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'MUST_NOT_LEAK'}})+'\n',encoding='utf-8')
    result=client.get(BASE+url)
    assert result.status_code in {200,409}
    assert 'MUST_NOT_LEAK' not in result.text
    meta=get(client,'/calls/'+ident(cid))['data']
    assert meta['transcript_availability'] in {'missing','partial','unreadable'}


def test_unknown_source_schema_keeps_research_readable(client,project):
    path=project/'.opc/local/ledger.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE runs RENAME TO future_runs')
    overview=get(client,'/overview')
    assert overview['data']['tasks']
    assert overview['issues'] or overview['data']['project']['meta']['issues']


def test_active_html_is_source_only_not_inline_execution(client,project):
    path=project/'.opc/local/artifacts/test/dma/old-run/attempts/a000001/report.html'
    path.write_text('<script>window.evil=true</script><h1>report</h1>',encoding='utf-8')
    artifacts=run(client)['artifacts']
    artifact=next(a for a in artifacts if 'report.html' in a['label'])
    response=client.get(BASE+'/artifacts/'+ident(artifact['id'])+'/content')
    assert response.status_code==200
    assert response.headers['content-type'].startswith('application/json')
    assert '<script>' in response.json()['data']['content']


def test_registered_artifact_symlink_replacement_cannot_escape(client,project,tmp_path):
    artifact=next(a for a in run(client)['artifacts'] if 'candidate.patch' in a['label'])
    secret=tmp_path/'outside.txt'
    secret.write_text('SECRET_OUTSIDE_BOUNDARY',encoding='utf-8')
    patch=project/'.opc/local/artifacts/test/dma/old-run/attempts/a000001/candidate.patch'
    patch.unlink()
    try:
        patch.symlink_to(secret)
    except OSError as exc:
        pytest.skip(f'Symlink unavailable: {exc}')
    response=client.get(BASE+'/artifacts/'+ident(artifact['id'])+'/content')
    assert response.status_code in {403,404,503}
    assert 'SECRET_OUTSIDE_BOUNDARY' not in response.text


def test_explicit_external_artifact_root_is_readable(project,tmp_path,observer_test_client):
    import shutil
    from opc.observer.api import create_app
    external=tmp_path/'external-artifacts'
    old_root=project/'.opc/local/artifacts'
    shutil.move(str(old_root),str(external))
    put(project/'.opc/local/bindings.json',{'artifact_root':str(external),'private_token':'MUST_NOT_PUBLISH_CONFIG'})
    with sqlite3.connect(project/'.opc/local/ledger.sqlite3') as db:
        for seq,body in db.execute("SELECT seq,body FROM events WHERE kind='worker_call'").fetchall():
            value=json.loads(body)
            value['log_dir']=value['log_dir'].replace(str(old_root),str(external))
            db.execute('UPDATE events SET body=? WHERE seq=?',(json.dumps(value),seq))
    with observer_test_client(create_app(project)) as c:
        old=run(c)
        artifact=next(a for a in old['artifacts'] if 'candidate.patch' in a['label'])
        response=get(c,'/artifacts/'+ident(artifact['id'])+'/content')
        assert 'capacity_check' in response['data']['content']
        assert 'MUST_NOT_PUBLISH_CONFIG' not in json.dumps(get(c,'/overview'))


def test_unknown_run_state_preserves_raw_and_never_asserts_success(client,project):
    with sqlite3.connect(project/'.opc/local/ledger.sqlite3') as db:
        db.execute("UPDATE runs SET state='future-state' WHERE run_id='new-run'")
    value=run(client,'new-run')['execution']
    assert value['value']=='unknown'
    assert value['raw_value']=='future-state'


@pytest.mark.parametrize('line_ending', ['\n', '\r\n'], ids=['lf', 'crlf'])
def test_utf8_content_pagination_reassembles_exact_source(client,project,line_ending):
    patch=project/'.opc/local/artifacts/test/dma/old-run/attempts/a000001/candidate.patch'
    expected=line_ending.join(['中文边界', 'ASCII', '最后一行'])
    # Exact source bytes: text-mode writes translate LF on Windows.
    patch.write_bytes(expected.encode('utf-8'))
    artifact=next(a for a in run(client)['artifacts'] if 'candidate.patch' in a['label'])
    offset=0
    result=''
    for _ in range(100):
        data=get(client,'/artifacts/'+ident(artifact['id'])+f'/content?offset={offset}&limit=5')['data']
        assert '\ufffd' not in data['content']
        result+=data['content']
        if data['eof']:
            break
        assert data['next_offset']>offset
        offset=data['next_offset']
    else:
        pytest.fail('UTF-8 content pagination never finished')
    assert result==expected


def test_message_cursor_pages_are_stable_and_deduplicated(client):
    cid=next(c['id'] for c in run(client)['calls'] if get(client,'/calls/'+ident(c['id']))['data']['provider_call_id']=='codex-one')
    url='/calls/'+ident(cid)+'/messages?limit=1'
    first=get(client,url)
    cursor=first['next_cursor']
    assert len(first['data']['items'])==1 and cursor is not None
    second=get(client,url+'&cursor='+ident(cursor))
    retry=get(client,url+'&cursor='+ident(cursor))
    assert second['data']['items']==retry['data']['items']
    assert not ({i['id'] for i in first['data']['items']} & {i['id'] for i in second['data']['items']})


def test_same_call_source_replacement_resets_safe_cursor(client,project):
    cid=next(c['id'] for c in run(client)['calls'] if get(client,'/calls/'+ident(c['id']))['data']['provider_call_id']=='codex-one')
    url='/calls/'+ident(cid)+'/messages'
    cursor=get(client,url+'?limit=1')['next_cursor']
    path=project/'.opc/local/artifacts/test/dma/old-run/attempts/a000001/designer-events.jsonl'
    replacement=path.with_suffix('.new')
    replacement.write_text(json.dumps({'type':'thread.started','thread_id':'codex-one'})+'\n'+json.dumps({'type':'item.completed','item':{'id':'replacement','type':'agent_message','text':'同一调用新文件'}},ensure_ascii=False)+'\n',encoding='utf-8')
    replacement.replace(path)
    result=get(client,url+'?cursor='+ident(cursor))
    assert result['data']['reset'] is True
    assert result['data']['reset_reason']
    assert '同一调用新文件' in json.dumps(result,ensure_ascii=False)


def test_corrupt_complete_line_does_not_hide_later_valid_events(client,project):
    cid=next(c['id'] for c in run(client)['calls'] if get(client,'/calls/'+ident(c['id']))['data']['provider_call_id']=='codex-one')
    path=project/'.opc/local/artifacts/test/dma/old-run/attempts/a000001/designer-events.jsonl'
    with path.open('a',encoding='utf-8') as stream:
        stream.write('{malformed complete line}\n')
        stream.write(json.dumps({'type':'item.completed','item':{'id':'after-corrupt','type':'agent_message','text':'坏行之后有效消息'}},ensure_ascii=False)+'\n')
    result=get(client,'/calls/'+ident(cid)+'/messages')
    assert '坏行之后有效消息' in json.dumps(result,ensure_ascii=False)
    assert result['issues'] or any(i['kind']=='unknown' for i in result['data']['items'])


def bind_brief(project, *, task='dma', revision='r0001', path='.opc/research/tasks/r01/task-brief.md', append=False):
    body=(project/path).read_bytes()
    sha=hashlib.sha256(body).hexdigest()
    target=project/'.opc/context/DECISIONS.md'
    target.parent.mkdir(exist_ok=True)
    with target.open('a' if append else 'w',encoding='utf-8') as stream:
        stream.write(f'task={task} revision={revision} brief={path} sha256={sha}\n')


def selected_revision(client):
    old=run(client)
    return get(client,'/task-revisions/'+ident(old['task_revision_id']))['data']['revision']


def test_explicit_brief_digest_binding_and_changed_content(client,project):
    bind_brief(project)
    revision=selected_revision(client)
    assert revision['link_state']=='verified'
    assert revision['brief_id']
    old_brief_id=revision['brief_id']
    brief=project/'.opc/research/tasks/r01/task-brief.md'
    brief.write_text(brief.read_text(encoding='utf-8')+'\n后续讨论改变了正文。\n',encoding='utf-8')
    changed=selected_revision(client)
    assert changed['link_state']=='digest_mismatch'
    assert changed['brief_id'] is None
    assert old_brief_id != changed['brief_id']
    assert changed['goal']=='修复满载拒绝'
    assert changed['ownership_state']=='verified'
    assert changed['research_task_id']==revision['research_task_id']
    owner=get(client,'/research-tasks/'+ident(changed['research_task_id']))['data']
    assert any(r['id']==changed['id'] for r in owner['revisions'])


def test_multiple_explicit_brief_relations_remain_ambiguous(client,project):
    import shutil
    target=project/'.opc/research/tasks/r02/task-brief.md'
    shutil.copyfile(project/'.opc/research/tasks/r01/task-brief.md',target)
    bind_brief(project)
    bind_brief(project,path='.opc/research/tasks/r02/task-brief.md',append=True)
    revision=selected_revision(client)
    assert revision['link_state']=='ambiguous'
    assert revision['brief_id'] is None


def test_binding_tokens_do_not_match_longer_task_identity(client,project):
    bind_brief(project,task='dma-extra')
    revision=selected_revision(client)
    assert revision['link_state']=='unresolved'
    assert revision['brief_id'] is None


@pytest.mark.parametrize('field,value',[('task','not-this-contract'),('evaluator','not-this-evaluator'),('commit','not-the-selected-commit')])
def test_report_evidence_scope_mismatch_never_grants_acceptance(client,project,field,value):
    path=project/'.opc/local/artifacts/test/dma/old-run/promotion/p1/report.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    report['complete']=True
    report['promotable']=True
    report['evidence_key'][field]=value
    put(path,report)
    old=run(client)
    assert old['acceptance']['value']!='passed'
    assert all(r['result']=='unverified' for r in old['requirements'])
    assert old['report_refs']  # Conflicting evidence remains inspectable.


def test_host_usage_does_not_double_count_ledger_charges_and_unknown_usd(client,project):
    with sqlite3.connect(project/'.opc/local/ledger.sqlite3') as db:
        db.execute('INSERT INTO charges(run_id,attempt_no,role,wall_seconds,tokens,usd,usd_known,at) VALUES(?,?,?,?,?,?,?,?)',
                   ('old-run',1,'designer',2.0,30,None,0,AT))
        event(db,'old-run','host_usage',tokens=30,usd=None,wall_seconds=2.0)
    usage=run(client)['usage']
    assert usage['scope']=='run'
    assert usage['recorded_tokens']==30
    assert usage['recorded_wall_seconds']==2.0
    assert usage['recorded_usd'] is None
    assert usage['completeness'] in {'partial','unknown'}


def test_valid_existing_positive_promotion_report_is_observed(client,project):
    path=project/'.opc/local/artifacts/test/dma/old-run/promotion/p1/report.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    report['complete']=True
    report['promotable']=True
    report['findings']=[]
    for requirement in report['requirements']:
        requirement['status']='met_by_review' if requirement['verification']=='review' else 'met_by_gates'
    put(path,report)
    old=run(client)
    assert old['acceptance']['value']=='passed'
    assert all(r['result']=='met' for r in old['requirements'])


def test_view_only_snapshot_keeps_historical_contract_and_is_not_live(client,project):
    path=project/'.opc/local/artifacts/test/dma/old-run/views/report.json'
    report={'run_id':'old-run','task':'dma','revision':'r0001','state':'closed','stop_reason':'budget_exhausted',
            'result':'no_valid_candidate','champion_ref':'','champion':None,'selected_version':'b'*40,
            'working_version':'b'*40,'baseline':'a'*40,'baseline_metrics':{},'champion_metrics':None,
            'target_met':False,'objective':None,'objective_gain':None,'outcomes':{'work':1},'pending_conclusions':[],
            'spent':{'wall_seconds':2.0,'tokens':30,'usd':None},'budget_left':{'tokens':9970},
            'attempts':[{'run_id':'old-run','attempt_no':1,'state':'decided','champion_before':'a'*40,
                         'plan':{'title':'已有离线计划'},'outcome':'work','reason':'saved','started_at':AT,
                         'parent':'a'*40,'candidate':'b'*40,'execution':{'summary':'已有离线成果'},
                         'experiment':None,'conclusion':'尚缺恢复验证'}], 'champions':[]}
    put(path,report)
    (project/'.opc/local/ledger.sqlite3').unlink()
    before=snapshot(project)
    overview=get(client,'/overview')['data']
    assert overview['project']['source_mode']=='snapshot'
    old=run(client)
    assert old['acceptance']['value']!='passed' or old['report_refs']
    revision=get(client,'/task-revisions/'+ident(old['task_revision_id']))['data']['revision']
    assert revision['goal']=='修复满载拒绝'
    detail=get(client,f'/runs/{ident(old["id"])}/attempts/1')['data']
    assert detail['conclusion']['text']=='尚缺恢复验证'
    assert snapshot(project)==before


@pytest.mark.parametrize('provider_id', ['new-run-call','codex-one'])
def test_same_path_reused_by_another_run_does_not_leak_messages_or_raw_log(client,project,provider_id):
    old=run(client)
    cid=next(c['id'] for c in old['calls'] if get(client,'/calls/'+ident(c['id']))['data']['provider_call_id']=='codex-one')
    call=get(client,'/calls/'+ident(cid))['data']
    log_refs=[r for r in call['artifacts'] if 'events.jsonl' in r['label']]
    assert log_refs
    log_dir=project/'.opc/local/artifacts/test/dma/old-run/attempts/a000001'
    (log_dir/'designer-events.jsonl').write_text(json.dumps({'type':'thread.started','thread_id':provider_id})+'\n'+json.dumps({'type':'item.completed','item':{'id':'new-message','type':'agent_message','text':'SECOND_RUN_PRIVATE'}})+'\n',encoding='utf-8')
    with sqlite3.connect(project/'.opc/local/ledger.sqlite3') as db:
        event(db,'new-run','worker_call',None,role='designer',call_id=provider_id,ok=True,tokens=4,seconds=1,error='',log_dir=str(log_dir))
    new=run(client,'new-run')
    new_messages=get(client,'/calls/'+ident(new['calls'][0]['id'])+'/messages')
    assert 'SECOND_RUN_PRIVATE' in json.dumps(new_messages)
    response=client.get(BASE+'/calls/'+ident(cid)+'/messages')
    assert response.status_code in {200,409}
    assert 'SECOND_RUN_PRIVATE' not in response.text
    raw=client.get(BASE+'/artifacts/'+ident(log_refs[0]['id'])+'/content')
    assert raw.status_code in {404,409}
    assert 'SECOND_RUN_PRIVATE' not in raw.text


def test_active_wal_reads_see_committed_writer_rows_without_blocking(client,project):
    path=project/'.opc/local/ledger.sqlite3'
    with sqlite3.connect(path,timeout=0.2) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
        event(writer,'old-run','conclusion',2,text='WAL 新结论一')
        writer.commit()
        rid=runs(client)['old-run']
        assert get(client,f'/runs/{ident(rid)}/attempts/2')['data']['conclusion']['text']=='WAL 新结论一'
        event(writer,'old-run','conclusion',2,text='WAL 新结论二')
        writer.commit()
        assert get(client,f'/runs/{ident(rid)}/attempts/2')['data']['conclusion']['text']=='WAL 新结论二'
        assert writer.execute('PRAGMA journal_mode').fetchone()[0]=='wal'


def test_unknown_columns_are_diagnosed_without_schema_repair(client,project):
    path=project/'.opc/local/ledger.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE runs')
        db.execute('CREATE TABLE runs(run_id TEXT PRIMARY KEY, future_metadata TEXT)')
        db.execute("INSERT INTO runs VALUES('future-run','{}')")
    overview=get(client,'/overview')
    assert overview['data']['tasks']
    assert overview['issues'] or overview['data']['project']['meta']['issues']
    with sqlite3.connect(path) as db:
        assert [row[1] for row in db.execute('PRAGMA table_info(runs)')]==['run_id','future_metadata']


def update_contract(project, **changes):
    """Fixture writer updates the run's actual matching frozen/source contract."""
    frozen=project/'.opc/local/artifacts/test/dma/old-run/frozen/task.json'
    contract=json.loads(frozen.read_text(encoding='utf-8'))
    contract.update(changes)
    put(frozen,contract)
    put(project/'.opc/tasks/dma/revisions/r0001/task.json',contract)
    sha=hashlib.sha256(canonical_json(contract).encode()).hexdigest()
    with sqlite3.connect(project/'.opc/local/ledger.sqlite3') as db:
        db.execute("UPDATE runs SET task_digest=? WHERE run_id='old-run'",(sha,))
    report_path=project/'.opc/local/artifacts/test/dma/old-run/promotion/p1/report.json'
    report=json.loads(report_path.read_text(encoding='utf-8'))
    report['evidence_key']['task']=sha
    put(report_path,report)
    return sha


def test_later_selected_version_invalidates_old_report_evidence(client,project):
    assert run(client)['versions']['selected']=='b'*40
    with sqlite3.connect(project/'.opc/local/ledger.sqlite3') as db:
        event(db,'old-run','selected_version',2,commit='c'*40)
    value=run(client)
    assert value['versions']['selected']=='c'*40
    assert value['acceptance']['value']=='not_evaluated'
    assert all(r['result']=='unverified' for r in value['requirements'])
    assert value['report_refs']


def test_historical_contract_digest_mismatch_withholds_uncertain_goal_requirements(client,project):
    frozen=project/'.opc/local/artifacts/test/dma/old-run/frozen/task.json'
    changed=json.loads(frozen.read_text(encoding='utf-8'))
    changed['goal']='另一个不属于该运行的目标'
    put(frozen,changed)  # Preserve original ledger digest deliberately.
    value=run(client)
    assert value['task_revision_id'] is None
    assert value['requirements']==[]
    assert value['acceptance']['value']!='passed'
    assert value['meta']['availability']=='partial'
    assert any('digest' in i['code'] for i in value['meta']['issues'])


def test_malformed_requirements_are_not_used_as_completion_conditions(client,project):
    update_contract(project,requirements=42)
    value=get(client,'/runs/'+ident(runs(client)['old-run']))
    assert value['data']['requirements']==[]
    assert value['issues']


@pytest.mark.parametrize('invalid',[42,[None,'unexpected',{'id':'R1','status':[]} ]])
def test_malformed_report_requirements_do_not_crash_or_grant_result(client,project,invalid):
    path=project/'.opc/local/artifacts/test/dma/old-run/promotion/p1/report.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    report['requirements']=invalid
    put(path,report)
    response=get(client,'/runs/'+ident(runs(client)['old-run']))
    assert all(r['result']=='unverified' for r in response['data']['requirements'])
    assert response['issues']


def test_malformed_acceptance_shape_does_not_generate_numeric_measurements(client,project):
    update_contract(project,acceptance=['unexpected'])
    value=run(client)
    assert value['metrics']==[]


def test_numeric_measurements_retain_distinct_commit_scopes_and_conditions(client,project):
    update_contract(project,acceptance={'objective':{'metric':'cycles','direction':'minimize'}})
    def measurements(value,commit,evaluator='eval1'):
        return {'values':{'cycles':value},'source_commit':commit,'evaluator_digest':evaluator,'toolchain_digest':'tool1'}
    with sqlite3.connect(project/'.opc/local/ledger.sqlite3') as db:
        db.execute('INSERT INTO champions VALUES(?,?,?,?,?,?,?)',('old-run',1,'a'*40,json.dumps(measurements(100,'a'*40)),None,'baseline',AT))
        db.execute('INSERT INTO champions VALUES(?,?,?,?,?,?,?)',('old-run',2,'c'*40,json.dumps(measurements(60,'c'*40,'other-evaluator')),1,'champion',AT))
        db.execute("UPDATE attempts SET metrics=? WHERE run_id='old-run' AND attempt_no=1",(json.dumps(measurements(90,'b'*40)),))
    path=project/'.opc/local/artifacts/test/dma/old-run/promotion/p1/report.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    report['selected_metrics']={'cycles':80}
    report['baseline_metrics']={'cycles':100}
    put(path,report)
    value=run(client)
    row=value['metrics'][0]
    assert row['name']=='cycles' and row['direction']=='minimize'
    assert row['baseline']==100 and row['candidate']==90 and row['champion']==60 and row['selected']==80
    assert value['versions']['champion']=='c'*40 and value['versions']['selected']=='b'*40
    assert row['comparison_state']=='not_comparable'
    assert row['scopes']['candidate']['commit']=='b'*40
    assert row['scopes']['champion']['evaluator_digest']=='other-evaluator'
    assert row['source_refs']


def test_contract_content_is_explicit_projection_without_worker_configuration(client,project):
    directory=project/'.opc/local/artifacts/test/dma/old-run'
    path=directory/'frozen/task.json'
    contract=json.loads(path.read_text(encoding='utf-8'))
    contract['workers']={'expert':{'kind':'codex','env':{'SECRET':'MUST_NOT_PUBLISH'},'api_key':'MUST_NOT_PUBLISH'}}
    put(path,contract)
    old=run(client)
    artifact=next(a for a in old['artifacts'] if 'task.json' in a['label'])
    metadata=get(client,'/artifacts/'+ident(artifact['id']))['data']
    assert metadata['content_is_projection'] is True
    assert metadata['can_download'] is False
    assert any(i['code']=='config_projection' for i in metadata['meta']['issues'])
    content=get(client,'/artifacts/'+ident(artifact['id'])+'/content')['data']['content']
    assert json.loads(content)['goal']=='修复满载拒绝'
    assert 'workers' not in json.loads(content)
    assert 'MUST_NOT_PUBLISH' not in content
    assert client.get(BASE+'/artifacts/'+ident(artifact['id'])+'/content?download=1').status_code==404


def test_markdown_evidence_navigation_does_not_register_protected_config(client,project):
    directory=project/'.opc/local/artifacts/test/dma/old-run'
    path=directory/'attempts/a000001/evidence.md'
    path.write_text('[component](../../frozen/component.json)\n[patch](candidate.patch)',encoding='utf-8')
    put(directory/'frozen/component.json',{'env':{'SECRET':'MUST_NOT_PUBLISH'}})
    old=run(client)
    artifact=next(a for a in old['artifacts'] if 'evidence.md' in a['label'])
    metadata=get(client,'/artifacts/'+ident(artifact['id']))['data']
    assert '../../frozen/component.json' not in metadata['link_targets']
    assert metadata['link_targets']['candidate.patch']['kind']=='artifact'


@pytest.mark.parametrize('entry', ['task.md', 'task-brief.md'])
def test_map_task_and_brief_are_one_stable_task(project, entry):
    from opc.observer.adapter import ObserverAdapter
    map_path = project / '.opc/research/research-map.md'
    before = ObserverAdapter(project).overview()['data']
    task_id = next(t['id'] for t in before['tasks'] if t['research_task_id'] == 'R01')
    map_path.write_text(map_path.read_text(encoding="utf-8").replace('tasks/r01/task.md', 'tasks/r01/' + entry), encoding="utf-8")
    adapter = ObserverAdapter(project)
    after = adapter.overview()['data']
    assert len(after['tasks']) == len(before['tasks']) == 3
    assert next(t['id'] for t in after['tasks'] if t['research_task_id'] == 'R01') == task_id
    assert next(iter(adapter.briefs.values()))['link_state'] == 'verified'


def historical_binding(project, form, revision='r0001', path='.opc/research/tasks/r01/task-brief.md'):
    sha = hashlib.sha256((project / path).read_bytes()).hexdigest()
    contract_path = project / f'.opc/tasks/dma/revisions/{revision}/task.json'
    if form == 'source':
        raw = json.loads(contract_path.read_text(encoding="utf-8"))
        raw['_source'] = dict(brief=path, sha256=sha)
        put(contract_path, raw)
    else:
        target = project / '.opc/context/DECISIONS.md'
        target.parent.mkdir(exist_ok=True)
        if form == 'single':
            text = f'task=dma revision={revision} brief={path} sha256={sha}\n'
        else:
            identity = f'dma/dma/{revision}' if form == 'task' else f'.opc/tasks/dma/revisions/{revision}/task.json'
            text = f'- Brief: `{path}`\n- Brief SHA-256: `{sha}`\n- {form.title()}: `{identity}`\n\n'
        with target.open('a', encoding='utf-8') as stream:
            stream.write(text)


@pytest.mark.parametrize('form', ['source', 'task', 'contract', 'single'])
def test_revision_ownership_survives_historical_brief_change(project, form):
    from opc.observer.adapter import ObserverAdapter
    for rev in ('r0001', 'r0002'):
        historical_binding(project, form, rev)
    brief = project / '.opc/research/tasks/r01/task-brief.md'
    brief.write_text(brief.read_text(encoding="utf-8") + '\n更新后的目标。\n', encoding="utf-8")
    adapter = ObserverAdapter(project)
    task = next(t for t in adapter.overview()['data']['tasks'] if t['research_task_id'] == 'R01')
    detail = adapter.research_task(task['id'])['data']
    assert len(detail['revisions']) == 2
    assert {r['label'] for r in detail['runs']} == {'old-run', 'new-run'}
    for revision in detail['revisions']:
        assert revision['research_task_id'] == task['id']
        assert revision['ownership_state'] == 'verified'
        assert revision['link_state'] == 'digest_mismatch'
        assert revision['brief_id'] is None
        assert revision['brief_bindings'][0]['sha256']
    if form != 'source':
        for revision in detail['revisions']:
            assert sum(s['display_path'] == '.opc/context/DECISIONS.md' for s in revision['meta']['source_refs']) == 1


def test_missing_historical_brief_still_has_explicit_owner(project):
    from opc.observer.adapter import ObserverAdapter
    historical_binding(project, 'source')
    (project / '.opc/research/tasks/r01/task-brief.md').unlink()
    revision = next(r for r in ObserverAdapter(project).revisions.values() if r['revision'] == 'r0001')
    assert revision['ownership_state'] == 'verified'
    assert revision['link_state'] == 'unresolved'
    assert revision['brief_id'] is None


def test_conflicting_contract_source_and_handoff_do_not_choose_owner(project):
    from opc.observer.adapter import ObserverAdapter
    historical_binding(project, 'source')
    other = project / '.opc/research/tasks/r02/task-brief.md'
    other.write_text((project / '.opc/research/tasks/r01/task-brief.md').read_text(encoding="utf-8"), encoding="utf-8")
    historical_binding(project, 'single', path='.opc/research/tasks/r02/task-brief.md')
    revision = next(r for r in ObserverAdapter(project).revisions.values() if r['revision'] == 'r0001')
    assert revision['ownership_state'] == 'ambiguous'
    assert revision['research_task_id'] is None
    assert revision['link_state'] == 'ambiguous'


def test_brief_only_and_direct_task_remain_accessible(project):
    from opc.observer.adapter import ObserverAdapter
    path = project / '.opc/research/tasks/only/task-brief.md'
    path.parent.mkdir()
    path.write_text('Goal: 只有简报\n', encoding="utf-8")
    adapter = ObserverAdapter(project)
    tasks = adapter.overview()['data']['tasks']
    assert len(tasks) == 4
    assert any(t['title'] == 'direct' for t in tasks)
    only = next(t for t in tasks if t['title'] == '只有简报')
    assert len(adapter.research_task(only['id'])['data']['briefs']) == 1


def test_same_owner_conflicting_historical_hashes_keep_content_ambiguous(project):
    from opc.observer.adapter import ObserverAdapter
    historical_binding(project, 'source')
    historical_binding(project, 'single')
    decisions = project / '.opc/context/DECISIONS.md'
    decisions.write_text(decisions.read_text(encoding="utf-8").split('sha256=')[0] + 'sha256=' + '0' * 64 + '\n', encoding="utf-8")
    revision = next(r for r in ObserverAdapter(project).revisions.values() if r['revision'] == 'r0001')
    assert revision['ownership_state'] == 'verified'
    assert revision['link_state'] == 'ambiguous'
    assert len(revision['brief_bindings']) == 2


@pytest.mark.parametrize('boundary', ['', '正文', '# 下一条'])
def test_multiline_boundaries_and_conflicting_identities(project, boundary):
    from opc.observer.adapter import ObserverAdapter
    target = project / '.opc/context/DECISIONS.md'
    target.parent.mkdir(exist_ok=True)
    brief = '.opc/research/tasks/r01/task-brief.md'
    target.write_text(f'- Brief: {brief}\n{boundary}\n- Task: dma/r0001\n', encoding="utf-8")
    revision = next(r for r in ObserverAdapter(project).revisions.values() if r['revision'] == 'r0001')
    assert revision['ownership_state'] == 'unresolved'
    target.write_text(f'- Brief: {brief}\n- Task: dma/r0001\n- Contract: dma/r0002\n', encoding="utf-8")
    adapter = ObserverAdapter(project)
    assert all(r['ownership_state'] == 'ambiguous' for r in adapter.revisions.values())
    target.write_text(f'- Brief: {brief}\n- Task: dma/r0001\n', encoding="utf-8")
    revision = next(r for r in ObserverAdapter(project).revisions.values() if r['revision'] == 'r0001')
    assert revision['ownership_state'] == 'verified'
    assert revision['link_state'] == 'unverified'
    assert revision['brief_bindings'] == [dict(path=brief, sha256=None)]
    target.write_text(f'task=dma revision=r0001 brief={brief}\n', encoding="utf-8")
    revision = next(r for r in ObserverAdapter(project).revisions.values() if r['revision'] == 'r0001')
    assert revision['ownership_state'] == 'verified'
    assert revision['link_state'] == 'unverified'
    # Duplicate keys end a record; they must not overwrite earlier identities.
    target.write_text(f'- Brief: {brief}\n- Task: dma/r0001\n- Task: dma/r0002\n', encoding="utf-8")
    revisions = {r['revision']: r for r in ObserverAdapter(project).revisions.values()}
    assert revisions['r0001']['ownership_state'] == 'verified'
    assert revisions['r0002']['ownership_state'] == 'unresolved'


def test_two_map_identities_in_one_directory_remain_ambiguous(project):
    from opc.observer.adapter import ObserverAdapter
    path = project / '.opc/research/research-map.md'
    path.write_text(path.read_text(encoding="utf-8") + '- [ ] R03 | [第二身份](tasks/r01/task-brief.md) | status=todo | depends=none\n', encoding="utf-8")
    historical_binding(project, 'single')
    adapter = ObserverAdapter(project)
    assert len(adapter.tasks) == 4
    revision = next(r for r in adapter.revisions.values() if r['revision'] == 'r0001')
    assert revision['ownership_state'] == 'ambiguous'


def test_no_map_keeps_direct_task_and_brief_entry(project):
    from opc.observer.adapter import ObserverAdapter
    (project / '.opc/research/research-map.md').unlink()
    historical_binding(project, 'source')
    adapter = ObserverAdapter(project)
    assert len(adapter.tasks) == 3
    owner = next(r for r in adapter.revisions.values() if r['revision'] == 'r0001')['research_task_id']
    assert len(adapter.research_task(owner)['data']['briefs']) == 1


def test_digest_match_does_not_hide_ambiguous_brief_source(project):
    from opc.observer.adapter import ObserverAdapter
    # The brief explicitly names a different task while residing beside R01.
    brief = project / '.opc/research/tasks/r01/task-brief.md'
    brief.write_text(brief.read_text(encoding="utf-8").replace('Map: .opc/research/research-map.md', 'Task: .opc/research/tasks/r02/task.md'), encoding="utf-8")
    historical_binding(project, 'source')
    revision = next(r for r in ObserverAdapter(project).revisions.values() if r['revision'] == 'r0001')
    assert revision['ownership_state'] == 'verified'
    assert revision['link_state'] == 'ambiguous'
    assert revision['brief_id'] is None


def test_task_usage_includes_preparation_and_other_runs(project):
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        for owner, tokens in [('old-run', 3), ('new-run', 5), ('preparation:dma', 7)]:
            db.execute('INSERT INTO charges(run_id,attempt_no,role,wall_seconds,tokens,usd,usd_known,at) VALUES(?,?,?,?,?,?,?,?)',
                       (owner, None, 'host', 2, tokens, None, 0, AT))
    from opc.observer.adapter import ObserverAdapter
    adapter = ObserverAdapter(project)
    refs = adapter.overview()['data']['unlinked_runs']
    for revision in adapter.overview()['data']['unlinked_revisions']:
        refs += adapter.task_revision(revision['id'])['data']['runs']
    detail = next(adapter.run(ref['id'])['data'] for ref in refs
                  if adapter.run(ref['id'])['data']['source_run_id'] == 'old-run')
    usage = detail['task_usage']
    assert usage['scope'] == 'task'
    assert usage['includes_preparation']
    assert usage['recorded_tokens'] == 15
    assert usage['recorded_wall_seconds'] == 6
    assert usage['source_refs'][0]['kind'] == 'ledger'


def test_task_editorial_handoff_uses_latest_attributed_source(project):
    from opc.observer.adapter import ObserverAdapter
    brief = '.opc/research/tasks/r01/task-brief.md'
    row = dict(task_id='dma', revision='r0001', brief=brief,
               contract='.opc/tasks/dma/revisions/r0001/task.json', sha256='0' * 64)
    target = project / '.opc/context/DECISIONS.md'
    target.parent.mkdir(exist_ok=True)
    target.write_text('<!-- archa-handoff ' + json.dumps(row) + ' -->\n', encoding='utf-8')
    row.update(sha256=hashlib.sha256((project / brief).read_bytes()).hexdigest(), change='editorial')
    with target.open('a', encoding='utf-8') as stream:
        stream.write('<!-- archa-handoff ' + json.dumps(row) + ' -->\n')
    contract = project / row['contract']
    original = json.loads(contract.read_text(encoding='utf-8'))
    original['_source'] = dict(brief=brief, sha256='0' * 64)
    put(contract, original)
    revision = next(r for r in ObserverAdapter(project).revisions.values() if r['revision'] == 'r0001')
    assert revision['link_state'] == 'verified'
    assert len(revision['brief_bindings']) == 1
    assert any(ref['display_path'] == '.opc/context/DECISIONS.md' for ref in revision['meta']['source_refs'])


def test_run_compatibility_keeps_legacy_material_readable(project):
    from opc.observer.adapter import ObserverAdapter
    adapter = ObserverAdapter(project)
    refs = adapter.overview()['data']['unlinked_runs']
    for revision in adapter.overview()['data']['unlinked_revisions']:
        refs += adapter.task_revision(revision['id'])['data']['runs']
    detail = next(adapter.run(ref['id'])['data'] for ref in refs
                  if adapter.run(ref['id'])['data']['source_run_id'] == 'old-run')
    assert detail['compatibility']['record']['state'] == 'readable'
    assert detail['compatibility']['execution']['state'] == 'blocked'
    assert detail['compatibility']['measurement']['state'] == 'unknown'
    assert detail['report_refs']


def test_environment_recheck_baseline_uses_its_own_measurement_source(project):
    update_contract(project, acceptance={'objective': {'metric': 'loss', 'direction': 'minimize'}})
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        event(db, 'old-run', 'measurement_baseline', commit='a' * 40, cached=False,
              metrics={'values': {'loss': 123}, 'source_commit': 'a' * 40,
                       'evaluator_digest': 'eval1', 'toolchain_digest': 'tool2'})
    from opc.observer.adapter import ObserverAdapter
    adapter = ObserverAdapter(project)
    refs = adapter.overview()['data']['unlinked_runs']
    for revision in adapter.overview()['data']['unlinked_revisions']:
        refs += adapter.task_revision(revision['id'])['data']['runs']
    detail = next(adapter.run(ref['id'])['data'] for ref in refs
                  if adapter.run(ref['id'])['data']['source_run_id'] == 'old-run')
    assert detail['metrics'][0]['baseline'] == 123
    assert detail['metrics'][0]['scopes']['baseline']['toolchain_digest'] == 'tool2'
    assert any('events.seq=' in (source.get('locator') or '')
               for source in detail['metrics'][0]['source_refs'])


def test_pending_call_and_pause_request_remain_distinct_from_paused_run(project, client):
    db = sqlite3.connect(project / '.opc/local/ledger.sqlite3')
    db.execute("UPDATE runs SET state='active' WHERE run_id='old-run'")
    log = project / '.opc/local/artifacts/test/dma/old-run/attempts/a000002/designer'
    event(db, 'old-run', 'call_dispatched', 2, call_id='call-current', role='designer',
          inputs={'tree': 'fixed-worktree'}, receipt_path=str(log / 'receipt.json'))
    event(db, 'old-run', 'control_pause')
    db.commit()
    observed = run(client)
    assert observed['execution']['value'] == 'running'
    assert observed['control_request'] == 'pause'
    pending = [get(client, '/calls/' + ident(c['id']))['data'] for c in observed['calls']]
    pending = [c for c in pending if c['state']['raw_value'] == 'dispatched']
    assert len(pending) == 1
    assert pending[0]['state']['value'] == 'running' and pending[0]['ended_at'] is None
    ident_before = pending[0]['id']
    event(db, 'old-run', 'worker_call', 2, call_id='call-current', role='designer',
          ok=False, state='cancelled', log_dir=str(log), error='stopped by user')
    db.commit()
    after = run(client)
    same_call = [c for c in after['calls'] if c['id'] == ident_before]
    assert len(same_call) == 1
    assert get(client, '/calls/' + ident(ident_before))['data']['state']['value'] == 'cancelled'
    db.close()


def test_run_shows_frozen_role_backends_without_exposing_cli_credentials(client, project):
    baseline = project / '.opc/local/artifacts/test/dma/old-run/frozen/baseline.json'
    put(baseline, {'execution': {
        'workers': {'expert': {'kind': 'codex', 'model': 'frozen-model', 'native_model_provider': 'local', 'native_profile': 'research', 'env': {'PRIVATE_KEY': 'hidden'}},
                    'reviewer': {'kind': 'codex', 'model': 'independent-reviewer'}},
        'configuration_sources': {'workers.expert.kind': '.opc/local/workers.json'}}})
    before = snapshot(project)
    data = run(client)
    assert data['workers'] == {'expert': {'kind': 'codex', 'model': 'frozen-model', 'native_model_provider': 'local', 'native_profile': 'research'},
                               'reviewer': {'kind': 'codex', 'model': 'independent-reviewer'}}
    assert data['configuration_sources']['workers.expert.kind'] == '.opc/local/workers.json'
    assert 'hidden' not in json.dumps(data)
    assert snapshot(project) == before


def observed_run(adapter, source_run_id):
    overview = adapter.overview()['data']
    refs = list(overview['unlinked_runs'])
    for revision in overview['unlinked_revisions']:
        refs += adapter.task_revision(revision['id'])['data']['runs']
    return next(adapter.run(item['id'])['data'] for item in refs
                if adapter.run(item['id'])['data']['source_run_id'] == source_run_id)


def test_unknown_call_keeps_partial_usage_and_unknown_terminal(project):
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        event(db, 'new-run', 'worker_call', role='expert', call_id='archa-unknown', session_id='native',
              state='unknown', ok=False, tokens=0, seconds=2, usage_complete=False)
    from opc.observer.adapter import ObserverAdapter
    adapter = ObserverAdapter(project)
    current = observed_run(adapter, 'new-run')
    call = adapter.call(current['calls'][-1]['id'])['data']
    assert call['state']['value'] == 'unknown'
    assert call['usage']['recorded_tokens'] is None
    assert call['usage']['recorded_wall_seconds'] == 2
    assert call['usage']['completeness'] == 'unknown'


def test_observer_distinguishes_switched_execution_allowance_from_history(project):
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        cutoff = db.execute('SELECT MAX(seq) FROM events').fetchone()[0]
        event(db, 'new-run', 'run_created')
        event(db, 'new-run', 'budget_origin', source_run='old-run', after_event=cutoff, tokens=10, wall_seconds=3)
        for owner, tokens in [('old-run', 10), ('new-run', 2)]:
            db.execute('INSERT INTO charges(run_id,role,wall_seconds,tokens,usd,usd_known,at) VALUES(?,?,?,?,?,?,?)',
                       (owner, 'expert', 1, tokens, None, 0, AT))
    put(project / '.opc/local/artifacts/test/dma/new-run/frozen/baseline.json',
        {'execution': {'budget_origin': {'source_run':'old-run', 'after_event':cutoff, 'tokens':10, 'wall_seconds':3}}})
    from opc.observer.adapter import ObserverAdapter
    adapter = ObserverAdapter(project)
    current = observed_run(adapter, 'new-run')
    assert current['task_usage']['recorded_tokens'] == 12
    assert current['execution_usage']['recorded_tokens'] == 2
    assert current['budget_origin']['source_run'] == 'old-run'


def test_workbench_projects_real_stages_dependencies_and_filtered_pages(project):
    from opc.observer.adapter import ObserverAdapter
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        for n, stage, plan in [(3, 'planned', {'title': '等待前序', 'work_id': 'consumer', 'dependencies': [{'work_id': 'producer', 'artifact': 'result'}]}),
                               (4, 'designed', {'title': '等待评价', 'work_id': 'producer'}),
                               (5, 'decided', {'title': '等待反馈'}),
                               (6, 'planned', {'title': '失败重试'})]:
            db.execute('INSERT INTO attempts(run_id,attempt_no,state,champion_before,plan,outcome,started_at) VALUES(?,?,?,?,?,?,?)',
                       ('new-run', n, stage, 'a'*40, json.dumps(plan), 'work' if n == 5 else None, AT))
        event(db, 'new-run', 'node_waiting', 3, reason='inputs', blocked_by=['producer:result'])
        event(db, 'new-run', 'node_waiting', 4, reason='inputs', blocked_by=['removed'])
        event(db, 'new-run', 'node_waiting', 4, reason='ready', blocked_by=[])
        event(db, 'new-run', 'execution', 6, completed=False, error='worker unavailable')
        event(db, 'new-run', 'worker_call', 6, call_id='failed-call', role='designer', ok=False, error='worker unavailable')
        event(db, 'new-run', 'call_dispatched', 4, call_id='parallel-one', role='designer', receipt_path='unused/receipt.json')
        event(db, 'new-run', 'call_dispatched', 4, call_id='parallel-two', role='designer', receipt_path='unused/receipt.json')
        event(db, 'new-run', 'call_dispatched', call_id='run-expert', role='expert', receipt_path='unused/receipt.json')
    adapter = ObserverAdapter(project)
    rid = next(r['id'] for r in adapter.overview()['data']['unlinked_runs'] if r['source_run_id'] == 'new-run')
    before = snapshot(project)
    scene = adapter.workbench(rid)['data']
    assert scene['execution'] == 'active'
    assert scene['control']['pause']['enabled'] is False
    assert len(scene['workers']) == 4
    assert sum(c['attempt_no'] is None for c in scene['workers']) == 1
    assert all('artifacts' not in c and 'payload' not in c for c in scene['workers'])
    first = adapter.work_items(rid, limit=2)
    assert [(x['title'], x['stage']) for x in first['data']['items']] == [('等待前序', 'waiting'), ('等待评价', 'executing')]
    assert first['data']['items'][0]['dependencies'][0]['attempt_no'] == 4
    assert first['data']['items'][1]['blocked_by'] == []
    second = adapter.work_items(rid, cursor=first['next_cursor'], limit=2)
    assert [(x['title'], x['stage']) for x in second['data']['items']] == [('等待反馈', 'pending_feedback'), ('失败重试', 'failed')]
    attention = adapter.work_items(rid, scope='attention', limit=1)
    assert attention['data']['items'][0]['title'] == '等待前序'
    assert attention['next_cursor']
    attention2 = adapter.work_items(rid, scope='attention', cursor=attention['next_cursor'], limit=1)
    assert attention2['data']['items'][0]['title'] == '失败重试'
    assert snapshot(project) == before


def test_workbench_discards_historical_dependency_wait_after_saved_result(project):
    from opc.observer.adapter import ObserverAdapter
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        for n, plan in [(3, {'title': '前序', 'work_id': 'upstream'}), (4, {'title': '后序', 'work_id': 'downstream', 'dependencies': [{'work_id': 'upstream', 'artifact': 'candidate'}]})]:
            db.execute('INSERT INTO attempts(run_id,attempt_no,state,champion_before,plan,started_at) VALUES(?,?,?,?,?,?)', ('new-run', n, 'planned', 'a'*40, json.dumps(plan), AT))
        event(db, 'new-run', 'node_waiting', 4, reason='inputs', blocked_by=['upstream:candidate'])
        event(db, 'new-run', 'candidate_saved', 3, commit='b'*40)
    adapter = ObserverAdapter(project)
    rid = next(r['id'] for r in adapter.overview()['data']['unlinked_runs'] if r['source_run_id'] == 'new-run')
    item = adapter.work_items(rid)['data']['items'][-1]
    assert item['blocked_by'] == []
    assert item['reason'] == '等待派发'
    assert item['needs_attention'] is False


def test_activity_reads_inflight_call_and_pairs_parallel_tools_without_fabricated_time(project):
    from opc.observer.adapter import ObserverAdapter
    log = project / '.opc/local/artifacts/test/dma/new-run/calls/live'
    log.mkdir(parents=True)
    path = log / 'designer-events.jsonl'
    rows = [dict(type='thread.started', thread_id='native-session'),
            dict(type='item.started', item=dict(id='read', type='command_execution', command='cat task.py')),
            dict(type='item.started', item=dict(id='test', type='command_execution', command='pytest task_test.py')),
            dict(type='item.started', item=dict(id='internal', type='command_execution', command='cat ' + str(project / '.opc/research/tasks/r01/evidence/boundary.md'))),
            dict(type='item.started', item=dict(id='internal-relative', type='command_execution', command='cat .opc/research/tasks/r01/../r01/evidence/boundary.md')),
            dict(type='future.secret', secret='NEVER_RENDER_THIS')]
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        event(db, 'new-run', 'call_dispatched', 3, call_id='archa-call-live', role='designer',
              receipt_path=str(log / 'receipt.json'), activity_log=dict(provider='codex', path=str(path)))
    adapter = ObserverAdapter(project)
    rid = next(r['id'] for r in adapter.overview()['data']['unlinked_runs'] if r['source_run_id'] == 'new-run')
    call = adapter.workbench(rid)['data']['workers'][-1]
    page = adapter.activity(call['id'])
    assert page['data']['availability'] == 'available'
    assert [(a['object'], a['state']) for a in page['data']['actions']] == [('cat task.py', 'pending'), ('pytest task_test.py', 'pending')]
    assert all(a['started_at'] is None for a in page['data']['actions'])
    assert 'NEVER_RENDER_THIS' not in json.dumps(page)
    with path.open('a') as out:
        out.write(json.dumps(dict(type='item.completed', item=dict(id='test', type='command_execution', command='pytest task_test.py', exit_code=1, aggregated_output='assertion failed'))) + '\n')
        out.write('{"type":"item.completed"')
    update = adapter.activity(call['id'], page['next_cursor'])
    assert [(a['object'], a['state']) for a in update['data']['actions']] == [('cat task.py', 'pending'), ('pytest task_test.py', 'failed')]
    assert update['data']['actions'][-1]['summary'] == '动作失败'
    assert call['state'] == 'pending'  # tool failure is not the Call outcome
    with path.open('a') as out:
        out.write(',"item":{"id":"read","type":"command_execution","command":"cat task.py","exit_code":0}}\n')
    final = adapter.activity(call['id'], update['next_cursor'])
    assert all(a['state'] == 'completed' or a['state'] == 'failed' for a in final['data']['actions'])


def test_activity_is_bounded_resets_replaced_logs_and_rejects_wrong_ownership(project):
    from opc.observer.adapter import ObserverAdapter
    log = project / '.opc/local/artifacts/test/dma/new-run/calls/bounded'
    log.mkdir(parents=True)
    path = log / 'designer-events.jsonl'
    with path.open('w') as out:
        out.write(json.dumps(dict(type='thread.started', thread_id='native')) + '\n')
        for n in range(3000):
            out.write(json.dumps(dict(type='item.completed', item=dict(id=str(n), type='command_execution', command='test ' + str(n), exit_code=0, aggregated_output='ok' * 200))) + '\n')
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        event(db, 'new-run', 'call_dispatched', 3, call_id='bounded', role='designer', receipt_path=str(log / 'receipt.json'), activity_log=dict(provider='codex', path=str(path)))
    adapter = ObserverAdapter(project)
    rid = next(r['id'] for r in adapter.overview()['data']['unlinked_runs'] if r['source_run_id'] == 'new-run')
    ident = adapter.workbench(rid)['data']['workers'][-1]['id']
    first = adapter.activity(ident)
    assert first['data']['truncated'] is True
    assert first['data']['actions'][-1]['object'] == 'test 2999'
    assert len(first['data']['actions']) < 200
    old = path.with_suffix('.old')
    path.rename(old)
    path.write_text(json.dumps(dict(type='item.started', item=dict(id='new', type='command_execution', command='new action'))) + '\n')
    reset = adapter.activity(ident, first['next_cursor'])
    assert reset['data']['reset'] is True
    assert [a['object'] for a in reset['data']['actions']] == ['new action']
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        event(db, 'new-run', 'call_dispatched', 4, call_id='replacement-owner', role='designer', receipt_path=str(log / 'receipt.json'), activity_log=dict(provider='codex', path=str(path)))
    refused = adapter.activity(ident, reset['next_cursor'])['data']
    assert refused['availability'] == 'unreadable' and refused['actions'] == []


def test_activity_legacy_session_and_dsh_tools_are_scoped(project):
    from opc.observer.adapter import ObserverAdapter
    adapter = ObserverAdapter(project)
    current = observed_run(adapter, 'old-run')
    ident = current['calls'][0]['id']
    page = adapter.activity(ident)['data']
    assert page['actions'][0]['object'] == 'pytest'
    assert page['actions'][0]['state'] == 'completed'
    path = project / '.opc/local/artifacts/test/dma/old-run/attempts/a000002/expert-events.jsonl'
    with path.open('a') as out:
        for row in [dict(type='tool_call', callId='c1', tool='read', input={'file_path': 'params.json'}),
                    dict(type='tool_result', callId='c1', status='completed', result='{}')]:
            out.write(json.dumps(row) + '\n')
    dsh = adapter.activity(current['calls'][1]['id'])['data']
    assert dsh['actions'][0]['object'] == 'params.json'
    assert dsh['actions'][0]['summary'] == '动作完成'
    assert dsh['actions'][0]['state'] == 'completed'
    path.write_text('{"type":"session","sessionId":"different-owner"}\n')
    assert adapter.activity(current['calls'][1]['id'])['data']['availability'] == 'unreadable'


def test_inspection_binds_saved_call_input_and_material_purpose(project):
    from opc.observer.adapter import ObserverAdapter, ObserverError
    log = project / '.opc/local/artifacts/test/dma/old-run/attempts/a000002'
    outputs = log / 'outputs'
    outputs.mkdir(exist_ok=True)
    (outputs / 'answer.md').write_text('# 用户产出\n\n[内部材料](../decision.json)\n', encoding='utf-8')
    (outputs / 'internal.json').write_text('{"audit":"not user content"}')
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        for call_id, purpose, ok in [('first-try', '修复第一次输入', False), ('retry', '修复第二次输入', True)]:
            inputs = dict(plan=dict(title='修复解析', changes=purpose, deliverables=['answer.md']),
                          context=dict(task=dict(goal='用户任务'), handoff=dict(purpose=purpose, evidence='internal-secret'), claims=['internal-claim']))
            result = dict(ok=ok, output=dict(summary=purpose + '结果', evidence_files=['internal.json']), error='' if ok else 'parser failed')
            db.execute('INSERT INTO calls(call_id,run_id,attempt_no,role,state,input,result,receipt_path,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (call_id, 'old-run', 2, 'designer', 'completed', json.dumps(inputs), json.dumps(result), str(log / call_id / 'receipt.json'), AT))
            event(db, 'old-run', 'call_dispatched', 2, call_id=call_id, role='designer', inputs=inputs)
            event(db, 'old-run', 'worker_call', 2, call_id=call_id, role='designer', ok=ok, error=result['error'])
            if ok:
                event(db, 'old-run', 'deliverables_saved', 2, paths=['outputs/answer.md', 'outputs/internal.json'])
    adapter = ObserverAdapter(project)
    rid = adapter._id('run', 'old-run')
    page = adapter.inspection(rid, 2)['data']
    assert page['input']['purpose'] == '修复第二次输入'
    assert [m['name'] for m in page['materials']] == ['answer.md']
    first = next(c for c in page['calls'] if c['error'] == 'parser failed')
    earlier = adapter.inspection(rid, 2, first['id'])['data']
    assert earlier['input']['purpose'] == '修复第一次输入'
    assert earlier['output']['summary'] == '修复第一次输入结果'
    assert earlier['materials'] == []
    assert 'internal-secret' not in json.dumps(page) and 'internal-claim' not in json.dumps(page)
    with pytest.raises(ObserverError, match='调用不属于'):
        adapter.inspection(rid, 1, first['id'])
    material = page['materials'][0]
    content = adapter.content(material['id'], 0, 20)['data']
    assert content['content'].startswith('# 用户产出') and not content['eof']
    assert adapter.artifact(material['id'])['data'].get('link_targets', {}) == {}


def test_inspection_code_uses_registered_version_and_old_outputs_do_not_read_replacements(project):
    import subprocess
    from opc.observer.adapter import ObserverAdapter, ObserverError
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', *args], cwd=project, text=True).strip()
    git('init', '-q')
    (project / 'parser.py').write_text('old input\n')
    git('add', 'parser.py'); git('commit', '-qm', 'base')
    parent = git('rev-parse', 'HEAD')
    (project / 'parser.py').write_text('saved result\n')
    git('commit', '-qam', 'candidate')
    candidate = git('rev-parse', 'HEAD')
    (project / 'parser.py').write_text('current unrelated content\n')
    adir = project / '.opc/local/artifacts/test/dma/old-run/attempts/a000002'
    (adir / 'outputs').mkdir(exist_ok=True)
    (adir / 'outputs/answer.txt').write_text('newer replacement')
    put(adir.parent.parent / 'frozen/component.json', dict(editable=['*.py'], frozen=[], evaluator_files=[]))
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        event(db, 'old-run', 'call_dispatched', 2, call_id='old-material-call', role='designer', inputs=dict(plan=dict(changes='saved input', deliverables=['answer.txt'])))
        event(db, 'old-run', 'worker_call', 2, call_id='old-material-call', role='designer', ok=True)
        event(db, 'old-run', 'candidate_saved', 2, parent=parent, commit=candidate)
        event(db, 'old-run', 'deliverables_saved', 2, paths=['outputs/answer.txt'])
        event(db, 'old-run', 'call_dispatched', 2, call_id='later-material-call', role='designer', inputs=dict(plan=dict(changes='later input', deliverables=['answer.txt'])))
        event(db, 'old-run', 'deliverables_saved', 2, paths=['outputs/answer.txt'])
    adapter = ObserverAdapter(project)
    rid = adapter._id('run', 'old-run')
    page = adapter.inspection(rid, 2)['data']
    old = next(c for c in page['calls'] if c['state'] == 'finished' and c['role'] == 'designer')
    page = adapter.inspection(rid, 2, old['id'])['data']
    materials = {m['name']:m for m in page['materials']}
    assert materials['answer.txt']['availability'] == 'missing'
    with pytest.raises(ObserverError, match='不可用'):
        adapter.content(materials['answer.txt']['id'])
    assert adapter.content(materials['parser.py']['id'])['data']['content'] == 'saved result\n'
    (adir / 'outputs/answer.txt').unlink()
    missing = adapter.inspection(rid, 2)['data']['materials'][0]
    assert missing['availability'] == 'missing'


def test_workbench_delivery_result_is_structured_and_does_not_expose_report(project):
    from opc.observer.adapter import ObserverAdapter
    adir = project / '.opc/local/artifacts/test/dma/old-run'
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        task_digest = db.execute("SELECT task_digest FROM runs WHERE run_id='old-run'").fetchone()[0]
        report = dict(candidate=dict(commit='b'*40), acceptance_task_digest=task_digest, complete=False,
                      next_step=dict(action='repair_candidate', gaps=[dict(text='internal-report-marker')]))
        path = adir / 'promotion/result.json'
        put(path, report)
        event(db, 'old-run', 'promotion_report', selected_commit='b'*40, complete=False, report_path=str(path))
    adapter = ObserverAdapter(project)
    scene = adapter.workbench(adapter._id('run', 'old-run'))['data']
    assert scene['result']['complete'] is False and scene['result']['reason'] == '交付内容仍需修正'
    assert 'internal-report-marker' not in json.dumps(scene)
    assert scene['stop_reason'] == '本次运行已结束'
    # S4 may register delivery against a later acceptance revision on this same Run.
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        revised_digest = db.execute("SELECT task_digest FROM runs WHERE run_id='new-run'").fetchone()[0]
    report.update(acceptance_revision='r0002', acceptance_task_digest=revised_digest, acceptance_source_digest=revised_digest, complete=True)
    put(path, report)
    assert adapter.workbench(adapter._id('run', 'old-run'))['data']['result']['complete'] is True


def test_inspection_allows_declared_dependency_output_but_not_internal_dependency(project):
    from opc.observer.adapter import ObserverAdapter
    run_dir = project / '.opc/local/artifacts/test/dma/old-run'
    (run_dir / 'attempts/a000001/outputs').mkdir(exist_ok=True)
    (run_dir / 'attempts/a000001/outputs/input.txt').write_text('registered task input')
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        db.execute("UPDATE attempts SET plan=? WHERE run_id='old-run' AND attempt_no=1", (json.dumps(dict(work_id='upstream',deliverables=['input.txt'])),))
        event(db, 'old-run', 'deliverables_saved', 1, paths=['outputs/input.txt'])
        event(db, 'old-run', 'call_dispatched', 2, call_id='dependency-call', role='designer', inputs=dict(plan=dict(changes='use input'), context=dict(handoff=dict(inputs=[dict(work_id='upstream', artifact='outputs/input.txt'),dict(work_id='upstream',artifact='decision.json')]))))
    adapter=ObserverAdapter(project)
    page=adapter.inspection(adapter._id('run','old-run'),2)['data']
    assert [(m['name'],m['purpose']) for m in page['materials']] == [('input.txt','传入任务材料')]
    assert adapter.content(page['materials'][0]['id'])['data']['content'] == 'registered task input'


def test_task_material_rejects_changed_and_binary_content(project):
    from opc.observer.adapter import ObserverAdapter, ObserverError
    path = project / '.opc/local/artifacts/test/dma/old-run/attempts/a000002/outputs/answer.txt'
    path.parent.mkdir()
    path.write_text('saved task content')
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        event(db, 'old-run', 'call_dispatched', 2, call_id='content-call', role='designer', inputs=dict(plan=dict(deliverables=['answer.txt'])))
        event(db, 'old-run', 'deliverables_saved', 2, paths=['outputs/answer.txt'])
    adapter = ObserverAdapter(project)
    rid = adapter._id('run', 'old-run')
    item = adapter.inspection(rid, 2)['data']['materials'][0]
    path.write_text('replacement task content')
    with pytest.raises(ObserverError, match='已变化'):
        adapter.content(item['id'])
    path.write_bytes(b'\x00\xff\xfe')
    item = adapter.inspection(rid, 2)['data']['materials'][0]
    with pytest.raises(ObserverError, match='不支持文本预览'):
        adapter.content(item['id'])


def test_workbench_run_display_is_stable_and_refreshes_for_newly_recorded_runs(project):
    from opc.observer.adapter import ObserverAdapter
    first = ObserverAdapter(project)
    original = next(r for r in first.overview()['data']['unlinked_runs'] if r['source_run_id'] == 'new-run')
    assert original['source_run_id'] not in original['display_label']
    assert first.workbench(original['id'])['data']['display_label'] == original['display_label']
    with sqlite3.connect(project / '.opc/local/ledger.sqlite3') as db:
        db.execute("INSERT INTO runs SELECT 'run-7eaf1f6341ac',task_id,revision,task_digest,component,base_commit,evaluator_digest,toolchain_digest,champion_ref,direction,state,stop_reason,'2026-11-02T00:00:00Z',closed_at FROM runs WHERE run_id='new-run'")
    second = ObserverAdapter(project)
    added = next(r for r in second.overview()['data']['unlinked_runs'] if r['source_run_id'] == 'run-7eaf1f6341ac')
    assert added['display_label'] != original['display_label']
    assert first.workbench(added['id'])['data']['display_label'] == added['display_label']
    assert first.workbench(original['id'])['data']['display_label'] == original['display_label']
