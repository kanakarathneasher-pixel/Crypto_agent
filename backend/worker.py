"""One scheduler per machine/database, with OS lock released on process exit."""
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import threading
from sqlalchemy import select
from backend.config import config
from backend.database import SessionLocal
from backend.models import AgentSettings, MarketSnapshot, ExecutionLog
from backend.coinbase_client import latest_market
from backend.trading_agent import execute_cycle
from src.prediction import predict

log = logging.getLogger(__name__)


class WorkerLock:
    def __init__(self, path):
        self.path, self.handle = Path(path), None

    def acquire(self):
        self.handle = self.path.open("a+b")
        self.handle.seek(0)
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.handle.close()
            self.handle = None
            return False

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None


class Worker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None
        self.active = False

    def start(self):
        self.thread = threading.Thread(target=self.run, name="paper-market-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def run_once(self):
        market = latest_market()
        serializable = market["candles"].copy()
        serializable["open_time"] = serializable.open_time.astype(str)
        with SessionLocal.begin() as db:
            db.merge(MarketSnapshot(product=market["product"], price=market["price"],
                updated_at=market["updated_at"], candles_json=serializable.to_json(orient="records")))
            users = list(db.scalars(select(AgentSettings.user_id).where(AgentSettings.enabled.is_(True))))
        prediction, error = None, None
        try:
            prediction = predict(market["candles"], config.model_path)
        except (ValueError, OSError, KeyError) as exc:
            error = str(exc)
        for user_id in users:
            if self.stop_event.is_set():
                break
            try:
                with SessionLocal.begin() as db:
                    execute_cycle(db, user_id, market, prediction, error)
            except Exception:
                log.exception("User %s cycle failed", user_id)
                with SessionLocal.begin() as db:
                    db.add(ExecutionLog(user_id=user_id, level="ERROR", message="Cycle failed; no partial fill committed."))

    def run(self):
        # Local prototype requires all workers to share the same working directory.
        key = hashlib.sha256(config.database_url.encode()).hexdigest()[:16]
        lock = WorkerLock(f".worker-{key}.lock")
        try:
            while not self.stop_event.is_set() and not lock.acquire():
                self.stop_event.wait(config.worker_poll_seconds)
            if self.stop_event.is_set():
                return
            self.active = True
            while not self.stop_event.is_set():
                try:
                    self.run_once()
                except Exception:
                    log.exception("Public market refresh failed")
                    try:
                        with SessionLocal.begin() as db:
                            db.add(ExecutionLog(level="ERROR", message="Public market refresh failed; trading held."))
                    except Exception:
                        log.exception("Could not persist worker failure; run migrations first")
                self.stop_event.wait(config.worker_poll_seconds)
        finally:
            self.active = False
            lock.close()
