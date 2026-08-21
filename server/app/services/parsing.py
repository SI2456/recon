"""Turn uploaded files (Tally CSV, GSTR-2A/2B JSON, PDF invoices) into
canonical invoice rows that the reconciliation engine can consume.

Every parser returns ``(rows, errors)`` where ``rows`` is a list of
``ParsedInvoice`` dataclasses and ``errors`` is a list of human-readable
validation messages surfaced back to the uploader.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.core.config import settings
from app.services.vision_ocr import extract_invoice_from_image, extract_invoice_from_pages


# --- canonical row -----------------------------------------------------------


@dataclass
class ParsedInvoice:
    invoice_no: str
    supplier: str
    supplier_gstin: str
    invoice_date: str
    taxable: float
    gst: float
    total: float
    hsn: str = ""
    # Tax components kept alongside the combined figure: an intra-state supply
    # must carry CGST+SGST and an inter-state one IGST, so the split is what
    # makes place-of-supply validation possible.
    cgst: float = 0.0
    sgst: float = 0.0
    igst: float = 0.0
    cess: float = 0.0
    recipient_gstin: str = ""
    place_of_supply: str = ""
    po_number: str = ""
    document_type: str = "invoice"
    warnings: list[str] = field(default_factory=list)

    def is_usable(self) -> bool:
        # A row needs at least an invoice number and a value to be reconcilable.
        return bool(self.invoice_no) and self.total > 0


@dataclass
class ParsedPurchaseOrder:
    """A purchase order line, normalised the same way invoices are.

    Deliberately has no tax fields: an order is not a tax document. What
    matters for reconciliation is who was ordered from, for how much.
    """

    po_number: str
    supplier: str
    supplier_gstin: str
    po_date: str
    total: float
    taxable: float = 0.0
    hsn: str = ""
    description: str = ""
    quantity: float = 0.0
    rate: float = 0.0
    currency: str = "INR"

    def is_usable(self) -> bool:
        return bool(self.po_number) and self.total > 0


# --- header synonyms ---------------------------------------------------------

_COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "invoice_no": ("invoice_no", "invoiceno", "invoicenumber", "invoice", "invno", "inv", "billno", "billnumber", "voucherno", "voucherno", "documentnumber", "docno", "inum"),
    "supplier": ("supplier", "suppliername", "party", "partyname", "vendor", "vendorname", "tradename", "trdnm", "legalname", "name", "sellername"),
    "supplier_gstin": ("supplier_gstin", "suppliergstin", "gstin", "gstno", "gstinno", "ctin", "gstinofsupplier", "partygstin"),
    "invoice_date": ("invoice_date", "invoicedate", "date", "billdate", "documentdate", "docdate", "dt", "idt"),
    "taxable": ("taxable", "taxablevalue", "taxableamount", "txval", "assessablevalue"),
    "gst": ("gst", "gstamount", "tax", "totaltax", "taxamount"),
    "igst": ("igst", "iamt", "igstamount"),
    "cgst": ("cgst", "camt", "cgstamount"),
    "sgst": ("sgst", "samt", "sgstamount", "utgst", "utgstamount"),
    "cess": ("cess", "csamt", "cessamount"),
    "total": ("total", "totalvalue", "invoicevalue", "val", "amount", "grandtotal", "netamount"),
    "hsn": ("hsn", "hsncode", "hsnsac", "hsnsaccode", "sac", "saccode", "hsn_sc", "hsnsc", "chapterheading", "tariffcode"),
    "recipient_gstin": ("recipient_gstin", "recipientgstin", "buyergstin", "buyergstinno", "customergstin", "gstinofrecipient", "ourgstin"),
    "place_of_supply": ("place_of_supply", "placeofsupply", "pos", "posstate", "supplystate", "statecode"),
    "po_number": ("po_number", "ponumber", "pono", "po", "purchaseorder", "purchaseorderno",
                  "purchaseordernumber", "orderno", "ordernumber", "ponum"),
    # An order's own date. Kept separate from invoice_date so a purchase-order
    # export headed "PO Date" resolves, while an invoice file is unaffected.
    "po_date": ("po_date", "podate", "orderdate", "purchaseorderdate", "dateoforder"),
    "quantity": ("quantity", "qty", "units", "nos", "count"),
    "rate": ("rate", "unitrate", "unitprice", "price", "rateperunit"),
    "description": ("description", "item", "itemdescription", "particulars", "product", "goods"),
}

_GSTIN_PATTERN = re.compile(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]")


def _canon(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (header or "").strip().lower())


def _build_header_map(headers: list[str]) -> dict[str, str]:
    """Map each canonical field -> the actual header present in the file."""
    lookup = {_canon(h): h for h in headers if h}
    mapping: dict[str, str] = {}
    for field_name, synonyms in _COLUMN_SYNONYMS.items():
        for syn in synonyms:
            if syn in lookup:
                mapping[field_name] = lookup[syn]
                break
    return mapping


def _to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if cleaned in ("", "-", ".", "-."):
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _normalize_date(value) -> str:
    """Return an ISO ``yyyy-mm-dd`` string when possible, else the raw text."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d.%m.%y", "%d-%b-%Y", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


def _clean_gstin(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


# GST state codes, so a place of supply written as a name still resolves.
_STATE_NAME_CODES: dict[str, str] = {
    "jammukashmir": "01", "jammuandkashmir": "01", "himachalpradesh": "02", "punjab": "03",
    "chandigarh": "04", "uttarakhand": "05", "haryana": "06", "delhi": "07",
    "rajasthan": "08", "uttarpradesh": "09", "bihar": "10", "sikkim": "11",
    "arunachalpradesh": "12", "nagaland": "13", "manipur": "14", "mizoram": "15",
    "tripura": "16", "meghalaya": "17", "assam": "18", "westbengal": "19",
    "jharkhand": "20", "odisha": "21", "orissa": "21", "chhattisgarh": "22",
    "madhyapradesh": "23", "gujarat": "24", "damandiu": "25", "dadranagarhaveli": "26",
    "maharashtra": "27", "andhrapradesh": "28", "karnataka": "29", "goa": "30",
    "lakshadweep": "31", "kerala": "32", "tamilnadu": "33", "puducherry": "34",
    "andamannicobarislands": "35", "telangana": "36", "andhrapradeshnew": "37",
    "ladakh": "38", "othersterritory": "97",
}


def _clean_pos(value) -> str:
    """Two-digit state code from whatever the source calls a place of supply.

    Accepts "27", "27-Maharashtra", "Maharashtra", and free text such as
    "Dakshina Kannada, KARNATAKA, 574142" — OCR frequently returns the whole
    address line rather than the state alone, so the state name is searched
    for inside the string instead of being matched exactly.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    digits = re.match(r"\s*(\d{1,2})\s*(?:[-–—]|$|\s)", raw)
    if digits:
        code = int(digits.group(1))
        if 1 <= code <= 38 or code in (97, 99):
            return f"{code:02d}"
    letters = re.sub(r"[^a-z]", "", raw.lower())
    if not letters:
        return ""
    exact = _STATE_NAME_CODES.get(letters)
    if exact:
        return exact
    # Longest first so "andhrapradesh" is preferred over a shorter substring.
    for name in sorted(_STATE_NAME_CODES, key=len, reverse=True):
        if len(name) >= 4 and name in letters:
            return _STATE_NAME_CODES[name]
    return ""


def _clean_hsn(value) -> str:
    """Digits only. Spreadsheets often hand these over as floats ("8471.0")."""
    raw = str(value or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return re.sub(r"[^0-9]", "", raw)[:8]


def _row_from_mapped(record: dict, header_map: dict[str, str]) -> ParsedInvoice:
    """Build a ParsedInvoice from a raw record using a header map."""

    def get(field_name: str):
        header = header_map.get(field_name)
        return record.get(header) if header else None

    taxable = _to_float(get("taxable"))
    total = _to_float(get("total"))

    # Prefer an explicit GST column, else sum the component taxes.
    gst = _to_float(get("gst"))
    igst = _to_float(get("igst"))
    cgst = _to_float(get("cgst"))
    sgst = _to_float(get("sgst"))
    cess = _to_float(get("cess"))
    components = igst + cgst + sgst + cess
    if gst == 0 and components > 0:
        gst = components

    # Backfill total / taxable when only some values are present.
    if total == 0 and (taxable or gst):
        total = round(taxable + gst, 2)
    if taxable == 0 and total and gst:
        taxable = round(total - gst, 2)

    return ParsedInvoice(
        invoice_no=str(get("invoice_no") or "").strip(),
        supplier=str(get("supplier") or "").strip(),
        supplier_gstin=_clean_gstin(get("supplier_gstin")),
        invoice_date=_normalize_date(get("invoice_date")),
        taxable=taxable,
        gst=gst,
        total=total,
        hsn=_clean_hsn(get("hsn")),
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        cess=cess,
        recipient_gstin=_clean_gstin(get("recipient_gstin")),
        place_of_supply=_clean_pos(get("place_of_supply")),
        po_number=str(get("po_number") or "").strip()[:80],
    )


# --- CSV ---------------------------------------------------------------------


def parse_csv(content: bytes) -> tuple[list[ParsedInvoice], list[str]]:
    errors: list[str] = []
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["CSV file is empty or has no header row."]

    header_map = _build_header_map(list(reader.fieldnames))
    if "invoice_no" not in header_map:
        errors.append(f"Could not find an invoice-number column. Headers seen: {', '.join(reader.fieldnames)}.")
        return [], errors

    rows: list[ParsedInvoice] = []
    for line_no, record in enumerate(reader, start=2):
        row = _row_from_mapped(record, header_map)
        if not row.invoice_no and row.total == 0:
            continue  # skip fully blank lines
        if not row.is_usable():
            errors.append(f"Row {line_no}: skipped (missing invoice number or amount).")
            continue
        rows.append(row)
    return rows, errors


# --- purchase orders ---------------------------------------------------------


def parse_purchase_order_csv(content: bytes) -> tuple[list[ParsedPurchaseOrder], list[str]]:
    errors: list[str] = []
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["The purchase order file is empty or has no header row."]

    header_map = _build_header_map(list(reader.fieldnames))
    if "po_number" not in header_map:
        return [], [
            "Could not find a purchase-order number column. Headers seen: "
            f"{', '.join(reader.fieldnames)}."
        ]

    rows: list[ParsedPurchaseOrder] = []
    for line_no, record in enumerate(reader, start=2):
        def get(name: str):
            header = header_map.get(name)
            return record.get(header) if header else None

        quantity = _to_float(get("quantity"))
        rate = _to_float(get("rate"))
        taxable = _to_float(get("taxable"))
        total = _to_float(get("total"))
        # An order line often states only quantity and rate.
        if total == 0 and quantity and rate:
            total = round(quantity * rate, 2)
        if taxable == 0:
            taxable = total

        row = ParsedPurchaseOrder(
            po_number=str(get("po_number") or "").strip()[:80],
            supplier=str(get("supplier") or "").strip(),
            supplier_gstin=_clean_gstin(get("supplier_gstin")),
            # The order's own date when the file gives one, else whatever
            # generic date column it carries.
            po_date=_normalize_date(get("po_date") or get("invoice_date")),
            total=total,
            taxable=taxable,
            hsn=_clean_hsn(get("hsn")),
            description=str(get("description") or "").strip()[:255],
            quantity=quantity,
            rate=rate,
        )
        if not row.po_number and total == 0:
            continue  # blank line
        if not row.is_usable():
            errors.append(f"Row {line_no}: skipped (missing PO number or value).")
            continue
        rows.append(row)
    return rows, errors


async def parse_purchase_order(filename: str, content: bytes) -> tuple[list[ParsedPurchaseOrder], list[str]]:
    """Read a purchase order from a spreadsheet export or a scanned document."""
    name = (filename or "").lower()
    if name.endswith((".csv", ".tsv")):
        return parse_purchase_order_csv(content)

    # A PDF or image order goes through the same vision pipeline as invoices;
    # extract.py already surfaces order_info.po_number.
    if name.endswith(_IMAGE_EXTENSIONS):
        pages = [content]
    elif name.endswith(".pdf") or content[:5] == b"%PDF-":
        pages, render_error = _render_pdf_to_images(content)
        if render_error:
            return [], [f"Could not render the purchase order for OCR: {render_error}"]
    else:
        return [], [f"Unsupported purchase-order file '{filename}'. Upload a CSV, PDF or image."]

    try:
        data = await extract_invoice_from_pages(pages)
    except httpx.HTTPError:
        return [], [_vlm_unavailable_message()]

    order = data.get("order_info") if isinstance(data.get("order_info"), dict) else {}
    amounts = data.get("amount_summary") if isinstance(data.get("amount_summary"), dict) else {}
    supplier = data.get("supplier") if isinstance(data.get("supplier"), dict) else {}

    total = _to_float(amounts.get("grand_total") or data.get("total"))
    row = ParsedPurchaseOrder(
        po_number=str(order.get("po_number") or data.get("invoice_number") or "").strip()[:80],
        supplier=str(supplier.get("name") or "").strip(),
        supplier_gstin=_clean_gstin(supplier.get("gstin")),
        po_date=_normalize_date(data.get("invoice_date")),
        total=total,
        taxable=_to_float(amounts.get("subtotal")) or total,
        hsn=_clean_hsn(data.get("hsn") or "") or _hsn_from_line_items(data),
        description=str(data.get("document_title") or "").strip()[:255],
    )
    if not row.is_usable():
        return [], ["Could not read a purchase-order number and value from this document."]
    return [row], []


# --- GSTR JSON ---------------------------------------------------------------


def _iter_b2b_sections(data) -> list[dict]:
    """Find GSTR B2B supplier sections anywhere in the document tree."""
    found: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() == "b2b" and isinstance(value, list):
                    found.extend(item for item in value if isinstance(item, dict))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


def parse_gstr_json(content: bytes) -> tuple[list[ParsedInvoice], list[str]]:
    errors: list[str] = []
    try:
        data = json.loads(content.decode("utf-8-sig", errors="replace"))
    except json.JSONDecodeError as exc:
        return [], [f"Invalid JSON: {exc.msg} (line {exc.lineno})."]

    rows: list[ParsedInvoice] = []

    # 1) Official GSTR-2A/2B structure: b2b -> [{ctin, trdnm, inv: [...]}]
    sections = _iter_b2b_sections(data)
    for section in sections:
        ctin = _clean_gstin(section.get("ctin"))
        trade_name = str(section.get("trdnm") or section.get("cfs") or "").strip()
        invoices = section.get("inv")
        if not isinstance(invoices, list):
            continue
        for inv in invoices:
            if not isinstance(inv, dict):
                continue
            # GSTR-2A nests each line under "itms" -> "itm_det" with the tax
            # columns abbreviated (iamt/camt/samt/csamt). GSTR-2B uses "items"
            # with the amounts spelled out flat (igst/cgst/sgst/cess). Both are
            # accepted, because 2B is the statement reconciliation actually
            # runs against and reading only the 2A shape left every 2B row with
            # a zero taxable value.
            raw_items = inv.get("itms")
            if not isinstance(raw_items, list):
                raw_items = inv.get("items")
            items = raw_items if isinstance(raw_items, list) else []

            taxable = gst = 0.0
            igst = cgst = sgst = cess = 0.0
            hsn = ""
            for item in items:
                det = item.get("itm_det", item) if isinstance(item, dict) else {}
                taxable += _to_float(det.get("txval"))
                igst += _to_float(det.get("iamt") if det.get("iamt") is not None else det.get("igst"))
                cgst += _to_float(det.get("camt") if det.get("camt") is not None else det.get("cgst"))
                sgst += _to_float(det.get("samt") if det.get("samt") is not None else det.get("sgst"))
                cess += _to_float(det.get("csamt") if det.get("csamt") is not None else det.get("cess"))
                gst = igst + cgst + sgst + cess
                # A GSTR line can carry several HSNs; the first identifies the
                # principal supply, which is what the rate check needs.
                if not hsn:
                    hsn = _clean_hsn(det.get("hsn_sc") or det.get("hsn") or "")
            total = _to_float(inv.get("val"))
            if taxable == 0 and total and gst:
                taxable = round(total - gst, 2)
            if total == 0:
                total = round(taxable + gst, 2)
            row = ParsedInvoice(
                invoice_no=str(inv.get("inum") or "").strip(),
                supplier=trade_name,
                supplier_gstin=ctin,
                invoice_date=_normalize_date(inv.get("dt") or inv.get("idt")),
                taxable=taxable,
                gst=gst,
                total=total,
                hsn=hsn,
                cgst=cgst,
                sgst=sgst,
                igst=igst,
                cess=cess,
                place_of_supply=_clean_pos(inv.get("pos")),
                document_type="invoice",
            )
            if row.is_usable():
                rows.append(row)

    if rows:
        return rows, errors

    # 2) Fallback: a flat list of invoice objects, or {invoices|data: [...]}.
    flat = data
    if isinstance(data, dict):
        for key in ("invoices", "data", "records", "rows"):
            if isinstance(data.get(key), list):
                flat = data[key]
                break
    if isinstance(flat, list) and flat and isinstance(flat[0], dict):
        header_map = _build_header_map(list(flat[0].keys()))
        if "invoice_no" in header_map:
            for record in flat:
                if not isinstance(record, dict):
                    continue
                row = _row_from_mapped(record, header_map)
                if row.is_usable():
                    rows.append(row)
        else:
            errors.append("JSON records found but no recognizable invoice-number field.")
    if not rows and not errors:
        errors.append("No GSTR B2B invoices or recognizable invoice records were found in the JSON.")
    return rows, errors


# --- PDF ---------------------------------------------------------------------

# Ordered patterns — the first that matches wins, so put the most specific
# label first. ``_AMOUNT`` allows an optional currency symbol and thousands
# separators (Indian or Western).
_AMOUNT = r"(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*\.?[0-9]*)"
_DATE = r"([0-9]{1,4}[\-\/.][0-9]{1,2}[\-\/.][0-9]{1,4})"

_PDF_INVOICE_NO_PATTERNS = (
    re.compile(r"invoice\s*(?:number|no\.?|#)\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9\-\/]{2,})", re.I),
    re.compile(r"(?:bill|voucher|document)\s*(?:number|no\.?|#)\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9\-\/]{2,})", re.I),
)
_PDF_DATE_PATTERNS = (
    re.compile(r"invoice\s*date\s*[:\-]?\s*" + _DATE, re.I),
    re.compile(r"(?:bill|document)\s*date\s*[:\-]?\s*" + _DATE, re.I),
    re.compile(r"date\s*[:\-]?\s*" + _DATE, re.I),
)
_PDF_TOTAL_PATTERNS = (
    re.compile(r"invoice\s*value\s*[:\-]?\s*" + _AMOUNT, re.I),
    re.compile(r"grand\s*total\s*[:\-]?\s*" + _AMOUNT, re.I),
    re.compile(r"amount\s*payable\s*[:\-]?\s*" + _AMOUNT, re.I),
    re.compile(r"total\s*amount\s*[:\-]?\s*" + _AMOUNT, re.I),
)
_PDF_TAXABLE_PATTERNS = (
    re.compile(r"taxable\s*(?:value|amount)\s*[:\-]?\s*" + _AMOUNT, re.I),
    re.compile(r"net\s*amount\s*[:\-]?\s*" + _AMOUNT, re.I),
)
# Sum every CGST/SGST/IGST/cess amount found in the document.
_PDF_TAX_LINE = re.compile(r"(?:CGST|SGST|UTGST|IGST|CESS)\s*" + _AMOUNT, re.I)

# Individual tax heads, so an intra-state (CGST+SGST) invoice can be told
# apart from an inter-state (IGST) one.
_PDF_CGST = re.compile(r"\bCGST\b[^0-9₹]{0,24}" + _AMOUNT, re.I)
_PDF_SGST = re.compile(r"\b(?:SGST|UTGST)\b[^0-9₹]{0,24}" + _AMOUNT, re.I)
_PDF_IGST = re.compile(r"\bIGST\b[^0-9₹]{0,24}" + _AMOUNT, re.I)

_PDF_POS_PATTERNS = (
    re.compile(r"place\s*of\s*supply\s*[:\-]?\s*([0-9]{1,2})\s*[-–]", re.I),
    re.compile(r"place\s*of\s*supply\s*[:\-]?\s*([A-Za-z ]{3,30})", re.I),
    re.compile(r"state\s*code\s*[:\-]?\s*([0-9]{1,2})", re.I),
)

# HSN/SAC as printed on an invoice, e.g. "HSN: 8471" or "HSN/SAC Code - 998314".
_PDF_HSN_PATTERNS = (
    re.compile(r"HSN\s*/?\s*SAC(?:\s*code)?\s*[:\-]?\s*(\d{2,8})", re.I),
    re.compile(r"\bHSN(?:\s*code)?\s*[:\-]?\s*(\d{2,8})", re.I),
    re.compile(r"\bSAC(?:\s*code)?\s*[:\-]?\s*(\d{2,8})", re.I),
)


def _first_match(patterns, text: str) -> str:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


def _extract_pdf_text(content: bytes) -> tuple[str, str | None]:
    """Return (text, error). Uses pypdf if available; degrades gracefully."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "PDF parsing needs the 'pypdf' package (pip install pypdf) or an OCR engine for scanned invoices."
    try:
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return text, None
    except Exception as exc:  # noqa: BLE001 - surface any pypdf failure to the user
        return "", f"Could not read PDF: {exc}"


def parse_pdf(content: bytes) -> tuple[list[ParsedInvoice], list[str]]:
    text, error = _extract_pdf_text(content)
    if error:
        return [], [error]
    if not text.strip():
        return [], ["No selectable text found in the PDF. It looks scanned and needs OCR (PaddleOCR) to extract invoice data."]

    taxable = _to_float(_first_match(_PDF_TAXABLE_PATTERNS, text))
    total = _to_float(_first_match(_PDF_TOTAL_PATTERNS, text))
    gst = round(sum(_to_float(m) for m in _PDF_TAX_LINE.findall(text)), 2)
    cgst = round(sum(_to_float(m) for m in _PDF_CGST.findall(text)), 2)
    sgst = round(sum(_to_float(m) for m in _PDF_SGST.findall(text)), 2)
    igst = round(sum(_to_float(m) for m in _PDF_IGST.findall(text)), 2)

    if total == 0 and (taxable or gst):
        total = round(taxable + gst, 2)
    if taxable == 0 and total and gst:
        taxable = round(total - gst, 2)

    # Supplier name often appears after a "Sold By" / "Seller" label.
    supplier_match = re.search(r"(?:sold\s*by|seller\s*name|supplier\s*name)\s*[:\-]\s*([A-Za-z0-9 .,&()'-]{3,80})", text, re.I)

    gstin_match = _GSTIN_PATTERN.search(text.upper())
    row = ParsedInvoice(
        invoice_no=_first_match(_PDF_INVOICE_NO_PATTERNS, text).strip(),
        supplier=supplier_match.group(1).strip() if supplier_match else "",
        supplier_gstin=gstin_match.group(0) if gstin_match else "",
        invoice_date=_normalize_date(_first_match(_PDF_DATE_PATTERNS, text)),
        taxable=taxable,
        gst=gst,
        total=total,
        hsn=_clean_hsn(_first_match(_PDF_HSN_PATTERNS, text)),
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        place_of_supply=_clean_pos(_first_match(_PDF_POS_PATTERNS, text)),
    )

    if not row.is_usable():
        return [], ["Could not extract an invoice number and amount from the PDF text. Manual entry may be required."]
    return [row], []


# --- vision-language OCR (Ollama) --------------------------------------------

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif")


_HSN_HEADER = re.compile(r"hsn|sac", re.I)


def _hsn_from_line_items(data: dict) -> str:
    """Pull the HSN/SAC out of the item table by locating its column.

    ``line_items`` are positional lists aligned to ``table_headers``, so the
    code has to be read by column index rather than by key.
    """
    headers = data.get("table_headers")
    items = data.get("line_items")
    if not isinstance(headers, list) or not isinstance(items, list):
        return ""
    column = next((i for i, h in enumerate(headers) if _HSN_HEADER.search(str(h or ""))), None)
    if column is None:
        return ""
    for row in items:
        if isinstance(row, list) and column < len(row):
            code = _clean_hsn(row[column])
            if code:
                return code
        elif isinstance(row, dict):
            code = _clean_hsn(row.get("hsn_sac") or row.get("hsn") or row.get("sac"))
            if code:
                return code
    return ""


def _row_from_vlm(data: dict) -> ParsedInvoice:
    """Map the vision model's JSON output into a canonical invoice row.

    Handles both shapes: the nested schema from ``extract.py`` (supplier /
    tax_summary / amount_summary objects) and the flat keys the fallback
    prompt returns. Nested values are preferred — they come from the
    invoice's summary block, whereas a flat prompt tends to grab whichever
    number it saw first, which is often a line-item value.
    """
    supplier = data.get("supplier") if isinstance(data.get("supplier"), dict) else {}
    buyer = data.get("buyer") if isinstance(data.get("buyer"), dict) else {}
    tax = data.get("tax_summary") if isinstance(data.get("tax_summary"), dict) else {}
    amounts = data.get("amount_summary") if isinstance(data.get("amount_summary"), dict) else {}

    def first(*values) -> float:
        for value in values:
            number = _to_float(value)
            if number:
                return number
        return 0.0

    taxable = first(tax.get("taxable_amount"), amounts.get("subtotal"), data.get("taxable"))
    gst = first(tax.get("total_tax"), data.get("gst"))
    total = first(amounts.get("grand_total_normalized"), amounts.get("grand_total"), data.get("total"))

    cgst = first(tax.get("cgst_amount"), data.get("cgst"))
    sgst = first(tax.get("sgst_amount"), tax.get("utgst"), data.get("sgst"))
    igst = first(tax.get("igst_amount"), tax.get("igst"), data.get("igst"))
    cess = first(tax.get("cess"), data.get("cess"))

    # Prefer the sum of the components when the reported total tax disagrees:
    # the parts are read off individual rows and are the more reliable figure.
    components = round(cgst + sgst + igst + cess, 2)
    if components and abs(components - gst) > 1.0:
        gst = components

    if total == 0 and (taxable or gst):
        total = round(taxable + gst, 2)
    if taxable == 0 and total and gst:
        taxable = round(total - gst, 2)

    # Read out before the constructor: written inline, the conditional bound
    # more loosely than the `or` chain, so when order_info *was* a dict but
    # carried no po_number the expression yielded None and str() turned it into
    # the literal text "None" — an invoice citing a purchase order called
    # "None", which then raised a PO_NOT_FOUND finding against a clean invoice.
    order_info = data.get("order_info") if isinstance(data.get("order_info"), dict) else {}
    po_number = str(order_info.get("po_number") or data.get("po_number") or "").strip()[:80]

    return ParsedInvoice(
        invoice_no=str(data.get("invoice_number") or data.get("invoice_no") or "").strip(),
        supplier=str(supplier.get("name") or data.get("supplier_name") or "").strip(),
        supplier_gstin=_clean_gstin(supplier.get("gstin") or data.get("supplier_gstin")),
        invoice_date=_normalize_date(data.get("invoice_date")),
        taxable=taxable,
        gst=gst,
        total=total,
        hsn=_clean_hsn(data.get("hsn") or data.get("hsn_sac") or "") or _hsn_from_line_items(data),
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        cess=cess,
        recipient_gstin=_clean_gstin(
            buyer.get("gstin") or data.get("recipient_gstin") or data.get("buyer_gstin") or ""
        ),
        place_of_supply=_clean_pos(data.get("place_of_supply")),
        po_number=po_number,
    )


# Vision-token cost scales with pixel count, so the render is capped on its
# long edge. Beyond roughly this size the model gains no accuracy on invoice
# text but the request starts overflowing the context window.
_MAX_RENDER_EDGE = 2200


def _render_pdf_to_images(content: bytes, max_pages: int = 10, zoom: float = 3.0) -> tuple[list[bytes], str | None]:
    try:
        import pymupdf
    except ImportError:
        return [], "pymupdf is not installed for PDF rendering."
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - surface any open failure to caller
        return [], f"could not open PDF: {exc}"
    images: list[bytes] = []
    for index in range(min(len(doc), max_pages)):
        page = doc[index]
        # Scale back if the requested zoom would exceed the render cap, so a
        # large-format PDF does not silently produce an over-budget request.
        rect = page.rect
        longest = max(rect.width, rect.height) * zoom
        effective = zoom * (_MAX_RENDER_EDGE / longest) if longest > _MAX_RENDER_EDGE else zoom
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(effective, effective))
        images.append(pixmap.tobytes("png"))
    doc.close()
    return images, None


def _vlm_unavailable_message() -> str:
    return (
        f"Vision OCR model '{settings.ollama_vision_model}' is unavailable. "
        f"Start Ollama and run: ollama pull {settings.ollama_vision_model}"
    )


def _ocr_warnings(row: ParsedInvoice, data: dict) -> list[str]:
    """Flag fields the model read with low confidence.

    OCR on a dense invoice is not reliable field-by-field, so anything that
    comes out structurally wrong is reported at ingestion. The reviewer can
    then correct it in the verification screen instead of discovering it later
    as a fraud alert on an invoice that is actually fine.
    """
    warnings: list[str] = []

    # The item table is the strongest evidence the whole page was read.
    if not (data.get("line_items") or []):
        warnings.append("No line items were read; only the summary fields were captured.")

    if row.supplier_gstin and not _GSTIN_PATTERN.fullmatch(row.supplier_gstin):
        warnings.append(
            f"Supplier GSTIN '{row.supplier_gstin}' is not a valid GSTIN format - "
            "OCR may have misread it. Please verify against the document."
        )
    if row.recipient_gstin and not _GSTIN_PATTERN.fullmatch(row.recipient_gstin):
        warnings.append(
            f"Buyer GSTIN '{row.recipient_gstin}' is not a valid GSTIN format - "
            "OCR may have misread it. Please verify against the document."
        )
    if row.supplier_gstin and row.supplier_gstin == row.recipient_gstin:
        warnings.append(
            "Supplier and buyer GSTIN were read as the same value; one of them is wrong."
        )
    if not row.hsn:
        warnings.append("No HSN/SAC code was found, so the tax rate could not be cross-checked.")
    return warnings


async def parse_image_via_vlm(content: bytes) -> tuple[list[ParsedInvoice], list[str]]:
    try:
        data = await extract_invoice_from_image(content)
    except httpx.HTTPError:
        return [], [_vlm_unavailable_message()]
    row = _row_from_vlm(data)
    if not row.is_usable():
        return [], ["Could not extract an invoice number and amount from the image."]
    return [row], _ocr_warnings(row, data)


async def _ocr_pdf_via_vlm(content: bytes) -> tuple[list[ParsedInvoice], list[str]]:
    """Render the PDF and extract one invoice from it via the vision model.

    All pages are read and merged into a single invoice rather than one per
    page. A multi-page invoice is still one invoice: continuation pages carry
    extra line items but no invoice number of their own, so treating each page
    separately produced one good row plus a trail of unusable ones.
    """
    images, render_error = _render_pdf_to_images(content)
    if render_error:
        return [], [f"Could not render PDF for OCR: {render_error}"]
    if not images:
        return [], ["The PDF has no pages to read."]

    try:
        data = await extract_invoice_from_pages(images)
    except httpx.HTTPError:
        return [], [_vlm_unavailable_message()]

    row = _row_from_vlm(data)
    if not row.is_usable():
        return [], ["Could not extract an invoice number and amount from the PDF."]

    return [row], _ocr_warnings(row, data)


async def parse_pdf_hybrid(content: bytes) -> tuple[list[ParsedInvoice], list[str]]:
    """Digital PDFs → fast, accurate pypdf text extraction; scanned PDFs with
    no usable text layer → vision-model OCR."""
    rows, errors = parse_pdf(content)
    if rows:
        return rows, errors
    # pypdf found no usable rows (scanned image or unparseable layout) → OCR.
    ocr_rows, ocr_errors = await _ocr_pdf_via_vlm(content)
    if ocr_rows:
        return ocr_rows, ocr_errors
    return [], errors + ocr_errors


# --- dispatcher --------------------------------------------------------------


async def parse_upload(filename: str, content_type: str, content: bytes) -> tuple[list[ParsedInvoice], list[str]]:
    name = (filename or "").lower()
    ctype = (content_type or "").lower()

    if name.endswith(".csv") or name.endswith(".tsv") or "csv" in ctype:
        return parse_csv(content)
    if name.endswith(".json") or "json" in ctype:
        return parse_gstr_json(content)
    if name.endswith(_IMAGE_EXTENSIONS) or ctype.startswith("image"):
        return await parse_image_via_vlm(content)
    if name.endswith(".pdf") or "pdf" in ctype:
        return await parse_pdf_hybrid(content)

    # Unknown extension: sniff the leading bytes.
    head = content[:64].lstrip()
    if head[:1] in (b"{", b"["):
        return parse_gstr_json(content)
    if content[:5] == b"%PDF-":
        return await parse_pdf_hybrid(content)
    if content[:8].startswith(b"\x89PNG") or content[:3] == b"\xff\xd8\xff":
        return await parse_image_via_vlm(content)
    return [], [f"Unsupported file type '{filename}'. Upload a Tally CSV, GSTR-2A/2B JSON, PDF, or image invoice."]
