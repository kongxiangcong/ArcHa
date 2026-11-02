"""Explicit local control boundary; GET paths never construct a writable Ledger."""
from __future__ import annotations

import ipaddress
import json
import sqlite3
import os
import subprocess
import sys
from urllib.parse import urlsplit

from .adapter import ObserverError, mapping


def read_requests(adapter, run_id=None, request_id=None):
    path = adapter.root / '.opc/local/ledger.sqlite3'
    if not path.is_file() or not adapter._allowed(path):
        return None
    try:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.5) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_requests'").fetchone():
                return None
            if request_id is not None:
                row = db.execute('SELECT * FROM control_requests WHERE request_id=?' + (' AND run_id=?' if run_id is not None else ''), (request_id, run_id) if run_id is not None else (request_id,)).fetchone()
            else:
                row = db.execute('SELECT * FROM control_requests WHERE run_id=? ORDER BY accepted_seq DESC LIMIT 1', (run_id,)).fetchone()
            if row is None:
                return None
            record = dict(row)
            record['_run'] = dict(db.execute('SELECT * FROM runs WHERE run_id=?', (record['run_id'],)).fetchone())
            owner = db.execute("SELECT run_id,kind,body FROM events WHERE kind IN ('control_execution_started','controller_started','controller_finished') ORDER BY seq DESC LIMIT 1").fetchone()
            record['_executor'] = dict(owner) if owner else None
            return record
    except sqlite3.Error:
        raise ObserverError(503, 'control_unreadable', '运行控制反馈暂不可读；未改变运行结果') from None


def unavailable_reason(adapter, row):
    reason = ('演示模式仅供查看' if adapter.demo else '当前服务为只读模式' if not adapter.control_enabled else
              '历史快照不能执行控制' if row.get('_snapshot') else
              '运行已经结束' if row.get('state') == 'closed' else None)
    run_dir = adapter._run_dir(row)
    if reason is None and not (run_dir and all((run_dir / 'frozen' / name).is_file() for name in ('task.json', 'component.json', 'baseline.json'))):
        reason = '此运行缺少可执行的保存配置，仅供查看'
    if reason is None:
        execution = mapping(mapping(adapter._read(run_dir / 'frozen/baseline.json', json_file=True, default={})).get('execution'))
        workers = mapping(execution.get('workers'))
        if not execution or not workers or any(spec.get('kind') != 'scripted' and not spec.get('frozen_config') for spec in workers.values()):
            reason = '历史运行缺少可靠执行配置，仅供查看'
        elif any(spec.get('kind') == 'codex' and not spec.get('native_defaults_frozen') for spec in workers.values()):
            reason = '历史运行缺少原执行环境，仅供查看'
    return reason


def capability(adapter, row):
    reason = unavailable_reason(adapter, row)
    latest = read_requests(adapter, row['run_id']) if adapter.control_enabled and reason is None else None
    if latest:
        row = latest['_run']
    pending = latest and latest['status'] in ('accepted', 'processing', 'unknown')
    unknown = any(c.get("state") == "unknown" or c.get("result") is None for c in adapter._db(row["run_id"], tables_to_read=("calls",))["calls"])
    resuming = latest and latest['action'] == 'resume' and latest['status'] in ('accepted', 'processing')
    return dict(pause=dict(enabled=reason is None and (resuming or (not pending and row.get('state') != 'paused')),
                           reason=reason or ('暂停结果尚待确认' if pending else '运行已暂停' if row.get('state') == 'paused' else '可请求暂停，已派发调用将正常收尾')),
                resume=dict(enabled=reason is None and not pending and not unknown and row.get('state') in ('paused', 'blocked'), reason=reason or ('仍有执行结果待确认，不能继续' if unknown else '控制请求尚待确认' if pending else '继续同一运行，保留已保存结果')),
                stop=dict(enabled=reason is None and not (latest and latest['action'] == 'stop' and pending), reason=reason or '停止当前运行，保留已有工作与结果'))


def view(adapter, row, record):
    row = record.get('_run', row)
    calls = adapter._db(row['run_id'], tables_to_read=('calls',))['calls']
    unknown = any(c.get('state') == 'unknown' or (row['state'] != 'active' and c.get('result') is None) for c in calls)
    return dict(request_id=record['request_id'], run_id=adapter._id('run', row['run_id']), action=record['action'],
                status=record['status'], sequence=record['accepted_seq'], reason=record['reason'], created_at=record['created_at'], updated_at=record['updated_at'],
                run=dict(state=row['state'], execution_unknown=unknown))


def validate_write(request):
    host = request.headers.get('host', '')
    try:
        parsed = urlsplit('http://' + host)
        local = parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname).is_loopback
        valid = local and parsed.path == '' and parsed.username is None and parsed.password is None and (parsed.port is None or 1 <= parsed.port <= 65535)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ObserverError(403, 'host_denied', '控制请求仅接受合法的本机地址')
    origin = request.headers.get('origin')
    if origin != str(request.base_url).rstrip('/') or request.headers.get('sec-fetch-site') in ('cross-site', 'same-site'):
        raise ObserverError(403, 'origin_denied', '控制请求必须来自同一工作台地址')
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise ObserverError(415, 'json_required', '控制请求必须使用 JSON')


class ControlService:
    def __init__(self, adapter):
        self.adapter = adapter
        self.children = {}
        adapter.control_service = self

    def target(self, ident):
        if not self.adapter.control_enabled:
            raise ObserverError(403, 'control_disabled', '此服务未启用运行控制')
        rows = self.adapter._db(tables_to_read=('runs',))['runs']
        row = next((row for row in rows if self.adapter._id('run', row['run_id']) == ident), None)
        if row is None:
            raise ObserverError(404, 'not_found', '目标运行不可用')
        return row

    def query(self, ident, request_id):
        with self.adapter.lock:
            row = self.target(ident)
            record = read_requests(self.adapter, row['run_id'], request_id)
            if record is None:
                raise ObserverError(404, 'request_not_found', '未找到本次控制请求；未自动重新提交')
            return self.adapter.envelope(self.observe(row, record))

    def observe(self, row, record):
        result = view(self.adapter, row, record)
        child = self.children.get(record['request_id'])
        if child and child.poll() is not None:
            self.children.pop(record['request_id'], None)
            child = None
        if record['action'] in ('resume', 'stop') and record['status'] in ('accepted', 'processing') and child is None:
            from ..core.platform import lock_writer, unlock_writer
            path = self.adapter.root / '.opc/local/ledger.lock'
            fd = os.open(path, os.O_RDWR) if path.exists() else None
            if fd is None:
                result.update(status='unknown', reason='尚未确认本次执行或结束情况；不会自动再次启动')
                return result
            try:
                try:
                    lock_writer(fd)
                except BlockingIOError:
                    owner = record.get('_executor')
                    owner_body = json.loads(owner['body']) if owner else {}
                    if not owner or owner['run_id'] != record['run_id'] or owner['kind'] == 'controller_finished' or (record['action'] == 'resume' and owner_body.get('request_id') != record['request_id']):
                        result.update(status='unknown', reason='尚未确认本次执行情况；项目占用不代表本次执行仍在进行，不会自动再次启动')
                else:
                    unlock_writer(fd)
                    result.update(status='unknown', reason='尚未确认本次执行或结束情况；不会自动再次启动')
            finally:
                os.close(fd)
        if result['action'] == 'resume' and result['status'] == 'applied':
            if result['run']['state'] == 'closed':
                result['reason'] = '原运行已结束，未创建新运行'
            elif result['run']['state'] == 'blocked':
                result['reason'] = '原运行需要处理，已保存工作保留'
        return result

    def launch(self, row, request_id):
        for identity, process in list(self.children.items()):
            if process.poll() is not None:
                self.children.pop(identity)
        options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        if os.name == 'nt':
            options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            options['start_new_session'] = True
        child = subprocess.Popen([sys.executable, '-m', 'opc.observer.runner', '--project', str(self.adapter.root),
                                  '--run-id', row['run_id'], '--request-id', request_id], **options)
        self.children[request_id] = child

    def submit(self, ident, request_id, action):
        from ..core.ledger import Ledger
        with self.adapter.lock:
            row = self.target(ident)
            existing = read_requests(self.adapter, request_id=request_id)
            if existing:
                if existing['action'] != action or existing['run_id'] != row['run_id']:
                    raise ObserverError(409, 'request_conflict', '同一请求身份不能更换动作或目标运行')
                return self.adapter.envelope(self.observe(row, existing)), False
            if action not in ('pause', 'resume', 'stop'):
                raise ObserverError(409, 'action_unavailable', '此入口暂不提供该控制动作')
            reason = unavailable_reason(self.adapter, row)
            if action == 'stop' and row['state'] == 'closed':
                reason = None
            if reason:
                raise ObserverError(409 if row.get('state') == 'closed' else 403, 'control_unavailable', reason)
            if row.get('state') not in ('active', 'paused', 'blocked') and not (action == 'stop' and row['state'] == 'closed'):
                raise ObserverError(409, 'state_conflict', '此运行状态不能接收暂停请求')
            path = self.adapter.root / '.opc/local/ledger.sqlite3'
            if not path.is_file() or not self.adapter._allowed(path):
                raise ObserverError(403, 'control_unavailable', '此运行没有可控制的项目记录')
            ledger = None
            try:
                ledger = Ledger(path, timeout=.5)
                already_running = False
                if action == 'resume' and row['state'] == 'active':
                    latest = ledger.db.execute("SELECT run_id,kind FROM events WHERE kind IN ('controller_started','controller_finished') ORDER BY seq DESC LIMIT 1").fetchone()
                    from ..core.model import OPCError
                    try:
                        with ledger.writer():
                            pass
                    except OPCError as error:
                        if not str(error).startswith('another controller holds '):
                            raise
                        already_running = bool(latest and latest['run_id'] == row['run_id'] and latest['kind'] == 'controller_started' and ledger.control(row['run_id']) == 'run')
                record, created = ledger.accept_control_request(row['run_id'], request_id, action, already_running=already_running)
                if created and action in ('resume', 'stop') and record['status'] == 'accepted':
                    try:
                        launch = True
                        if action == 'stop':
                            from ..core.model import OPCError
                            try:
                                with ledger.writer():
                                    pass
                            except OPCError as error:
                                if not str(error).startswith('another controller holds '):
                                    raise
                                launch = False
                                owner = ledger.db.execute("SELECT run_id,kind FROM events WHERE kind IN ('controller_started','controller_finished','control_execution_started') ORDER BY seq DESC LIMIT 1").fetchone()
                                if not owner or owner['run_id'] != row['run_id'] or owner['kind'] == 'controller_finished':
                                    ledger.finish_control_request(request_id, 'failed', '项目由其他运行端占用，未启动第二个执行者')
                        if launch:
                            self.launch(row, request_id)
                    except OSError as error:
                        ledger.event(row['run_id'], 'control_execution_failed', request_id=request_id,
                                     action=action, error_type=type(error).__name__, error=str(error))
                        ledger.finish_control_request(request_id, 'failed', ('停止' if action == 'stop' else '恢复') + '进程未能启动，原有工作保留')
                    record = dict(ledger.db.execute('SELECT * FROM control_requests WHERE request_id=?', (request_id,)).fetchone())
                elif action == 'pause' and record['status'] == 'accepted':
                    from ..core.model import OPCError
                    try:
                        with ledger.writer():
                            # No controller owns this project. Do not infer an old pause was applied.
                            ledger.finish_control_request(request_id, 'unknown', '尚未确认有运行端处理本次暂停；不会自动重新提交')
                    except OPCError as error:
                        if not str(error).startswith('another controller holds '):
                            raise
                    record = dict(ledger.db.execute('SELECT * FROM control_requests WHERE request_id=?', (request_id,)).fetchone())
                row = dict(ledger.run(row['run_id']))
            except ValueError as error:
                raise ObserverError(409, str(error), '请求身份或目标状态与已保存事实冲突') from None
            except sqlite3.Error:
                raise ObserverError(503, 'control_write_failed', '控制请求未能保存，请查询本次请求结果后再决定下一步') from None
            finally:
                if ledger:
                    ledger.close()
            return self.adapter.envelope(self.observe(row, record)), created
