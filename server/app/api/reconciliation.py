from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import ensure_client_scope, get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services.reconciliation import run_reconciliation


router = APIRouter()


class RunRequest(BaseModel):
    clientId: int


@router.post("/run")
def run(payload: RunRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_client_scope(db, user, payload.clientId)
    return run_reconciliation(db, payload.clientId, user.id)
