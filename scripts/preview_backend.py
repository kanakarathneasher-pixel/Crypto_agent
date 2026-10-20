"""Disposable local integration preview; no accounts or funds in the main DB."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
folder = root / '.qa'
folder.mkdir(exist_ok=True)
os.environ['DATABASE_URL'] = 'sqlite:///' + (folder / 'preview.db').as_posix()
os.environ['TRADING_ENABLED'] = 'true'
from alembic import command
from alembic.config import Config
import uvicorn

command.upgrade(Config('alembic.ini'), 'head')
uvicorn.run('backend.main:app', host='127.0.0.1', port=8000)
