"""Reconcile a client's books (Tally) invoices against their GSTR-2A/2B data.

Matching runs in two passes:

1. **Exact** — a normalized ``GSTIN:INVOICE_NO`` key, with a small amount
   tolerance.
2. **Fuzzy** — for anything still unmatched, find the best GSTR invoice from the
   *same supplier GSTIN* whose invoice number is a close fuzzy match (handles
   leading zeros, OCR slips, minor typos) and whose amount is within tolerance.

Fuzzy matching uses RapidFuzz when available and falls back to the stdlib
``difflib`` ratio so the module keeps working without the dependency.
"""

import json
import re
from collections import defaultdict

from sqlalchemy.orm import Session

from app.db.models import Invoice, ReconciliationJob


# Fuzzy match acceptance thresholds.
INVOICE_SIMILARITY_THRESHOLD = 82  # 0–100 fuzzy score on the invoice number
AMOUNT_ABS_TOLERANCE = 1.0         # rupees
AMOUNT_PCT_TOLERANCE = 0.01        # 1% of the invoice total


def _similarity(a: str, b: str) -> float:
    """Return a 0–100 similarity score, preferring RapidFuzz."""
    if not a or not b:
        return 0.0
    try:
        from rapidfuzz import fuzz

        return float(fuzz.ratio(a, b))
    except ImportError:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a, b).ratio() * 100


def _clean_invoice_no(invoice_no: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (invoice_no or "").upper())


def normalize_key(invoice_no: str, supplier_gstin: str) -> str:
    clean_invoice = re.sub(r"[^A-Z0-9]", "", invoice_no.upper())
    clean_gstin = re.sub(r"[^A-Z0-9]", "", supplier_gstin.upper())
    return f"{clean_gstin}:{clean_invoice}"


def _amounts_match(a: float, b: float) -> bool:
    return abs(a - b) <= max(AMOUNT_ABS_TOLERANCE, AMOUNT_PCT_TOLERANCE * max(abs(a), abs(b)))


def _best_fuzzy_partner(invoice: Invoice, candidates: list[Invoice], used: set[int]) -> tuple[Invoice | None, float]:
    """Best same-GSTIN GSTR invoice by fuzzy invoice-number similarity."""
    target = _clean_invoice_no(invoice.invoice_no)
    best: Invoice | None = None
    best_score = 0.0
    for candidate in candidates:
        if candidate.id in used:
            continue
        score = _similarity(target, _clean_invoice_no(candidate.invoice_no))
        # Nudge ties toward the closer amount.
        if _amounts_match(invoice.total or 0, candidate.total or 0):
            score += 0.5
        if score > best_score:
            best_score, best = score, candidate
    return best, best_score


def run_reconciliation(db: Session, client_id: int, user_id: int) -> dict:
    books = db.query(Invoice).filter(Invoice.client_id == client_id, Invoice.source == "books").all()
    gstr = db.query(Invoice).filter(Invoice.client_id == client_id, Invoice.source == "gstr").all()

    gstr_by_key = {item.normalized_key: item for item in gstr}
    gstr_by_gstin: dict[str, list[Invoice]] = defaultdict(list)
    for item in gstr:
        gstr_by_gstin[item.supplier_gstin].append(item)

    summary = {"total": len(books), "matched": 0, "fuzzyMatched": 0, "mismatched": 0, "missing": 0, "duplicates": 0}
    seen_keys: set[str] = set()
    used_gstr: set[int] = set()

    # Pass 1 runs to completion over every invoice before pass 2 starts. If the
    # two were interleaved, a fuzzy match could consume a GSTR row that is the
    # *exact* counterpart of a later invoice — leaving the genuine pair
    # reported as "Missing" and the wrong pair as "Mismatched".
    unmatched: list[Invoice] = []

    for invoice in books:
        if invoice.normalized_key in seen_keys:
            invoice.status = "Duplicate"
            invoice.risk = "High"
            summary["duplicates"] += 1
            continue
        seen_keys.add(invoice.normalized_key)

        # Pass 1: exact key match.
        partner = gstr_by_key.get(invoice.normalized_key)
        if partner and partner.id not in used_gstr:
            used_gstr.add(partner.id)
            if _amounts_match(invoice.total or 0, partner.total or 0):
                invoice.status = partner.status = "Matched"
                invoice.risk = "Low"
                summary["matched"] += 1
            else:
                invoice.status = partner.status = "Mismatched"
                invoice.risk = partner.risk = "Medium"
                summary["mismatched"] += 1
            continue

        unmatched.append(invoice)

    for invoice in unmatched:
        # Pass 2: fuzzy match against remaining GSTR invoices from the same supplier.
        candidate, score = _best_fuzzy_partner(invoice, gstr_by_gstin.get(invoice.supplier_gstin, []), used_gstr)
        # A fuzzy pairing must agree on the amount as well as the number.
        #
        # Sequential numbering makes a supplier's own invoices highly similar to
        # each other — "HIG/26-27/00312" and "HIG/26-27/00412" score about 92% —
        # so similarity alone will pair an invoice the supplier never filed with
        # some *other* invoice's counterpart. That does double damage: the
        # unfiled invoice is reported as a mere amount mismatch, and the invoice
        # whose counterpart was stolen is reported as missing.
        #
        # Fuzzy matching exists for a mistyped or misread invoice *number*; the
        # value should still line up. When it does not, leaving the invoice
        # unmatched is the safer answer — "missing" sends it for review, whereas
        # a false pairing hides a genuine non-filing and corrupts a good record.
        if candidate and score >= INVOICE_SIMILARITY_THRESHOLD and _amounts_match(
            invoice.total or 0, candidate.total or 0
        ):
            used_gstr.add(candidate.id)
            invoice.status = candidate.status = "Matched"
            invoice.risk = "Low"
            summary["matched"] += 1
            summary["fuzzyMatched"] += 1
            continue

        # No counterpart at all: present in books, absent from GSTR.
        invoice.status = "Missing"
        invoice.risk = "Medium"
        summary["missing"] += 1

    # json.dumps, not str(): a Python repr uses single quotes, so the column
    # named summary_json held text that json.loads cannot read back.
    job = ReconciliationJob(
        client_id=client_id, run_by=user_id, status="completed", summary_json=json.dumps(summary)
    )
    db.add(job)
    db.commit()
    return {"jobId": job.id, "status": "completed", "summary": summary}
