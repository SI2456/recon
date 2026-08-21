import hashlib
import json
import re
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import ensure_client_scope, get_current_user, require_roles, scoped_client_ids
from app.core import roles
from app.db.models import AuditLog, Client, FraudAlert, Invoice, PurchaseOrder, SourceType, Upload, User
from app.db.session import SessionLocal, get_db
from app.services.parsing import parse_purchase_order, parse_upload
from app.services.reconciliation import normalize_key
from app.services.purchase_orders import link_invoices_to_orders, po_key
from app.services.storage import delete_object, read_bytes, upload_bytes


router = APIRouter()

STATUS_PROCESSING = "processing"
# Statuses a document can sit in once a run has finished, either way.
TERMINAL_STATUSES = {"parsed", "parsed_with_warnings", "processed", "failed"}

_GSTR_FILE_TYPES = {"gstr", "gstr-2a", "gstr-2b", "gstr2a", "gstr2b", "gstr1"}

# Anything the uploader can call a purchase order.
_PO_FILE_TYPES = {"po", "purchase_order", "purchase-order", "purchaseorder", "order"}


def is_purchase_order(upload: Upload) -> bool:
    return (
        str(upload.file_type or "").strip().lower() in _PO_FILE_TYPES
        or str(upload.document_type or "").strip().lower() in _PO_FILE_TYPES
    )


def ingest_purchase_orders(db: Session, upload: Upload, rows) -> int:
    """Persist parsed order lines against this upload."""
    created = 0
    for row in rows:
        db.add(
            PurchaseOrder(
                client_id=upload.client_id,
                upload_id=upload.id,
                po_number=row.po_number,
                supplier=row.supplier,
                supplier_gstin=row.supplier_gstin,
                po_date=row.po_date,
                hsn=row.hsn,
                description=row.description,
                quantity=row.quantity,
                rate=row.rate,
                taxable=row.taxable,
                total=row.total,
                currency=row.currency,
                normalized_key=po_key(row.po_number, row.supplier_gstin),
            )
        )
        created += 1
    return created



class VisibilityRequest(BaseModel):
    visible: bool


def safe_file_name(raw: str) -> str:
    """Reduce a client-supplied filename to a single safe path segment.

    The uploaded name is attacker-controlled and is concatenated into the
    storage object key, so it must not be able to escape the upload root or
    address a drive/UNC path. Strips any directory component (POSIX *and*
    Windows separators, since the client OS is unknown), then allows only a
    conservative character set.
    """
    candidate = PureWindowsPath(PurePosixPath(raw or "").name).name
    candidate = re.sub(r"[^A-Za-z0-9._-]", "_", candidate).lstrip(".")
    # Collapse to a default when the name was entirely separators/dots
    # (e.g. "..", "../", "") or reduced to nothing by the filter.
    if not candidate:
        return "upload"
    # Truncate the stem rather than the whole name: parse_upload dispatches on
    # the extension, so a long filename must not lose its ".csv"/".pdf" tail.
    stem, dot, suffix = candidate.rpartition(".")
    if dot and 0 < len(suffix) <= 10:
        return f"{stem[:180 - len(suffix) - 1]}.{suffix}"
    return candidate[:180]


_SOURCE_TYPE_VALUES = {item.value for item in SourceType}

# What a plain file kind implies about its origin, when the uploader does not
# say. GST statements are exports the user pulled from the portal; books data
# comes out of the accounting system.
_SOURCE_TYPE_BY_KIND = {
    "gstr": SourceType.gst_export,
    "gstr-2a": SourceType.gst_export,
    "gstr-2b": SourceType.gst_export,
    "gstr2a": SourceType.gst_export,
    "gstr2b": SourceType.gst_export,
    "gstr1": SourceType.gst_export,
    "books": SourceType.accounting_export,
    "purchase_register": SourceType.accounting_export,
    "sales_register": SourceType.accounting_export,
    "po": SourceType.accounting_export,
    "purchase_order": SourceType.accounting_export,
}


def resolve_source_type(declared: str, kind: str) -> str:
    """Provenance for an upload: what the uploader declared, else inferred.

    Recording this means the origin of a figure can always be stated — whether
    a GST statement was exported from the portal by the user or generated for
    testing — instead of being assumed.
    """
    value = (declared or "").strip().upper()
    if value in _SOURCE_TYPE_VALUES:
        return value
    inferred = _SOURCE_TYPE_BY_KIND.get((kind or "").strip().lower())
    return (inferred or SourceType.user_upload).value


def ingest_invoices(db: Session, upload: Upload, source: str, rows) -> int:
    """Persist parsed rows as Invoice records tied to this upload."""
    created = 0
    for row in rows:
        db.add(
            Invoice(
                client_id=upload.client_id,
                upload_id=upload.id,
                invoice_no=row.invoice_no,
                supplier=row.supplier,
                supplier_gstin=row.supplier_gstin,
                invoice_date=row.invoice_date,
                taxable=row.taxable,
                gst=row.gst,
                total=row.total,
                hsn=row.hsn,
                cgst=row.cgst,
                sgst=row.sgst,
                igst=row.igst,
                cess=row.cess,
                recipient_gstin=row.recipient_gstin,
                place_of_supply=row.place_of_supply,
                po_number=row.po_number,
                document_type=row.document_type,
                source=source,
                normalized_key=normalize_key(row.invoice_no, row.supplier_gstin),
            )
        )
        created += 1
    return created


def reset_stalled_processing() -> None:
    """Clear rows left mid-flight by a restart.

    A background task dies with the process, so anything still marked
    "processing" at startup will never finish on its own. Without this the
    document is stuck forever and the 409 guard refuses to retry it.
    """
    db = SessionLocal()
    try:
        stalled = db.query(Upload).filter(Upload.status == STATUS_PROCESSING).all()
        for upload in stalled:
            upload.status = "uploaded"
            upload.validation_errors = json.dumps(
                ["Processing was interrupted when the server restarted. Run Process again."]
            )
        if stalled:
            db.commit()
            print(f"[ingestion] reset {len(stalled)} interrupted upload(s) to 'uploaded'")
    finally:
        db.close()


@router.post("/upload", status_code=201)
async def upload_document(
    clientId: int | None = Form(None),
    source: str = Form("books"),
    gstin: str = Form(""),
    financialYear: str = Form(""),
    taxPeriod: str = Form(""),
    documentType: str = Form(""),
    sourceType: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if clientId is None:
        client_ids = scoped_client_ids(db, user)
        if not client_ids:
            raise HTTPException(status_code=404, detail="No client workspace is linked to this account.")
        clientId = client_ids[0]

    ensure_client_scope(db, user, clientId)
    content = await file.read()
    stored_name = safe_file_name(file.filename or "")
    # A checksum makes a re-upload of the same bytes identifiable, and the
    # period metadata is what lets a GST statement be compared to anything.
    checksum = hashlib.sha256(content).hexdigest()
    # The checksum prefix keeps each upload's bytes distinct. Keying on the
    # filename alone meant a second "invoice.pdf" overwrote the first, so every
    # earlier upload with that name silently started serving the newer file —
    # the wrong document shown beside the right document's extracted amounts.
    # Re-uploading identical bytes still lands on the same key, which is
    # correct: it is the same document.
    object_key = f"clients/{clientId}/uploads/{checksum[:16]}-{stored_name}"
    upload_bytes(object_key, content, file.content_type or "application/octet-stream")

    # Store only — OCR/parsing runs later when the CA presses Process.
    upload = Upload(
        client_id=clientId,
        uploaded_by=user.id,
        file_name=stored_name,
        file_type=source,
        object_key=object_key,
        gstin=re.sub(r"[^A-Z0-9]", "", gstin.upper())[:15],
        financial_year=financialYear.strip()[:12],
        tax_period=taxPeriod.strip()[:12],
        document_type=(documentType.strip() or source).lower()[:40],
        source_type=resolve_source_type(sourceType, source),
        checksum=checksum,
        status="uploaded",
        visible_to_client=False,
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return {"upload": serialize_upload(db, upload)}


def _invoice_source(file_type: str) -> str:
    return "gstr" if str(file_type).strip().lower() in _GSTR_FILE_TYPES else "books"


async def run_processing(upload_id: int) -> None:
    """Parse a stored document and record the outcome on the upload row.

    Runs after the response has been sent, so it opens its own session — the
    request-scoped one from ``get_db`` is already closed by this point.

    OCR on a scanned invoice takes minutes, and the heavy work happens in a
    worker thread (see services/vision_ocr), so awaiting it here does not block
    the event loop or any other request.
    """
    db = SessionLocal()
    try:
        upload = db.get(Upload, upload_id)
        if upload is None:
            return

        try:
            content = read_bytes(upload.object_key)
        except (FileNotFoundError, OSError):
            upload.status = "failed"
            upload.validation_errors = json.dumps(["The stored file is no longer available."])
            db.commit()
            return

        purchase_order = is_purchase_order(upload)
        try:
            if purchase_order:
                rows, errors = await parse_purchase_order(upload.file_name or "", content)
            else:
                rows, errors = await parse_upload(upload.file_name or "", "", content)
        except Exception as exc:  # noqa: BLE001 - a parser crash must not strand the row in "processing"
            upload.status = "failed"
            upload.validation_errors = json.dumps([f"Processing failed: {exc}"])
            db.commit()
            return

        # Re-processing is idempotent: clear the previous run's rows only once
        # the new parse has succeeded, so a failure leaves the old data.
        if purchase_order:
            db.query(PurchaseOrder).filter(PurchaseOrder.upload_id == upload.id).delete()
            parsed = ingest_purchase_orders(db, upload, rows)
        else:
            db.query(Invoice).filter(Invoice.upload_id == upload.id).delete()
            parsed = ingest_invoices(db, upload, _invoice_source(upload.file_type), rows)

        upload.parsed_rows = parsed
        upload.validation_errors = json.dumps(errors)
        if parsed:
            upload.status = "parsed" if not errors else "parsed_with_warnings"
        else:
            upload.status = "failed" if errors else "processed"
        db.commit()

        # An invoice can arrive before its order or after it, so the link is
        # rebuilt whenever either side changes.
        if parsed:
            link_invoices_to_orders(db, upload.client_id)
    finally:
        db.close()


@router.post("/process/{upload_id}", status_code=202)
def process_upload(
    upload_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(roles.TAX_REVIEWER, roles.ADMIN)),
) -> dict:
    """Queue a document for parsing and return immediately.

    Extraction can take minutes per page, which is far too long to hold a
    request open. The row is marked "processing" and the work is handed to a
    background task; clients poll GET /api/ingestion/uploads for the result.
    """
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")
    ensure_client_scope(db, user, upload.client_id)

    if upload.status == STATUS_PROCESSING:
        raise HTTPException(status_code=409, detail="This document is already being processed.")

    upload.status = STATUS_PROCESSING
    upload.validation_errors = json.dumps([])
    db.commit()
    db.refresh(upload)

    background_tasks.add_task(run_processing, upload.id)
    return {"upload": serialize_upload(db, upload), "queued": True}


@router.patch("/uploads/{upload_id}/visibility")
def set_visibility(
    upload_id: int,
    payload: VisibilityRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(roles.TAX_REVIEWER, roles.ADMIN)),
) -> dict:
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")
    ensure_client_scope(db, user, upload.client_id)
    upload.visible_to_client = payload.visible
    db.commit()
    db.refresh(upload)
    return {"upload": serialize_upload(db, upload)}


@router.delete("/uploads/{upload_id}")
def delete_upload(
    upload_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(roles.TAX_REVIEWER, roles.ADMIN)),
) -> dict:
    """Remove a document and everything parsed out of it.

    The rows extracted from a document are not evidence in their own right —
    they are that document read into the database — so deleting the file has to
    take them with it. Leaving them behind would keep a withdrawn invoice in
    the reconciliation counts and the supplier graph with nothing to trace it
    back to.
    """
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")
    ensure_client_scope(db, user, upload.client_id)
    if upload.status == STATUS_PROCESSING:
        raise HTTPException(status_code=409, detail="This document is being processed. Wait for it to finish.")

    # Read before the delete: the row is expired once the session commits.
    file_name = upload.file_name
    client_id = upload.client_id
    invoice_ids = [row.id for row in db.query(Invoice.id).filter(Invoice.upload_id == upload_id).all()]
    if invoice_ids:
        # Alerts point at invoices; they cannot outlive the rows they explain.
        db.query(FraudAlert).filter(FraudAlert.invoice_id.in_(invoice_ids)).delete(synchronize_session=False)
    db.query(Invoice).filter(Invoice.upload_id == upload_id).delete(synchronize_session=False)
    db.query(PurchaseOrder).filter(PurchaseOrder.upload_id == upload_id).delete(synchronize_session=False)

    object_key = upload.object_key
    db.delete(upload)
    db.add(AuditLog(actor_id=user.id, action="upload.delete", target=str(upload_id)))
    db.commit()

    # The stored bytes go last: a storage failure must not leave the database
    # rows deleted but the row still listed, so this runs after the commit and
    # cannot fail the request.
    if object_key:
        delete_object(object_key)

    # An invoice can lose the order it cited, so the links are rebuilt.
    link_invoices_to_orders(db, client_id)
    return {"ok": True, "message": f"'{file_name}' and the records extracted from it were deleted."}


@router.get("/purchase-orders")
def list_purchase_orders(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Uploaded orders, each with the invoice raised against it, if any."""
    client_ids = scoped_client_ids(db, user)
    if not client_ids:
        return {"purchaseOrders": []}

    orders = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.client_id.in_(client_ids))
        .order_by(PurchaseOrder.created_at.desc())
        .all()
    )
    billed = {}
    for invoice in db.query(Invoice).filter(Invoice.po_id.isnot(None)).all():
        billed.setdefault(invoice.po_id, []).append(invoice)

    return {
        "purchaseOrders": [
            {
                "id": order.id,
                "clientId": order.client_id,
                "poNumber": order.po_number,
                "supplier": order.supplier,
                "supplierGstin": order.supplier_gstin,
                "poDate": order.po_date,
                "hsn": order.hsn,
                "description": order.description,
                "quantity": order.quantity,
                "rate": order.rate,
                "taxable": order.taxable,
                "total": order.total,
                "status": order.status,
                "billedInvoices": [
                    {"id": inv.id, "invoiceNo": inv.invoice_no, "total": inv.total}
                    for inv in billed.get(order.id, [])
                ],
                "billedTotal": round(sum(inv.total or 0 for inv in billed.get(order.id, [])), 2),
            }
            for order in orders
        ]
    }


@router.get("/uploads")
def list_uploads(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    client_ids = scoped_client_ids(db, user)
    if not client_ids:
        return {"uploads": []}

    query = db.query(Upload).filter(Upload.client_id.in_(client_ids))
    # Clients only see documents the CA has shared with them.
    if roles.normalize(user.role) == roles.BUSINESS_USER:
        query = query.filter(Upload.visible_to_client.is_(True))

    uploads = query.order_by(Upload.created_at.desc()).all()
    return {"uploads": [serialize_upload(db, upload) for upload in uploads]}


def serialize_upload(db: Session, upload: Upload) -> dict:
    client = db.get(Client, upload.client_id)
    uploader = db.get(User, upload.uploaded_by)
    return {
        "id": upload.id,
        "clientId": upload.client_id,
        "clientName": client.name if client else "",
        "uploadedBy": upload.uploaded_by,
        "uploadedByName": uploader.name if uploader else "",
        "uploadedByRole": uploader.role if uploader else "",
        "fileName": upload.file_name,
        "fileType": upload.file_type,
        "status": upload.status,
        "parsedRows": upload.parsed_rows,
        "validationErrors": json.loads(upload.validation_errors or "[]"),
        "gstin": upload.gstin,
        "financialYear": upload.financial_year,
        "taxPeriod": upload.tax_period,
        "documentType": upload.document_type,
        "sourceType": upload.source_type,
        "checksum": upload.checksum,
        "visibleToClient": upload.visible_to_client,
        "objectKey": upload.object_key,
        "createdAt": upload.created_at,
    }
