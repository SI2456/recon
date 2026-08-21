"""Test data helpers."""

from __future__ import annotations

from app.services.integrity import gstin_check_digit


def make_gstin(state: str = "27", pan: str = "AAACA1234F", entity: str = "1") -> str:
    """Build a structurally valid GSTIN with a correct check digit.

    Hand-written GSTINs almost always fail the mod-36 checksum, which the
    integrity layer treats as a fabricated supplier — so a test using one would
    be asserting against a finding it accidentally created.
    """
    body = f"{state}{pan}{entity}Z"
    return f"{body}{gstin_check_digit(body)}"


BOOKS_CSV_HEADER = "Invoice No,Supplier,GSTIN,Date,Taxable,GST,Total,HSN\n"


def books_csv(invoice_no: str, gstin: str, *, taxable: int = 1000, gst: int = 180) -> bytes:
    total = taxable + gst
    return (
        BOOKS_CSV_HEADER + f"{invoice_no},Apex Steel,{gstin},2026-07-01,{taxable},{gst},{total},7214\n"
    ).encode()
