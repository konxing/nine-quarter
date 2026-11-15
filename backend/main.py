"""FastAPI 应用入口：启动初始化数据库、账户、调度器；挂载查询 API。

运行：uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .ai_config import apply_ai_overrides, load_ai_overrides
from .api import router
from .config import settings
from .db import connect, init_db
from .logging_setup import setup_logging
from .scheduler.jobs import shutdown_scheduler, start_scheduler
from .simulation.account import ensure_account

log = logging.getLogger("nine-quarter.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    setup_logging(settings.logs_dir)
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    try:
        ensure_account(conn, settings.initial_capital)
        # 页面内保存的 AI 配置优先于 .env，启动调度器前生效
        apply_ai_overrides(settings, load_ai_overrides(conn))
    finally:
        conn.close()
    start_scheduler(settings)
    log.info("nine-quarter 后端就绪，数据库 %s", settings.db_path)
    yield
    shutdown_scheduler()


app = FastAPI(title="nine-quarter", version="2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3100", "http://127.0.0.1:3100"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
def root():
    return {"name": "nine-quarter", "docs": "/docs", "api": "/api/status"}