"""Match invoices to the purchase orders they were raised against.

A purchase order is the only record of what was actually *agreed* before a
supply happened, which makes it the one piece of evidence that can contradict
an invoice on its own terms. Checking an invoice against itself can prove it is
internally consistent; only the order can show it is for more than was ordered,
or that nothing was ordered at all.

Two findings come out of this, both aimed at the first link in the ITC chain:

``PO_VALUE_EXCEEDED``
    The invoice bills materially more than the order it cites — the paper
    trail of an inflated claim.
``PO_NOT_FOUND``
    The invoice cites a purchase-order number that does not exist in the
    uploaded orders.

Note what is deliberately *not* a finding: an invoice with no PO reference at
all. Plenty of businesses do not raise orders for every purchase, so treating a
missing reference as suspicious would bury the reviewer in noise.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.db.models import Invoice, PurchaseOrder
from app.services.integrity import Finding


# An invoice may legitimately exceed its order a little — freight, rounding, a
# partial rate revision. Beyond this it is a discrepancy worth a human look.
VALUE_TOLERANCE_PCT = 5.0
VALUE_TOLERANCE_ABS = 100.0


def normalize_po(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def po_key(po_number: str, supplier_gstin: str) -> str:
    """Same shape as the invoice match key, so lookups are symmetric."""
    return f"{normalize_po(supplier_gstin)}:{normalize_po(po_number)}"


def link_invoices_to_orders(db: Session, client_id: int) -> dict:
    """Attach each invoice to its purchase order, where one is cited.

    Matching is by PO number rather than by amount: the number is what the
    invoice actually claims, and matching on value would happily pair an
    inflated invoice with some unrelated order of the right size — hiding the
    very thing this is meant to surface.
    """
    orders = db.query(PurchaseOrder).filter(PurchaseOrder.client_id == client_id).all()
    invoices = db.query(Invoice).filter(Invoice.client_id == client_id).all()

    by_key = {order.normalized_key: order for order in orders}
    by_number: dict[str, list[PurchaseOrder]] = {}
    for order in orders:
        by_number.setdefault(normalize_po(order.po_number), []).append(order)

    linked = unmatched = 0
    for invoice in invoices:
        cited = normalize_po(invoice.po_number)
        if not cited:
            invoice.po_id = None
            continue

        order = by_key.get(po_key(invoice.po_number, invoice.supplier_gstin))
        if order is None:
            # Fall back to the number alone: the order may predate the GSTIN
            # being recorded, or name the supplier differently.
            candidates = by_number.get(cited, [])
            order = candidates[0] if len(candidates) == 1 else None

        if order is None:
            invoice.po_id = None
            unmatched += 1
            continue

        invoice.po_id = order.id
        order.status = "Matched"
        linked += 1

    db.commit()
    return {"orders": len(orders), "linked": linked, "citedButNotFound": unmatched}


def check_against_order(invoice, order) -> list[Finding]:
    """Compare one invoice with the order it cites."""
    if order is None:
        if normalize_po(getattr(invoice, "po_number", "")):
            return [Finding(
                "PO_NOT_FOUND", "purchase_order", 1, 30, "Cited purchase order not found",
                f"The invoice cites purchase order '{invoice.po_number}', which is not among the "
                "uploaded orders. Either the order is missing or the reference is wrong.")]
        return []

    invoice_value = float(getattr(invoice, "total", 0) or 0)
    order_value = float(getattr(order, "total", 0) or 0)
    if order_value <= 0 or invoice_value <= 0:
        return []

    excess = invoice_value - order_value
    allowed = max(VALUE_TOLERANCE_ABS, order_value * VALUE_TOLERANCE_PCT / 100)
    if excess > allowed:
        pct = excess / order_value * 100
        return [Finding(
            "PO_VALUE_EXCEEDED", "purchase_order", 1, 45, "Invoice exceeds the purchase order",
            f"Ordered {order_value:,.2f} on '{order.po_number}' but billed {invoice_value:,.2f} "
            f"— {excess:,.2f} more ({pct:.1f}%). Billing above the agreed order is how an "
            "inflated input tax credit claim is dressed up as a genuine purchase.")]
    return []


def findings_for_client(db: Session, client_id: int) -> dict[int, list[Finding]]:
    """Purchase-order findings for every invoice of a client, keyed by id."""
    orders = {o.id: o for o in db.query(PurchaseOrder).filter(PurchaseOrder.client_id == client_id).all()}
    if not orders:
        return {}  # No orders uploaded: nothing to compare against, so stay silent.

    results: dict[int, list[Finding]] = {}
    for invoice in db.query(Invoice).filter(Invoice.client_id == client_id).all():
        found = check_against_order(invoice, orders.get(invoice.po_id))
        if found:
            results[invoice.id] = found
    return results
