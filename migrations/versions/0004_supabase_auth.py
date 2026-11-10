"""Bind Supabase Auth identities to isolated Orbit workspaces."""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('supabase_identities',
                    sa.Column('subject', sa.String(36), primary_key=True),
                    sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, unique=True),
                    sa.Column('email', sa.String(320), nullable=False))


def downgrade():
    op.drop_table('supabase_identities')
