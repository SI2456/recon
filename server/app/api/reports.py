import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import ensure_client_scope, get_current_user, scoped_client_ids
from app.db.models import FraudAlert, Report, User
from app.db.session import get_db


router = APIRouter()


class CreateReportRequest(BaseModel):
    clientId: int
    type: str = "PDF"


@router.get("")
def list_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    client_ids = scoped_client_ids(db, user)
    reports = db.query(Report).filter(Report.client_id.in_(client_ids)).order_by(Report.created_at.desc()).all() if client_ids else []
    return {"reports": [serialize_report(item) for item in reports]}


@router.post("", status_code=201)
def create_report(payload: CreateReportRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_client_scope(db, user, payload.clientId)
    alerts = db.query(FraudAlert).filter(FraudAlert.client_id == payload.clientId).all()
    report = Report(
        client_id=payload.clientId,
        generated_by=user.id,
        name=f"ReconAI {payload.type.upper()} Audit Report",
        type=payload.type.upper(),
        payload_json=json.dumps({"alertCount": len(alerts), "highRiskAlerts": len([item for item in alerts if item.risk >= 70])}),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"report": serialize_report(report)}


def serialize_report(report: Report) -> dict:
    return {"id": report.id, "clientId": report.client_id, "name": report.name, "type": report.type, "status": report.status, "payload": json.loads(report.payload_json)}
