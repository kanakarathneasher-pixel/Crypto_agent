"""One authenticated round trip for the dashboard's account summary."""
from fastapi import APIRouter, Depends
from backend.auth import current_user
from backend.database import session_dependency
from backend.dashboard import dashboard_summary

router = APIRouter(tags=['Dashboard'])


@router.get('/dashboard')
def dashboard(user=Depends(current_user), db=Depends(session_dependency)):
    return dashboard_summary(db, user.id)
