from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core import roles
from app.db.models import CAProfile, Client, ClientProfile, User
from app.db.session import get_db
from app.services.gstverify import fetch_gstin_captcha, normalize_gstin, verify_gstin_details, verify_gstin_profile


router = APIRouter()


class SelectCARequest(BaseModel):
    caId: int


class VerifyGstinRequest(BaseModel):
    gstin: str
    sessionId: str = ""
    captcha: str = ""


def get_or_create_profile(db: Session, user: User) -> ClientProfile:
    profile = db.query(ClientProfile).filter(ClientProfile.user_id == user.id).first()
    if not profile:
        profile = ClientProfile(user_id=user.id, selected_ca_id=None)
        db.add(profile)
        db.flush()
    return profile


def serialize_profile(db: Session, user: User) -> dict:
    profile = get_or_create_profile(db, user)
    client = db.query(Client).filter((Client.email == user.email) | (Client.gstin == user.gstin)).first()
    public_gstin = "" if client and client.gstin.startswith("PENDING") else (client.gstin if client else user.gstin)
    ca = db.get(User, profile.selected_ca_id) if profile.selected_ca_id else None
    ca_profile = db.query(CAProfile).filter(CAProfile.user_id == ca.id).first() if ca else None
    return {
        "id": profile.id,
        "userId": user.id,
        "clientId": client.id if client else None,
        "selectedCaId": profile.selected_ca_id,
        "needsCaSelection": profile.selected_ca_id is None,
        "client": {
            "name": client.name if client else user.name,
            "gstin": public_gstin,
            "city": client.city if client else "",
            "gstLegalName": client.gst_legal_name if client else "",
            "gstTradeName": client.gst_trade_name if client else "",
            "gstStatus": client.gst_status if client else "",
            "gstVerifiedAt": client.gst_verified_at if client and client.gst_verified_at else None,
            "gstDetails": json.loads(client.gst_details_json) if client and client.gst_details_json else {},
        },
        "ca": {
            "id": ca.id,
            "name": ca.name,
            "email": ca.email,
            "firmName": ca.firm_name,
            "specialization": ca_profile.specialization if ca_profile else "GST",
            "experience": ca_profile.experience if ca_profile else "0 Years",
            "city": ca_profile.city if ca_profile else "",
            "rating": ca_profile.rating if ca_profile else 4.5,
        }
        if ca
        else None,
    }


def assign_ca(db: Session, user: User, ca_id: int) -> dict:
    ca = db.get(User, ca_id)
    if not ca or roles.normalize(ca.role) != roles.TAX_REVIEWER or ca.status != "active" or not ca.email_verified:
        raise HTTPException(status_code=404, detail="Verified CA not found.")

    profile = get_or_create_profile(db, user)
    profile.selected_ca_id = ca.id

    clients = db.query(Client).filter((Client.email == user.email) | (Client.gstin == user.gstin)).all()
    for client in clients:
        client.ca_id = ca.id

    db.commit()
    return {"message": "CA selected successfully.", "profile": serialize_profile(db, user)}


@router.get("/profile")
def client_profile(db: Session = Depends(get_db), user: User = Depends(require_roles(roles.BUSINESS_USER))) -> dict:
    return {"profile": serialize_profile(db, user)}


@router.post("/select-ca")
def select_ca(payload: SelectCARequest, db: Session = Depends(get_db), user: User = Depends(require_roles(roles.BUSINESS_USER))) -> dict:
    return assign_ca(db, user, payload.caId)


@router.put("/change-ca")
def change_ca(payload: SelectCARequest, db: Session = Depends(get_db), user: User = Depends(require_roles(roles.BUSINESS_USER))) -> dict:
    return assign_ca(db, user, payload.caId)


@router.get("/gstin-captcha")
async def gstin_captcha(user: User = Depends(require_roles(roles.BUSINESS_USER))) -> dict:
    return await fetch_gstin_captcha()


@router.post("/verify-gstin")
async def verify_client_gstin(payload: VerifyGstinRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(roles.BUSINESS_USER))) -> dict:
    gstin = normalize_gstin(payload.gstin)
    # With a solved captcha we can fetch the full taxpayer profile (legal name,
    # address); without one we fall back to a captcha-free validity check.
    if payload.sessionId and payload.captcha:
        data = await verify_gstin_details(gstin, payload.sessionId, payload.captcha)
    else:
        data = await verify_gstin_profile(gstin)
    client = db.query(Client).filter((Client.email == user.email) | (Client.gstin == user.gstin) | (Client.gstin == gstin)).first()
    if not client:
        client = Client(name=user.name, gstin=gstin, email=user.email, ca_id=None)
        db.add(client)
        db.flush()

    legal_name = data["legalName"] or data["tradeName"]
    client.gstin = gstin
    client.gst_legal_name = data["legalName"]
    client.gst_trade_name = data["tradeName"]
    client.gst_status = data["status"]
    client.gst_details_json = json.dumps(data, default=str)
    client.gst_verified_at = datetime.utcnow()
    if legal_name:
        client.name = legal_name

    user.gstin = gstin
    if legal_name:
        user.name = legal_name

    db.commit()
    return {"message": "GSTIN verified successfully.", "client": serialize_profile(db, user)["client"]}
