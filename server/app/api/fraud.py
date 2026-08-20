import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import ensure_client_scope, get_current_user, scoped_client_ids
from app.db.models import FraudAlert, User
from app.db.session import get_db
from app.services.ml import run_fraud_detection


router = APIRouter()


class RunRequest(BaseModel):
    clientId: int


@router.get("/alerts")
def alerts(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    client_ids = scoped_client_ids(db, user)
    items = db.query(FraudAlert).filter(FraudAlert.client_id.in_(client_ids)).order_by(FraudAlert.risk.desc()).all() if client_ids else []
    return {"alerts": [serialize_alert(item) for item in items]}


@router.post("/run")
def run(payload: RunRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_client_scope(db, user, payload.clientId)
    return {"alerts": [serialize_alert(item) for item in run_fraud_detection(db, payload.clientId)]}


def serialize_alert(alert: FraudAlert) -> dict:
    return {
        "id": alert.id,
        "clientId": alert.client_id,
        "invoiceId": alert.invoice_id,
        "type": alert.type,
        "entity": alert.entity,
        "risk": alert.risk,
        "amount": alert.amount,
        "reason": alert.reason,
        "shap": json.loads(alert.shap_json or "[]"),
        "findings": json.loads(alert.findings_json or "[]"),
        "status": alert.status,
    }
