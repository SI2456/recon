from fastapi import APIRouter, Depends
import json
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, scoped_client_ids
from app.db.models import Client, Invoice, User
from app.db.session import get_db


router = APIRouter()


def serialize_client(db: Session, client: Client) -> dict:
    invoice_count = db.query(Invoice).filter(Invoice.client_id == client.id).count()
    ca = client.ca
    public_gstin = "" if client.gstin.startswith("PENDING") else client.gstin
    return {
        "id": client.id,
        "name": client.name,
        "gstin": public_gstin,
        "gstLegalName": client.gst_legal_name,
        "gstTradeName": client.gst_trade_name,
        "gstStatus": client.gst_status,
        "gstVerifiedAt": client.gst_verified_at,
        "gstDetails": json.loads(client.gst_details_json) if client.gst_details_json else {},
        "email": client.email,
        "city": client.city,
        "status": client.status,
        "risk": client.risk,
        "compliance": client.compliance,
        "invoices": invoice_count,
        "caId": client.ca_id,
        "caName": ca.name if ca else "",
        "caEmail": ca.email if ca else "",
        "firmName": ca.firm_name if ca else "",
    }


@router.get("")
def list_clients(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    client_ids = scoped_client_ids(db, user)
    clients = db.query(Client).filter(Client.id.in_(client_ids)).order_by(Client.name).all() if client_ids else []
    return {"clients": [serialize_client(db, client) for client in clients]}


@router.get("/me")
def my_client(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    client_ids = scoped_client_ids(db, user)
    client = db.get(Client, client_ids[0]) if client_ids else None
    return {"client": serialize_client(db, client) if client else None}
