"""Casos: flat issues, browser API and MCP on port 8514."""
import logging
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from dashboard.api_auth import router as auth_router
from dashboard.api_issues import router as issues_router
from dashboard.api_mail import mail_user_router
from dashboard.auth import _extract_user_from_request, get_current_user
from dashboard.errors import ApplicationError
from dashboard.agent_guide import build_agent_metadata, build_agent_guide_markdown
from dashboard.mcp_transport import api_csrf_protection, install_mcp, mcp_lifespan
from dashboard.tls_utils import get_tls_config

app = FastAPI(title='Casos', lifespan=mcp_lifespan)
app.include_router(auth_router)
app.include_router(issues_router)
app.include_router(mail_user_router)
install_mcp(app)
app.middleware('http')(api_csrf_protection)
root = Path(__file__).parent
app.mount('/static', StaticFiles(directory=root / 'static'), name='static')


@app.exception_handler(ApplicationError)
async def application_error(request, exc):
    body = {'detail': exc.detail, 'code': exc.code}
    if exc.field:
        body['field'] = exc.field
    if exc.fields:
        body['fields'] = exc.fields
    return JSONResponse(body, status_code=exc.status_code)


@app.middleware('http')
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
    if request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache'
    elif request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/dashboard/info')
async def dashboard_info(user=Depends(get_current_user)):
    return {'version': (root.parent / 'version.txt').read_text().strip(), 'title': 'Casos',
            'description': 'Issues, Updates und lokale Anhänge',
            'components': ['FastAPI', 'SQLite', 'Vanilla JS', 'Markdown', 'MCP']}


@app.get('/.well-known/casos-agent.json')
async def agent_metadata(request: Request):
    return build_agent_metadata(request)


@app.get('/agent-guide.md', response_class=PlainTextResponse)
async def agent_guide(request: Request):
    return PlainTextResponse(build_agent_guide_markdown(build_agent_metadata(request)), media_type='text/markdown; charset=utf-8')


@app.get('/login')
async def login_page():
    return FileResponse(root / 'templates/login.html')


@app.get('/')
@app.get('/issues/{issue_id:int}')
async def index(request: Request):
    if not _extract_user_from_request(request):
        return RedirectResponse('/login', status_code=302)
    return FileResponse(root / 'templates/index.html')


def main():
    logging.basicConfig(level=logging.INFO)
    tls = get_tls_config()
    kwargs = {'host': os.environ.get('CASOS_HOST', '0.0.0.0'), 'port': int(os.environ.get('CASOS_PORT', '8514'))}
    if tls and tls['enabled']:
        kwargs.update(ssl_certfile=tls['cert_path'], ssl_keyfile=tls['key_path'])
    uvicorn.run(app, **kwargs)


if __name__ == '__main__':
    main()
