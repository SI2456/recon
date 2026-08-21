from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class UserRole(str, Enum):
    admin = "admin"
    business_user = "business_user"
    tax_reviewer = "tax_reviewer"


class SourceType(str, Enum):
    """Where a document came from.

    Recorded on every upload so the origin of any figure can be stated rather
    than assumed — in particular, whether GST data was exported by the user
    from the portal or generated for testing.
    """

    user_upload = "USER_UPLOAD"
    gst_export = "GST_EXPORT"
    accounting_export = "ACCOUNTING_EXPORT"
    ocr_document = "OCR_DOCUMENT"
    simulated_gst = "SIMULATED_GST"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), index=True)
    phone: Mapped[str] = mapped_column(String(40), default="")
    firm_name: Mapped[str] = mapped_column(String(180), default="")
    gstin: Mapped[str] = mapped_column(String(20), default="")
    icai_number: Mapped[str] = mapped_column(String(40), default="")
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    gstin: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    gst_legal_name: Mapped[str] = mapped_column(String(255), default="")
    gst_trade_name: Mapped[str] = mapped_column(String(255), default="")
    gst_status: Mapped[str] = mapped_column(String(80), default="")
    gst_details_json: Mapped[str] = mapped_column(Text, default="{}")
    gst_verified_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    ca_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    city: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(32), default="Active")
    risk: Mapped[str] = mapped_column(String(32), default="Low")
    compliance: Mapped[int] = mapped_column(Integer, default=0)
    ca = relationship("User")


class CAProfile(Base):
    __tablename__ = "ca_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    specialization: Mapped[str] = mapped_column(String(120), default="GST")
    experience: Mapped[str] = mapped_column(String(80), default="0 Years")
    city: Mapped[str] = mapped_column(String(80), default="")
    profile_photo: Mapped[str] = mapped_column(String(500), default="")
    rating: Mapped[float] = mapped_column(Float, default=4.5)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user = relationship("User")


class ClientProfile(Base):
    __tablename__ = "client_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    selected_ca_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user = relationship("User", foreign_keys=[user_id])
    selected_ca = relationship("User", foreign_keys=[selected_ca_id])


class EmailOtp(Base):
    __tablename__ = "email_otps"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    otp_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    resend_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    used_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user = relationship("User")


class CAChangeRequest(Base):
    """A business user's request to be moved to a different reviewer.

    The move is not made when the request is filed. Reassigning a workspace
    hands a new reviewer every invoice and every exception in it, so an admin
    approves it and the approval is what actually changes ``Client.ca_id``.
    """

    __tablename__ = "ca_change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    client_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    current_ca_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    requested_ca_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="Pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(40))
    object_key: Mapped[str] = mapped_column(String(500), default="")
    # Period and provenance. A GST statement cannot be compared to anything
    # without knowing which GSTIN and tax period it covers, and source_type
    # records where the data came from so a figure's origin is never guessed.
    gstin: Mapped[str] = mapped_column(String(20), default="", index=True)
    financial_year: Mapped[str] = mapped_column(String(12), default="")
    tax_period: Mapped[str] = mapped_column(String(12), default="")
    document_type: Mapped[str] = mapped_column(String(40), default="")
    source_type: Mapped[str] = mapped_column(String(32), default=SourceType.user_upload.value)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(40), default="received")
    validation_errors: Mapped[str] = mapped_column(Text, default="[]")
    parsed_rows: Mapped[int] = mapped_column(Integer, default=0)
    visible_to_client: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), nullable=True)
    invoice_no: Mapped[str] = mapped_column(String(120), index=True)
    supplier: Mapped[str] = mapped_column(String(180))
    supplier_gstin: Mapped[str] = mapped_column(String(20), index=True)
    invoice_date: Mapped[str] = mapped_column(String(20))
    taxable: Mapped[float] = mapped_column(Float, default=0)
    # gst stays as the combined figure every existing query relies on; the
    # components below are what make place-of-supply validation possible,
    # since an intra-state supply must carry CGST+SGST and an inter-state one
    # must carry IGST.
    gst: Mapped[float] = mapped_column(Float, default=0)
    cgst: Mapped[float] = mapped_column(Float, default=0)
    sgst: Mapped[float] = mapped_column(Float, default=0)
    igst: Mapped[float] = mapped_column(Float, default=0)
    cess: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float, default=0)
    hsn: Mapped[str] = mapped_column(String(12), default="")
    # The purchase order this invoice was raised against, when it cites one.
    po_number: Mapped[str] = mapped_column(String(80), default="", index=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    recipient_gstin: Mapped[str] = mapped_column(String(20), default="")
    place_of_supply: Mapped[str] = mapped_column(String(4), default="")
    document_type: Mapped[str] = mapped_column(String(24), default="invoice")
    source: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(40), default="Pending")
    risk: Mapped[str] = mapped_column(String(40), default="Low")
    normalized_key: Mapped[str] = mapped_column(String(180), index=True)


class PurchaseOrder(Base):
    """An order placed with a supplier, before any supply happens.

    Kept in its own table rather than folded into ``invoices``: a purchase
    order is not a tax document. It carries no GST, is never reconciled against
    a GST return, and would distort reconciliation counts, fraud scoring and
    the supplier graph if it were treated as an invoice.

    Its value is as evidence. An invoice billed well above the order it cites
    is the paper trail of an inflated claim, which no amount of checking the
    invoice against itself can reveal.
    """

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), nullable=True)
    po_number: Mapped[str] = mapped_column(String(80), index=True)
    supplier: Mapped[str] = mapped_column(String(180), default="")
    supplier_gstin: Mapped[str] = mapped_column(String(20), default="", index=True)
    po_date: Mapped[str] = mapped_column(String(20), default="")
    hsn: Mapped[str] = mapped_column(String(12), default="")
    description: Mapped[str] = mapped_column(String(255), default="")
    quantity: Mapped[float] = mapped_column(Float, default=0)
    rate: Mapped[float] = mapped_column(Float, default=0)
    taxable: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    status: Mapped[str] = mapped_column(String(40), default="Open")
    normalized_key: Mapped[str] = mapped_column(String(180), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReconciliationJob(Base):
    __tablename__ = "reconciliation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    run_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(40), default="completed")
    summary_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FraudAlert(Base):
    __tablename__ = "fraud_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(180))
    risk: Mapped[int] = mapped_column(Integer)
    amount: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str] = mapped_column(Text)
    shap_json: Mapped[str] = mapped_column(Text, default="[]")
    # Deterministic rule findings from services/integrity.py, kept separate
    # from the model's SHAP explanation so the UI can show "this is provably
    # wrong" apart from "this looks statistically unusual".
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="Open")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    generated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="Ready")
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    sender = relationship("User")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120))
    target: Mapped[str] = mapped_column(String(180))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
