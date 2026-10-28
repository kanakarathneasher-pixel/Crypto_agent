"""Google Identity Services: signed ID tokens and one-use browser-bound nonces.

Google's stable subject identifies accounts. Email never implicitly links users.
Tokens are verified then discarded; Orbit issues its own revocable session.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from backend.auth import current_user, is_guest, issue_session, rate_limit
from backend.accounts import create_account
from backend.config import config
from backend.database import session_dependency
from backend.models import AuthSession, GoogleIdentity, GoogleLoginChallenge, User

router = APIRouter(prefix='/auth/google', tags=['Google sign-in'])
google_keys = jwt.PyJWKClient('https://www.googleapis.com/oauth2/v3/certs', timeout=5)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def require_config():
    if not config.google_client_id:
        raise HTTPException(503, 'Google sign-in is not configured. Set GOOGLE_CLIENT_ID in the backend.')


def verify_google_token(credential):
    try:
        key = google_keys.get_signing_key_from_jwt(credential)
        claims = jwt.decode(credential, key.key, algorithms=['RS256'], audience=config.google_client_id,
                            issuer=['accounts.google.com', 'https://accounts.google.com'],
                            options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'nonce']})
        if (not isinstance(claims['sub'], str) or not 1 <= len(claims['sub']) <= 255
                or not isinstance(claims['nonce'], str) or claims.get('email_verified') is not True
                or not isinstance(claims.get('email'), str) or not 3 <= len(claims['email']) <= 320
                or ('azp' in claims and claims['azp'] != config.google_client_id)
                or (isinstance(claims['aud'], list) and len(claims['aud']) > 1
                    and claims.get('azp') != config.google_client_id)):
            raise ValueError('Invalid identity claims')
        return claims
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, 'Google sign-in verification is unavailable. Try again shortly.') from None
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(401, 'Google sign-in could not be verified. Please try again.') from None


class GoogleCredential(BaseModel):
    model_config = ConfigDict(extra='forbid')
    credential: str = Field(min_length=100, max_length=8192)


@router.get('/config')
def google_config(user=Depends(current_user), db=Depends(session_dependency)):
    identity = db.scalar(select(GoogleIdentity).where(GoogleIdentity.user_id == user.id))
    return {'enabled': bool(config.google_client_id), 'client_id': config.google_client_id,
            'linked': bool(identity), 'email': identity.email if identity else None}


@router.post('/challenge')
def challenge(request: Request, response: Response, user=Depends(current_user), db=Depends(session_dependency)):
    require_config()
    rate_limit(request, 'google-login', 20)
    session_hash = digest(request.cookies.get('crypto_session', ''))
    now = datetime.now(timezone.utc)
    db.execute(delete(GoogleLoginChallenge).where(
        (GoogleLoginChallenge.session_hash == session_hash) | (GoogleLoginChallenge.expires_at <= now.isoformat())))
    token, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(GoogleLoginChallenge(token_hash=digest(token), session_hash=session_hash, nonce_hash=digest(nonce),
                                expires_at=(now + timedelta(minutes=5)).isoformat()))
    db.commit()
    response.set_cookie('orbit_google_challenge', token, httponly=True, secure=config.cookie_secure,
                        samesite='strict', max_age=300, path='/')
    return {'nonce': nonce}


@router.post('')
def sign_in(body: GoogleCredential, request: Request, response: Response,
            user=Depends(current_user), db=Depends(session_dependency)):
    require_config()
    rate_limit(request, 'google-verify', 10)
    token_hash = digest(request.cookies.get('orbit_google_challenge', ''))
    session_hash = digest(request.cookies.get('crypto_session', ''))
    pending = db.get(GoogleLoginChallenge, token_hash)
    if (not pending or pending.session_hash != session_hash
            or pending.expires_at <= datetime.now(timezone.utc).isoformat()):
        raise HTTPException(401, 'Google sign-in expired or belongs to another browser. Please try again.')
    nonce_hash = pending.nonce_hash
    # Commit consumption before verification: concurrent requests cannot replay a challenge.
    removed = db.execute(delete(GoogleLoginChallenge).where(GoogleLoginChallenge.token_hash == token_hash))
    db.commit()
    if removed.rowcount != 1:
        raise HTTPException(401, 'Google sign-in has already been used. Please try again.')
    claims = verify_google_token(body.credential)
    if not secrets.compare_digest(digest(claims['nonce']), nonce_hash):
        raise HTTPException(401, 'Google sign-in did not match this browser. Please try again.')

    identity = db.get(GoogleIdentity, claims['sub'])
    linked = db.scalar(select(GoogleIdentity).where(GoogleIdentity.user_id == user.id))
    if not is_guest(user):
        # A signed-in user explicitly adds Google to that same account/owner ID.
        if (identity and identity.user_id != user.id) or (linked and linked.subject != claims['sub']):
            raise HTTPException(409, 'This Google account or Orbit account is already linked. Sign out to switch accounts.')
        target = user
    elif identity:
        target = db.get(User, identity.user_id)
    else:
        target = create_account(db, 'google_' + secrets.token_hex(12), '!google')
    if not identity:
        db.add(GoogleIdentity(subject=claims['sub'], user_id=target.id, email=claims['email']))
    else:
        identity.email = claims['email']
    try:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == session_hash))
        issue_session(db, target, response)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Google sign-in changed in another request. Please try again.') from None
    response.delete_cookie('orbit_google_challenge', path='/')
    return {'id': target.id, 'username': target.username, 'guest': False}
