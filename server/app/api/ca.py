from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import roles
from app.db.models import CAProfile, Client, User
from app.db.session import get_db


router = APIRouter()


def serialize_ca(db: Session, user: User, profile: CAProfile | None) -> dict:
    total_clients = db.query(Client).filter(Client.ca_id == user.id).count()
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "firmName": user.firm_name,
        "profilePhoto": profile.profile_photo if profile else "",
        "experience": profile.experience if profile else "0 Years",
        "rating": profile.rating if profile else 4.5,
        "specialization": profile.specialization if profile else "GST",
        "city": profile.city if profile else "",
        "totalClients": total_clients,
        "verificationBadge": bool(profile.is_verified if profile else user.email_verified),
    }


@router.get("/list")
def list_cas(db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(User, CAProfile)
        .outerjoin(CAProfile, CAProfile.user_id == User.id)
        .filter(User.role.in_(roles.reviewer_role_values()), User.status == "active", User.email_verified.is_(True))
        .order_by(User.name)
        .all()
    )
    return {"cas": [serialize_ca(db, user, profile) for user, profile in rows]}


@router.get("/{ca_id}")
def get_ca(ca_id: int, db: Session = Depends(get_db)) -> dict:
    user = db.get(User, ca_id)
    if not user or roles.normalize(user.role) != roles.TAX_REVIEWER or user.status != "active" or not user.email_verified:
        raise HTTPException(status_code=404, detail="CA not found.")
    profile = db.query(CAProfile).filter(CAProfile.user_id == user.id).first()
    return {"ca": serialize_ca(db, user, profile)}
