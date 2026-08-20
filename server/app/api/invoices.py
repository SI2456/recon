from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, scoped_client_ids
from app.db.models import Invoice, User
from app.db.session import get_db


router = APIRouter()


@router.get("")
def list_invoices(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    client_ids = scoped_client_ids(db, user)
    invoices = (
        db.query(Invoice)
        .filter(Invoice.client_id.in_(client_ids))
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .all()
        if client_ids
        else []
    )
    return {
        "invoices": [
            {
                "id": invoice.id,
                "client_id": invoice.client_id,
                "invoice_no": invoice.invoice_no,
                "supplier": invoice.supplier,
                "supplier_gstin": invoice.supplier_gstin,
                "invoice_date": invoice.invoice_date,
                "hsn": invoice.hsn,
                "recipient_gstin": invoice.recipient_gstin,
                "place_of_supply": invoice.place_of_supply,
                "document_type": invoice.document_type,
                "taxable": invoice.taxable,
                "cgst": invoice.cgst,
                "sgst": invoice.sgst,
                "igst": invoice.igst,
                "cess": invoice.cess,
                "gst": invoice.gst,
                "total": invoice.total,
                "source": invoice.source,
                "status": invoice.status,
                "risk": invoice.risk,
            }
            for invoice in invoices
        ]
    }
