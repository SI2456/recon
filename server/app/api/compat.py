from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, scoped_client_ids
from app.api.fraud import serialize_alert
from app.db.models import FraudAlert, User
from app.db.session import get_db


router = APIRouter()


@router.get("/api/fraud-alerts")
def fraud_alerts_alias(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    client_ids = scoped_client_ids(db, user)
    alerts = (
        db.query(FraudAlert)
        .filter(FraudAlert.client_id.in_(client_ids))
        .order_by(FraudAlert.risk.desc())
        .all()
        if client_ids
        else []
    )
    return {"alerts": [serialize_alert(alert) for alert in alerts]}
