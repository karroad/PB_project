import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .ai.llm import get_provider
from .api import admin, auth, domains, jobs, public, websites
from .config import settings
from .errors import PipelineError
from .events import bus
from .init_db import init_db
from .monitoring.monitor import monitor_loop
from .orchestrator.queue import queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("siteforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await bus.start()
    tasks = []
    if settings.RUN_EMBEDDED_WORKER:
        await queue.start(settings.MAX_CONCURRENT_JOBS)
    if settings.RUN_MONITOR:
        tasks.append(asyncio.create_task(monitor_loop()))
    log.info("SiteForge ready — AI: %s · queue: %s · workers: %s", get_provider().name, queue.backend,
             settings.MAX_CONCURRENT_JOBS if settings.RUN_EMBEDDED_WORKER else "external")
    yield
    for t in tasks:
        t.cancel()
    await queue.stop()
    await bus.stop()


app = FastAPI(title="SiteForge AI", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.FRONTEND_ORIGIN, "http://127.0.0.1:3000"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


_PLATFORM_HOSTS = {"localhost", "127.0.0.1", "testserver", (urlparse(settings.PUBLIC_BASE_URL).hostname or "").lower(),
                   (urlparse(settings.FRONTEND_ORIGIN).hostname or "").lower(), settings.SERVER_PUBLIC_IP}


@app.middleware("http")
async def custom_domain_router(request: Request, call_next):
    """Serve locally hosted sites on their own domains: Host: example.com → /sites/<slug>/..."""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    path = request.scope["path"]
    if host and host not in _PLATFORM_HOSTS and not path.startswith(("/api/", "/sites/", "/preview/", "/docs", "/openapi")):
        slug = public.slug_for_host(host)
        if slug:
            request.scope["path"] = f"/sites/{slug}{path if path.startswith('/') else '/' + path}"
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    return JSONResponse({"error": {"code": f"http_{exc.status_code}", "message": exc.detail}}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errs = [{"field": ".".join(str(x) for x in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    msg = "; ".join(f"{e['field']}: {e['message']}" for e in errs)
    return JSONResponse({"error": {"code": "validation_error", "message": msg, "fields": errs}}, status_code=422)


@app.exception_handler(PipelineError)
async def pipeline_error(_: Request, exc: PipelineError):
    return JSONResponse({"error": exc.to_dict()}, status_code=400)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled API error")
    return JSONResponse({"error": {"code": "internal_error", "message": "Internal server error — the incident was logged."}}, status_code=500)


@app.get("/api/health")
async def health():
    return {"ok": True, "ai_provider": get_provider().name, "queue": await queue.stats(), "sandbox": settings.SANDBOX_PROVIDERS}


for r in (auth.router, websites.router, domains.router, jobs.router, admin.router, public.router):
    app.include_router(r)
