import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import ensure_client_scope, get_current_user
from app.db.models import FraudAlert, Invoice, User
from app.db.session import get_db
from app.services.rag import ask_ollama


router = APIRouter()


class AskRequest(BaseModel):
    clientId: int
    question: str


@router.post("/ask")
async def ask(payload: AskRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_client_scope(db, user, payload.clientId)
    invoices = db.query(Invoice).filter(Invoice.client_id == payload.clientId).limit(20).all()
    alerts = db.query(FraudAlert).filter(FraudAlert.client_id == payload.clientId).limit(20).all()
    context = "\n".join(
        [f"Invoice {item.invoice_no}: {item.status}, total {item.total}, supplier {item.supplier}" for item in invoices]
        + [f"Alert {item.id}: risk {item.risk}, {item.reason}" for item in alerts]
    )
    try:
        return {"answer": await ask_ollama(payload.question, context)}
    except httpx.HTTPError:
        invoice_count = len(invoices)
        alert_count = len(alerts)
        high_risk = len([alert for alert in alerts if alert.risk >= 70])
        return {
            "answer": (
                "Ollama is not running, so I used the local ReconAI database context. "
                f"This client currently has {invoice_count} invoice records, {alert_count} fraud alerts, "
                f"and {high_risk} high-risk alerts. Start Ollama to enable full natural-language RAG answers."
            )
        }
