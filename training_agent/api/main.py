import logging
from contextlib import asynccontextmanager
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.config import setup_cors
from api.schemas.common import Response
from core.adapters import init_adapters
from core.config import settings
from core.exceptions import AppException, NotFoundException
from models.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    await init_db()
    init_adapters()
    yield


app = FastAPI(
    title="Training Agent API",
    description="Enterprise Training Agent Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)

setup_cors(app)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.code,
        content={"code": exc.code, "data": None, "msg": exc.message},
    )


@app.get("/health")
async def health_check():
    return Response(data={"status": "ok"})


from api.routers import auth, kb, docs, chat, stats, ppt, pdf, departments, sources, platform, agent

app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(departments.router, prefix="/api", tags=["departments"])
app.include_router(kb.router, prefix="/api/kb", tags=["knowledge_base"])
app.include_router(docs.router, prefix="/api/kb/{kb_id}/docs", tags=["documents"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(platform.router, prefix="/api", tags=["platform"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(agent.router, prefix="/api", tags=["agent"])
app.include_router(stats.router, prefix="/api/stats", tags=["statistics"])
app.include_router(ppt.router, prefix="/api", tags=["ppt"])
app.include_router(pdf.router, prefix="/api", tags=["pdf"])
