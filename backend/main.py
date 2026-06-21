from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.routes import account, admin, analyze, regime, report, scanner#,signals
from config.settings import settings
from database.store import init_db, record_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("trading_desk.api")

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Trading Desk OS monetizable API: analysis, scanner, regime, reports, usage metering, and API-key auth.",
)

origins = ["*"] if settings.cors_allow_origins == "*" else [x.strip() for x in settings.cors_allow_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    logger.info("Trading Desk OS API started | db=%s", settings.db_path)


@app.middleware("http")
async def request_logger(request: Request, call_next: Callable):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    t0 = time.perf_counter()
    status_code = 500
    error = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        error = str(exc)
        logger.exception("Unhandled API error request_id=%s", request_id)
        return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})
    finally:
        latency_ms = (time.perf_counter() - t0) * 1000
        try:
            record_request(
                request_id=request_id,
                endpoint=f"{request.method} {request.url.path}",
                user_id=getattr(request.state, "user_id", None),
                status_code=status_code,
                latency_ms=latency_ms,
                error=error,
            )
        except Exception:
            logger.exception("Failed to record request")


@app.get("/health", tags=["system"])
def health():
    return {"ok": True, "app": settings.app_name, "environment": settings.environment}


app.include_router(account.router)
app.include_router(admin.router)
app.include_router(analyze.router)
app.include_router(scanner.router)
app.include_router(report.router)
app.include_router(regime.router)
#app.include_router(signals.router)

