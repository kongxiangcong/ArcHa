"""Local observer HTTP boundary with explicitly enabled run control."""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .adapter import ObserverAdapter, ObserverError

from .models import (Envelope, Overview, ResearchDetail, RevisionDetail, Run, Attempt,
                     Call, CallContent, Artifact, ArtifactContent, Workbench, WorkItems, CallActivity, Inspection, ControlRequestView)


class LogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str | None = None


class ControlInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    action: Literal['pause', 'resume', 'stop']


def create_app(root: Path | str, demo=False, *, control=False, topics=None):
    adapter = ObserverAdapter(root, demo=demo, topics=topics)
    adapter.control_enabled = bool(control and not demo)
    from .control import ControlService, validate_write
    controller = ControlService(adapter)
    app = FastAPI(title='ArcHa Workbench', version='1.0', docs_url=None, redoc_url=None)
    app.state.adapter = adapter
    prefix = '/api/observer/v1'

    def error(status, code, message):
        return JSONResponse(status_code=status, content={'schema_version': '1.0', 'error': {'code': code, 'message': message}})

    @app.exception_handler(ObserverError)
    async def observer_error(request, exc):
        return error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(422, 'invalid_parameter', '请求参数无效，请检查类型和允许范围')

    @app.exception_handler(ResponseValidationError)
    async def unsupported_response(request, exc):
        return error(503, 'source_unsupported', '本次来源字段与观察合同不兼容；未迁移或修复源数据')

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(exc.status_code, 'not_found' if exc.status_code == 404 else 'method_not_allowed' if exc.status_code == 405 else 'http_error', '未找到资源' if exc.status_code == 404 else '此资源只提供读取接口')

    @app.middleware('http')
    async def safety_headers(request: Request, call_next):
        if request.method == 'POST' and request.url.path.startswith('/api/control/v1/'):
            try:
                validate_write(request)
            except ObserverError as exc:
                return error(exc.status, exc.code, exc.message)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.get(prefix + '/overview', response_model=Envelope[Overview])
    def overview():
        return adapter.overview()

    @app.get(prefix + '/research-tasks/{ident}', response_model=Envelope[ResearchDetail])
    def research_task(ident: str):
        return adapter.research_task(ident)

    @app.get(prefix + '/task-revisions/{ident}', response_model=Envelope[RevisionDetail])
    def task_revision(ident: str):
        return adapter.task_revision(ident)

    @app.get(prefix + '/runs/{ident}', response_model=Envelope[Run])
    def run(ident: str):
        return adapter.run(ident)

    @app.get(prefix + '/runs/{ident}/workbench', response_model=Envelope[Workbench])
    def workbench(ident: str):
        return adapter.workbench(ident)

    @app.get(prefix + '/runs/{ident}/work-items', response_model=Envelope[WorkItems])
    def work_items(ident: str, cursor: str | None = None, limit: int = Query(100, ge=1, le=200), scope: str = 'all'):
        return adapter.work_items(ident, cursor, limit, scope)

    @app.get(prefix + '/runs/{ident}/attempts/{number}', response_model=Envelope[Attempt])
    def attempt(ident: str, number: int = 1):
        return adapter.attempt(ident, number)

    @app.get(prefix + '/runs/{ident}/attempts/{number}/inspection', response_model=Envelope[Inspection])
    def inspection(ident: str, number: int, call: str | None = None):
        return adapter.inspection(ident, number, call)

    @app.get(prefix + '/calls/{ident}', response_model=Envelope[Call])
    def call(ident: str):
        return adapter.call(ident)

    @app.get(prefix + '/calls/{ident}/activity', response_model=Envelope[CallActivity])
    def activity(ident: str, cursor: str | None = None, limit: int = Query(100, ge=1, le=200)):
        return adapter.activity(ident, cursor, limit)

    @app.get(prefix + '/calls/{ident}/messages', response_model=Envelope[CallContent])
    def messages(ident: str, cursor: str | None = None, limit: int = Query(100, ge=1, le=200)):
        return adapter.messages(ident, cursor, limit)

    @app.get(prefix + '/artifacts/{ident}', response_model=Envelope[Artifact])
    def artifact(ident: str):
        return adapter.artifact(ident)

    @app.get(prefix + '/artifacts/{ident}/content', response_model=Envelope[ArtifactContent])
    def content(ident: str, offset: int = Query(0, ge=0), limit: int = Query(262144, ge=1, le=1048576), download: int = Query(0, ge=0, le=1)):
        if download:
            item = adapter.artifact(ident)['data']
            if not item['can_download']:
                raise ObserverError(404, 'download_unavailable', '该产物没有可下载的文件')
            # Always attachment, never execute a registered HTML/SVG as a page.
            return Response(adapter.artifact_bytes(ident), media_type='application/octet-stream',
                            headers={'Content-Disposition': "attachment; filename=artifact.bin"})
        return adapter.content(ident, offset, limit)

    @app.post('/api/control/v1/runs/{ident}/requests', response_model=Envelope[ControlRequestView], responses={202: {'model': Envelope[ControlRequestView]}})
    def submit_control(ident: str, body: ControlInput, request: Request):
        result, created = controller.submit(ident, body.request_id, body.action)
        return JSONResponse(status_code=202 if created else 200, content=result)

    @app.get('/api/control/v1/runs/{ident}/requests/{request_id}', response_model=Envelope[ControlRequestView])
    def query_control(ident: str, request_id: str):
        return controller.query(ident, request_id)

    @app.get(prefix + '/runs/{ident}/research-log')
    def research_log(ident: str):
        from ..log import read
        import sqlite3
        row = adapter._find_run(ident)
        enabled = bool(adapter.control_enabled and not adapter.demo and not row.get('_preparation') and not row.get('_snapshot'))
        try:
            value = read(adapter.root, row['run_id'])
        except (ValueError, OSError, sqlite3.Error) as exc:
            value = dict(path=None, content='', added=0, reason=str(exc))
            enabled = False
        return adapter.envelope(dict(value, can_update=enabled))

    @app.post('/api/control/v1/runs/{ident}/research-log')
    def update_research_log(ident: str, body: LogInput):
        import json
        import os
        import subprocess
        import sys
        if not adapter.control_enabled or adapter.demo:
            raise ObserverError(403, 'log_read_only', '当前工作台仅可查看日志，未启用写入')
        row = adapter._find_run(ident)
        if row.get('_preparation') or row.get('_snapshot'):
            raise ObserverError(409, 'log_unavailable', '请先选择已有账本记录的正式 Run')
        env = dict(os.environ)
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2]) + os.pathsep + env.get('PYTHONPATH', '')
        command = [sys.executable, '-m', 'opc.log', '--project', str(adapter.root), '--run-id', row['run_id']]
        if body.timezone:
            command += ['--timezone', body.timezone]
        result = subprocess.run(command, cwd=adapter.root, env=env, capture_output=True, text=True)
        try:
            value = json.loads(result.stdout)
        except ValueError:
            raise ObserverError(502, 'log_failed', '日志脚本未返回有效结果，已有日志保留') from None
        if result.returncode:
            raise ObserverError(409, 'log_failed', value.get('error', '日志更新失败'))
        return adapter.envelope(dict(value, can_update=True))

    # Unknown API routes must not fall through to SPA HTML.
    @app.get('/api/{unknown:path}')
    def unknown_api(unknown: str):
        raise ObserverError(404, 'not_found', '未知观察接口')

    static = Path(__file__).parent / 'static'
    if (static / 'index.html').is_file():
        app.mount('/', StaticFiles(directory=static, html=True), name='observer-web')
    else:
        @app.get('/')
        def missing_frontend():
            return Response('Observer frontend not built. Run: cd web && npm ci && npm run build', media_type='text/plain', status_code=503)
    return app
