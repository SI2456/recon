from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.models import AuditLog, Client, FraudAlert, Invoice, User
from app.db.session import get_db


router = APIRouter()


@router.get("/users")
def users(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> dict:
    items = db.query(User).order_by(User.created_at.desc()).all()
    return {"users": [{"id": item.id, "name": item.name, "email": item.email, "role": item.role, "status": item.status} for item in items]}


@router.get("/system")
def system(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> dict:
    return {
        "system": {
            "users": db.query(User).count(),
            "clients": db.query(Client).count(),
            "invoices": db.query(Invoice).count(),
            "alerts": db.query(FraudAlert).count(),
        }
    }


@router.get("/audit-logs")
def audit_logs(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> dict:
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(200).all()
    return {"logs": [{"id": item.id, "action": item.action, "target": item.target, "createdAt": item.created_at} for item in logs]}
