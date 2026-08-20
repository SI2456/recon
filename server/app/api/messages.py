from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import ensure_client_scope, get_current_user, scoped_client_ids
from app.core import roles
from app.db.models import Message, User
from app.db.session import get_db


router = APIRouter()


class MessageRequest(BaseModel):
    clientId: int
    text: str


def serialize_message(message: Message) -> dict:
    return {
        "id": message.id,
        "clientId": message.client_id,
        "senderId": message.sender_id,
        "senderName": message.sender.name if message.sender else "",
        "senderRole": message.sender.role if message.sender else "",
        "text": message.text,
        "createdAt": message.created_at,
    }


def resolve_client_id(db: Session, user: User, requested_client_id: int) -> int:
    client_ids = scoped_client_ids(db, user)
    if requested_client_id in client_ids:
        return requested_client_id
    if roles.normalize(user.role) == roles.BUSINESS_USER and client_ids:
        return client_ids[0]
    ensure_client_scope(db, user, requested_client_id)
    return requested_client_id


@router.get("")
def list_messages(clientId: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    resolved_client_id = resolve_client_id(db, user, clientId)
    messages = db.query(Message).filter(Message.client_id == resolved_client_id).order_by(Message.created_at).all()
    return {"messages": [serialize_message(message) for message in messages]}


@router.post("", status_code=201)
def create_message(payload: MessageRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    client_id = resolve_client_id(db, user, payload.clientId)
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Message text is required.")
    message = Message(client_id=client_id, sender_id=user.id, text=payload.text.strip())
    db.add(message)
    db.commit()
    db.refresh(message)
    return {"message": serialize_message(message)}
