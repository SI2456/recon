from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, scoped_client_ids
from app.db.models import FraudAlert, Invoice, User
from app.db.session import get_db


router = APIRouter()


@router.get("")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    client_ids = scoped_client_ids(db, user)
    invoices = db.query(Invoice).filter(Invoice.client_id.in_(client_ids)).all() if client_ids else []
    alerts = db.query(FraudAlert).filter(FraudAlert.client_id.in_(client_ids)).all() if client_ids else []
    return {
        "kpis": {
            "totalClients": len(client_ids),
            "uploadedInvoices": len(invoices),
            "matchedInvoices": len([item for item in invoices if item.status == "Matched"]),
            "mismatchedInvoices": len([item for item in invoices if item.status == "Mismatched"]),
            "duplicateInvoices": len([item for item in invoices if item.status == "Duplicate"]),
            "highRiskTransactions": len([item for item in alerts if item.risk >= 70]),
        },
        "monthlyData": [],
        "supplierRisk": [{"supplier": item.entity, "risk": item.risk, "amount": item.amount, "reason": item.reason} for item in alerts],
    }
