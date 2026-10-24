"""Authenticated local paper-trading API. Run migrations before starting."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from argon2.exceptions import VerificationError, InvalidHashError
from backend.auth import current_user, issue_session, passwords, rate_limit, _dummy_hash, is_guest
from backend.config import config
from backend.database import session_dependency
from backend.models import User, AuthSession, AgentSettings, RiskSettings, PaperBalance, PaperPosition, MarketSnapshot, ExecutionLog
from backend.schemas import Credentials, SettingsInput, ChatInput
from backend import views
from backend.chat import answer
from backend.worker import Worker
from src.prediction import load_approved
from backend.managed_api import router as managed_router
from backend.xrp_chart import router as chart_router, ticker as chart_ticker

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


@app.post("/auth/register", status_code=201)
def register(body: Credentials, request: Request, response: Response, db=Depends(session_dependency)):
    rate_limit(request)
    user = User(username=body.username.lower(), password_hash=passwords.hash(body.password))
    db.add(user)
    try:
        db.flush()
        db.add_all([
            AgentSettings(user_id=user.id, fee_rate=config.estimated_fee_rate, slippage_rate=config.estimated_slippage_rate),
            RiskSettings(user_id=user.id, max_trades_per_day=config.max_trades_per_day,
                         max_position_usdc=config.max_position_usdc, max_daily_loss_usdc=config.max_daily_loss_usdc),
            PaperBalance(user_id=user.id, usdc=config.initial_paper_balance_usdc, initial_usdc=config.initial_paper_balance_usdc),
            PaperPosition(user_id=user.id, product="XRP-USDC"),
        ])
        issue_session(db, user, response)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username unavailable.") from None
    return {"id": user.id, "username": user.username}


@app.post('/auth/guest')
def guest(request: Request, response: Response, db=Depends(session_dependency)):
    """Open the dashboard without credentials, retaining browser session isolation."""
    try:
        user = current_user(request, db)
        return {'id': user.id, 'username': user.username, 'guest': is_guest(user)}
    except HTTPException as error:
        if error.status_code != 401:
            raise
    rate_limit(request, category='guest', maximum=10)
    import secrets
    user = User(username='guest_'+secrets.token_hex(16), password_hash='!guest')
    db.add(user)
    db.flush()
    db.add_all([
        AgentSettings(user_id=user.id, fee_rate=config.estimated_fee_rate, slippage_rate=config.estimated_slippage_rate),
        RiskSettings(user_id=user.id, max_trades_per_day=config.max_trades_per_day,
                     max_position_usdc=config.max_position_usdc, max_daily_loss_usdc=config.max_daily_loss_usdc),
        PaperBalance(user_id=user.id, usdc=config.initial_paper_balance_usdc, initial_usdc=config.initial_paper_balance_usdc),
        PaperPosition(user_id=user.id, product='XRP-USDC'),
    ])
    issue_session(db, user, response)
    db.commit()
    return {'id': user.id, 'username': user.username, 'guest': True}


@app.post("/auth/login")
def login(body: Credentials, request: Request, response: Response, db=Depends(session_dependency)):
    rate_limit(request)
    user = db.scalar(select(User).where(User.username == body.username.lower()))
    try:
        valid = passwords.verify(user.password_hash if user else _dummy_hash, body.password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not user or not valid:
        raise HTTPException(401, "Invalid username or password.")
    issue_session(db, user, response)
    db.commit()
    return {"id": user.id, "username": user.username}


@app.post("/auth/logout")
def logout(request: Request, response: Response, user=Depends(current_user), db=Depends(session_dependency)):
    token = request.cookies.get("crypto_session", "")
    session = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie("crypto_session", path="/")
    return {"logged_out": True}


@app.get("/auth/me")
def me(user=Depends(current_user)):
    return {"id": user.id, "username": user.username}


@app.get("/market/latest")
def latest(user=Depends(current_user), db=Depends(session_dependency)):
    return views.market(db)


@app.get("/market/history")
def history(limit: int = Query(168, ge=1, le=300), user=Depends(current_user), db=Depends(session_dependency)):
    snapshot = db.get(MarketSnapshot, "XRP-USDC")
    return json.loads(snapshot.candles_json)[-limit:] if snapshot else []


@app.get("/predictions/latest")
def prediction(user=Depends(current_user), db=Depends(session_dependency)):
    record = views.latest_prediction(db, user.id)
    try:
        _, metadata = load_approved(config.model_path)
        model = {"version": metadata["version"], "validated": True}
    except (ValueError, OSError, KeyError) as error:
        model = {"version": None, "validated": False, "reason": str(error)}
    return {"prediction": record, "model": model}


@app.get("/agent/status")
def status(user=Depends(current_user), db=Depends(session_dependency)):
    return views.status(db, user.id)


@app.get('/agent/research/latest')
def research_latest(user=Depends(current_user), db=Depends(session_dependency)):
    return views.research_forecast(db)


@app.get("/agent/settings")
def get_settings(user=Depends(current_user), db=Depends(session_dependency)):
    return views.settings(db, user.id)


@app.put("/agent/settings")
def update_settings(body: SettingsInput, user=Depends(current_user), db=Depends(session_dependency)):
    settings, risk = db.get(AgentSettings, user.id), db.get(RiskSettings, user.id)
    for key, value in body.model_dump().items():
        setattr(risk if key in {"max_trades_per_day", "max_position_usdc", "max_allocation", "max_daily_loss_usdc"} else settings, key, value)
    if settings.emergency_stop:
        settings.enabled = False
    db.add(ExecutionLog(user_id=user.id, level="INFO", message="User updated agent/risk settings."))
    db.commit()
    return views.settings(db, user.id)


@app.post("/agent/start")
def start(user=Depends(current_user), db=Depends(session_dependency)):
    from backend.managed_models import ManagedAgent
    if db.get(ManagedAgent, user.id):
        raise HTTPException(409, 'Use the Managed spot agent controls for this account.')
    settings = db.get(AgentSettings, user.id)
    if settings.emergency_stop:
        raise HTTPException(409, "Clear emergency stop in settings first.")
    if not config.trading_enabled:
        raise HTTPException(409, "Operator disabled paper execution. Set TRADING_ENABLED=true in .env and restart.")
    settings.enabled = True
    db.add(ExecutionLog(user_id=user.id, level="INFO", message="User started autonomous paper evaluation."))
    db.commit()
    return views.status(db, user.id)


@app.post("/agent/stop")
def stop(user=Depends(current_user), db=Depends(session_dependency)):
    db.get(AgentSettings, user.id).enabled = False
    db.add(ExecutionLog(user_id=user.id, level="INFO", message="User stopped paper evaluation."))
    db.commit()
    return views.status(db, user.id)


@app.get("/trades/paper")
def trades(limit: int = Query(100, ge=1, le=500), user=Depends(current_user), db=Depends(session_dependency)):
    return views.trades(db, user.id, limit)


@app.get("/decisions")
def decisions(limit: int = Query(100, ge=1, le=500), user=Depends(current_user), db=Depends(session_dependency)):
    return views.decisions(db, user.id, limit)


@app.get("/portfolio/paper")
def portfolio(user=Depends(current_user), db=Depends(session_dependency)):
    return views.portfolio(db, user.id)


@app.get("/performance/paper")
def performance(user=Depends(current_user), db=Depends(session_dependency)):
    return views.performance(db, user.id)


@app.post("/chat")
def chat(body: ChatInput, request: Request, user=Depends(current_user), db=Depends(session_dependency)):
    rate_limit(request, "chat", 10)
    return answer(body.message, db, user.id)
