"""Read-only content cards. Edges describe recorded inputs, never inferred agent chat."""
import hashlib

from .adapter import mapping, parsed
from .workbench import text


def project(adapter, row, attempts, events, calls, work):
    cards, edges, rounds = [], [], {}
    selections = {e.get('attempt_no'): e for e in events if e['kind'] == 'work_selected'}
    decisions = {e['body'].get('call_id'): e for e in events if e['kind'] == 'expert_decision' and isinstance(e['body'].get('call_id'), str) and e['body']['call_id']}
    by_number = {a['attempt_no']: a for a in attempts}
    by_work = {w['work_id']: w for w in work}
    run = row['run_id']

    def add(key, role, kind, title, summary, *, number=None, event=None, state='unknown', call=None, material=None):
        selection = selections.get(number)
        decision = decisions.get(selection['body'].get('decision_call')) if selection else None
        group = 'decision:' + str(decision['seq']) if decision else None
        if group and group not in rounds:
            rounds[group] = dict(id=group, title='协调 ' + str(len(rounds) + 1), at=decision.get('at'), attempts=[])
        if group and number not in rounds[group]['attempts']:
            rounds[group]['attempts'].append(number)
        card = dict(id=adapter._id('canvas', run + ':' + key), role=role, kind=kind, title=title,
                    summary=summary, attempt_no=number, round_id=group, state=state,
                    call_id=call['id'] if call else None, material=material,
                    at=event.get('at') if event else None,
                    sequence=event['seq'] if event else 0,
                    source=dict(kind=event['kind'], sequence=event['seq']) if event else None)
        cards.append(card)
        return card

    def edge(source, target, event, label):
        edges.append(dict(id=str(event['seq']) + ':' + source['id'] + ':' + target['id'],
                          source=source['id'], target=target['id'], at=event.get('at'),
                          sequence=event['seq'], label=label, source_call_id=source.get('call_id'),
                          target_call_id=adapter._id('call', run + ':' + str(event['seq'])) if event['kind'] == 'call_dispatched' else target.get('call_id')))

    if row.get('_preparation'):
        receipt = next((e for e in reversed(events) if e['kind'] == 'preparation'), None)
        add('preparation', 'onboard', 'preparation', '研究准备',
            text(row.get('_preparation_state', {}).get('reason')) or '准备调用归属未登记，当前活动未知',
            event=receipt, state=row.get('state') or 'unknown', call=calls[-1] if calls else None)
        return dict(cards=cards, edges=edges, rounds=[], note='准备事件范围，不是正式 Run')

    nodes = {}
    for item in work:
        n = item['attempt_no']
        a = by_number[n]
        plan = mapping(parsed(a.get('plan'), {}))
        related = [e for e in events if e.get('attempt_no') == n]
        selection = selections.get(n)
        planned = add('plan:' + str(n), 'expert', 'direction', item['title'], item['goal'],
                      number=n, event=selection, state='recorded')
        designers = [c for c in calls if c['attempt_no'] == n and c['role'] == 'designer']
        dispatches = [e for e in related if e['kind'] == 'call_dispatched' and e['body'].get('role') == 'designer']
        execution = next((e for e in reversed(related) if e['kind'] == 'execution'), None)
        candidate = next((e for e in reversed(related) if e['kind'] == 'candidate_saved'), None)
        implementation = None
        if designers or execution or candidate:
            source = execution or candidate or (dispatches[-1] if dispatches else None)
            implementation = add('work:' + str(n), 'designer', 'implementation', item['title'],
                item['summary'] or item['reason'] or '已记录实施调用；输出尚未确认', number=n, event=source,
                state=designers[-1]['state'] if designers else item['stage'], call=designers[-1] if designers else None)
            if dispatches and mapping(mapping(dispatches[-1]['body'].get('inputs')).get('plan')).get('work_id') == item['work_id']:
                edge(planned, implementation, dispatches[-1], '派发实施')
        artifacts = {}
        if adapter._run_dir(row):
            from .inspection import register, relative
            for e in related:
                if e['kind'] != 'deliverables_saved':
                    continue
                # Only the task's declared deliverables, never internal evidence/log files.
                for path in e['body'].get('paths', []):
                    if not isinstance(path, str) or not path.startswith('outputs/'):
                        continue
                    name = path.removeprefix('outputs/')
                    if name not in (plan.get('deliverables') or []) or not relative(name):
                        continue
                    full = adapter._run_dir(row) / 'attempts' / ('a%06d' % n) / path
                    material = register(adapter, 'canvas:' + run + ':' + str(n) + ':' + path,
                                        name, '声明的任务产出', path=full)
                    old = artifacts.get(path)
                    slot = cards.index(old) if old else None
                    if old:
                        cards.remove(old)
                        edges[:] = [link for link in edges if link['target'] != old['id']]
                    dispatch = next((d for d in reversed(dispatches) if d['seq'] < e['seq']), None)
                    producer = next((c for c in designers if dispatch and c['id'] == adapter._id('call', run + ':' + str(dispatch['seq']))), None)
                    node = add('artifact:' + str(n) + ':' + path, 'designer', 'artifact', name,
                               '任务产出' if material['availability'] == 'available' else '产出已登记，内容当前不可用',
                               number=n, event=e, state='recorded', material=material, call=producer)
                    if slot is not None:
                        cards.remove(node)
                        cards.insert(slot, node)
                    artifacts[path] = node
                    if implementation:
                        edge(implementation, node, e, '保存产出')
        feedback = next((e for e in reversed(related) if e['kind'] == 'conclusion'), None)
        evaluators = [c for c in calls if c['attempt_no'] == n and c['role'] == 'evaluator']
        if evaluators or item['outcome']:
            receipt = next((e for e in reversed(related) if e['kind'] == 'evaluation_call' or (e['kind'] == 'call_dispatched' and e['body'].get('role') == 'evaluator')), None)
            experiment = next((e for e in reversed(related) if e['kind'] == 'experiment'), None)
            add('evaluation:' + str(n), 'evaluator' if evaluators else 'system', 'evaluation', '工作结果 · ' + item['title'],
                text((experiment or {}).get('body', {}).get('summary')) or text(a.get('reason')) or item['outcome'] or '评价已派发；结果尚未确认',
                number=n, event=receipt or experiment,
                state='result_failed' if item['outcome'] in ('broken', 'worker_failed', 'sandbox_violation', 'infra') else 'result_recorded' if item['outcome'] else evaluators[-1]['state'] if evaluators else item['stage'], call=evaluators[-1] if evaluators else None)
        if feedback:
            reviewed_by = feedback['body'].get('reviewed_by_call')
            dispatch = next((e for e in events if reviewed_by and e['kind'] == 'call_dispatched' and e['body'].get('call_id') == reviewed_by and e['body'].get('role') == 'expert'), None)
            author = next((c for c in calls if dispatch and c['id'] == adapter._id('call', run + ':' + str(dispatch['seq']))), None)
            add('feedback:' + str(n), 'expert', 'feedback', '反馈分析 · ' + item['title'],
                text(feedback['body'].get('text')), number=n, event=feedback, state='recorded', call=author)
        nodes[n] = dict(direction=planned, implementation=implementation, artifacts=artifacts)

    for e in events:
        if e['kind'] != 'call_dispatched':
            continue
        target = nodes.get(e.get('attempt_no'), {}).get('implementation')
        if not target or e['body'].get('role') != 'designer':
            continue
        handoff = mapping(mapping(mapping(e['body'].get('inputs')).get('context')).get('handoff'))
        for dependency in handoff.get('inputs', []):
            if not isinstance(dependency, dict):
                continue
            if not isinstance(dependency.get('artifact'), str):
                continue
            upstream = by_work.get(dependency.get('work_id'))
            source = nodes.get(upstream['attempt_no'], {}).get('artifacts', {}).get(dependency.get('artifact')) if upstream else None
            if source and source['sequence'] < e['seq']:
                edge(source, target, e, '传入任务材料')
    return dict(cards=cards, edges=edges, rounds=list(rounds.values()),
                note='连线仅表示已保存的派发输入或产物归属；无回执时不推断返回')


def run_brief(adapter, row, contract):
    """A current file is historical input only if its bytes match the frozen binding."""
    if row.get('_preparation'):
        return None
    result = dict(goal=text(mapping(contract).get('goal')), material=None, version='unconfirmed')
    source = mapping(mapping(contract).get('_source'))
    if not isinstance(source.get('brief'), str) or not isinstance(source.get('sha256'), str):
        return result
    path = adapter._path(source['brief'])
    if not adapter._allowed(path) or not path.is_file() or path.stat().st_size > 1048576:
        return result
    stat = path.stat()
    signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    cache = getattr(adapter, '_bound_briefs', {})
    previous = cache.get(str(path))
    if not previous or previous[0] != signature:
        raw = path.read_bytes()
        previous = (signature, hashlib.sha256(raw).hexdigest(), raw)
        cache[str(path)] = previous
        adapter._bound_briefs = cache
    if previous[1] == source['sha256']:
        from .inspection import register
        # Freeze the verified bytes in the existing transient material registry.
        # A later edit cannot make this ID silently open a different input version.
        result['material'] = register(adapter, 'bound-brief:' + row['run_id'] + ':' + source['sha256'],
            'task-brief.md', '与本次运行合同匹配的简报版本', content=previous[2], version=source['sha256'])
        result['version'] = 'matched'
    return result
