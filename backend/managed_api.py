"""Authenticated managed-agent controls and a replayable user-scoped SSE feed."""
import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from backend.auth import current_user, is_guest
from backend.config import config
from backend.database import session_dependency, SessionLocal
from backend.managed_contracts import ConfigureAgent, AgentCommand, StrategyConfig
from backend.managed_models import ManagedAgent, ManagedOrder, ManagedFill, ManagedWallet, AgentEvent
from backend.models import AgentSettings, MarketSnapshot
from backend.managed_engine import event, ACTIVE, lock_agent
from backend.views import public_row
from src.classifier_prediction import selection_status

router = APIRouter(prefix='/v2/agent', tags=['Managed spot agent'])


def owned(db, user_id):
    agent = db.get(ManagedAgent, user_id)
    if not agent:
        raise HTTPException(409, 'Configure the managed agent first.')
    return agent


@router.put('/configuration')
def configure(body: ConfigureAgent, user=Depends(current_user), db=Depends(session_dependency)):
    if body.mode == 'live' and is_guest(user):
        raise HTTPException(403, 'Guest workspaces support paper trading only.')
    agent = db.get(ManagedAgent, user.id)
    if agent:
        db.commit()
        agent = lock_agent(db, user.id)
    if body.mode == 'live' and (not config.live_execution_enabled or user.id != config.live_owner_user_id):
        raise HTTPException(409, 'Live mode is disabled or not bound to this account.')
    if agent:
        if db.scalar(select(ManagedOrder.id).where(ManagedOrder.user_id == user.id, ManagedOrder.state.in_(ACTIVE))):
            raise HTTPException(409, 'Reconcile pending orders before changing configuration.')
        wallet = db.get(ManagedWallet, (user.id, agent.mode))
        if body.mode != agent.mode:
            raise HTTPException(409, 'Execution mode is fixed for this managed account. Use a separate account for another mode.')
        if agent.phase == 'emergency' and wallet.quantity == 0:
            agent.phase = 'paused'
        agent.mode, agent.config_json = body.mode, body.settings.model_dump_json()
        agent.recovered = False
    else:
        agent = ManagedAgent(user_id=user.id, mode=body.mode, config_json=body.settings.model_dump_json())
        db.add(agent)
    if not db.get(ManagedWallet, (user.id, body.mode)):
        initial = config.initial_paper_balance_usdc if body.mode == 'paper' else Decimal(0)
        db.add(ManagedWallet(user_id=user.id, mode=body.mode, cash=initial, initial_equity=initial))
    # Exactly one strategy implementation owns this user's future order decisions.
    db.get(AgentSettings, user.id).enabled = False
    event(db, user.id, 'config:'+datetime.now(timezone.utc).isoformat(), 'configuration', body.model_dump(mode='json'))
    db.commit()
    return {'configured': True, 'mode': body.mode, 'phase': agent.phase}


@router.get('/configuration')
def configuration(user=Depends(current_user), db=Depends(session_dependency)):
    agent = owned(db, user.id)
    return {'mode': agent.mode, 'settings': json.loads(agent.config_json)}


@router.post('/commands')
def command(body: AgentCommand, user=Depends(current_user), db=Depends(session_dependency)):
    # End the authentication read transaction before taking the SQLite writer lock.
    owned(db, user.id)
    db.commit()
    agent = lock_agent(db, user.id)
    key = 'command:'+body.request_id
    previous = db.scalar(select(AgentEvent).where(AgentEvent.user_id == user.id, AgentEvent.event_key == key))
    if previous:
        original = json.loads(previous.payload)
        if original['action'] != body.action: raise HTTPException(409, 'Request ID already used for another action.')
        return {'accepted': True, 'duplicate': True, 'phase': agent.phase}
    if body.action in ('start', 'resume'):
        if agent.phase == 'emergency': raise HTTPException(409, 'Emergency stop requires operator review; reconfigure to reset while flat.')
        agent.phase = 'running'
        agent.recovered = False
    elif body.action == 'pause': agent.phase = 'paused'
    elif body.action == 'cancel_entries': agent.cancel_requested = True
    elif body.action == 'emergency_stop':
        agent.phase = 'emergency'
        agent.cancel_requested = StrategyConfig.model_validate_json(agent.config_json).emergency_cancel_entries
    elif body.action == 'close_position':
        agent.close_requested = db.get(ManagedWallet, (user.id, agent.mode)).quantity > 0
    event(db, user.id, key, 'command', {'action': body.action, 'phase': agent.phase})
    db.commit()
    return {'accepted': True, 'phase': agent.phase, 'note': 'Worker processes requests; acknowledgements are not fills.'}


@router.get('/status')
def status(user=Depends(current_user), db=Depends(session_dependency)):
    agent = db.get(ManagedAgent, user.id)
    if not agent: return {'configured': False, 'mode': 'paper', 'research_model': selection_status()}
    wallet = db.get(ManagedWallet, (user.id, agent.mode))
    quote = db.get(MarketSnapshot, 'XRP-USDC')
    value = wallet.cash + wallet.quantity*quote.price if quote else (wallet.cash if wallet.quantity == 0 else None)
    events = list(db.scalars(select(AgentEvent).where(AgentEvent.user_id == user.id).order_by(AgentEvent.id.desc()).limit(30)))
    orders = list(db.scalars(select(ManagedOrder).where(ManagedOrder.user_id == user.id).order_by(ManagedOrder.id.desc()).limit(100)))
    fills = list(db.scalars(select(ManagedFill).where(ManagedFill.user_id == user.id).order_by(ManagedFill.id.desc()).limit(100)))
    return {'configured': True, 'mode': agent.mode, 'phase': agent.phase, 'reconciled': agent.recovered,
            'last_reconciled': agent.last_reconciled, 'research_model': selection_status(),
            'wallet': public_row(wallet), 'equity': value,
            'unrealized_pnl': wallet.quantity*quote.price-wallet.cost_basis if quote else None,
            'total_pnl': value-wallet.initial_equity if value is not None else None,
            'orders': [public_row(o) for o in orders], 'fills': [public_row(f) for f in fills],
            'events': [{'id': e.id, 'kind': e.kind, 'timestamp': e.created_at, 'data': json.loads(e.payload)} for e in events]}


@router.get('/orders')
def orders(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
           user=Depends(current_user), db=Depends(session_dependency)):
    rows = db.scalars(select(ManagedOrder).where(ManagedOrder.user_id == user.id,
        ManagedOrder.id > after).order_by(ManagedOrder.id).limit(limit))
    return [public_row(row) for row in rows]


@router.get('/fills')
def fills(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
          user=Depends(current_user), db=Depends(session_dependency)):
    rows = db.scalars(select(ManagedFill).where(ManagedFill.user_id == user.id,
        ManagedFill.id > after).order_by(ManagedFill.id).limit(limit))
    return [public_row(row) for row in rows]


@router.get('/activity')
def activity(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
             user=Depends(current_user), db=Depends(session_dependency)):
    rows = db.scalars(select(AgentEvent).where(AgentEvent.user_id == user.id,
        AgentEvent.id > after).order_by(AgentEvent.id).limit(limit))
    return [{'id': row.id, 'kind': row.kind, 'timestamp': row.created_at, 'data': json.loads(row.payload)} for row in rows]


@router.get('/prediction')
def prediction(user=Depends(current_user), db=Depends(session_dependency)):
    row = db.scalar(select(AgentEvent).where(AgentEvent.user_id == user.id,
        AgentEvent.kind == 'prediction').order_by(AgentEvent.id.desc()).limit(1))
    return {'prediction': json.loads(row.payload) if row else None}


@router.get('/performance')
def performance(user=Depends(current_user), db=Depends(session_dependency)):
    agent = owned(db, user.id)
    wallet = db.get(ManagedWallet, (user.id, agent.mode))
    quote = db.get(MarketSnapshot, 'XRP-USDC')
    equity = wallet.cash+wallet.quantity*quote.price if quote else wallet.cash if wallet.quantity == 0 else None
    fees = db.scalar(select(func.sum(ManagedFill.fee)).where(ManagedFill.user_id == user.id)) or Decimal(0)
    peak, drawdown = wallet.initial_equity, Decimal(0)
    for row in db.scalars(select(AgentEvent).where(AgentEvent.user_id == user.id,
            AgentEvent.kind == 'decision').order_by(AgentEvent.id)):
        value = json.loads(row.payload).get('equity')
        if value is None: continue
        value = Decimal(value)
        peak = max(peak, value)
        if peak > 0: drawdown = min(drawdown, value/peak-1)
    return {'mode': agent.mode, 'equity': equity, 'realized_pnl': wallet.realized_pnl,
            'unrealized_pnl': wallet.quantity*quote.price-wallet.cost_basis if quote else None,
            'total_return': equity/wallet.initial_equity-1 if equity is not None and wallet.initial_equity else None,
            'fees': fees, 'recorded_drawdown': drawdown,
            'metric_note': 'Drawdown uses recorded decision equity. Execution mode is immutable for this account.'}


@router.get('/events')
async def events(request: Request, after: int = Query(0, ge=0), user=Depends(current_user)):
    user_id = user.id
    try:
        cursor = max(after, int(request.headers.get('last-event-id', '0')))
    except ValueError:
        raise HTTPException(422, 'Invalid event cursor.') from None
    token = request.cookies.get('crypto_session', '')
    async def stream():
        nonlocal cursor
        from backend.models import AuthSession
        import hashlib
        while not await request.is_disconnected():
            with SessionLocal() as db:
                session = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
                if not session or session.user_id != user_id or datetime.fromisoformat(session.expires_at) <= datetime.now(timezone.utc):
                    break
                rows = list(db.scalars(select(AgentEvent).where(AgentEvent.user_id == user_id,
                    AgentEvent.id > cursor).order_by(AgentEvent.id).limit(100)))
                for row in rows:
                    cursor = row.id
                    yield f'id: {row.id}\nevent: activity\ndata: {json.dumps({"kind":row.kind,"timestamp":row.created_at,"data":json.loads(row.payload)})}\n\n'
            if not rows: yield ': heartbeat\n\n'
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})
