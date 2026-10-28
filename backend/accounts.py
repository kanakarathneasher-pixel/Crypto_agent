"""Create the same isolated paper workspace for every account provider."""
from backend.config import config
from backend.models import AgentSettings, RiskSettings, PaperBalance, PaperPosition, User


def create_account(db, username, password_hash):
    user = User(username=username, password_hash=password_hash)
    db.add(user)
    db.flush()
    db.add_all([
        AgentSettings(user_id=user.id, fee_rate=config.estimated_fee_rate,
                      slippage_rate=config.estimated_slippage_rate),
        RiskSettings(user_id=user.id, max_trades_per_day=config.max_trades_per_day,
                     max_position_usdc=config.max_position_usdc,
                     max_daily_loss_usdc=config.max_daily_loss_usdc),
        PaperBalance(user_id=user.id, usdc=config.initial_paper_balance_usdc,
                     initial_usdc=config.initial_paper_balance_usdc),
        PaperPosition(user_id=user.id, product='XRP-USDC'),
    ])
    return user
