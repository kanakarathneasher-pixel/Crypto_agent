"""Password and guest sign-in; provider identities live in google_auth.py."""
import hashlib
import secrets
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from backend.accounts import create_account
from backend.auth import current_user, issue_session, passwords, rate_limit, _dummy_hash, is_guest
from backend.database import session_dependency
from backend.models import AuthSession, User
from backend.schemas import Credentials

router = APIRouter(prefix='/auth', tags=['Accounts'])


def identity(user):
    return {'id': user.id, 'username': user.username, 'guest': is_guest(user)}


@router.post('/register', status_code=201)
def register(body: Credentials, request: Request, response: Response, db=Depends(session_dependency)):
    rate_limit(request)
    try:
        user = create_account(db, body.username.lower(), passwords.hash(body.password))
        issue_session(db, user, response)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Username unavailable.') from None
    return identity(user)


@router.post('/guest')
def guest(request: Request, response: Response, db=Depends(session_dependency)):
    try:
        return identity(current_user(request, db))
    except HTTPException as error:
        if error.status_code != 401:
            raise
    rate_limit(request, category='guest', maximum=10)
    user = create_account(db, 'guest_' + secrets.token_hex(16), '!guest')
    issue_session(db, user, response)
    db.commit()
    return identity(user)


@router.post('/login')
def login(body: Credentials, request: Request, response: Response, db=Depends(session_dependency)):
    rate_limit(request)
    user = db.scalar(select(User).where(User.username == body.username.lower()))
    try:
        valid = passwords.verify(user.password_hash if user else _dummy_hash, body.password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not user or not valid:
        raise HTTPException(401, 'Invalid username or password.')
    issue_session(db, user, response)
    db.commit()
    return identity(user)


@router.post('/logout')
def logout(request: Request, response: Response, user=Depends(current_user), db=Depends(session_dependency)):
    token = request.cookies.get('crypto_session', '')
    session = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie('crypto_session', path='/')
    return {'logged_out': True}


@router.get('/me')
def me(user=Depends(current_user)):
    return identity(user)
