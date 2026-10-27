"""Local GET-only observer HTTP boundary and static application hosting."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .adapter import ObserverAdapter, ObserverError

from .models import (Envelope, Overview, ResearchDetail, RevisionDetail, Run, Attempt,
                     Call, CallContent, Artifact, ArtifactContent)


def create_app(root: Path | str, demo=False):
    adapter = ObserverAdapter(root, demo=demo)
    app = FastAPI(title='ArcHa Read-only Observer', version='1.0', docs_url=None, redoc_url=None)
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

    @app.get(prefix + '/runs/{ident}/attempts/{number}', response_model=Envelope[Attempt])
    def attempt(ident: str, number: int = 1):
        return adapter.attempt(ident, number)

    @app.get(prefix + '/calls/{ident}', response_model=Envelope[Call])
    def call(ident: str):
        return adapter.call(ident)

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
