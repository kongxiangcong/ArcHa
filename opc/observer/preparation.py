"""Read-only preparation views. These are event scopes, never execution Runs."""
from .adapter import mapping, parsed, issue


def discover(adapter, events):
    groups = {}
    for event in events:
        scope = event['run_id']
        if scope.startswith('preparation:'):
            groups.setdefault(scope, []).append(event)
    rows = []
    for scope, history in groups.items():
        task_id = scope.removeprefix('preparation:')
        contract_owners = {rv['research_task_id'] for rv in adapter.revisions.values()
                  if rv['execution_task_id'] == task_id and rv.get('research_task_id')}
        owners, explicit_paths = set(), set()
        contract_paths = {adapter._path(b['path']) for rv in adapter.revisions.values()
                          if rv['execution_task_id'] == task_id for b in rv.get('brief_bindings', [])}
        states = []
        for event in sorted(history, key=lambda e:e['seq']):
            body = mapping(parsed(event.get('body'), {}))
            inputs = mapping(body.get('inputs'))
            brief = mapping(body.get('brief_input') or inputs.get('brief_input')).get('brief')
            if brief:
                path = adapter._path(brief)
                explicit_paths.add(path)
                owners.update(t['id'] for t in adapter.tasks.values() if t['_path'].parent == path.parent)
            if event['kind'] == 'preparation':
                states.append(body)
        if not explicit_paths:
            owners = contract_owners
        ambiguous = len(explicit_paths or contract_paths) > 1 or len(owners) > 1
        if ambiguous:
            owners = set()
            adapter.issues.append(issue('preparation_owner_ambiguous', '准备来源涉及多个专题，未合并到任何专题；可在工程未关联准备中查看'))
        last = states[-1] if states else {}
        latest_receipt = max((e['seq'] for e in history if e['kind']=='preparation'), default=-1)
        dispatched = [e for e in history if e['kind']=='call_dispatched' and e['seq'] > latest_receipt]
        if dispatched:
            finished = {mapping(parsed(e.get('body'), {})).get('call_id') for e in history if e['kind']=='worker_call'}
            pending = any(mapping(parsed(e.get('body'), {})).get('call_id') not in finished for e in dispatched)
            last = dict(state='pending' if pending else 'unknown', reason='准备调用已登记；本轮最终准备结果尚未确认')
        rows.append(dict(run_id=scope, task_id=task_id, revision='preparation',
                         state=last.get('state', 'unknown'), stop_reason=last.get('reason'),
                         created_at=history[0].get('at'), _preparation=True,
                         _owners=owners, _ownership_ambiguous=ambiguous, _preparation_state=last))
    return rows
