"""Current ArcHa source-format adapter; no Engine, Ledger, shell or provider calls.

The adapter owns source interpretation. Public methods return the v1 presentation
contract; only registered artifact IDs can cross the HTTP file boundary.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import mimetypes
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else str(value).encode()).hexdigest()


def mapping(value):
    return value if isinstance(value, dict) else {}


def parsed(value, fallback=None):
    if not isinstance(value, str):
        return value if value is not None else fallback
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return fallback


def state(value='unknown', raw=None, at=None, basis='unknown', note=None):
    return dict(value=value, raw_value=raw, basis=basis, at=at, note=note)


def issue(code, message, entity_id=None):
    return dict(code=code, message=message, entity_id=entity_id)


def meta(refs=None, issues=None, availability='available'):
    return dict(availability=availability, source_refs=refs or [], issues=issues or [])


def ref(entity, label=None):
    return dict(id=entity['id'], label=label or entity.get('title') or entity.get('revision') or entity.get('source_run_id') or entity['id'])


class ObserverError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


class ObserverAdapter:
    adapter_id = 'archa-current'
    adapter_version = '1.0'

    def __init__(self, root: Path | str, demo=False):
        self.root = Path(root).resolve()
        self.demo = demo
        self.project_key = 'p_' + digest(str(self.root))[:16]
        self.lock = threading.RLock()
        self.artifact_registry: dict[str, dict] = {}
        self.last_files: dict[str, tuple[Any, str]] = {}
        self.discovery_at = 0.0
        self.tasks: dict[str, dict] = {}
        self.briefs: dict[str, dict] = {}
        self.revisions: dict[str, dict] = {}
        self.calls: dict[str, dict] = {}
        self.call_sources: dict[str, dict] = {}
        self.run_rows: list[dict] = []
        self.snapshots: dict[str, dict] = {}
        self.source_at = None
        self.issues: list[dict] = []
        self.artifact_root = self.root / '.opc/local/artifacts'
        self.project = {}
        self.maps: list[dict] = []
        self._discover()

    def _id(self, kind, value):
        return self.project_key + ':' + kind + ':' + digest(value)[:24]

    def _path(self, path):
        path = Path(path)
        return (self.root / path).resolve() if not path.is_absolute() else path.resolve()

    def _allowed(self, path):
        resolved = Path(path).resolve()
        return any(resolved == root or root in resolved.parents for root in (self.root, self.artifact_root.resolve()))

    def _display(self, path):
        p = Path(path)
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            return str(p)

    def _read(self, path, *, json_file=False, default=None):
        path = Path(path)
        if not self._allowed(path):
            self.issues.append(issue('path_denied', '来源超出允许读取范围：' + self._display(path)))
            return default
        key = str(path)
        try:
            raw = path.read_bytes()
            value = json.loads(raw) if json_file else raw.decode('utf-8')
            self.last_files[key] = (value, now())
            return value
        except FileNotFoundError:
            if key in self.last_files:
                cached, at = self.last_files[key]
                self.issues.append(dict(code='source_unreadable', message='来源暂时缺失，数据可能滞后；最后成功读取 ' + at + '：' + self._display(path), entity_id=None, cached_at=at))
                return cached
            return default
        except (OSError, ValueError, UnicodeError):
            cached_at = self.last_files.get(key, (None, None))[1]
            self.issues.append(dict(code='source_unreadable', message='更新失败，数据可能滞后；最后成功读取 ' + str(cached_at or '未知') + '：' + self._display(path), entity_id=None, cached_at=cached_at))
            return self.last_files.get(key, (default, None))[0]

    def _register(self, path=None, *, title=None, phase='other', owners=None, record=None, locator=None):
        if path is not None:
            # Stable identity uses the lexical path; access checks always resolve again.
            p = Path(path).absolute()
            call_owner = next((o['id'] for o in (owners or []) if ':call:' in o.get('id', '')), None)
            ident = self._id('artifact', str(p) + (':' + call_owner if call_owner else ''))
            allowed = self._allowed(p)
            try:
                stat = p.stat() if allowed and p.is_file() else None
            except OSError:
                stat = None
            availability = 'available' if stat else ('missing' if allowed else 'unreadable')
            mime = mimetypes.guess_type(str(p))[0] or ('text/plain' if p.suffix in ('.patch', '.jsonl', '.log') else 'application/octet-stream')
            text = mime.startswith('text/') or p.suffix in ('.json', '.jsonl', '.md', '.patch', '.svg', '.log')
            obj = dict(id=ident, kind=p.suffix.lstrip('.') or 'file', title=title or p.name,
                       display_path=self._display(p), content_origin='file', owner_refs=owners or [],
                       phase=phase, availability=availability, mime=mime, size_bytes=stat.st_size if stat else None,
                       digest=None, digest_algorithm=None, key_facts=[], can_preview=bool(text and stat),
                       can_download=bool(stat and allowed), meta=meta(availability=availability))
            self.artifact_registry[ident] = dict(dto=obj, path=p, call_owner=call_owner)
        else:
            ident = self._id('artifact', locator)
            obj = dict(id=ident, kind='ledger_record', title=title or locator, display_path='.opc/local/ledger.sqlite3 • ' + locator,
                       content_origin='ledger', owner_refs=owners or [], phase=phase, availability='available',
                       mime='application/json', size_bytes=None, digest=None, digest_algorithm=None, key_facts=[],
                       can_preview=True, can_download=False, meta=meta())
            self.artifact_registry[ident] = dict(dto=obj, record=record)
        return obj

    def _source(self, artifact, locator=None):
        return dict(kind='ledger' if artifact['content_origin'] == 'ledger' else 'file',
                    display_path=artifact['display_path'], locator=locator, artifact_id=artifact['id'])

    def _db(self, run_id=None, tables_to_read=None):
        path = self.root / '.opc/local/ledger.sqlite3'
        if not path.exists():
            return {name: [] for name in ('runs', 'events', 'attempts', 'champions', 'charges')}
        if not self._allowed(path):
            raise ObserverError(503, 'path_denied', '账本路径超出允许范围')
        result = {}
        try:
            con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.5)
            con.row_factory = sqlite3.Row
            try:
                con.execute('PRAGMA query_only=ON')
                con.execute('BEGIN')
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for name in (tables_to_read or ('runs', 'events', 'attempts', 'champions', 'charges')):
                    if name not in tables:
                        result[name] = []
                        self.issues.append(issue('source_unsupported', '账本缺少表：' + name))
                        continue
                    columns = {r[1] for r in con.execute('PRAGMA table_info(' + name + ')')}
                    required = {'runs': {'run_id', 'task_id', 'revision', 'state'}, 'events': {'seq', 'run_id', 'at', 'kind', 'attempt_no', 'body'}, 'attempts': {'run_id', 'attempt_no'}, 'champions': {'run_id', 'seq', 'commit_sha'}, 'charges': {'run_id', 'tokens', 'wall_seconds', 'usd', 'usd_known'}}[name]
                    if not required <= columns:
                        result[name] = []
                        self.issues.append(issue('source_unsupported', '账本缺少必要列：' + name))
                        continue
                    sql = 'SELECT * FROM ' + name
                    args = ()
                    if run_id is not None:
                        sql += ' WHERE run_id=?'
                        args = (run_id,)
                    result[name] = [dict(r) for r in con.execute(sql, args)]
                con.rollback()
            finally:
                con.close()
        except sqlite3.Error:
            raise ObserverError(503, 'ledger_unreadable', '本次账本暂不可读；未尝试修复或迁移') from None
        return result

    def envelope(self, data, next_cursor=None, issues=None):
        return dict(schema_version='1.0', snapshot_at=now(), source_observed_at=self.source_at,
                    data=data, issues=list({(i['code'], i['message'], i.get('entity_id')): i for i in (issues if issues is not None else self.issues)}.values()), next_cursor=next_cursor)

    def _requirements(self, rows):
        if rows is not None and not isinstance(rows, list):
            self.issues.append(issue('source_invalid_shape', 'requirements 应为列表；未使用损坏字段作为完成条件'))
            return []
        return [dict(id=str(r.get('id') or ''), text=str(r.get('text') or ''), verification=r.get('verification') if isinstance(r.get('verification'), str) else None,
                     result='unverified', tested_commit=None, evidence_refs=[], report_artifact_id=None)
                for r in rows or [] if isinstance(r, dict)]

    def _discover(self):
        self.issues = []
        project = self._read(self.root / '.opc/project.json', json_file=True, default={})
        if not isinstance(project, dict):
            project = {}
        bindings = self._read(self.root / '.opc/local/bindings.json', json_file=True, default={})
        configured = bindings.get('artifact_root') if isinstance(bindings, dict) else None
        if configured is not None and not isinstance(configured, str):
            self.issues.append(issue('source_invalid_shape', 'artifact_root 不是路径字符串；使用默认产物目录'))
            configured = None
        if configured:
            self.artifact_root = self._path(configured)
        self.project = dict(id=self.project_key, project_key=self.project_key,
                            display_name=project.get('display_name') or self.root.name,
                            source_project_id=project.get('project_id'), source_format='archa-opc-v0.3' if project else None,
                            source_runtime_version=None, adapter_id=self.adapter_id, adapter_version=self.adapter_version,
                            source_mode='demo' if self.demo else 'live', meta=meta())
        if not (self.root / '.opc').exists():
            self.issues.append(issue('source_missing', '未发现 ArcHa 材料；观察器不会初始化项目'))
        self.tasks = {}
        self.briefs = {}
        self.revisions = {}
        self.maps = []
        map_path = self.root / '.opc/research/research-map.md'
        body = self._read(map_path)
        if body is not None:
            art = self._register(map_path, title='研究地图', phase='map')
            self.maps.append(dict(id=art['id'], artifact_id=art['id'], label='研究地图', title='研究地图'))
            for match in re.finditer(r'^- \[([ xX])\]\s*([^|\n]+)\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*status=([^|\n]+)\|\s*depends=(.*)$', body, re.M):
                _, raw_id, title, relpath, status_raw, depends = match.groups()
                task_path = map_path.parent / relpath.strip()
                tid = self._id('research-task', str(map_path) + ':' + raw_id.strip())
                task_art = self._register(task_path, phase='task')
                self.tasks[tid] = dict(id=tid, title=title, research_task_id=raw_id.strip(), map_artifact_id=art['id'],
                                       task_artifact_id=task_art['id'], depends_on=re.findall(r'\b[A-Z]+\d+\b', depends),
                                       raw_preparation_status=status_raw.strip(), briefs=[], revision_refs=[],
                                       link_state='verified', meta=meta([self._source(task_art)]), _path=task_path.resolve())
        research = self.root / '.opc/research/tasks'
        task_files = sorted(research.glob('*/task.md')) if research.exists() else []
        brief_files = sorted(research.glob('*/task-brief.md')) if research.exists() else []
        for path in task_files:
            if not self._allowed(path) or any(t.get('_path') == path.resolve() for t in self.tasks.values()):
                continue
            text = self._read(path, default='')
            title = next((s.lstrip('# ').strip() for s in text.splitlines() if s.startswith('# ')), path.parent.name)
            art = self._register(path, phase='task')
            tid = self._id('research-task', str(path.resolve()))
            self.tasks[tid] = dict(id=tid, title=title, research_task_id=None, map_artifact_id=None,
                                   task_artifact_id=art['id'], depends_on=[], raw_preparation_status=None,
                                   briefs=[], revision_refs=[], link_state='unresolved', meta=meta([self._source(art)]), _path=path.resolve())
        for path in brief_files:
            self._brief(path)
        for path in sorted((self.root / '.opc/tasks').glob('*/revisions/*/task.json')):
            raw = self._read(path, json_file=True)
            if not isinstance(raw, dict):
                continue
            self._revision(raw, path)
        try:
            db = self._db()
        except ObserverError as exc:
            self.issues.append(issue(exc.code, exc.message))
            db = {'runs': [], 'events': []}
        self.run_rows = db['runs']
        self.snapshots = {}
        if not self.run_rows:
            project_id = self.project.get('source_project_id')
            if project_id:
                for snapshot_path in sorted((self.artifact_root / project_id).glob('*/*/views/report.json')):
                    snapshot = self._read(snapshot_path, json_file=True)
                    if not isinstance(snapshot, dict) or not snapshot.get('run_id') or not snapshot.get('task'):
                        continue
                    frozen = self._read(snapshot_path.parents[1] / 'frozen/task.json', json_file=True, default={})
                    row = dict(run_id=snapshot['run_id'], task_id=snapshot['task'], revision=snapshot.get('revision'),
                               task_digest=digest(json.dumps(frozen, sort_keys=True, separators=(',', ':'), ensure_ascii=False)) if frozen else None,
                               state=snapshot.get('state'), stop_reason=snapshot.get('stop_reason'), base_commit=snapshot.get('baseline'),
                               evaluator_digest=None, toolchain_digest=None, created_at=None, closed_at=None, _snapshot=str(snapshot_path))
                    self.run_rows.append(row)
                    self.snapshots[row['run_id']] = snapshot
                if self.snapshots and not self.demo:
                    self.project['source_mode'] = 'snapshot'
                if self.snapshots:
                    self.issues.append(issue('snapshot_only', '账本不可用；仅显示已有 views 快照，时间与内容可能滞后'))
        self.source_at = max((e['at'] for e in db['events'] if e.get('at')), default=None)
        self._link_revisions()
        self.discovery_at = __import__('time').monotonic()

    def _brief(self, path):
        text = self._read(path)
        if text is None:
            return None
        sha = digest(text.encode('utf-8'))
        ident = self._id('brief', str(path.resolve()) + ':' + sha)
        art = self._register(path, phase='task')
        def field(name):
            m = re.search(r'^' + re.escape(name) + r':\s*(.+)$', text, re.M)
            return m.group(1).strip() if m else None
        source_kind = 'map' if field('Map') else 'task' if field('Task') else 'unknown'
        source_path = self._path(path.parent / (field('Map') or field('Task') or ''))
        # Source paths in briefs are project-relative by the current format.
        source_path = self._path(field('Map') or field('Task') or str(path))
        matching = [t for t in self.tasks.values() if t.get('_path') == source_path or t.get('_path', Path('.')).parent == path.parent]
        if not matching:
            tid = self._id('research-task', str(path.parent.resolve()))
            self.tasks[tid] = dict(id=tid, title=field('Goal') or path.parent.name,
                                   research_task_id=None, map_artifact_id=None, task_artifact_id=None,
                                   depends_on=[], raw_preparation_status=field('Status'), briefs=[], revision_refs=[],
                                   link_state='unresolved', meta=meta(), _path=path.parent / 'task.md')
            matching = [self.tasks[tid]]
        requirements = []
        for m in re.finditer(r'^-\s*(R\d+):\s*(.*?)\s*\|\s*verification=(\w+)', text, re.M):
            requirements.append(dict(id=m.group(1), text=m.group(2), verification=m.group(3)))
        obj = dict(id=ident, path=self._display(path), sha256=sha, source_kind=source_kind,
                   source_task_id=matching[0]['id'] if len(matching) == 1 else None, body_artifact_id=art['id'],
                   goal=field('Goal'), done_when=field('Done when'), scope=None,
                   deliverables=re.findall(r'^- D\d+: (.+)$', text, re.M), requirements=self._requirements(requirements),
                   objective=field('Objective'), link_state='verified' if len(matching) == 1 else 'ambiguous',
                   meta=meta([self._source(art)]))
        self.briefs[ident] = obj
        for task in matching:
            task['briefs'].append(ref(obj, '任务简报'))
        return obj

    def _revision(self, raw, path, *, frozen=False):
        task_id = raw.get('task_id') or path.parents[2].name
        revision = raw.get('revision') or path.parent.name
        sha = digest(json.dumps(raw, sort_keys=True, separators=(',', ':'), ensure_ascii=False))
        ident = self._id('revision', task_id + ':' + revision + ':' + sha)
        art = self._register(path, phase='onboard')
        obj = dict(id=ident, execution_task_id=task_id, revision=revision, task_digest=sha,
                   goal=raw.get('goal') if isinstance(raw.get('goal'), str) else None, requirements=self._requirements(raw.get('requirements')),
                   objective=mapping(raw.get('acceptance')).get('objective'), budget=raw.get('budget') if isinstance(raw.get('budget'), dict) else None,
                   brief_id=None, link_state='unresolved', contract_artifact_id=art['id'], meta=meta([self._source(art)]), _raw=raw)
        self.revisions[ident] = obj
        return obj

    def _link_revisions(self):
        decisions = self._read(self.root / '.opc/context/DECISIONS.md', default='')
        # Conservative explicit convention: no title, timestamp or substring guesses.
        bindings = []
        for line in decisions.splitlines():
            fields = dict(re.findall(r'(?:^|\s)(task|revision|brief|sha256)=([^\s]+)', line))
            if {'task', 'revision', 'brief', 'sha256'} <= fields.keys():
                bindings.append(fields)
        for task in self.tasks.values():
            task['revision_refs'] = []
        for revision in self.revisions.values():
            explicit = [b for b in bindings if b['task'] == revision['execution_task_id'] and b['revision'] == revision['revision']]
            unique = {(b['brief'], b['sha256']) for b in explicit}
            revision['brief_id'] = None
            if len(unique) > 1:
                revision['link_state'] = 'ambiguous'
            elif len(unique) == 1:
                path, expected = next(iter(unique))
                brief = next((b for b in self.briefs.values() if b['path'] == path), None)
                if not brief:
                    revision['link_state'] = 'unresolved'
                elif brief['sha256'] != expected:
                    revision['link_state'] = 'digest_mismatch'
                else:
                    revision['link_state'] = 'verified'
                    revision['brief_id'] = brief['id']
                    task = self.tasks.get(brief['source_task_id'])
                    if task is not None:
                        task['revision_refs'].append(ref(revision, revision['execution_task_id'] + ' / ' + revision['revision']))
            else:
                revision['link_state'] = 'unresolved'
            revision['meta']['issues'] = [i for i in revision['meta']['issues'] if not i['code'].startswith('brief_')]
            if revision['link_state'] != 'verified':
                revision['meta']['issues'].append(issue('brief_' + revision['link_state'], '简报与执行合同的关系：' + revision['link_state'], revision['id']))

    def _public(self, obj):
        return {k: v for k, v in obj.items() if not k.startswith('_')}

    def overview(self):
        with self.lock:
            self._discover()
            linked_revs = {r['id'] for t in self.tasks.values() for r in t['revision_refs']}
            revision_refs = [ref(r, r['execution_task_id'] + ' / ' + r['revision']) for r in self.revisions.values() if r['id'] not in linked_revs]
            unlinked = [self._run_ref(r) for r in self.run_rows if not any(rv['execution_task_id'] == r.get('task_id') and rv['revision'] == r.get('revision') and rv['id'] in linked_revs for rv in self.revisions.values())]
            return self.envelope(dict(project=self.project, maps=self.maps,
                                      tasks=[self._public(t) for t in self.tasks.values()],
                                      unlinked_revisions=revision_refs, unlinked_runs=unlinked,
                                      capabilities=dict(task_graph='available' if self.maps else 'missing',
                                                        attempt_history='available' if self.run_rows else 'missing',
                                                        call_content='partial', live_activity='missing',
                                                        requirement_results='partial', numeric_measurements='partial')))

    def _run_ref(self, row):
        return dict(id=self._id('run', row['run_id']), label=row['run_id'], source_run_id=row['run_id'],
                    execution_task_id=row.get('task_id'), revision=row.get('revision'))

    def research_task(self, ident):
        with self.lock:
            self._discover()
            task = self.tasks.get(ident)
            if task is None:
                raise ObserverError(404, 'not_found', '未知研究任务')
            revisions = [r for r in self.revisions.values() if any(x['id'] == r['id'] for x in task['revision_refs'])]
            rows = [r for r in self.run_rows if any(rv['execution_task_id'] == r.get('task_id') and rv['revision'] == r.get('revision') for rv in revisions)]
            return self.envelope(dict(task=self._public(task), briefs=[self.briefs[b['id']] for b in task['briefs']],
                                      revisions=[self._public(r) for r in revisions], runs=[self._run_ref(r) for r in rows],
                                      artifacts=[self.artifact_registry[a]['dto'] for a in (task.get('task_artifact_id'), task.get('map_artifact_id')) if a in self.artifact_registry]))

    def task_revision(self, ident):
        with self.lock:
            if ident not in self.revisions:
                self._discover()
            revision = self.revisions.get(ident)
            if revision is None:
                raise ObserverError(404, 'not_found', '未知合同版本')
            rows = [r for r in (self._db()['runs'] or self.run_rows) if r.get('task_id') == revision['execution_task_id'] and r.get('revision') == revision['revision']]
            return self.envelope(dict(revision=self._public(revision), runs=[self._run_ref(r) for r in rows],
                                      artifacts=[self.artifact_registry[revision['contract_artifact_id']]['dto']]))

    def _find_run(self, ident):
        try:
            rows = self._db(tables_to_read=('runs',))['runs']
        except ObserverError:
            rows = []
        rows = rows or self.run_rows
        for row in rows:
            if self._id('run', row['run_id']) == ident:
                return row
        raise ObserverError(404, 'not_found', '未知运行记录')

    def _run_dir(self, row):
        project_id = self.project.get('source_project_id')
        if not project_id:
            return None
        return self.artifact_root / project_id / row.get('task_id', '') / row['run_id']

    def _usage(self, row, charges, events, contract):
        if not charges:
            tokens = usd = seconds = None
            complete = 'unknown'
        else:
            tokens = sum(c.get('tokens', 0) for c in charges)
            seconds = sum(c.get('wall_seconds', 0) for c in charges)
            usd = sum(c.get('usd') or 0 for c in charges) if all(c.get('usd_known') and c.get('usd') is not None for c in charges) else None
            complete = 'partial' if usd is None or any(e.get('kind') == 'accounting_unknown' for e in events) else 'complete'
        budget = mapping(contract.get('budget'))
        return dict(scope='run', scope_id=self._id('run', row['run_id']), includes_preparation=row.get('revision') == 'preparation',
                    recorded_tokens=tokens, recorded_usd=usd, recorded_wall_seconds=seconds, completeness=complete,
                    budget_tokens=budget.get('max_tokens'), budget_wall_seconds=budget.get('max_wall_seconds'),
                    note='仅账本 charges 已记录用量；未把 host_usage 累计再次相加', source_refs=[])

    def run(self, ident):
        with self.lock:
            row = self._find_run(ident)
            data = self._db(row['run_id'])
            if data['runs']:
                row = data['runs'][0]
            if row.get('_snapshot'):
                snapshot = self.snapshots[row['run_id']]
                data['attempts'] = [dict(a, run_id=row['run_id'], _snapshot=row['_snapshot']) for a in snapshot.get('attempts', [])]
                data['champions'] = snapshot.get('champions', [])
                for key in ('working_version', 'selected_version'):
                    value = snapshot.get(key)
                    if value:
                        data['events'].append(dict(seq=-999999 if key == 'working_version' else -999998, run_id=row['run_id'], at=None, kind=key, attempt_no=None, body={'commit': value}, _snapshot=row['_snapshot']))
                for a in data['attempts']:
                    for index, key in enumerate(('development_parent', 'candidate_saved', 'execution', 'experiment', 'conclusion')):
                        value = a.get({'development_parent': 'parent', 'candidate_saved': 'candidate'}.get(key, key))
                        if value is None:
                            continue
                        body = {'commit': value, 'parent': a.get('parent')} if key in ('development_parent', 'candidate_saved') else {'text': value} if key == 'conclusion' else value
                        data['events'].append(dict(seq=-a['attempt_no'] * 10 - index, run_id=row['run_id'], at=None, kind=key, attempt_no=a['attempt_no'], body=body, _snapshot=row['_snapshot']))
            events = sorted(data['events'], key=lambda x: x.get('seq', 0))
            self.source_at = max((e['at'] for e in events if e.get('at')), default=None)
            for event in events:
                event['body'] = parsed(event.get('body'), {})
                if not isinstance(event['body'], dict):
                    event['body'] = {}
                    self.issues.append(issue('event_body_invalid', '事件内容无法解析'))
            run_dir = self._run_dir(row)
            revision = None
            if row.get('revision') != 'preparation':
                frozen = self._read(run_dir / 'frozen/task.json', json_file=True) if run_dir else None
                if isinstance(frozen, dict):
                    revision = self._revision(frozen, run_dir / 'frozen/task.json', frozen=True)
                    self._link_revisions()
                else:
                    revision = next((r for r in self.revisions.values() if r['execution_task_id'] == row.get('task_id') and r['revision'] == row.get('revision')), None)
                if revision and row.get('task_digest') and revision['task_digest'] != row['task_digest']:
                    revision = dict(revision, _contract_mismatch=True, link_state='digest_mismatch', meta=meta(revision['meta']['source_refs'], [issue('contract_digest_mismatch', '合同摘要与运行账本不一致')], 'partial'))
            contract = revision.get('_raw', {}) if revision and not revision.get('_contract_mismatch') else {}
            requirements = self._requirements(contract.get('requirements'))
            reports = []
            artifacts = []
            report_refs = []
            if revision:
                artifacts.append(self.artifact_registry[revision['contract_artifact_id']]['dto'])
            if run_dir and self._allowed(run_dir):
                for path in sorted(run_dir.glob('promotion/*/report.json')):
                    report = self._read(path, json_file=True)
                    art = self._register(path, phase='acceptance', owners=[ref(dict(id=ident), row['run_id'])])
                    artifacts.append(art)
                    report_refs.append(ref(art))
                    if isinstance(report, dict):
                        reports.append((report, art))
                # Restricted known artifact directories only, never scan arbitrary workspace.
                for pattern in ('attempts/*/*.json', 'attempts/*/*.patch', 'attempts/*/*.md', 'attempts/*/*.html', 'attempts/*/*.svg', 'views/*.md', 'views/*.json', 'frozen/baseline.json'):
                    for path in sorted(run_dir.glob(pattern)):
                        if path.name.endswith('-request.json') or 'prompt' in path.name:
                            continue
                        a = self._register(path, phase='loop', owners=[dict(id=ident, label=row['run_id'])])
                        artifacts.append(a)
            champs = sorted(data['champions'], key=lambda c: c.get('seq', 0))
            working_event = next((e for e in reversed(events) if e['kind'] == 'working_version'), None)
            working = working_event['body'].get('commit') if working_event else row.get('base_commit')
            selected_event = next((e for e in reversed(events) if e['kind'] == 'selected_version'), None)
            current_selected = selected_event['body'].get('commit') if selected_event else champs[-1].get('commit_sha') if champs else working
            valid_report = None
            for report, art in reports:
                key = mapping(report.get('evidence_key'))
                if (revision and not revision.get('_contract_mismatch') and report.get('run_id') == row['run_id']
                        and key.get('task') == row.get('task_digest') and key.get('commit') == report.get('selected_version') == current_selected
                        and key.get('evaluator') == row.get('evaluator_digest') and key.get('toolchain') == row.get('toolchain_digest')):
                    valid_report = (report, art)
                else:
                    art['meta']['issues'].append(issue('evidence_scope_mismatch', '终验依据不匹配当前运行的合同/版本/评价条件'))
            acceptance = state('not_evaluated', basis='derived', note='未发现对应版本的终验记录')
            selected = current_selected
            if valid_report:
                report, art = valid_report
                selected = report.get('selected_version')
                acceptance = state('passed' if report.get('complete') is True and report.get('promotable') is True else 'failed', raw=str(report.get('complete')), basis='recorded')
                report_rows = report.get('requirements')
                if not isinstance(report_rows, list):
                    self.issues.append(issue('source_invalid_shape', '终验 requirements 应为列表；未使用损坏的逐项结论'))
                    report_rows = []
                if any(not isinstance(r, dict) or not isinstance(r.get('status'), str) or not isinstance(r.get('id'), str) for r in report_rows):
                    self.issues.append(issue('source_invalid_shape', '终验逐项结论含无法识别的记录；未将其视为通过'))
                report_requirements = {r.get('id'): r for r in report_rows if isinstance(r, dict) and isinstance(r.get('id'), str)}
                for req in requirements:
                    result = report_requirements.get(req['id'], {})
                    raw_status = str(result.get('status') or '')
                    req.update(result='met' if raw_status in ('met', 'met_by_gates', 'met_by_review') else 'not_met' if raw_status.startswith('not_met') else 'pending_review' if raw_status == 'needs_review' else 'unverified',
                               tested_commit=selected, evidence_refs=[self._source(art)], report_artifact_id=art['id'])
                if acceptance['value'] == 'passed' and any(r['result'] != 'met' for r in requirements):
                    acceptance = state('unknown', raw='complete=true', basis='recorded', note='总体结论与逐项证据不一致；无法确认验收通过')
                    self.issues.append(issue('report_inconsistent', '终验总体结论与逐项证据不一致'))
            prep = state('unknown', note='准备记录未明确关联此运行')
            if row.get('revision') == 'preparation':
                receipt = next((e for e in reversed(events) if e['kind'] == 'preparation'), None)
                raw = receipt['body'].get('state') if receipt else None
                mapped = {'ready': 'ready', 'pending': 'preparing', 'external_blocked': 'blocked', 'budget_exhausted': 'blocked', 'accounting_unknown': 'blocked'}.get(raw, 'unknown')
                prep = state(mapped, raw, receipt.get('at') if receipt else None, 'recorded' if receipt else 'unknown', receipt['body'].get('reason') if receipt else None)
                if receipt:
                    receipt_art = self._register(record=receipt, locator='events.seq=%s' % receipt['seq'], phase='onboard', owners=[dict(id=ident, label=row['run_id'])], title='准备回执 · 账本记录')
                    artifacts.append(receipt_art)
                acceptance = state('not_applicable', basis='derived')
            execution_raw = row.get('state')
            execution = state({'active': 'running', 'closed': 'finished', 'paused': 'paused', 'blocked': 'blocked', 'failed': 'failed', 'cancelled': 'cancelled'}.get(execution_raw, 'unknown'), execution_raw,
                              row.get('closed_at') or row.get('created_at'), 'recorded',
                              '记录中运行，实时状态未确认' if execution_raw == 'active' else None)
            attempts = []
            call_refs = []
            for event in events:
                if event['kind'] == 'worker_call':
                    call = self._call_from_event(row, event, events, run_dir)
                    call_refs.append(ref(call, call['role'] + ' · ' + str(call.get('provider') or '未知 provider')))
                    artifacts.extend(self.artifact_registry[x['id']]['dto'] for x in call['artifacts'])
            for raw_attempt in sorted(data['attempts'], key=lambda a: a.get('attempt_no', 0)):
                attempt = self._attempt_from_row(row, raw_attempt, events, artifacts)
                attempts.append(ref(attempt, '第 %s 轮' % attempt['attempt_no']) | {'attempt_no': attempt['attempt_no']})
            champs = sorted(data['champions'], key=lambda c: c.get('seq', 0))
            versions = dict(baseline=row.get('base_commit'), working=working, champion=champs[-1].get('commit_sha') if champs else None, selected=selected)
            metrics = []
            objective = mapping(contract.get('acceptance')).get('objective')
            if isinstance(objective, dict) and objective.get('metric'):
                metric_name = objective['metric']
                baseline_record = next((c for c in champs if c.get('commit_sha') == row.get('base_commit')), None)
                champion_record = champs[-1] if champs else None
                candidate_record = next((a for a in reversed(data['attempts']) if isinstance(parsed(a.get('metrics')), dict)), None)
                candidate_event = next((e for e in reversed(events) if e['kind'] == 'candidate_saved' and candidate_record and e.get('attempt_no') == candidate_record['attempt_no']), None)
                values, scopes, numeric_refs = {}, {}, []
                for label, record, commit in (('baseline', baseline_record, row.get('base_commit')),
                                               ('champion', champion_record, versions['champion']),
                                               ('candidate', candidate_record, candidate_event['body'].get('commit') if candidate_event else None)):
                    measurement = mapping(parsed(record.get('metrics'), {})) if record else {}
                    measured_values = mapping(measurement.get('values'))
                    value = measured_values.get(metric_name)
                    values[label] = value if isinstance(value, (int, float)) else None
                    scopes[label] = dict(commit=measurement.get('source_commit') or commit,
                                         task_digest=row.get('task_digest'), evaluator_digest=measurement.get('evaluator_digest'),
                                         toolchain_digest=measurement.get('toolchain_digest'))
                    if record:
                        locator = ('attempts.run_id=%s,attempt_no=%s' % (row['run_id'], record['attempt_no'])) if label == 'candidate' else ('champions.run_id=%s,seq=%s' % (row['run_id'], record['seq']))
                        numeric_art = self._register(record=record, locator=locator, phase='loop', owners=[dict(id=ident, label=row['run_id'])], title=label + ' · 测量记录')
                        artifacts.append(numeric_art)
                        numeric_refs.append(self._source(numeric_art))
                valid = valid_report[0] if valid_report else {}
                selected_value = mapping(valid.get('selected_metrics')).get(metric_name)
                values['selected'] = selected_value if isinstance(selected_value, (int, float)) else None
                scopes['selected'] = dict(commit=selected, task_digest=row.get('task_digest'), evaluator_digest=mapping(valid.get('evidence_key')).get('evaluator'), toolchain_digest=mapping(valid.get('evidence_key')).get('toolchain'))
                if valid_report:
                    numeric_refs.append(self._source(valid_report[1]))
                    if values['baseline'] is None:
                        baseline_value = mapping(valid.get('baseline_metrics')).get(metric_name)
                        values['baseline'] = baseline_value if isinstance(baseline_value, (int, float)) else None
                comparable_scopes = [scopes[k] for k in scopes if values.get(k) is not None]
                proven = all(scope.get('evaluator_digest') and scope.get('toolchain_digest') for scope in comparable_scopes)
                compatible = len({(scope.get('evaluator_digest'), scope.get('toolchain_digest'), scope.get('task_digest')) for scope in comparable_scopes}) <= 1
                comparison = ('comparable' if compatible else 'not_comparable') if proven and len(comparable_scopes) > 1 else 'unknown'
                metrics.append(dict(name=metric_name, unit=None, direction=objective.get('direction'),
                                    threshold=mapping(contract.get('acceptance')).get('target'), **values,
                                    comparison_state=comparison, scopes=scopes, source_refs=numeric_refs))
            run_meta = meta([dict(kind='snapshot' if row.get('_snapshot') else 'ledger', display_path=self._display(row['_snapshot']) if row.get('_snapshot') else '.opc/local/ledger.sqlite3', locator='run_id=' + row['run_id'], artifact_id=None)], availability='partial' if row.get('_snapshot') else 'available')
            if revision and revision['link_state'] == 'digest_mismatch':
                run_meta['availability'] = 'partial'
                run_meta['issues'].extend(revision['meta']['issues'])
            if not revision and row.get('revision') != 'preparation':
                run_meta = meta(run_meta['source_refs'], [issue('contract_missing', '未发现可核对的历史合同')], 'partial')
            result = dict(id=ident, source_run_id=row['run_id'], kind='preparation' if row.get('revision') == 'preparation' else 'execution',
                          task_revision_id=revision['id'] if revision and not revision.get('_contract_mismatch') else None, execution_task_id=row.get('task_id'),
                          preparation=prep, execution=execution, acceptance=acceptance, stop_reason=row.get('stop_reason'),
                          phase='onboard' if row.get('revision') == 'preparation' else 'loop', last_activity_at=self.source_at,
                          versions=versions, requirements=requirements, metrics=metrics, usage=self._usage(row, data['charges'], events, contract),
                          attempts=attempts, calls=call_refs, artifacts=[ref(a) for a in {a['id']: a for a in artifacts}.values()], report_refs=report_refs,
                          meta=run_meta)
            self._attempt_cache = getattr(self, '_attempt_cache', {})
            return self.envelope(result)

    def _attempt_from_row(self, run, row, events, artifacts):
        rid = self._id('run', run['run_id'])
        n = row['attempt_no']
        ident = self._id('attempt', run['run_id'] + ':' + str(n))
        relevant = [e for e in events if e.get('attempt_no') == n]
        projected = {}
        sources = {}
        event_artifacts = []
        for e in relevant:
            artifact = self._register(path=e.get('_snapshot'), record=e, locator='events.seq=%s' % e['seq'], phase='loop', owners=[dict(id=ident, label='第 %s 轮' % n)], title=e['kind'] + ' · 账本记录')
            event_artifacts.append(ref(artifact))
            projected[e['kind']] = e['body']
            sources[e['kind']] = [self._source(artifact, 'events.seq=%s' % e['seq'])]
        def fact(value, kind):
            if value is None:
                return None
            # Prefer the existing author-written summary without reinterpreting it.
            # The complete record remains available through its artifact source.
            if isinstance(value, dict):
                readable = next((value[k] for k in ('summary', 'text') if isinstance(value.get(k), str)), None)
                text = readable if readable is not None else json.dumps(value, ensure_ascii=False, indent=2)
            else:
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
            return dict(text=text, source_refs=sources.get(kind, []))
        plan = parsed(row.get('plan'), {})
        if not isinstance(plan, dict):
            plan = {}
        # The plan is an actual attempts row, not a fabricated file.
        plan_art = self._register(path=row.get('_snapshot'), record=row, locator='attempts.run_id=%s,attempt_no=%s' % (run['run_id'], n), phase='loop', owners=[dict(id=ident, label='第 %s 轮' % n)], title='第 %s 轮计划与状态 · 账本记录' % n)
        sources['plan'] = [self._source(plan_art)]
        event_artifacts.append(ref(plan_art))
        outcome = row.get('outcome')
        execution = projected.get('execution')
        experiment = projected.get('experiment')
        conclusion = projected.get('conclusion') or {}
        attempt_artifacts = [ref(a) for a in artifacts if ('/a%06d/' % n) in a['display_path']]
        obj = dict(id=ident, run_id=rid, attempt_no=n, phase='loop', execution_state=state('finished' if row.get('state') == 'decided' else 'unknown', row.get('state'), row.get('finished_at'), 'recorded'),
                   outcome=outcome, intent=fact(plan.get('title') or plan.get('changes'), 'plan'), rationale=fact(plan.get('hypothesis'), 'plan'),
                   execution_summary=fact(execution, 'execution'), experiment_summary=fact(experiment, 'experiment'),
                   conclusion=fact(conclusion.get('text'), 'conclusion'), gaps=fact(conclusion.get('gaps'), 'conclusion'), next_step=fact(conclusion.get('next_step'), 'conclusion'),
                   parent_commit=(projected.get('development_parent') or {}).get('commit') or row.get('champion_before'),
                   candidate_commit=(projected.get('candidate_saved') or {}).get('commit'),
                   calls=[ref(c, c['role']) for c in self.calls.values() if c.get('run_id') == rid and c.get('attempt_id') == ident],
                   artifacts=attempt_artifacts + event_artifacts, usage=None, meta=meta([self._source(plan_art)]))
        if not hasattr(self, '_attempt_cache'):
            self._attempt_cache = {}
        self._attempt_cache[ident] = obj
        return obj

    def attempt(self, run_id, number):
        with self.lock:
            self.run(run_id)
            ident = next((a['id'] for a in self._attempt_cache.values() if a['run_id'] == run_id and a['attempt_no'] == number), None)
            if ident is None:
                raise ObserverError(404, 'not_found', '未知轮次')
            return self.envelope(self._attempt_cache[ident])

    def _log_reused_after(self, event, log_dir, role):
        """Use the globally ordered ledger event identity, never a reusable session ID."""
        path = self.root / '.opc/local/ledger.sqlite3'
        try:
            con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.5)
            try:
                con.execute('PRAGMA query_only=ON')
                for (body,) in con.execute("SELECT body FROM events WHERE kind='worker_call' AND seq>?", (event['seq'],)):
                    value = parsed(body, {})
                    if isinstance(value, dict) and value.get('role') == role and value.get('log_dir') and self._path(value['log_dir']) == self._path(log_dir):
                        return True
            finally:
                con.close()
        except sqlite3.Error:
            return True  # Ownership cannot be established this time.
        return False

    def _call_from_event(self, row, event, events, run_dir):
        body = event['body']
        ident = self._id('call', row['run_id'] + ':' + str(event['seq']))
        role = body.get('role') if isinstance(body.get('role'), str) else 'unknown'
        provider_id = body.get('call_id') if isinstance(body.get('call_id'), str) else None
        log_dir = body.get('log_dir') if isinstance(body.get('log_dir'), str) else None
        provider = None
        log_path = None
        if log_dir:
            directory = self._path(log_dir)
            # Both current adapters emit <role>-events.jsonl; identity header determines provider.
            candidate = directory / (role + '-events.jsonl')
            if self._allowed(candidate) and candidate.is_file():
                log_path = candidate
        raw_events = []
        log_issue = []
        if log_path:
            try:
                raw_events, _, _, _ = self._jsonl(log_path, max_bytes=65536)
            except ObserverError:
                log_issue.append(issue('transcript_unreadable', '调用日志暂不可读', ident))
            providers = {str(ev.get('type')) for _, ev, _ in raw_events}
            provider = 'codex' if 'thread.started' in providers else 'dsh' if providers & {'session', 'session_start', 'turn_start', 'turn_end', 'step_end', 'final'} else None
        art_refs = []
        availability = 'missing'
        if log_path:
            # A later call referencing this same path invalidates old ownership even if
            # the first complete line has not yet been written by the replacement.
            later = [e for e in events if e.get('kind') == 'worker_call' and e.get('seq', 0) > event['seq'] and e['body'].get('log_dir') == log_dir and e['body'].get('role') == role]
            header_ids = self._header_ids(raw_events)
            reused = bool(later) or self._log_reused_after(event, log_dir, role)
            if reused or not provider_id or not header_ids or provider_id not in header_ids:
                availability = 'unreadable'
                log_issue.append(issue('transcript_overwritten' if reused or (header_ids and provider_id not in header_ids) else 'transcript_unresolved', '调用日志已覆盖或无法确认归属；未将当前路径内容归入旧调用', ident))
            else:
                availability = 'available'
                art = self._register(log_path, phase='loop', owners=[dict(id=ident, label=role)])
                art_refs.append(ref(art))
        event_art = self._register(record=event, locator='events.seq=%s' % event['seq'], phase='onboard' if row.get('revision') == 'preparation' else 'loop', owners=[dict(id=ident, label=role)], title=role + ' · 调用回执')
        art_refs.append(ref(event_art))
        obj = dict(id=ident, run_id=self._id('run', row['run_id']), attempt_id=self._id('attempt', row['run_id'] + ':' + str(event['attempt_no'])) if event.get('attempt_no') is not None else None,
                   phase='onboard' if row.get('revision') == 'preparation' else 'loop', role=role, provider=provider,
                   provider_call_id=provider_id, parent_call_id=body.get('parent_call_id'),
                   state=state('finished' if body.get('ok') is True else 'failed' if body.get('ok') is False else 'unknown', str(body.get('ok')), event.get('at'), 'recorded'),
                   started_at=None, ended_at=event.get('at'), last_activity_at=None,
                   transcript_availability=availability, artifacts=art_refs, usage=None,
                   meta=meta([self._source(event_art)], [issue('call_start_unrecorded', '未记录调用开始时间', ident)] + log_issue, 'partial'))
        self.calls[ident] = obj
        self.call_sources[ident] = dict(path=log_path, provider_id=provider_id, availability=availability, event=event)
        return obj

    def _ensure_call(self, ident):
        if ident not in self.calls:
            for row in self._db(tables_to_read=('runs',))['runs']:
                self.run(self._id('run', row['run_id']))
                if ident in self.calls:
                    break
        if ident not in self.calls:
            raise ObserverError(404, 'not_found', '未知调用')
        self.run(self.calls[ident]['run_id'])
        return self.calls[ident]

    def call(self, ident):
        with self.lock:
            return self.envelope(self._ensure_call(ident))

    def _prefix(self, path, length):
        with path.open('rb') as stream:
            return stream.read(length)

    def _jsonl(self, path, start=0, max_items=None, max_bytes=None):
        if not self._allowed(path):
            raise ObserverError(404, 'path_denied', '调用日志超出允许范围')
        items, offset = [], start
        try:
            with path.open('rb') as stream:
                stat = __import__('os').fstat(stream.fileno())
                identity = '%s:%s' % (stat.st_dev, stat.st_ino)
                stream.seek(start)
                while max_items is None or len(items) < max_items:
                    line = stream.readline(max_bytes - (offset - start) if max_bytes is not None else -1)
                    if not line or not line.endswith(b'\n'):
                        break
                    try:
                        obj = json.loads(line)
                        if not isinstance(obj, dict):
                            obj = {'type': 'unknown', 'value': obj}
                    except (ValueError, UnicodeError):
                        obj = {'type': 'malformed', 'raw': line[:32768].decode('utf-8', 'replace')}
                    items.append((offset, obj, offset + len(line)))
                    offset += len(line)
                    if max_bytes is not None and offset - start >= max_bytes:
                        break
        except OSError:
            raise ObserverError(503, 'source_unreadable', '调用日志暂不可读') from None
        return items, identity, stat.st_size, offset

    @staticmethod
    def _header_ids(raw_events):
        ids = set()
        for _, ev, _ in raw_events:
            if ev.get('type') == 'thread.started' and isinstance(ev.get('thread_id'), str):
                ids.add(ev['thread_id'])
            if ev.get('type') in ('session', 'session_start', 'session.started', 'turn_start'):
                for key in ('sessionId', 'session_id', 'session', 'thread_id'):
                    if isinstance(ev.get(key), str):
                        ids.add(ev[key])
        return ids

    def _message_item(self, call, offset, event, log_artifact):
        typ = str(event.get('type') or 'unknown')
        item = event.get('item') if isinstance(event.get('item'), dict) else event
        subtype = item.get('type', typ)
        kind = 'unknown'
        text = None
        tool_id = None
        tool_name = None
        role = event.get('role')
        if subtype in ('agent_message', 'message', 'assistant_message', 'text', 'text_delta') or typ in ('message', 'message_delta', 'text_delta', 'final'):
            kind = 'message'
            role = role or 'assistant'
            text = item.get('text') or item.get('content') or event.get('delta')
            if isinstance(text, list):
                text = '\n'.join(p.get('text', '') for p in text if isinstance(p, dict))
        elif subtype in ('command_execution', 'mcp_tool_call', 'file_change') or typ in ('tool_call', 'tool_start', 'tool_result', 'tool_end'):
            kind = 'tool_result' if typ in ('item.completed', 'tool_result', 'tool_end') else 'tool_call'
            tool_id = item.get('id') or item.get('tool_call_id') or event.get('toolCallId') or event.get('callId')
            tool_name = item.get('name') or item.get('toolName') or item.get('tool') or item.get('tool_name') or ('shell' if subtype == 'command_execution' else subtype)
            text = item.get('aggregated_output') or item.get('output') or item.get('result') or item.get('command')
        elif 'error' in typ or typ in ('turn.failed',):
            kind = 'error'
            text = event.get('message') or json.dumps(event.get('error'), ensure_ascii=False)
        elif typ in ('thread.started', 'turn.started', 'turn.completed', 'session', 'session_start', 'turn_start', 'turn_end', 'step_end'):
            kind = 'activity'
            text = typ
        payload = event
        if len(json.dumps(event, ensure_ascii=False)) > 32768:
            payload = {'type': typ, 'truncated': True, 'artifact_id': log_artifact['id']}
        return dict(id=call['id'] + ':item:' + str(offset), call_id=call['id'], sequence=offset, at=event.get('timestamp') or event.get('at'),
                    kind=kind, role=role, text=str(text) if text is not None else None, tool_call_id=tool_id, tool_name=tool_name,
                    payload=payload, state=None, artifact_ids=[log_artifact['id']], source_refs=[self._source(log_artifact)])

    def messages(self, ident, cursor=None, limit=100):
        with self.lock:
            if not 1 <= limit <= 200:
                raise ObserverError(422, 'invalid_limit', 'limit 必须在 1–200 之间')
            call = self._ensure_call(ident)
            source = self.call_sources[ident]
            if source['availability'] != 'available' or not source['path']:
                if cursor:
                    raise ObserverError(409, 'transcript_identity_changed', '调用日志归属无法确认或已被其他调用覆盖')
                return self.envelope(dict(call_id=ident, items=[], reset=False, reset_reason=source['availability']))
            rows, identity, size, complete_offset = self._jsonl(source['path'], max_bytes=65536)
            header_ids = self._header_ids(rows)
            if source['provider_id'] not in header_ids:
                raise ObserverError(409, 'transcript_identity_changed', '调用日志归属已变化')
            start, reset, reset_reason = 0, False, None
            if cursor:
                try:
                    cur = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                    if cur['call'] != ident:
                        raise ValueError()
                    start = int(cur['offset'])
                    prefix_length = min(start, 128)
                    prefix = self._prefix(source['path'], prefix_length)
                    if cur['identity'] != identity or start > size or cur.get('prefix') != digest(prefix):
                        start, reset, reset_reason = 0, True, '调用日志被截断或替换，已重新读取属于此调用的内容'
                except (ValueError, KeyError, TypeError):
                    raise ObserverError(422, 'invalid_cursor', '无效调用内容游标') from None
            selected, identity, size, complete_offset = self._jsonl(source['path'], start=start, max_items=limit)
            artifact = self._register(source['path'], phase='loop', owners=[dict(id=ident, label=call['role'])])
            items = [self._message_item(call, offset, ev, artifact) for offset, ev, end in selected]
            next_offset = selected[-1][2] if selected else start
            next_cursor = base64.urlsafe_b64encode(json.dumps(dict(call=ident, identity=identity, offset=next_offset, prefix=digest(self._prefix(source['path'], min(next_offset, 128))))).encode()).decode()
            return self.envelope(dict(call_id=ident, items=items, reset=reset, reset_reason=reset_reason), next_cursor=next_cursor)

    def _markdown_links(self, path, text):
        from urllib.parse import unquote, urlsplit
        result = {}
        for href in re.findall(r'\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)', text):
            parts = urlsplit(href)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            candidate = (path.parent / unquote(parts.path)).absolute()
            resolved = candidate.resolve()
            task = next((t for t in self.tasks.values() if t.get('_path') == resolved), None)
            if task:
                result[href] = dict(kind='task', id=task['id'])
                continue
            existing = next((v['dto'] for v in self.artifact_registry.values() if v.get('path') and v['path'].resolve() == resolved and not v.get('call_owner')), None)
            evidence_root = self.root / '.opc/research/tasks'
            relative_parts = ()
            try:
                relative_parts = resolved.relative_to(evidence_root).parts
            except ValueError:
                pass
            is_evidence = len(relative_parts) >= 3 and relative_parts[1] == 'evidence'
            is_artifact = self.artifact_root.resolve() in resolved.parents
            if existing is None and (is_evidence or is_artifact) and self._allowed(candidate) and candidate.is_file():
                existing = self._register(candidate, phase='task' if is_evidence else 'other')
            if existing is not None:
                result[href] = dict(kind='artifact', id=existing['id'])
        return result

    def artifact(self, ident):
        with self.lock:
            if ident not in self.artifact_registry:
                # Deep links need discovery without filesystem-wide scanning.
                self._discover()
                if ident not in self.artifact_registry:
                    for row in self.run_rows:
                        self.run(self._id('run', row['run_id']))
                        if ident in self.artifact_registry:
                            break
            if ident not in self.artifact_registry:
                raise ObserverError(404, 'not_found', '未知产物 ID')
            item = self.artifact_registry[ident]
            if item.get('call_owner'):
                self._ensure_call(item['call_owner'])
                if self.call_sources[item['call_owner']]['availability'] != 'available':
                    raise ObserverError(409, 'transcript_identity_changed', '此产物所属调用的日志已覆盖或归属无法确认')
            if item.get('path'):
                old = item['dto']
                obj = self._register(item['path'], title=old['title'], phase=old['phase'], owners=old['owner_refs'])
            else:
                obj = item['dto']
            if obj['can_preview']:
                try:
                    raw = item['path'].read_bytes()[:32768] if item.get('path') else json.dumps(item['record'], ensure_ascii=False).encode()
                    obj['digest'] = digest(raw) if not item.get('path') or (obj['size_bytes'] is not None and obj['size_bytes'] <= 32768) else None
                    obj['digest_algorithm'] = 'sha256' if obj['digest'] else None
                    value = parsed(raw.decode('utf-8'), None)
                    if isinstance(value, dict):
                        selected = {k: value[k] for k in ('goal', 'title', 'summary', 'complete', 'promotable', 'selected_version', 'requirements', 'findings', 'outcome', 'reason') if k in value}
                        obj['key_facts'] = [dict(text=str(k) + ': ' + (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)), source_refs=[self._source(obj)]) for k, v in selected.items()]
                    elif obj['kind'] == 'md':
                        text = raw.decode('utf-8', 'replace')
                        obj['key_facts'] = [dict(text=line, source_refs=[self._source(obj)]) for line in text.splitlines() if line.strip()][:3]
                        obj['link_targets'] = self._markdown_links(item['path'], text)
                except (OSError, UnicodeError):
                    pass
            return self.envelope(obj)

    def artifact_bytes(self, ident):
        self.artifact(ident)
        entry = self.artifact_registry[ident]
        if entry.get('path'):
            path = entry['path']
            if not self._allowed(path):
                raise ObserverError(404, 'path_denied', '产物路径超出允许范围')
            try:
                return path.read_bytes()
            except OSError:
                raise ObserverError(503, 'source_unreadable', '产物暂不可读') from None
        return json.dumps(entry['record'], ensure_ascii=False, indent=2).encode()

    def content(self, ident, offset=0, limit=262144):
        with self.lock:
            if offset < 0 or not 1 <= limit <= 1048576:
                raise ObserverError(422, 'invalid_range', 'offset 或 limit 超出允许范围')
            raw = self.artifact_bytes(ident)
            if offset > len(raw):
                raise ObserverError(422, 'invalid_offset', 'offset 超出文件末尾')
            # Advance a partial leading codepoint to the next UTF-8 boundary.
            start = offset
            while start < len(raw) and raw[start] & 0xC0 == 0x80:
                start += 1
            end = min(start + limit, len(raw))
            while end > start and end < len(raw) and raw[end] & 0xC0 == 0x80:
                end -= 1
            if end == start and start < len(raw):
                # One codepoint is the smallest useful page even for limit=1.
                end = min(start + 1, len(raw))
                while end < len(raw) and raw[end] & 0xC0 == 0x80:
                    end += 1
            text = raw[start:end].decode('utf-8', 'replace')
            return self.envelope(dict(artifact_id=ident, content=text, encoding='utf-8', byte_offset=start,
                                      next_offset=end, eof=end >= len(raw), truncated=start > 0 or end < len(raw), content_version=digest(raw)))
