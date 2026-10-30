#!/usr/bin/env python3
"""Research directories and DECISIONS handoffs; no execution or runtime changes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import subprocess

MARKER = 'archa-handoff'


def inside(root: Path, path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or absolute != resolved:
        raise ValueError('path must remain inside project without symlinks')
    return resolved


def slug(value: str) -> str:
    value = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    if not value:
        raise ValueError('provide a short readable ASCII name derived from the research goal')
    return value


def create(root: Path, name: str, title: str, scope: str) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError('project must exist')
    base = inside(root, root / '.opc/research/topics')
    base.mkdir(parents=True, exist_ok=True)
    name = slug(name)
    candidate = name
    number = 1
    while True:
        topic = inside(root, base / candidate)
        try:
            topic.mkdir()
            break
        except FileExistsError:
            number += 1
            candidate = f'{name}-{number}'
    task = topic / 'tasks/r01-baseline'
    task.mkdir(parents=True)
    title = ' '.join(title.split())
    scope = ' '.join(scope.split())
    (topic / 'research-map.md').write_text(
        f'# {title}\n\n{scope}\n\n## 研究任务 to-do\n\n'
        '- [ ] R01 | [基线与范围](tasks/r01-baseline/task.md) | status=todo | depends=none\n', encoding='utf-8')
    (topic / 'discussion.md').write_text(f'# {title}：讨论\n\n{scope}\n', encoding='utf-8')
    (task / 'task.md').write_text(
        '# R01：基线与范围\n\n[所属地图](../../research-map.md)\n\n'
        f'研究用途：{scope}\n\n范围与缺口：在本专题讨论中明确。\n', encoding='utf-8')
    index = inside(root, root / '.opc/research/index.md')
    if not index.exists():
        index.write_text('# 研究专题\n\n', encoding='utf-8')
    existing = index.read_text(encoding='utf-8')
    with index.open('a', encoding='utf-8') as stream:
        if (root / '.opc/research/research-map.md').is_file() and '(research-map.md)' not in existing:
            stream.write('- [旧布局专题](research-map.md) — 原有研究范围，见地图\n')
        stream.write(f'- [{title}](topics/{candidate}/research-map.md) — {scope}\n')
    return {'topic': str(topic), 'task_directory': str(task), 'next': command('archa-task', task)}


def command(skill: str, directory: Path) -> str:
    path = str(directory)
    return '$' + skill + ' ' + (json.dumps(path, ensure_ascii=False) if any(c.isspace() for c in path) else path)


def task_paths(root: Path, directory: str | None) -> tuple[Path, Path]:
    if not directory:
        raise ValueError('请提供具体任务目录')
    path = Path(directory)
    path = inside(root, path if path.is_absolute() else Path.cwd() / path)
    if path.is_file():
        raise ValueError('请使用所属任务目录：' + str(path.parent))
    if path == root or (path / 'research-map.md').exists() or path.name == 'tasks':
        raise ValueError('请提供具体任务目录，不能使用项目根、专题根或 tasks 集合目录')
    if not path.is_dir() or not any((path / p).is_file() for p in ('task.md', 'task-brief.md')):
        raise ValueError('请提供具体任务目录，不能使用项目根、专题根或 tasks 集合目录')
    for name in ('task.md', 'task-brief.md'):
        inside(root, path / name)
    return path, path / 'task-brief.md'


def records(root: Path) -> tuple[Path, str, list[dict]]:
    path = inside(root, root / '.opc/context/DECISIONS.md')
    body = path.read_text(encoding='utf-8') if path.exists() else ''
    entries = []
    for raw in re.findall(r'<!-- archa-handoff (.*?) -->', body):
        row = json.loads(raw)
        if not isinstance(row, dict) or not all(k in row for k in ('brief', 'sha256', 'task_id', 'revision', 'contract')):
            raise ValueError('incomplete DECISIONS handoff; resolve missing fields')
        entries.append(row)
    return path, body, entries


def append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write('\n<!-- archa-handoff ' + json.dumps(row, ensure_ascii=True) + ' -->\n')


def binding(root: Path, brief: Path) -> tuple[Path, list[dict], dict | None]:
    path, body, entries = records(root)
    rel = brief.relative_to(root).as_posix()
    matching = [r for r in entries if r['brief'] == rel]
    if len({r['task_id'] for r in matching}) > 1:
        raise ValueError('ambiguous task identities for brief; reconcile DECISIONS')
    row = matching[-1] if matching else None
    if row and any(r['task_id'] == row['task_id'] and r['brief'] != rel for r in entries):
        raise ValueError('task identity is bound to another directory')
    prose = re.sub(r'<!-- archa-handoff .*? -->', '', body)
    if not row and rel in prose:
        raise ValueError('legacy handoff found: verify explicit task/revision and record it before continuing')
    return path, entries, row


def contract(root: Path, task_id: str, revision: str) -> str:
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', task_id) or not re.fullmatch(r'r\d{4}', revision):
        raise ValueError('invalid task ID or revision')
    path = inside(root, root / f'.opc/tasks/{task_id}/revisions/{revision}/task.json')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if value.get('task_id') != task_id or value.get('revision') != revision:
        raise ValueError('contract identity does not match handoff')
    return path.relative_to(root).as_posix()


def resolve(root: Path, directory: str | None, prepare: bool = False) -> dict:
    root = root.resolve()
    task, brief = task_paths(root, directory)
    if not brief.is_file():
        raise ValueError('缺少简报；请运行 ' + command('archa-task', task))
    path, entries, row = binding(root, brief)
    digest = hashlib.sha256(brief.read_bytes()).hexdigest()
    if row is None:
        if not prepare:
            raise ValueError('尚未 onboard；请运行 ' + command('archa-task', task))
        # Reserve in the existing handoff document before dispatch: failed preparation
        # and retries must keep the same identity, even before a contract exists.
        parts = task.relative_to(root).parts
        label = '-'.join(parts[parts.index('topics') + 1:]) if 'topics' in parts else '-'.join(parts)
        base = ('t-' + slug(label.replace('tasks-', '')))[:56].rstrip('-')
        occupied = {r['task_id'] for r in entries}
        tasks = root / '.opc/tasks'
        if tasks.is_dir():
            occupied.update(p.name for p in tasks.iterdir())
        task_id, number = base, 1
        while task_id in occupied:
            number += 1
            task_id = f'{base}-{number}'
        row = {'brief': brief.relative_to(root).as_posix(), 'sha256': digest,
               'task_id': task_id, 'revision': None, 'contract': None}
        if not (root / '.opc/project.json').exists():
            launcher = inside(root, root / '.opc/archa.py')
            if not launcher.is_file():
                raise ValueError('initialize project runtime before preparing task')
            result = subprocess.run([sys.executable, str(launcher), 'init', '-p', str(root),
                                     '--project-id', 'research-project', '--name', root.name,
                                     '--task', task_id, '--apply'], capture_output=True, text=True)
            if result.returncode:
                raise ValueError('project initialization failed: ' + result.stderr + result.stdout)
        append(path, row)
    if row['revision'] is not None:
        actual = contract(root, row['task_id'], row['revision'])
        if actual != row['contract']:
            raise ValueError('contract path does not match handoff')
    elif not prepare:
        raise ValueError('尚未完成 onboard；请运行 ' + command('archa-task', task))
    changed = row['sha256'] != digest
    if changed and not prepare:
        raise ValueError('简报已变化；请运行 ' + command('archa-task', task))
    return dict(row, task_directory=str(task), brief_changed=changed,
                next=command('archa-task' if prepare else 'archa-loop', task))


def record(root: Path, directory: str, task_id: str, revision: str) -> dict:
    root = root.resolve()
    task, brief = task_paths(root, directory)
    path, _, entries = records(root)
    rel = brief.relative_to(root).as_posix()
    # Explicit record also supports importing an agent-verified legacy prose relation.
    if any((r['brief'] == rel and r['task_id'] != task_id) or
           (r['task_id'] == task_id and r['brief'] != rel) for r in entries):
        raise ValueError('conflicting task identity; preserve history and reconcile handoff')
    row = {'brief': rel, 'sha256': hashlib.sha256(brief.read_bytes()).hexdigest(),
           'task_id': task_id, 'revision': revision, 'contract': contract(root, task_id, revision)}
    if not entries or entries[-1] != row:
        append(path, row)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('create', 'resolve', 'record'):
        p = sub.add_parser(action)
        p.add_argument('--project', type=Path, required=True)
        if action == 'create':
            for field in ('name', 'title', 'scope'):
                p.add_argument('--' + field, required=True)
        else:
            p.add_argument('--directory')
        if action == 'resolve':
            p.add_argument('--prepare', action='store_true')
        if action == 'record':
            p.add_argument('--task', required=True)
            p.add_argument('--revision', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'create':
            result = create(args.project, args.name, args.title, args.scope)
        elif args.action == 'resolve':
            result = resolve(args.project, args.directory, args.prepare)
        else:
            result = record(args.project, args.directory, args.task, args.revision)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
