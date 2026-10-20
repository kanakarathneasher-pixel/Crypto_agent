"""Opaque revocable sessions; only token hashes are persisted."""
from datetime import datetime, timezone, timedelta
import hashlib
import secrets
import threading
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from backend.config import config
from backend.database import session_dependency
from backend.models import AuthSession, User

passwords = PasswordHasher()
_dummy_hash = passwords.hash("not-a-real-account-password")
_attempts = {}
_attempt_lock = threading.Lock()


def rate_limit(request, category="auth", maximum=10):
    key = (request.client.host if request.client else "local", category)
    now = time.monotonic()
    with _attempt_lock:
        # Bound the local rate-limit cache. Hosted production needs a shared limiter.
        for old in list(_attempts):
            if not _attempts[old] or _attempts[old][-1] < now - 60:
                _attempts.pop(old)
        attempts = [stamp for stamp in _attempts.get(key, []) if stamp > now - 60]
        if len(attempts) >= maximum:
            raise HTTPException(429, "Too many requests. Try again in one minute.")
        _attempts[key] = attempts + [now]


def issue_session(db, user, response):
    token = secrets.token_urlsafe(48)
    db.add(AuthSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                       expires_at=(datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()))
    response.set_cookie("crypto_session", token, httponly=True, secure=config.cookie_secure,
                        samesite="strict", max_age=43200, path="/")


def current_user(request: Request, db=Depends(session_dependency)):
    token = request.cookies.get("crypto_session")
    if not token:
        raise HTTPException(401, "Sign in required.")
    record = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    if not record or datetime.fromisoformat(record.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(401, "Session expired or invalid.")
    user = db.get(User, record.user_id)
    if not user:
        raise HTTPException(401, "Account unavailable.")
    return user
