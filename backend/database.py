"""Database engine; migrations, rather than application startup, create tables."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from backend.config import config


def make_engine(url):
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_options(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
    return engine


engine = make_engine(config.database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def session_dependency():
    with SessionLocal() as session:
        yield session
