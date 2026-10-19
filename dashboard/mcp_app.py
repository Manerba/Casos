"""Eigenstaendiger Casos-Agentendienst, Port 8516, ohne Web-/Admin-Oberflaeche."""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
import uvicorn

from dashboard.agent_guide import build_agent_metadata, build_agent_guide_markdown
from dashboard.api_attachments import router as attachments_router
from dashboard.errors import ApplicationError
from dashboard.auth import get_file_user, get_mcp_user
from dashboard.mcp_transport import install_mcp, mcp_lifespan, api_csrf_protection
from dashboard.tls_utils import get_tls_config


app = FastAPI(title="Casos MCP", lifespan=mcp_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
install_mcp(app, dedicated=True)
app.include_router(attachments_router)
# Middleware prueft MCP-Bearer vor dem Body; Dependency prueft danach erneut.
app.dependency_overrides[get_file_user] = get_mcp_user
app.middleware("http")(api_csrf_protection)


@app.exception_handler(ApplicationError)
async def application_error(request, exc):
    body = {"detail": exc.detail, "code": exc.code}
    if exc.field:
        body["field"] = exc.field
    if exc.fields:
        body["fields"] = exc.fields
    return JSONResponse(body, status_code=exc.status_code)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    return response


@app.get("/.well-known/casos-agent.json")
async def agent_metadata(request: Request):
    return build_agent_metadata(request, mcp_base_url=str(request.base_url).rstrip("/"))


@app.get("/agent-guide.md", response_class=PlainTextResponse)
async def agent_guide(request: Request):
    return PlainTextResponse(build_agent_guide_markdown(await agent_metadata(request)), media_type="text/markdown; charset=utf-8")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(levelname)s %(message)s")
    tls = get_tls_config()
    kwargs = {"host": os.environ.get("CASOS_HOST", "0.0.0.0"), "port": int(os.environ.get("CASOS_MCP_PORT", "8516"))}
    if tls and tls["enabled"]:
        kwargs.update(ssl_certfile=tls["cert_path"], ssl_keyfile=tls["key_path"])
    uvicorn.run(app, **kwargs)


if __name__ == "__main__":
    main()
