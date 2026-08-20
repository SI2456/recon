from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import roles
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import CAProfile, Client, ClientProfile, User
from app.db.session import get_db
from app.services.gstverify import normalize_gstin
from app.services.otp import create_email_otp, verify_email_otp


router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


# Roles a visitor may self-register as live in app.core.roles; "admin" is
# excluded there because admin accounts are provisioned, never self-selected.
SELF_SERVICE_ROLES = roles.SELF_SERVICE_ROLES


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str
    phone: str = ""
    firmName: str = ""
    gstin: str = ""
    icaiNumber: str = ""
    businessName: str = ""
    city: str = ""
    specialization: str = "GST"
    experience: str = "0 Years"


class OtpRequest(BaseModel):
    email: str
    otp: str


class ResendOtpRequest(BaseModel):
    email: str
    purpose: str = "registration"


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    otp: str
    password: str


def public_user(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "firmName": user.firm_name,
        "gstin": user.gstin,
        "icaiNumber": user.icai_number,
        "emailVerified": user.email_verified,
    }


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    if not user.email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Please verify your email OTP before login.")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is not active.")
    return {"token": create_access_token(str(user.id), user.role), "user": public_user(user)}


# "/register-otp" is the path the frontend has always called and the one the
# legacy stdlib server exposed; "/register" is the canonical name. Both are
# registered against the same handler so an older bundle keeps working.
@router.post("/register", status_code=201)
@router.post("/register-otp", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    role = roles.normalize(payload.role)
    if role not in SELF_SERVICE_ROLES:
        raise HTTPException(status_code=403, detail="This role cannot be self-registered.")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    email = payload.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email is already registered.")
    clean_gstin = ""
    if role != roles.BUSINESS_USER and payload.gstin:
        clean_gstin = normalize_gstin(payload.gstin)

    user = User(
        name=payload.name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        role=role,
        phone=payload.phone,
        firm_name=payload.firmName,
        gstin=clean_gstin,
        icai_number=payload.icaiNumber.upper().strip(),
        email_verified=False,
        status="pending_verification",
    )
    db.add(user)
    db.flush()

    if role == roles.BUSINESS_USER:
        pending_gstin = f"PENDING{user.id:08d}"
        db.add(
            Client(
                name=payload.businessName or payload.name,
                gstin=pending_gstin,
                email=user.email,
                ca_id=None,
                city=payload.city,
            )
        )
        db.add(ClientProfile(user_id=user.id, selected_ca_id=None))

    if role == roles.TAX_REVIEWER:
        db.add(
            CAProfile(
                user_id=user.id,
                specialization=payload.specialization or "GST",
                experience=payload.experience or "0 Years",
                city=payload.city,
                is_verified=False,
            )
        )

    try:
        otp = create_email_otp(db, user, "registration")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email or GSTIN is already registered.") from exc
    response = {"message": "Registration successful. Verify the OTP sent to your email.", "email": user.email}
    if otp:
        response["devOtp"] = otp
    return response


@router.post("/verify-otp")
def verify_otp(payload: OtpRequest, db: Session = Depends(get_db)) -> dict:
    user = verify_email_otp(db, payload.email, payload.otp, "registration")
    user.email_verified = True
    user.status = "active"
    db.commit()
    db.refresh(user)
    return {"token": create_access_token(str(user.id), user.role), "user": public_user(user)}


@router.post("/resend-otp")
def resend_otp(payload: ResendOtpRequest, db: Session = Depends(get_db)) -> dict:
    if payload.purpose not in {"registration", "password_reset"}:
        raise HTTPException(status_code=400, detail="Invalid OTP purpose.")
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found.")
    otp = create_email_otp(db, user, payload.purpose, resend=True)
    db.commit()
    response = {"message": "OTP sent again."}
    if otp:
        response["devOtp"] = otp
    return response


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found.")
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Email is not verified yet.")
    otp = create_email_otp(db, user, "password_reset")
    db.commit()
    response = {"message": "Password reset OTP sent.", "email": user.email}
    if otp:
        response["devOtp"] = otp
    return response


@router.post("/verify-reset-otp")
def verify_reset_otp(payload: OtpRequest, db: Session = Depends(get_db)) -> dict:
    verify_email_otp(db, payload.email, payload.otp, "password_reset", consume=False)
    db.commit()
    return {"message": "OTP verified. You can reset your password now."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> dict:
    user = verify_email_otp(db, payload.email, payload.otp, "password_reset")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    user.password_hash = hash_password(payload.password)
    db.commit()
    return {"message": "Password reset successful. Please sign in with your new password."}
