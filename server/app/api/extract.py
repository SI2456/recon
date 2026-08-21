"""Document extraction details — the CA's invoice verification screen.

Backs ``DocumentVerificationModal``: GET returns every field pulled out of an
uploaded invoice, PATCH saves the CA's corrections back.

Where the extraction pipeline (``extract.py``) has written a
``<stem>_extracted.json`` sidecar next to the stored file, that is the richest
source and is used directly. Otherwise the response is assembled from the
parsed ``Invoice`` row, and fields that were never captured come back empty.

Two deliberate differences from the legacy stdlib implementation this replaces:

* **Access is scoped.** The old handler looked documents up by raw id with no
  ownership check, so any signed-in user could read any client's invoice. Every
  lookup here goes through ``ensure_client_scope``.
* **Nothing is invented.** The old handler substituted a hard-coded GSTIN and
  supplier name when extraction came up empty. In a compliance tool a fabricated
  identifier is worse than a blank one, so missing values stay missing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import ensure_client_scope, get_current_user, require_roles
from app.core import roles
from app.core.security import decode_access_token
from app.db.models import FraudAlert, Invoice, Upload, User
from app.db.session import get_db
from app.services import integrity
from app.services.reconciliation import normalize_key
from app.services.storage import UPLOAD_ROOT, read_bytes, use_object_storage


router = APIRouter()

# Mounted separately at /api/uploads so the PDF viewer can reach
# /api/uploads/file/{id}.
files_router = APIRouter()

# --- lookup -------------------------------------------------------------------


def _resolve(db: Session, document_id: str) -> tuple[Upload | None, Invoice | None]:
    """Find the upload and/or invoice a document id refers to.

    The modal is opened from several places and may pass an upload id, an
    invoice id, or an invoice number, so all three are accepted.
    """
    upload: Upload | None = None
    invoice: Invoice | None = None

    # A numeric id means one thing or the other, never both. Looking the number
    # up in both tables and pairing the hits would splice together two
    # unrelated documents that merely share an id — upload #2's file shown
    # beside invoice #2's amounts.
    if document_id.isdigit():
        numeric = int(document_id)
        upload = db.get(Upload, numeric)
        if upload is not None:
            invoice = db.query(Invoice).filter(Invoice.upload_id == upload.id).first()
        else:
            invoice = db.get(Invoice, numeric)

    if invoice is None and upload is None:
        invoice = db.query(Invoice).filter(Invoice.invoice_no == document_id).first()
    if upload is None:
        upload = db.query(Upload).filter(Upload.file_name == document_id).first()
    # Pair up only through the real relationship.
    if upload is None and invoice is not None and invoice.upload_id:
        upload = db.get(Upload, invoice.upload_id)
    # An upload with no invoice yet (uploaded but not processed) still resolves,
    # so the CA can see what is there before pressing Process.
    if invoice is None and upload is not None:
        invoice = db.query(Invoice).filter(Invoice.upload_id == upload.id).first()

    return upload, invoice


def _authorize(db: Session, user: User, upload: Upload | None, invoice: Invoice | None) -> None:
    client_id = upload.client_id if upload else (invoice.client_id if invoice else None)
    if client_id is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    ensure_client_scope(db, user, client_id)


# --- extraction sidecar -------------------------------------------------------


def _sidecar_path(upload: Upload | None) -> Path | None:
    """Locate the ``<stem>_extracted.json`` written by the OCR pipeline."""
    if upload is None or not upload.object_key:
        return None
    # Object storage has no sibling files to read.
    if use_object_storage():
        return None

    stored = UPLOAD_ROOT / upload.object_key
    stem = stored.stem
    candidates = [
        stored.with_name(f"{stem}_extracted.json"),
        stored.with_suffix(".json"),
        # Older uploads were stored flat in the uploads root.
        UPLOAD_ROOT / f"{stem}_extracted.json",
        UPLOAD_ROOT / f"{Path(upload.file_name or '').stem}_extracted.json",
    ]
    return next((path for path in candidates if path.is_file()), None)


# The legacy server wrote a placeholder sidecar whenever extraction produced
# nothing, stamping it "extracted_hsn_sac" and filling the supplier with the
# PDF's filename and a hard-coded GSTIN. Those files are on disk and look like
# real extractions, so they are rejected by their marker — the genuine OCR
# pipeline stamps the model name ("qwen2.5vl") instead.
_LEGACY_PLACEHOLDER_TYPE = "extracted_hsn_sac"


def _load_sidecar(upload: Upload | None) -> dict:
    path = _sidecar_path(upload)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("type") == _LEGACY_PLACEHOLDER_TYPE:
        return {}
    return data


# --- shaping ------------------------------------------------------------------


def _section(data: dict, key: str) -> dict:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _text(*candidates) -> str:
    """First non-empty candidate as a string; empty when nothing is known."""
    for value in candidates:
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in ("none", "null"):
            return text
    return ""


def _money(*candidates) -> str:
    for value in candidates:
        if value is None or value == "":
            continue
        try:
            return f"{float(str(value).replace(',', '')):.2f}"
        except (TypeError, ValueError):
            text = str(value).strip()
            if text:
                return text
    return "0.00"


DEFAULT_TABLE_HEADERS = ["#", "Item Description", "HSN/SAC", "Qty", "Rate", "Taxable", "GST", "Total"]

_LINE_ITEM_HSN_KEYS = ("hsn_sac", "hsn", "sac", "hsn_code", "hsnCode")


def _first_line_item_hsn(data: dict) -> str:
    """Fall back to the first line item's code when no invoice-level one exists."""
    items = data.get("line_items")
    if not isinstance(items, list):
        return ""
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in _LINE_ITEM_HSN_KEYS:
            value = _text(item.get(key))
            if value:
                return value
    return ""


def build_details(document_id: str, upload: Upload | None, invoice: Invoice | None, data: dict) -> dict:
    supplier = _section(data, "supplier")
    buyer = _section(data, "buyer")
    tax = _section(data, "tax_summary")
    amounts = _section(data, "amount_summary")
    payment = _section(data, "payment")
    order = _section(data, "order_info")

    half_gst = f"{(invoice.gst or 0) / 2:.2f}" if invoice and invoice.gst else ""
    headers = data.get("table_headers")

    return {
        "id": document_id,
        "uploadId": str(upload.id) if upload else (str(invoice.upload_id) if invoice and invoice.upload_id else document_id),
        "fileName": _text(upload.file_name if upload else "", data.get("document_title")),
        "invoiceInfo": {
            "invoiceNumber": _text(data.get("invoice_number"), data.get("invoice_no"), invoice.invoice_no if invoice else ""),
            "invoiceDate": _text(data.get("invoice_date"), invoice.invoice_date if invoice else ""),
            "invoiceType": _text(data.get("invoice_type")) or "Tax Invoice",
            "documentTitle": _text(data.get("document_title")) or "TAX INVOICE",
            "poNumber": _text(order.get("po_number"), data.get("po_number")),
            "dueDate": _text(data.get("due_date")),
            "currency": _text(data.get("currency")) or "INR",
        },
        "supplierInfo": {
            "supplierName": _text(supplier.get("name"), data.get("supplier_name"), invoice.supplier if invoice else ""),
            "supplierGstin": _text(supplier.get("gstin"), data.get("supplier_gstin"), invoice.supplier_gstin if invoice else ""),
            "supplierAddress": _text(supplier.get("address"), data.get("supplier_address")),
            "supplierState": _text(supplier.get("state")),
            "supplierCity": _text(supplier.get("city")),
            "supplierPin": _text(supplier.get("pin")),
            "supplierPhone": _text(supplier.get("phone")),
            "supplierEmail": _text(supplier.get("email")),
        },
        "buyerInfo": {
            "buyerName": _text(buyer.get("name"), data.get("buyer_name")),
            "buyerGstin": _text(buyer.get("gstin"), data.get("buyer_gstin")),
            "buyerState": _text(buyer.get("state")),
            "billingAddress": _text(buyer.get("billing_address")),
            "shippingAddress": _text(buyer.get("shipping_address")),
            "placeOfSupply": _text(data.get("place_of_supply")),
        },
        "productInfo": {
            "lineItems": data.get("line_items") if isinstance(data.get("line_items"), list) else [],
            "tableHeaders": headers if isinstance(headers, list) and headers else DEFAULT_TABLE_HEADERS,
            # The HSN/SAC drives the rate cross-check, so it has to be visible
            # and correctable rather than buried in the line items.
            "hsnSac": _text(
                invoice.hsn if invoice else "",
                data.get("hsn"),
                data.get("hsn_sac"),
                _first_line_item_hsn(data),
            ),
            "subtotal": _money(amounts.get("subtotal"), amounts.get("taxable_amount"), invoice.taxable if invoice else None),
            "taxableAmount": _money(tax.get("taxable_amount"), amounts.get("taxable_amount"), invoice.taxable if invoice else None),
            "grandTotal": _money(amounts.get("grand_total"), invoice.total if invoice else None),
            "totalInWords": _text(amounts.get("total_in_words")),
        },
        "taxInfo": {
            "cgstRate": _text(tax.get("cgst_rate")),
            "sgstRate": _text(tax.get("sgst_rate")),
            "cgstAmount": _money(tax.get("cgst_amount"), half_gst),
            "sgstAmount": _money(tax.get("sgst_amount"), half_gst),
            "totalTaxAmount": _money(tax.get("total_tax"), invoice.gst if invoice else None),
        },
        "paymentInfo": {
            "balanceDue": _money(amounts.get("balance_due")),
            "bankName": _text(payment.get("bank_name")),
            "accountNumber": _text(payment.get("account_number")),
            "ifscCode": _text(payment.get("ifsc_code")),
            "accountHolder": _text(payment.get("account_holder")),
            "branch": _text(payment.get("branch")),
        },
    }


# --- routes -------------------------------------------------------------------


_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
}


def _user_from_token(db: Session, token: str) -> User:
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = db.get(User, int(payload["sub"]))
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


@files_router.get("/file/{document_id:path}")
def get_file(
    document_id: str,
    token: str = Query("", description="JWT, for browser contexts that cannot set headers"),
    db: Session = Depends(get_db),
) -> Response:
    """Stream the stored document so the viewer can display it inline.

    Authentication comes from a query parameter rather than the usual header
    because this URL is loaded by an ``<iframe>`` and an anchor target — neither
    can attach an ``Authorization`` header. The token is the same JWT and is
    validated identically, and access is still scoped to the caller's clients.

    The trade-off is that the token appears in the URL, where it can reach
    server logs and browser history. Prefer issuing a short-lived,
    download-only token here if this ever runs anywhere but localhost.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    user = _user_from_token(db, token)

    upload, invoice = _resolve(db, document_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="No stored file for this document.")
    _authorize(db, user, upload, invoice)

    try:
        content = read_bytes(upload.object_key)
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=410, detail="The stored file is no longer available.")

    suffix = Path(upload.file_name or upload.object_key or "").suffix.lower()
    media_type = _CONTENT_TYPES.get(suffix, "application/octet-stream")
    return Response(
        content=content,
        media_type=media_type,
        # "inline" so the browser renders it in place instead of downloading.
        headers={"Content-Disposition": f'inline; filename="{Path(upload.file_name or "document").name}"'},
    )


@router.get("/fraud/{document_id:path}")
def get_fraud_assessment(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Real integrity + fraud findings for one document.

    Runs the same deterministic checks as the batch fraud job so the
    verification screen shows what is actually wrong with this invoice rather
    than a fixed illustration.
    """
    upload, invoice = _resolve(db, document_id)
    if upload is None and invoice is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    _authorize(db, user, upload, invoice)

    if invoice is None:
        return {
            "assessment": {
                "score": 0,
                "findings": [],
                "checks": [],
                "alert": None,
                "invoiceKnown": False,
                "message": "This document has not been processed yet, so there is nothing to check. Run Process first.",
            }
        }

    assessment = integrity.assess_invoice(invoice)

    # Duplicates are only visible against the rest of the client's invoices.
    siblings = db.query(Invoice).filter(Invoice.client_id == invoice.client_id).all()
    duplicates = integrity.check_duplicates(siblings)
    target = next((row for row in siblings if row.id == invoice.id), None)
    findings = list(assessment.findings) + (duplicates.get(id(target), []) if target is not None else [])
    score = integrity.score_findings(findings)

    alert = (
        db.query(FraudAlert)
        .filter(FraudAlert.invoice_id == invoice.id)
        .order_by(FraudAlert.risk.desc())
        .first()
    )

    # Every check that ran, so the UI can show passes as well as failures.
    failed = {finding.check for finding in findings}
    checks = [
        {"key": key, "label": label, "passed": key not in failed}
        for key, label in (
            ("format", "Invoice format & required fields"),
            ("gstin", "Supplier GSTIN validity"),
            ("hsn", "HSN/SAC classification"),
            ("totals", "Amount & tax arithmetic"),
            ("duplicate", "Duplicate claim"),
        )
    ]

    return {
        "assessment": {
            "score": score,
            "riskLabel": _risk_label(score),
            "findings": [finding.as_dict() for finding in findings],
            "checks": checks,
            "invoiceKnown": True,
            "invoiceStatus": invoice.status,
            "alert": (
                {
                    "id": alert.id,
                    "type": alert.type,
                    "risk": alert.risk,
                    "reason": alert.reason,
                    "shap": json.loads(alert.shap_json or "[]"),
                    "status": alert.status,
                }
                if alert
                else None
            ),
        }
    }


def _risk_label(score: int) -> str:
    if score >= 70:
        return "Critical"
    if score >= 50:
        return "High"
    if score >= 25:
        return "Medium"
    return "Low"


@router.get("/details/{document_id:path}")
def get_details(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    upload, invoice = _resolve(db, document_id)
    if upload is None and invoice is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    _authorize(db, user, upload, invoice)
    return {"details": build_details(document_id, upload, invoice, _load_sidecar(upload))}


@router.patch("/details/{document_id:path}")
def save_details(
    document_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(roles.TAX_REVIEWER, roles.ADMIN)),
) -> dict:
    """Persist the CA's corrections to the invoice row and the sidecar."""
    upload, invoice = _resolve(db, document_id)
    if upload is None and invoice is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    _authorize(db, user, upload, invoice)

    invoice_info = payload.get("invoiceInfo") or {}
    supplier_info = payload.get("supplierInfo") or {}
    product_info = payload.get("productInfo") or {}
    tax_info = payload.get("taxInfo") or {}

    def amount(value) -> float:
        try:
            return float(str(value).replace(",", "").replace("₹", "").strip() or 0)
        except (TypeError, ValueError):
            return 0.0

    if invoice is not None:
        invoice.invoice_no = _text(invoice_info.get("invoiceNumber")) or invoice.invoice_no
        invoice.supplier = _text(supplier_info.get("supplierName"))
        invoice.supplier_gstin = _text(supplier_info.get("supplierGstin")).upper()
        invoice.invoice_date = _text(invoice_info.get("invoiceDate")) or invoice.invoice_date
        invoice.taxable = amount(product_info.get("taxableAmount"))
        invoice.gst = amount(tax_info.get("totalTaxAmount"))
        invoice.total = amount(product_info.get("grandTotal"))
        if "hsnSac" in product_info:
            # Digits only, matching how the parsers store it, so the rate
            # cross-check can find the code in the GST schedule.
            invoice.hsn = re.sub(r"[^0-9]", "", _text(product_info.get("hsnSac")))[:8]
        # The match key is derived from the number and GSTIN, so an edit to
        # either must rebuild it or reconciliation will miss the counterpart.
        invoice.normalized_key = normalize_key(invoice.invoice_no, invoice.supplier_gstin)
        db.commit()
        db.refresh(invoice)

    # Mirror the correction into the extraction sidecar when one exists, so a
    # re-read of the document shows the CA's values rather than the raw OCR.
    path = _sidecar_path(upload)
    if path is not None:
        data = _load_sidecar(upload)
        data["invoice_number"] = _text(invoice_info.get("invoiceNumber"), data.get("invoice_number"))
        data["invoice_date"] = _text(invoice_info.get("invoiceDate"), data.get("invoice_date"))
        supplier = _section(data, "supplier")
        supplier.update({
            "name": _text(supplier_info.get("supplierName"), supplier.get("name")),
            "gstin": _text(supplier_info.get("supplierGstin"), supplier.get("gstin")),
            "address": _text(supplier_info.get("supplierAddress"), supplier.get("address")),
        })
        data["supplier"] = supplier
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # A read-only store must not fail the save; the DB is the record.

    return {"details": build_details(document_id, upload, invoice, _load_sidecar(upload))}
