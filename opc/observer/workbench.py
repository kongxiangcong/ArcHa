"""Small user-facing projections; unopened logs and task materials stay unread."""
from __future__ import annotations

import base64
import json

from .adapter import ObserverError, mapping, parsed


def records(adapter, ident):
    row = adapter._find_run(ident)
    data = adapter._db(row['run_id'], tables_to_read=('runs', 'events', 'attempts'))
    if data['runs']:
        row = data['runs'][0]
    if row.get('_snapshot'):
        data['attempts'] = adapter.snapshots[row['run_id']].get('attempts', [])
    events = sorted(data['events'], key=lambda e: e['seq'])
    for e in events:
        e['body'] = mapping(parsed(e['body'], {}))
    adapter.source_at = max((e['at'] for e in events if e.get('at')), default=None)
    return row, data['attempts'], events


def workers(adapter, row, events):
    dispatches = {e['body'].get('call_id'): e for e in events if e['kind'] == 'call_dispatched'}
    completed = {e['body'].get('call_id') for e in events if e['kind'] in ('worker_call', 'evaluation_call')}
    calls = []
    for e in events:
        b = e['body']
        if e['kind'] not in ('worker_call', 'evaluation_call') and not (e['kind'] == 'call_dispatched' and b.get('call_id') not in completed):
            continue
        dispatch = dispatches.get(b.get('call_id'))
        state = ('pending' if e['kind'] == 'call_dispatched' else
                 b['state'] if b.get('state') in ('unknown', 'cancelled') else
                 'finished' if b.get('ok') is True else 'failed' if b.get('ok') is False else 'unknown')
        calls.append(dict(id=adapter._id('call', row['run_id'] + ':' + str((dispatch or e)['seq'])),
                          attempt_no=e.get('attempt_no'), role=b.get('role') or 'evaluator', state=state,
                          started_at=(dispatch or {}).get('at'), ended_at=None if state == 'pending' else e.get('at'),
                          error=b.get('error') if isinstance(b.get('error'), str) else None,
                          activity_available=bool(mapping((dispatch or {}).get('body', {}).get('activity_log'))) or bool(b.get('log_dir')), activity_note='尚无可确认的具体活动'))
    return calls


def text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(v for v in value if isinstance(v, str)) or None
    return None


def items(adapter, row, attempts, events, calls):
    plans = {}
    for a in attempts:
        p = mapping(parsed(a.get('plan'), {}))
        review = next((e for e in reversed(events) if e.get('attempt_no') == a['attempt_no'] and e['kind'] == 'work_reconsidered'), None)
        plans[a['attempt_no']] = mapping(review['body'].get('plan')) if review else p
    by_work = {p.get('work_id') or 'a%d' % n: n for n, p in plans.items()}
    run_dir = adapter._run_dir(row)
    def unresolved(value):
        work_id, _, artifact = value.partition(':')
        no = by_work.get(work_id)
        if no is None or not artifact:
            return True
        upstream = [e for e in events if e.get('attempt_no') == no]
        if artifact == 'candidate':
            return not any(e['kind'] == 'candidate_saved' for e in upstream)
        path = run_dir / 'attempts' / ('a%06d' % no) / ('decision.json' if artifact == 'result' else artifact) if run_dir else None
        available = bool(path and adapter._allowed(path) and path.is_file())
        if artifact.startswith('outputs/'):
            available = available and any(e['kind'] == 'deliverables_saved' and artifact in e['body'].get('paths', []) for e in upstream)
        return not available
    result = []
    for a in sorted(attempts, key=lambda a: a['attempt_no']):
        n = a['attempt_no']
        p = plans[n]
        projected = {e['kind']: e['body'] for e in events if e.get('attempt_no') == n}
        related = [c for c in calls if c['attempt_no'] == n]
        pending = [c for c in related if c['state'] == 'pending']
        outcome = a.get('outcome')
        wait = projected.get('node_waiting', {})
        blocked = [b for b in wait.get('blocked_by', []) if isinstance(b, str) and unresolved(b)] if not outcome and a.get('state') in ('planned', 'started') and not pending else []
        reason = None
        if pending:
            stage = 'evaluating' if any(c['role'] == 'evaluator' for c in pending) else 'executing'
        elif any(c['state'] == 'unknown' for c in related[-1:]):
            stage, reason = 'unknown', '调用的执行结果尚未确认'
        elif outcome in ('worker_failed', 'broken', 'sandbox_violation', 'infra'):
            stage, reason = 'failed', text(a.get('reason'))
        elif outcome == 'abandoned':
            stage, reason = 'unknown', '执行结束情况尚未确认'
        elif outcome:
            stage = 'completed' if 'conclusion' in projected else 'pending_feedback'
        elif related and related[-1]['state'] == 'failed':
            stage, reason = 'failed', related[-1]['error']
        elif a.get('state') == 'evaluated':
            stage = 'pending_feedback'
        elif a.get('state') == 'designed' or projected.get('execution', {}).get('completed') is True:
            stage = 'pending_evaluation'
        elif a.get('state') == 'decided':
            stage = 'completed'
        else:
            stage = 'waiting'
        if stage == 'waiting':
            reason = ('等待前序工作' if blocked else {'concurrency': '等待可用执行资源', 'measurement': '等待评价资源', 'ready': '等待派发'}.get(wait.get('reason'), '等待派发'))
        dependencies = []
        for d in p.get('dependencies') or []:
            no = by_work.get(d.get('work_id'))
            dependencies.append(dict(work_id=d.get('work_id'), artifact=d.get('artifact'), attempt_no=no,
                                     title=plans[no].get('title') if no in plans else '前序工作记录不可用'))
        result.append(dict(id=adapter._id('attempt', row['run_id'] + ':' + str(n)), attempt_no=n,
                           work_id=p.get('work_id') or 'a%d' % n,
                           title=text(p.get('title')) or '工作 %d' % n,
                           goal=text(p.get('changes')) or text(p.get('hypothesis')),
                           stage=stage, reason=reason, dependencies=dependencies, blocked_by=blocked,
                           calls=[c['id'] for c in related],
                           summary=text(projected.get('execution', {}).get('summary')),
                           outcome=outcome, needs_attention=stage in ('failed', 'unknown') or bool(blocked),
                           availability='partial' if row.get('_snapshot') or not p else 'available'))
    return result


def scene(adapter, ident):
    row, attempts, events = records(adapter, ident)
    calls = workers(adapter, row, events)
    return row, events, calls, items(adapter, row, attempts, events, calls)


def user_result(adapter, row, events, closure):
    candidate = next((e['body'] for e in reversed(events) if e['kind'] == 'selected_version'), None)
    report_event = next((e['body'] for e in reversed(events) if e['kind'] == 'promotion_report' and candidate and e['body'].get('selected_commit') == candidate.get('commit')), None)
    result = dict(complete=False if closure.get('finish') == 'close_incomplete' else None,
                  reason=text(closure.get('reason')), gaps=text(closure.get('gaps')))
    if report_event:
        path = adapter._path(report_event['report_path'])
        report = mapping(adapter._read(path, json_file=True, default={}))
        revision = report.get('acceptance_revision', row.get('revision'))
        standard = next((r['task_digest'] for r in adapter.revisions.values() if r['execution_task_id'] == row['task_id'] and r['revision'] == revision and adapter.artifact_registry[r['contract_artifact_id']]['path'].parent.name != 'frozen'), row.get('task_digest') if revision == row.get('revision') else None)
        recorded_standard = report.get('acceptance_source_digest', report.get('acceptance_task_digest'))
        if report.get('candidate', candidate) == candidate and recorded_standard == standard:
            complete = report.get('complete')
            if isinstance(complete, bool):
                action = mapping(report.get('next_step')).get('action')
                result.update(complete=complete, reason='任务交付已完成' if complete else {
                    'retry_review': '任务结果仍需确认', 'supplement_evidence': '任务结果尚需补充',
                    'repair_candidate': '交付内容仍需修正', 'revise_standard': '任务完成条件需要确认'
                }.get(action, '任务交付尚未完成'))
    return result


def stop_description(row):
    if row.get('state') == 'paused':
        return '已暂停，工作阶段与已保存结果保留'
    value = row.get('stop_reason')
    if not value:
        return None
    key = value.split(':', 1)[0]
    return {'budget_exhausted': '已达到本次运行额度', 'stagnation': '本次运行已停止探索',
            'user_stop': '用户已停止运行', 'stopped': '用户已停止运行',
            'target_met': '已达到当前目标', 'expert_exhausted': '本次探索已结束',
            'user_withdrawn': '任务已撤回', 'acceptance_requested': '工作已结束，交付结果单独记录'
            }.get(key, '运行需要处理，请查看相关工作' if row.get('state') == 'blocked' else '本次运行已结束')


def workbench(adapter, ident):
    row, events, calls, work = scene(adapter, ident)
    closure = next((e['body'] for e in reversed(events) if e['kind'] == 'expert_stop'), {})
    run_dir = adapter._run_dir(row)
    contract = adapter._read(run_dir / 'frozen/task.json', json_file=True, default={}) if run_dir else {}
    goal = text(mapping(contract).get('goal'))
    if row.get('_preparation'):
        owner = next((t for t in adapter.tasks.values() if t['id'] in row.get('_owners', set())), None)
        goal = owner['title'] if owner else '研究准备'

    from .control import capability
    unfinished = [c for c in calls if c['state'] in ('pending', 'unknown')]
    recent = [c for c in calls if c['state'] not in ('pending', 'unknown')][-200:]
    visible_calls = sorted(unfinished + recent, key=lambda c: calls.index(c))
    timeline = []
    names = {'preparation': '研究准备状态已更新', 'preparation_candidate': '准备产物已保存', 'expert_decision': '研究方向已更新', 'work_reconsidered': '工作安排已修订',
             'candidate_saved': '候选成果已保存', 'deliverables_saved': '任务产出已保存',
             'conclusion': '反馈分析已记录', 'expert_stop': '研究推进已收束',
             'promotion_report': '交付检查已返回'}
    for event in events:
        body = event['body']
        title = names.get(event['kind'])
        if event['kind'] == 'call_dispatched':
            title = {'onboard': '研究准备已派发', 'expert': '研究协调已派发', 'designer': '实施工作已派发',
                     'evaluator': '评价已派发', 'reviewer': '独立审核已派发'}.get(body.get('role'), '工作调用已派发')
        elif event['kind'] in ('worker_call', 'evaluation_call'):
            title = '调用结果未知' if (body.get('state') == 'unknown' or body.get('ok') is None) else '调用已返回' if body.get('ok') else '调用未成功'
        if title:
            timeline.append(dict(id=str(event['seq']), title=title, at=event.get('at'),
                                 attempt_no=event.get('attempt_no')))
    handoffs = {}
    by_work = {item['work_id']: item for item in work}
    by_attempt = {item['attempt_no']: item for item in work}
    for event in events:
        item = by_attempt.get(event.get('attempt_no'))
        if event['kind'] != 'call_dispatched' or item is None:
            continue
        inputs = mapping(mapping(event['body'].get('inputs')).get('context')).get('handoff', {})
        for dependency in mapping(inputs).get('inputs', []):
            if not isinstance(dependency, dict):
                continue
            source = by_work.get(dependency.get('work_id'))
            if source and dependency.get('artifact'):
                key = str(event['seq']) + ':' + str(source['attempt_no']) + ':' + str(dependency['artifact'])
                handoffs[key] = dict(id=key, source=source['title'], target=item['title'],
                                     attempt_no=item['attempt_no'], at=event.get('at'))
    data = dict(kind='preparation' if row.get('_preparation') else 'execution', preparation=row.get('_preparation_state'), timeline=timeline[-100:], handoffs=list(handoffs.values())[-100:], id=ident, source_run_id=row['run_id'], display_label=adapter._run_ref(row)['display_label'], execution=row.get('state') or 'unknown',
                goal=goal, stop_reason=stop_description(row), result=user_result(adapter, row, events, closure),
                control=capability(adapter, row),
                control_request=None,
                workers=visible_calls, workers_truncated=len(visible_calls) < len(calls), work_count=len(work),
                availability='partial' if row.get('_snapshot') or not goal else 'available',
                observation_note='显示最后已知记录；派发记录不代表执行仍然存活')
    from .canvas import project, run_brief
    data['run_brief'] = run_brief(adapter, row, contract)
    data['canvas'] = project(adapter, row, adapter._db(row['run_id'], tables_to_read=('attempts',))['attempts'] if not row.get('_snapshot') else adapter.snapshots[row['run_id']].get('attempts', []), events, calls, work)
    data['preparation_materials'] = []
    if row.get('_preparation'):
        data['result'] = dict(complete=None, reason=row['_preparation_state'].get('reason'), gaps=None)
        data['observation_note'] = '研究准备事件范围；尚非正式 Run。旧记录未登记调用归属时，执行情况未知；无需重跑准备。'
        if row.get('_ownership_ambiguous'):
            data['observation_note'] = '准备来源跨多个专题，归属有歧义；仅在工程未关联准备中显示，未混合到专题。'
        paths = []
        for task in adapter.tasks.values():
            if task['id'] in row.get('_owners', set()):
                paths.extend([task['_path'], task['_path'].parent / 'task-brief.md'])
        paths.extend(adapter.artifact_registry[rv['contract_artifact_id']]['path'] for rv in adapter.revisions.values()
                     if rv.get('research_task_id') in row.get('_owners', set()))
        for path in dict.fromkeys(paths):
            if adapter._allowed(path) and path.is_file():
                artifact = adapter._register(path, phase='task')
                data['preparation_materials'].append(dict(id=artifact['id'], name=adapter._display(path),
                    purpose='研究准备材料', availability=artifact['availability'], note=None))
    if adapter.control_enabled and not row.get('_preparation'):
        from .control import read_requests, view
        latest = read_requests(adapter, row['run_id'])
        data['control_request'] = adapter.control_service.observe(row, latest) if latest and hasattr(adapter, 'control_service') else view(adapter, row, latest) if latest else None
        if latest:
            data['execution'] = latest['_run']['state']
    return adapter.envelope(data)


def work_items(adapter, ident, cursor=None, limit=100, scope='all'):
    if scope not in ('all', 'attention') or not 1 <= limit <= 200:
        raise ObserverError(422, 'invalid_parameter', '工作筛选或分页范围无效')
    after = 0
    if cursor:
        try:
            target, selected_scope, after = json.loads(base64.urlsafe_b64decode(cursor))
            if target != ident or selected_scope != scope or not isinstance(after, int):
                raise ValueError()
        except (ValueError, TypeError, UnicodeDecodeError):
            raise ObserverError(422, 'invalid_cursor', '工作分页位置与当前运行或筛选不匹配') from None
    _, _, _, work = scene(adapter, ident)
    filtered = [w for w in work if scope == 'all' or w['needs_attention']]
    remaining = [w for w in filtered if w['attempt_no'] > after]
    page = remaining[:limit]
    next_cursor = (base64.urlsafe_b64encode(json.dumps([ident, scope, page[-1]['attempt_no']]).encode()).decode()
                   if len(remaining) > limit else None)
    return adapter.envelope(dict(items=page, total=len(filtered), scope=scope), next_cursor=next_cursor)
