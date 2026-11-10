"""Email/password authentication through Supabase; passwords are never persisted in Orbit."""
import hashlib
import secrets
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError

from backend.accounts import create_account
from backend.auth import issue_session, rate_limit
from backend.config import config
from backend.database import session_dependency
from backend.models import AuthSession, SupabaseIdentity, User

router = APIRouter(prefix='/auth/email', tags=['Email sign-in'])


class EmailCredentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=320, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=8, max_length=128)

    @field_validator('email', mode='before')
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


def auth_request(method, path, *, body=None, access_token=None):
    origin = config.supabase_url.rstrip('/')
    parsed = urlsplit(origin)
    if (not config.supabase_publishable_key or parsed.scheme != 'https' or not parsed.hostname
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise HTTPException(503, 'Email sign-in is not configured yet. Please contact the Orbit administrator.')
    headers = {'apikey': config.supabase_publishable_key}
    if access_token:
        headers['Authorization'] = 'Bearer ' + access_token
    try:
        # Never retry signup/login or follow redirects carrying credentials.
        result = httpx.request(method, origin + '/auth/v1/' + path, json=body,
                               headers=headers, timeout=10, follow_redirects=False)
    except httpx.RequestError:
        raise HTTPException(503, 'Sign-in is temporarily unavailable. Please try again shortly.') from None
    if result.status_code == 429:
        raise HTTPException(429, 'Too many attempts. Please wait a minute and try again.')
    if result.status_code in {401, 403}:
        raise HTTPException(503, 'Email sign-in is unavailable. Please contact the Orbit administrator.')
    try:
        data = result.json()
    except ValueError:
        raise HTTPException(502, 'The sign-in service returned an invalid response. Please try again.') from None
    if not isinstance(data, dict):
        raise HTTPException(502, 'The sign-in service returned an invalid response. Please try again.')
    if result.status_code >= 500 or 300 <= result.status_code < 400:
        raise HTTPException(503, 'Sign-in is temporarily unavailable. Please try again shortly.')
    if result.status_code >= 400:
        code = data.get('error_code') or data.get('code')
        if code == 'email_not_confirmed':
            raise HTTPException(401, 'Confirm your email before signing in. Check your inbox.')
        if code == 'weak_password':
            raise HTTPException(400, 'Choose a stronger password with letters, numbers and symbols.')
        if path == 'signup':
            raise HTTPException(400, 'Unable to register. Check your details or sign in if you already have an account.')
        raise HTTPException(401, 'Incorrect email or password.')
    return data


def open_account(data, request, response, db):
    token = data.get('access_token')
    if not isinstance(token, str) or not token:
        raise HTTPException(502, 'Sign-in could not be completed. Please try again.')
    # Verify the token at the configured project, never trust client-supplied IDs/emails.
    verified = auth_request('GET', 'user', access_token=token)
    try:
        subject = str(UUID(verified['id']))
        email = verified['email']
        if (not isinstance(email, str) or not 3 <= len(email) <= 320
                or verified.get('is_anonymous') or not verified.get('email_confirmed_at')):
            raise ValueError('Unconfirmed identity')
    except (KeyError, ValueError, TypeError, AttributeError):
        raise HTTPException(401, 'Confirm your email before signing in.') from None

    def account():
        identity = db.get(SupabaseIdentity, subject)
        if identity:
            identity.email = email
            return db.get(User, identity.user_id)
        user = create_account(db, 'orbit_' + secrets.token_hex(12), '!supabase')
        db.add(SupabaseIdentity(subject=subject, user_id=user.id, email=email))
        db.flush()
        return user

    try:
        user = account()
    except IntegrityError:
        # Two first logins may race; only the committed identity owns the workspace.
        db.rollback()
        identity = db.get(SupabaseIdentity, subject)
        if not identity:
            raise HTTPException(409, 'Sign-in is already in progress. Please try again.') from None
        user = db.get(User, identity.user_id)
    if not user:
        raise HTTPException(401, 'Account unavailable.')
    previous = request.cookies.get('crypto_session')
    if previous:
        session = db.get(AuthSession, hashlib.sha256(previous.encode()).hexdigest())
        if session:
            db.delete(session)
    issue_session(db, user, response)
    db.commit()
    return {'id': user.id, 'username': user.username, 'guest': False, 'email': email}


@router.post('/register', status_code=201)
def register(body: EmailCredentials, request: Request, response: Response, db=Depends(session_dependency)):
    rate_limit(request, 'email-register', 5)
    data = auth_request('POST', 'signup', body=body.model_dump())
    if not data.get('access_token'):
        return {'requires_confirmation': True,
                'message': 'Check your email for a confirmation link, then sign in. If you already registered, use Sign in.'}
    return open_account(data, request, response, db)


@router.post('/login')
def login(body: EmailCredentials, request: Request, response: Response, db=Depends(session_dependency)):
    rate_limit(request, 'email-login', 10)
    data = auth_request('POST', 'token?grant_type=password', body=body.model_dump())
    return open_account(data, request, response, db)
