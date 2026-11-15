"""Topic observation HTTP boundary; every GET is read-only."""
from pathlib import Path
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .adapter import ObserverAdapter, ObserverError


def create_app(root: Path | str, demo=False, *, control=False, topics=None):
    adapter = ObserverAdapter(root, demo=demo, topics=topics)
    app = FastAPI(title='ArcHa Workbench', docs_url=None, redoc_url=None)
    app.state.adapter = adapter
    prefix = '/api/observer/v1'

    @app.exception_handler(ObserverError)
    async def observer_error(request, exc):
        return JSONResponse(status_code=exc.status, content={'error': {'code': exc.code, 'message': exc.message}})

    @app.exception_handler(ValueError)
    @app.exception_handler(OSError)
    async def source_error(request, exc):
        return JSONResponse(status_code=409, content={'error': {'code': 'source_error', 'message': str(exc)}})

    @app.middleware('http')
    async def safety_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.get(prefix + '/topics')
    def topics_list():
        return adapter.overview()

    @app.get(prefix + '/topics/{topic}')
    def topic_detail(topic: str):
        return adapter.detail(topic)

    @app.get(prefix + '/materials')
    def material(path: str, offset: int = Query(0, ge=0), limit: int = Query(262144, ge=1, le=1048576)):
        return adapter.content(path, offset, limit)

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
