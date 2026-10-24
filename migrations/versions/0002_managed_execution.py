"""Persistent managed execution; no changes to existing datasets or paper tables."""
from alembic import op
import sqlalchemy as sa
from backend.managed_models import ManagedAgent, ManagedOrder, ManagedFill, AgentEvent, ManagedWallet

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in [ManagedAgent.__table__, ManagedWallet.__table__, ManagedOrder.__table__, ManagedFill.__table__, AgentEvent.__table__]:
        table.create(bind)


def downgrade():
    for name in ['managed_events', 'managed_fills', 'managed_orders', 'managed_wallets', 'managed_agents']:
        op.drop_table(name)
