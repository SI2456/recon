from fastapi import APIRouter, Depends, HTTPException
import json

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles, scoped_client_ids
from app.core import roles
from app.db.models import (
    AuditLog,
    CAChangeRequest,
    Client,
    FraudAlert,
    Invoice,
    Message,
    PurchaseOrder,
    ReconciliationJob,
    Report,
    Upload,
    User,
)
from app.db.session import get_db
from app.services.gstverify import normalize_gstin


router = APIRouter()


class CreateClientRequest(BaseModel):
    name: str
    gstin: str
    email: str = ""
    city: str = ""
    caId: int | None = None


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


@router.post("", status_code=201)
def create_client(
    payload: CreateClientRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(roles.TAX_REVIEWER, roles.ADMIN)),
) -> dict:
    """Open a workspace for a business a reviewer is acting for.

    The GSTIN is validated rather than stored as typed: it is the key every
    invoice, reconciliation and supplier edge is matched on, so a malformed one
    would quietly split a business's records across two workspaces.
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Business name is required.")
    gstin = normalize_gstin(payload.gstin)

    if db.query(Client).filter(Client.gstin == gstin).first():
        raise HTTPException(status_code=409, detail="A workspace for this GSTIN already exists.")

    # An admin may hand the workspace to a named reviewer; a reviewer only ever
    # creates workspaces for themselves.
    if roles.normalize(user.role) == roles.ADMIN:
        ca_id = payload.caId
        if ca_id is not None:
            reviewer = db.get(User, ca_id)
            if not reviewer or roles.normalize(reviewer.role) != roles.TAX_REVIEWER:
                raise HTTPException(status_code=404, detail="Reviewer not found.")
    else:
        ca_id = user.id

    client = Client(
        name=name,
        gstin=gstin,
        email=payload.email.strip().lower(),
        city=payload.city.strip(),
        ca_id=ca_id,
    )
    db.add(client)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A workspace for this GSTIN already exists.") from exc

    db.add(AuditLog(actor_id=user.id, action="client.create", target=str(client.id)))
    db.commit()
    db.refresh(client)
    return {"client": serialize_client(db, client)}


@router.delete("/{client_id}")
def delete_client(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(roles.ADMIN)),
) -> dict:
    """Remove a workspace and everything filed under it.

    Admin-only and deliberately explicit: the child rows are deleted in
    dependency order rather than left to a database cascade, because the SQLite
    development database does not enforce foreign keys and would otherwise
    leave invoices and alerts orphaned but still visible in aggregate counts.

    The user account behind the workspace is left alone. Deleting it would take
    the person's login with the workspace, which is not what removing a client
    record means.
    """
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client workspace not found.")
    # Read before the delete: the row is expired once the session commits.
    client_name = client.name

    # Alerts reference invoices as well as the client, so they go first.
    invoice_ids = [row.id for row in db.query(Invoice.id).filter(Invoice.client_id == client_id).all()]
    if invoice_ids:
        db.query(FraudAlert).filter(FraudAlert.invoice_id.in_(invoice_ids)).delete(synchronize_session=False)
    # Invoices cite purchase orders, so they are cleared before the orders are.
    for model in (FraudAlert, Invoice, PurchaseOrder, Upload, ReconciliationJob, Report, Message, CAChangeRequest):
        db.query(model).filter(model.client_id == client_id).delete(synchronize_session=False)

    db.delete(client)
    db.add(AuditLog(actor_id=user.id, action="client.delete", target=str(client_id)))
    db.commit()
    return {"ok": True, "message": f"Client workspace '{client_name}' and its records were deleted."}
