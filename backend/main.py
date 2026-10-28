"""Authenticated local paper-trading API. Run migrations before starting."""
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from backend.config import config
from backend.database import session_dependency
from backend.models import User
from backend.worker import Worker
from backend.managed_api import router as managed_router
from backend.xrp_chart import router as chart_router, ticker as chart_ticker
from backend.coinbase_account import router as coinbase_account_router
from backend.google_auth import router as google_auth_router

from backend.routes.legacy import router as legacy_router
from backend.routes.auth import router as auth_router
from backend.routes.dashboard import router as dashboard_router

worker = Worker()


@asynccontextmanager
async def lifespan(app):
    if config.worker_enabled:
        worker.start()
        chart_ticker.start()
    yield
    worker.stop()
    chart_ticker.stop()


app = FastAPI(title="Crypto Agent · Paper only", version="1.0.0", lifespan=lifespan)
app.include_router(managed_router)
app.include_router(chart_router)
app.include_router(coinbase_account_router)
app.include_router(google_auth_router)
app.include_router(auth_router)
app.include_router(legacy_router)
app.include_router(dashboard_router)
app.add_middleware(CORSMiddleware, allow_origins=[config.allowed_origin], allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT"], allow_headers=["Content-Type", "X-Requested-With"])


@app.middleware("http")
async def browser_security(request: Request, call_next):
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        origin = request.headers.get("origin")
        if origin and origin != config.allowed_origin:
            return JSONResponse({"detail": "Origin not allowed."}, status_code=403)
        if request.cookies.get("crypto_session") and request.headers.get("x-requested-with") != "CryptoAgent":
            return JSONResponse({"detail": "Missing CSRF request header."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health")
def health(db=Depends(session_dependency)):
    db.execute(select(User.id).limit(1))  # Missing migrations should fail readiness.
    return {"status": "ok", "mode": "paper", "worker_active_in_this_process": worker.active}
