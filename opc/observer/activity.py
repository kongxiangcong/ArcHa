"""Bounded, on-demand tool activity. Original events never cross this boundary."""
from __future__ import annotations

import base64
import json
import re
from collections import OrderedDict
from pathlib import Path

from .adapter import ObserverError, mapping, parsed

READ_BYTES = 65536
MAX_ACTIONS = 200


def locate(adapter, ident):
    data = adapter._db(tables_to_read=('runs', 'events'))
    events = [{**e, 'body': mapping(parsed(e['body'], {}))} for e in data['events']]
    dispatches = {(e['run_id'], e['body'].get('call_id')): e for e in events if e['kind'] == 'call_dispatched'}
    terminals = {(e['run_id'], e['body'].get('call_id')): e for e in events if e['kind'] in ('worker_call', 'evaluation_call')}
    for event in events:
        if event['kind'] not in ('call_dispatched', 'worker_call', 'evaluation_call'):
            continue
        body = event['body']
        dispatch = dispatches.get((event['run_id'], body.get('call_id')))
        if adapter._id('call', event['run_id'] + ':' + str((dispatch or event)['seq'])) != ident:
            continue
        terminal = terminals.get((event['run_id'], body.get('call_id')))
        current = (terminal or event)['body']
        association = mapping((dispatch or {}).get('body', {}).get('activity_log'))
        trusted = association.get('provider') in ('codex', 'dsh') and isinstance(association.get('path'), str)
        directory = current.get('log_dir') or str(Path(body.get('receipt_path', '')).parent)
        path = adapter._path(association['path'] if trusted else str(Path(directory) / (body.get('role', '') + '-events.jsonl')))
        owner_seq = (dispatch or event)['seq']
        reused = any(e['seq'] > owner_seq and (e['run_id'] != event['run_id'] or e['body'].get('call_id') != body.get('call_id')) and e['body'].get('role') == body.get('role') and
                     ((mapping(e['body'].get('activity_log')).get('path') and adapter._path(e['body']['activity_log']['path']) == path) or
                      (e['body'].get('log_dir') and adapter._path(e['body']['log_dir']) == path.parent) or
                      (e['body'].get('receipt_path') and adapter._path(e['body']['receipt_path']).parent == path.parent))
                     for e in events if e['kind'] in ('call_dispatched', 'worker_call'))
        if reused or not adapter._allowed(path):
            return None, 'unreadable', '日志归属无法确认，未读取其他调用的内容'
        if not path.is_file():
            return None, 'missing', '尚无具体活动记录' if trusted else '此调用没有可用的具体活动记录'
        session = current.get('session_id') or (current.get('call_id') if not dispatch else None)
        if not trusted or session:
            head, _, _, _ = adapter._jsonl(path, max_bytes=READ_BYTES)
            if not session or session not in adapter._header_ids(head):
                return None, 'unreadable', '日志归属无法确认，未读取其他调用的内容'
        return dict(path=path, provider=association.get('provider'), terminal=terminal is not None,
                    session=session, trusted=trusted), 'available', None
    raise ObserverError(404, 'not_found', '未知调用')


def clipped(value, size=2000):
    return value[:size] if isinstance(value, str) else None


def tool(event):
    typ = event.get('type')
    item = mapping(event.get('item')) or event
    subtype = item.get('type')
    if typ not in ('item.started', 'item.updated', 'item.completed', 'tool_call', 'tool_start', 'tool_result', 'tool_end'):
        return None
    if typ.startswith('item.') and subtype not in ('command_execution', 'mcp_tool_call', 'file_change', 'file_read', 'web_search'):
        return None
    ident = item.get('id') or item.get('tool_call_id') or item.get('toolCallId') or item.get('callId')
    if not isinstance(ident, str):
        return None  # Missing identity cannot pair actions reliably.
    name = item.get('name') or item.get('toolName') or item.get('tool_name') or item.get('tool') or subtype or 'tool'
    arguments = mapping(item.get('arguments')) or mapping(item.get('input'))
    obj = item.get('command') or item.get('path') or arguments.get('command') or arguments.get('path') or arguments.get('file_path') or item.get('query')
    if not obj and isinstance(item.get('changes'), list):
        obj = ', '.join(c['path'] for c in item['changes'] if isinstance(c, dict) and isinstance(c.get('path'), str))
    finished = typ in ('item.completed', 'tool_result', 'tool_end')
    exit_code = item.get('exit_code', item.get('exitCode'))
    failed = item.get('status') in ('failed', 'error') or item.get('isError') is True or (isinstance(exit_code, int) and exit_code != 0)
    at = event.get('timestamp') or event.get('at')
    return dict(id=ident, category='command' if subtype == 'command_execution' or name in ('bash', 'shell', 'exec_command') else 'file' if subtype in ('file_change', 'file_read') or name in ('read', 'write', 'edit') else 'tool',
                name=clipped(name, 100), object=clipped(obj), state='failed' if finished and failed else 'completed' if finished else 'pending',
                started_at=at if not finished else None, ended_at=at if finished else None,
                summary=('动作失败' if failed else '动作完成') if finished else None,
                exit_code=exit_code if isinstance(exit_code, int) else None)


def activity(adapter, ident, cursor=None, limit=100):
    if not 1 <= limit <= 200:
        raise ObserverError(422, 'invalid_limit', '活动数量必须在 1–200 之间')
    source, availability, note = locate(adapter, ident)
    if source is None:
        return adapter.envelope(dict(call_id=ident, actions=[], availability=availability, note=note, reset=bool(cursor), truncated=False, has_more=False))
    path = source['path']
    cache = adapter.activity_cache
    cur = None
    if cursor:
        try:
            cur = json.loads(base64.urlsafe_b64decode(cursor))
            if (cur['call'] != ident or not isinstance(cur['offset'], int) or cur['offset'] < 0
                    or not isinstance(cur['identity'], list) or not isinstance(cur['prefix'], str)):
                raise ValueError()
            base64.b64decode(cur['prefix'], validate=True)
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise ObserverError(422, 'invalid_cursor', '活动游标与当前调用不匹配') from None
    try:
        with path.open('rb') as stream:
            stat = __import__('os').fstat(stream.fileno())
            identity = [stat.st_dev, stat.st_ino]
            prefix = stream.read(128)
            state = cache.get(ident)
            reset = bool(cur and (cur['identity'] != identity or cur['offset'] > stat.st_size or
                                  base64.b64decode(cur['prefix']) != prefix[:len(base64.b64decode(cur['prefix']))]))
            if not state or reset:
                start = max(0, stat.st_size - READ_BYTES)
                state = dict(identity=identity, offset=start, prefix=prefix, actions=OrderedDict(), truncated=start > 0, skip=start > 0)
            elif state['identity'] != identity or state['offset'] > stat.st_size or prefix[:len(state['prefix'])] != state['prefix']:
                reset = True
                start = max(0, stat.st_size - READ_BYTES)
                state = dict(identity=identity, offset=start, prefix=prefix, actions=OrderedDict(), truncated=start > 0, skip=start > 0)
            stream.seek(state['offset'])
            chunk = stream.read(READ_BYTES)
    except OSError:
        raise ObserverError(503, 'source_unreadable', '具体活动暂不可读') from None
    end = chunk.rfind(b'\n') + 1
    if end:
        lines = chunk[:end].splitlines()
        if state['skip']:
            lines = lines[1:]
            state['skip'] = False
        for line in lines:
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(event, dict):
                continue
            action = tool(event)
            # These are registered system storage scopes, not filename guesses.
            obj = action['object'].replace('\\', '/') if action and action['object'] else ''
            if obj and (any(internal.replace('\\', '/') in obj for internal in
                    (str(adapter.root / '.opc/local'), '.opc/local/', str(path.parent))) or
                    re.search(r"\.opc/research/(?:topics/[^/]+/)?tasks/(?:[^\s\"';|]+/)?evidence(?:/|$)", obj)):
                continue
            if action:
                previous = state['actions'].get(action['id'])
                if previous:
                    action['started_at'] = previous['started_at']
                    action['object'] = action['object'] or previous['object']
                state['actions'][action['id']] = action
                state['actions'].move_to_end(action['id'])
                if len(state['actions']) > MAX_ACTIONS:
                    # Keep unfinished actions before recent completions; bound both.
                    completed = next((k for k, v in state['actions'].items() if v['state'] != 'pending'), next(iter(state['actions'])))
                    del state['actions'][completed]
                    state['truncated'] = True
        state['offset'] += end
    elif len(chunk) == READ_BYTES:
        state['offset'] += len(chunk)
        state['skip'] = True
        state['truncated'] = True
    state['prefix'] = prefix
    cache[ident] = state
    cache.move_to_end(ident)
    while len(cache) > 128:
        cache.popitem(last=False)
    actions = list(state['actions'].values())
    if source['terminal']:
        actions = [{**a, 'state': 'unconfirmed' if a['state'] == 'pending' else a['state']} for a in actions]
    pending = [a for a in actions if a['state'] in ('pending', 'unconfirmed')]
    completed = [a for a in actions if a['state'] not in ('pending', 'unconfirmed')]
    selected = pending + completed[-max(0, limit - len(pending)):] if len(pending) < limit else pending[:limit]
    next_cursor = base64.urlsafe_b64encode(json.dumps(dict(call=ident, identity=identity, offset=state['offset'], prefix=base64.b64encode(prefix).decode())).encode()).decode()
    return adapter.envelope(dict(call_id=ident, actions=selected, availability='available', note='动作已开始，结果待确认；日志不代表执行仍然存活' if pending else '显示已记录的具体活动',
                                 reset=reset, truncated=state['truncated'] or len(actions) > limit, has_more=state['offset'] < stat.st_size and (end > 0 or len(chunk) == READ_BYTES)), next_cursor=next_cursor)
