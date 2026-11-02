"""Saved-call handoffs and explicitly declared task materials, read on demand."""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
import subprocess

from ..core.config import matches, denied
from .adapter import ObserverError, mapping, parsed, meta
from .workbench import records, workers, text


def relative(value):
    return isinstance(value, str) and bool(value) and not Path(value).is_absolute() and not any(p in ('..', '.git', '.opc') for p in Path(value).parts) and '\\' not in value


def register(adapter, key, name, purpose, *, path=None, version=None, unavailable=False):
    ident = adapter._id('material', key)
    mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    available = bool(path and adapter._allowed(path) and path.is_file()) if path else bool(version and git_size(adapter, version, name) is not None)
    textual = mime.startswith('text/') or Path(name).suffix.lower() in ('.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.py', '.ts', '.tsx', '.js', '.c', '.cpp', '.h', '.sv', '.v', '.sh', '.svg')
    available = available and not unavailable and textual
    stat = path.stat() if available and path else None
    dto = dict(id=ident, kind='task_material', title=name, display_path=name, content_origin='file',
               phase='task', availability='available' if available else 'missing', mime=mime,
               can_preview=available, can_download=False, meta=meta(availability='available' if available else 'missing'), link_targets={})
    adapter.artifact_registry[ident] = dict(dto=dto, task_material=True, path=path, version=version, name=name, signature=(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) if stat else None)
    return dict(id=ident, name=name, purpose=purpose, availability=dto['availability'], note=None if available else '所选工作版本的材料不可用或不支持文本预览')


def git_size(adapter, version, name):
    # Git receives only a recorded version and a declared relative task path, never a shell command.
    result = subprocess.run(['git', 'cat-file', '-s', version + ':' + name], cwd=adapter.root, capture_output=True, timeout=5)
    return int(result.stdout) if result.returncode == 0 else None


def inspection(adapter, ident, number, call=None):
    row, attempts, events = records(adapter, ident)
    if not any(a['attempt_no'] == number for a in attempts):
        raise ObserverError(404, 'not_found', '工作记录不可用')
    calls = [c for c in workers(adapter, row, events) if c['attempt_no'] == number]
    selected = next((c for c in calls if c['id'] == call), None) if call else (calls[-1] if calls else None)
    if call and not selected:
        raise ObserverError(422, 'call_not_related', '调用不属于所选运行和工作')
    data = dict(attempt_no=number, calls=calls, call_id=selected['id'] if selected else None,
                error=selected['error'] if selected else None, input=None, output=None, materials=[],
                input_note='此调用没有保存的交接输入，不能重建历史输入')
    if not selected:
        return adapter.envelope(data)
    dispatch = next((e for e in events if e['kind'] == 'call_dispatched' and adapter._id('call', row['run_id'] + ':' + str(e['seq'])) == selected['id']), None)
    if not dispatch:
        return adapter.envelope(data)
    body = dispatch['body']
    saved = next((c for c in adapter._db(row['run_id'], tables_to_read=('calls',))['calls'] if c['call_id'] == body['call_id']), None)
    inputs = mapping(parsed(saved['input'], {})) if saved else mapping(body.get('inputs'))
    result = mapping(parsed(saved.get('result'), {})) if saved else {}
    plan = mapping(inputs.get('plan'))
    context = mapping(inputs.get('context'))
    handoff = mapping(context.get('handoff'))
    task = mapping(context.get('task'))
    if inputs:
        data['input'] = dict(title=text(plan.get('title')), purpose=text(handoff.get('purpose')) or text(plan.get('changes')),
                             goal=text(task.get('goal')), hypothesis=text(plan.get('hypothesis')),
                             deliverables=[p for p in plan.get('deliverables', []) if relative(p)])
        data['input_note'] = '仅展示本次调用保存的必要交接输入'
    output = mapping(result.get('output'))
    if output:
        data['output'] = dict(summary=text(output.get('summary')), completed=output.get('completed') if isinstance(output.get('completed'), bool) else result.get('ok'))
    data['error'] = text(result.get('error')) or data['error']
    next_dispatch = next((e['seq'] for e in events if e['seq'] > dispatch['seq'] and e['kind'] == 'call_dispatched' and e.get('attempt_no') == number and e['body'].get('role') == body.get('role')), float('inf'))
    owned_events = [e for e in events if dispatch['seq'] < e['seq'] < next_dispatch and e.get('attempt_no') == number]
    later_outputs = {p for e in events if e['seq'] >= next_dispatch and e.get('attempt_no') == number and e['kind'] == 'deliverables_saved' for p in e['body'].get('paths', [])}
    saved_outputs = {p for e in owned_events if e['kind'] == 'deliverables_saved' for p in e['body'].get('paths', [])}
    run_dir = adapter._run_dir(row)
    if run_dir:
        for dependency in handoff.get('inputs', []):
            if not isinstance(dependency, dict):
                continue
            artifact = dependency.get('artifact', '')
            if not isinstance(artifact, str) or not artifact.startswith('outputs/') or not relative(artifact):
                continue
            upstream = next((a for a in attempts if mapping(parsed(a.get('plan'), {})).get('work_id') == dependency.get('work_id')), None)
            if not upstream:
                continue
            no, name = upstream['attempt_no'], artifact.removeprefix('outputs/')
            source_dispatch = next((e for e in reversed(events) if e['seq'] < dispatch['seq'] and e.get('attempt_no') == no and e['kind'] == 'call_dispatched' and e['body'].get('role') == 'designer'), None)
            source_plan = mapping(mapping(source_dispatch['body'].get('inputs')).get('plan')) if source_dispatch else mapping(parsed(upstream.get('plan'), {}))
            if name not in source_plan.get('deliverables', []):
                continue
            saves = [e for e in events if e.get('attempt_no') == no and e['kind'] == 'deliverables_saved' and artifact in e['body'].get('paths', [])]
            if not any(e['seq'] < dispatch['seq'] for e in saves):
                continue
            path = run_dir / 'attempts' / ('a%06d' % no) / artifact
            if dependency.get('path') and adapter._path(dependency['path']) != path.resolve():
                continue
            data['materials'].append(register(adapter, selected['id'] + ':input:' + str(no) + ':' + name, name, '传入任务材料', path=path, unavailable=any(e['seq'] > dispatch['seq'] for e in saves)))
        for name in data['input']['deliverables'] if data['input'] else []:
            if 'outputs/' + name in saved_outputs:
                path = run_dir / 'attempts' / ('a%06d' % number) / 'outputs' / name
                data['materials'].append(register(adapter, selected['id'] + ':output:' + name, name, '任务产出', path=path, unavailable='outputs/' + name in later_outputs))
    candidate = next((e['body'] for e in owned_events if e['kind'] == 'candidate_saved'), None)
    if candidate:
        component = mapping(adapter._read(run_dir / 'frozen/component.json', json_file=True, default={})) if run_dir else {}
        version, parent = candidate.get('commit'), candidate.get('parent')
        if isinstance(version, str) and isinstance(parent, str):
            changed = subprocess.run(['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', parent, version, '--'], cwd=adapter.root, capture_output=True, text=True, timeout=5)
            if changed.returncode == 0:
                for name in changed.stdout.splitlines():
                    if relative(name) and matches(name, component.get('editable', [])) and not denied(name, component.get('frozen', []) + component.get('evaluator_files', [])) and name not in (data['input']['deliverables'] if data['input'] else []):
                        data['materials'].append(register(adapter, selected['id'] + ':code:' + name, name, '本次工作代码', version=version))
            else:
                data['material_note'] = '所选工作版本的代码不可用，未读取当前工作树'
    return adapter.envelope(data)


def content(adapter, ident, offset, limit):
    if offset < 0 or not 1 <= limit <= 1048576:
        raise ObserverError(422, 'invalid_range', '内容读取范围无效')
    item = adapter.artifact_registry[ident]
    path = item.get('path')
    if item['dto']['availability'] != 'available':
        raise ObserverError(404, 'material_unavailable', '所选工作版本的材料不可用')
    try:
        if path:
            if not adapter._allowed(path):
                raise ObserverError(404, 'path_denied', '任务材料超出允许目录')
            with path.open('rb') as stream:
                stat = os.fstat(stream.fileno())
                if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != item['signature']:
                    raise ObserverError(409, 'material_changed', '任务材料已变化，未读取其他版本')
                size = stream.seek(0, 2)
                stream.seek(offset)
                raw = stream.read(limit + 4)
            version = str(stat.st_mtime_ns) + ':' + str(size)
        else:
            size = git_size(adapter, item['version'], item['name'])
            if size is None:
                raise ObserverError(404, 'material_unavailable', '所选工作版本的材料不可用或不支持文本预览')
            process = subprocess.Popen(['git', 'show', item['version'] + ':' + item['name']], cwd=adapter.root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                remaining = offset
                while remaining:
                    chunk = process.stdout.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                raw = process.stdout.read(limit + 4)
            finally:
                process.stdout.close()
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
            version = item['version']
    except FileNotFoundError:
        raise ObserverError(404, 'material_unavailable', '所选工作版本的材料不可用或不支持文本预览') from None
    except OSError:
        raise ObserverError(503, 'source_unreadable', '任务材料暂不可读') from None
    if offset > size:
        raise ObserverError(422, 'invalid_offset', '内容读取位置超出末尾')
    start = 0
    while start < len(raw) and raw[start] & 0xC0 == 0x80:
        start += 1
    end = min(start + limit, len(raw))
    while end > start and end < len(raw) and raw[end] & 0xC0 == 0x80:
        end -= 1
    if end == start and start < len(raw):
        end = start + 1
        while end < len(raw) and raw[end] & 0xC0 == 0x80:
            end += 1
    try:
        decoded = raw[start:end].decode('utf-8')
        if '\0' in decoded:
            raise UnicodeError()
    except UnicodeError:
        raise ObserverError(415, 'material_not_text', '该任务材料不支持文本预览') from None
    return adapter.envelope(dict(artifact_id=ident, content=decoded, encoding='utf-8',
                                 byte_offset=offset + start, next_offset=offset + end, eof=offset + end >= size,
                                 truncated=offset > 0 or offset + end < size, content_version=version))
