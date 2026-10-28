"""Deterministic small source-format fixture writer; used only by explicit --demo.

No expected observer DTOs are embedded here. The ordinary adapter reads the same
SQLite, map, brief, frozen contracts and worker JSONL as for a real project.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


def create_demo(root: Path):
    from ..core.ledger import SCHEMA  # Schema constant only; never instantiate Ledger.
    from ..core.model import canonical_json
    root = Path(root)
    def write(path, value):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value, encoding='utf-8')
    write('.opc/project.json', {'project_id': 'dma-demo', 'display_name': 'DMA 背压研究 · 演示', 'components': ['dma']})
    write('.opc/research/research-map.md', '# DMA 输入链路\n\n在满载时拒绝写入，释放后恢复；保留已有输入消费行为。\n\n## 研究任务 to-do\n\n- [x] R01 | [DMA 背压行为](tasks/r01-dma/task.md) | status=ready-for-onboard | depends=none\n- [ ] R02 | [调度边界](tasks/r02-scheduling/task.md) | status=todo | depends=R01\n\n勾选仅表示简报已确认，不表示研究完成。\n')
    write('.opc/research/tasks/r01-dma/task.md', '# R01 · DMA 背压行为\n\n验证满载拒绝、释放恢复和既有行为保持。\n')
    write('.opc/research/tasks/r02-scheduling/task.md', '# R02 · 调度边界\n\n依赖 R01 的实际输入消费位置。\n')
    brief_path = '.opc/research/tasks/r01-dma/task-brief.md'
    brief = '# DMA 背压任务简报\n\n## Source\nMap: .opc/research/research-map.md\nStatus: ready-for-onboard\n\n## Question and use\n识别满载与恢复的边界。\n\n## Goal\nGoal: 满载拒绝后可以释放并恢复\nDone when: R1–R3 都有对应版本证据\nDirection: 先明确容量边界\n\n## Evidence\n已有输入链路分析。\n\n## Scope and deliverables\n- D1: 容量检查补丁\n- D2: 可复查测试证据\n- R1: 满载拒绝 | verification=automated\n- R2: 释放恢复 | verification=automated\n- R3: 既有行为保持 | verification=review\nObjective: none: 本轮为行为修复\n\n## Open decisions\n恢复时机留待验证。\n'
    write(brief_path, brief)
    sha = hashlib.sha256(brief.encode()).hexdigest()
    requirements = [dict(id='R1', text='满载拒绝', verification='automated', gates=['unit']), dict(id='R2', text='释放恢复', verification='automated', gates=['recovery']), dict(id='R3', text='既有行为保持', verification='review')]
    component = dict(component_id='dma', description='DMA 背压行为演示', editable=['dma.py'], evaluator_files=['tests/**'],
                     gates=[dict(id='unit', argv=['{python}', '-m', 'pytest', 'tests/test_dma.py']), dict(id='recovery', argv=['{python}', '-m', 'pytest', 'tests/test_recovery.py'])])
    write('.opc/components/dma.json', component)
    contracts = {}
    for rev, goal in [('r0001', '修复 DMA 满载拒绝与释放恢复'), ('r0002', '增加调度公平性（新版目标）')]:
        obj = dict(task_id='dma-backpressure', revision=rev, component='dma', goal=goal, direction='容量边界', requirements=requirements,
                   acceptance={}, budget=dict(max_attempts=4, max_tokens=20000, max_wall_seconds=1200),
                   workers=dict(expert=dict(kind='dsh'), designer=dict(kind='codex')))
        contracts[rev] = obj
        write('.opc/tasks/dma-backpressure/revisions/' + rev + '/task.json', obj)
    write('.opc/context/DECISIONS.md', '# 明确关联\n\n' + '\n'.join('task=dma-backpressure revision=' + rev + ' brief=' + brief_path + ' sha256=' + sha for rev in contracts) + '\n')
    local = root / '.opc/local'
    local.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(local / 'ledger.sqlite3')
    db.executescript(SCHEMA)
    at = '2026-10-27T14:00:00+00:00'
    def ev(run, kind, attempt=None, **body):
        db.execute('INSERT INTO events(run_id,at,kind,attempt_no,body) VALUES(?,?,?,?,?)', (run, at, kind, attempt, json.dumps(body, ensure_ascii=False)))
    for rid, rev, status in [('run-dma-r1', 'r0001', 'active'), ('run-dma-r2', 'r0002', 'paused'), ('prepare-dma', 'preparation', 'paused')]:
        dg = hashlib.sha256(canonical_json(contracts[rev]).encode()).hexdigest() if rev in contracts else 'preparation'
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (rid, 'dma-backpressure', rev, dg, 'dma', 'a'*40, 'evaluator-demo', 'toolchain-demo', '', '', status, None, at, None))
        ev(rid, 'run_created', task='dma-backpressure', revision=rev)
        if rev != 'preparation':
            directory = '.opc/local/artifacts/dma-demo/dma-backpressure/' + rid
            write(directory + '/frozen/task.json', contracts[rev])
            write(directory + '/frozen/component.json', component)
            write(directory + '/frozen/baseline.json', dict(commit='a'*40, evaluator_digest='evaluator-demo', evaluator_files=[], toolchain_digest='toolchain-demo'))
    ev('prepare-dma', 'preparation', state='ready', reason='演示准备材料已检查')
    for n, title in [(1, '增加写入容量检查'), (2, '验证释放后恢复')]:
        plan = dict(title=title, hypothesis='容量边界应显式返回拒绝信号', changes='将满载检查放在入队之前', expected='拒绝后不改变队列', evaluate=False)
        db.execute('INSERT INTO attempts(run_id,attempt_no,state,champion_before,plan,outcome,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?)', ('run-dma-r1', n, 'decided' if n == 1 else 'started', 'a'*40, json.dumps(plan, ensure_ascii=False), 'work' if n == 1 else None, at, at if n == 1 else None))
        relative = '.opc/local/artifacts/dma-demo/dma-backpressure/run-dma-r1/attempts/a%06d' % n
        role = 'designer' if n == 1 else 'expert'
        provider_id = 'demo-codex-1' if n == 1 else 'demo-dsh-2'
        events = ([dict(type='thread.started', thread_id=provider_id), dict(type='item.started', item=dict(type='command_execution', id='tool-1', command='python -m pytest tests/test_dma.py')), dict(type='item.completed', item=dict(type='command_execution', id='tool-1', command='python -m pytest tests/test_dma.py', aggregated_output='2 passed; recovery case 尚未覆盖')), dict(type='item.completed', item=dict(type='agent_message', id='message-1', text='已加入容量检查，保存候选。释放恢复尚未验证。'))] if n == 1 else [dict(type='session', sessionId=provider_id), dict(type='tool_call', toolCallId='tool-2', toolName='read_file', arguments=dict(path='tests/test_dma.py')), dict(type='final', text='正在检查恢复边界；尚未形成结论。'), dict(type='future.event', note='未知事件仍保留原文')])
        write(relative + '/' + role + '-events.jsonl', ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events))
        ev('run-dma-r1', 'worker_call', n, role=role, call_id=provider_id, ok=True, tokens=620 if n == 1 else 310, seconds=12, error='', log_dir=str(root / relative))
        db.execute('INSERT INTO charges(run_id,attempt_no,role,wall_seconds,tokens,usd,usd_known,at) VALUES(?,?,?,?,?,?,?,?)', ('run-dma-r1', n, role, 12, 620 if n == 1 else 310, None, 0, at))
    ev('run-dma-r1', 'candidate_saved', 1, commit='b'*40, parent='a'*40)
    ev('run-dma-r1', 'selected_version', 1, commit='b'*40)
    ev('run-dma-r1', 'execution', 1, completed=True, summary='容量检查已实现并保存候选。')
    ev('run-dma-r1', 'experiment', 1, summary='2 项局部测试通过，释放恢复尚未覆盖。')
    ev('run-dma-r1', 'conclusion', 1, text='第一轮完成满载拒绝；R2 未验证、R3 待独立审阅。', reviewed_by_attempt=2)
    write('.opc/local/artifacts/dma-demo/dma-backpressure/run-dma-r1/attempts/a000001/candidate.patch', 'diff --git a/dma.py b/dma.py\n+if queue.full():\n+    return REJECTED\n')
    report = dict(promotion_id='review-1', run_id='run-dma-r1', task='dma-backpressure', baseline='a'*40, selected_version='b'*40, champion=None,
                  evidence_key=dict(commit='b'*40, task=hashlib.sha256(canonical_json(contracts['r0001']).encode()).hexdigest(), evaluator='evaluator-demo', toolchain='toolchain-demo', environment='demo'),
                  requirements=[dict(id='R1', text='满载拒绝', verification='automated', status='met_by_gates'), dict(id='R2', text='释放恢复', verification='automated', status='unverified gates: recovery'), dict(id='R3', text='既有行为保持', verification='review', status='needs_review')],
                  findings=[dict(check='requirements', severity='block', text='R2 未验证，R3 需要独立审阅')], complete=False, promotable=False, baseline_metrics={}, selected_metrics={})
    write('.opc/local/artifacts/dma-demo/dma-backpressure/run-dma-r1/promotion/review-1/report.json', report)
    db.commit()
    db.close()
    return root
