from alembic import context
from backend.config import config
from backend.database import make_engine
from backend.models import Base

if context.is_offline_mode():
    context.configure(url=config.database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with make_engine(config.database_url).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
