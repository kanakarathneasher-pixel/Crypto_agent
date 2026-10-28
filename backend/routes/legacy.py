"""Legacy paper portfolio, market views and read-only chat endpoints."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from backend.auth import current_user, rate_limit
from backend.config import config
from backend.database import session_dependency
from backend.models import AgentSettings, RiskSettings, MarketSnapshot, ExecutionLog
from backend.schemas import SettingsInput, ChatInput
from backend import views
from backend.chat import answer
from backend.dashboard import prediction_summary

router = APIRouter(tags=['Paper portfolio'])

@router.get("/market/latest")
def latest(user=Depends(current_user), db=Depends(session_dependency)):
    return views.market(db)


@router.get("/market/history")
def history(limit: int = Query(168, ge=1, le=300), user=Depends(current_user), db=Depends(session_dependency)):
    snapshot = db.get(MarketSnapshot, "XRP-USDC")
    return json.loads(snapshot.candles_json)[-limit:] if snapshot else []


@router.get("/predictions/latest")
def prediction(user=Depends(current_user), db=Depends(session_dependency)):
    return prediction_summary(db, user.id)


@router.get("/agent/status")
def status(user=Depends(current_user), db=Depends(session_dependency)):
    return views.status(db, user.id)


@router.get('/agent/research/latest')
def research_latest(user=Depends(current_user), db=Depends(session_dependency)):
    return views.research_forecast(db)


@router.get("/agent/settings")
def get_settings(user=Depends(current_user), db=Depends(session_dependency)):
    return views.settings(db, user.id)


@router.put("/agent/settings")
def update_settings(body: SettingsInput, user=Depends(current_user), db=Depends(session_dependency)):
    settings, risk = db.get(AgentSettings, user.id), db.get(RiskSettings, user.id)
    for key, value in body.model_dump().items():
        setattr(risk if key in {"max_trades_per_day", "max_position_usdc", "max_allocation", "max_daily_loss_usdc"} else settings, key, value)
    if settings.emergency_stop:
        settings.enabled = False
    db.add(ExecutionLog(user_id=user.id, level="INFO", message="User updated agent/risk settings."))
    db.commit()
    return views.settings(db, user.id)


@router.post("/agent/start")
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


@router.post("/agent/stop")
def stop(user=Depends(current_user), db=Depends(session_dependency)):
    db.get(AgentSettings, user.id).enabled = False
    db.add(ExecutionLog(user_id=user.id, level="INFO", message="User stopped paper evaluation."))
    db.commit()
    return views.status(db, user.id)


@router.get("/trades/paper")
def trades(limit: int = Query(100, ge=1, le=500), user=Depends(current_user), db=Depends(session_dependency)):
    return views.trades(db, user.id, limit)


@router.get("/decisions")
def decisions(limit: int = Query(100, ge=1, le=500), user=Depends(current_user), db=Depends(session_dependency)):
    return views.decisions(db, user.id, limit)


@router.get("/portfolio/paper")
def portfolio(user=Depends(current_user), db=Depends(session_dependency)):
    return views.portfolio(db, user.id)


@router.get("/performance/paper")
def performance(user=Depends(current_user), db=Depends(session_dependency)):
    return views.performance(db, user.id)


@router.post("/chat")
def chat(body: ChatInput, request: Request, user=Depends(current_user), db=Depends(session_dependency)):
    rate_limit(request, "chat", 10)
    return answer(body.message, db, user.id)
