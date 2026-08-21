"""Reviewer reassignment requests.

A business user cannot move their own workspace to a different reviewer.
Reassignment hands the incoming reviewer every invoice, upload and exception in
that workspace, so the user files a request and an admin decides it; only the
approval writes ``Client.ca_id``.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles, scoped_client_ids
from app.core import roles
from app.db.models import AuditLog, CAChangeRequest, Client, User
from app.db.session import get_db


router = APIRouter()

PENDING = "Pending"
APPROVED = "Approved"
REJECTED = "Rejected"


class CreateRequest(BaseModel):
    requestedCaId: int
    reason: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(db: Session, actor_id: int, action: str, target: str) -> None:
    db.add(AuditLog(actor_id=actor_id, action=action, target=target))


def serialize_request(db: Session, item: CAChangeRequest) -> dict:
    """Snake_case keys, because that is what the admin table reads."""
    client = db.get(Client, item.client_id)
    current_ca = db.get(User, item.current_ca_id) if item.current_ca_id else None
    requested_ca = db.get(User, item.requested_ca_id) if item.requested_ca_id else None
    return {
        "id": item.id,
        "client_id": item.client_id,
        "client_name": client.name if client else "",
        "client_email": client.email if client else "",
        "current_ca_id": item.current_ca_id,
        "current_ca_name": current_ca.name if current_ca else "",
        "requested_ca_id": item.requested_ca_id,
        "requested_ca_name": requested_ca.name if requested_ca else "",
        "reason": item.reason,
        "status": item.status,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("")
def list_requests(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Every request for an admin; only their own workspaces' for anyone else."""
    query = db.query(CAChangeRequest)
    if roles.normalize(user.role) != roles.ADMIN:
        client_ids = scoped_client_ids(db, user)
        if not client_ids:
            return {"requests": []}
        query = query.filter(CAChangeRequest.client_id.in_(client_ids))
    items = query.order_by(CAChangeRequest.created_at.desc()).all()
    return {"requests": [serialize_request(db, item) for item in items]}


@router.post("", status_code=201)
def create_request(
    payload: CreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(roles.BUSINESS_USER)),
) -> dict:
    client_ids = scoped_client_ids(db, user)
    if not client_ids:
        raise HTTPException(status_code=400, detail="No client workspace is linked to this account.")
    client = db.get(Client, client_ids[0])

    requested = db.get(User, payload.requestedCaId)
    if (
        not requested
        or roles.normalize(requested.role) != roles.TAX_REVIEWER
        or requested.status != "active"
        or not requested.email_verified
    ):
        raise HTTPException(status_code=404, detail="Verified reviewer not found.")
    if client.ca_id == requested.id:
        raise HTTPException(status_code=400, detail="That reviewer is already assigned to this workspace.")

    # One open request at a time, or an admin sees the same ask several times
    # over and approving the stale one silently undoes the newer choice.
    existing = (
        db.query(CAChangeRequest)
        .filter(CAChangeRequest.client_id == client.id, CAChangeRequest.status == PENDING)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A change request for this workspace is already awaiting approval.")

    item = CAChangeRequest(
        client_id=client.id,
        client_user_id=user.id,
        current_ca_id=client.ca_id,
        requested_ca_id=requested.id,
        reason=(payload.reason or "").strip()[:2000],
        status=PENDING,
        updated_at=_now(),
    )
    db.add(item)
    db.flush()
    _audit(db, user.id, "ca_change.request", str(item.id))
    db.commit()
    db.refresh(item)
    return {
        "message": "Change request submitted to the System Admin for approval.",
        "requestId": item.id,
        "request": serialize_request(db, item),
    }


def _decide(db: Session, request_id: int, admin: User, status: str) -> CAChangeRequest:
    item = db.get(CAChangeRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Change request not found.")
    if item.status != PENDING:
        raise HTTPException(status_code=409, detail=f"This request has already been {item.status.lower()}.")
    item.status = status
    item.updated_at = _now()
    return item


@router.post("/{request_id}/approve")
def approve_request(
    request_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(roles.ADMIN)),
) -> dict:
    item = _decide(db, request_id, admin, APPROVED)

    client = db.get(Client, item.client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="The workspace this request refers to no longer exists.")
    client.ca_id = item.requested_ca_id

    # The user's own profile records their chosen reviewer too; leaving it on
    # the old one would make the client screen contradict the admin's decision.
    from app.db.models import ClientProfile  # noqa: PLC0415 - avoids a cycle at import time

    profile = db.query(ClientProfile).filter(ClientProfile.user_id == item.client_user_id).first()
    if profile:
        profile.selected_ca_id = item.requested_ca_id

    _audit(db, admin.id, "ca_change.approve", str(item.id))
    db.commit()
    return {"message": "Change request approved. The workspace has been transferred to the new reviewer."}


@router.post("/{request_id}/reject")
def reject_request(
    request_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(roles.ADMIN)),
) -> dict:
    item = _decide(db, request_id, admin, REJECTED)
    _audit(db, admin.id, "ca_change.reject", str(item.id))
    db.commit()
    return {"message": "Change request rejected. The workspace keeps its current reviewer."}
