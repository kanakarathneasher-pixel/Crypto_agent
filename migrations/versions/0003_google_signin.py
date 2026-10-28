"""Google identity bindings and short-lived browser-bound login challenges."""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('google_identities',
                    sa.Column('subject', sa.String(255), primary_key=True),
                    sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, unique=True),
                    sa.Column('email', sa.String(320), nullable=False))
    op.create_table('google_login_challenges',
                    sa.Column('token_hash', sa.String(64), primary_key=True),
                    sa.Column('session_hash', sa.String(64), nullable=False),
                    sa.Column('nonce_hash', sa.String(64), nullable=False),
                    sa.Column('expires_at', sa.String(40), nullable=False))
    op.create_index('ix_google_login_challenges_session_hash', 'google_login_challenges', ['session_hash'])


def downgrade():
    op.drop_index('ix_google_login_challenges_session_hash', table_name='google_login_challenges')
    op.drop_table('google_login_challenges')
    op.drop_table('google_identities')
