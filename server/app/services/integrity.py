"""Deterministic invoice-integrity checks — the rule-based fraud layer.

Where ``ml.py`` scores invoices *statistically* (what looks unusual relative to
its peers), this module checks each invoice against things that are simply
true or false about a valid GST document. It answers "is this document
internally coherent and does it refer to real, valid identifiers?" — questions
an anomaly detector cannot answer, because a well-forged invoice can look
perfectly ordinary.

Four families of checks, mapped to the links in the ITC fraud chain:

======  ==========================================  =========================
Check   Catches                                     Link
======  ==========================================  =========================
format  Missing/placeholder fields, impossible      LINK 1 — the invoice
        dates — the fingerprints of a fabricated    itself (fake / inflated /
        or template invoice                         duplicate)
gstin   Made-up or structurally impossible GSTINs   LINK 2 — supplier GSTIN
        via the mod-36 check digit                  validity
hsn     Unknown HSN/SAC codes, and codes whose      LINK 1 — misclassifying
        statutory rate contradicts the tax          goods to justify a higher
        actually charged                            ITC claim
totals  Arithmetic that does not add up, or an      LINK 1 — inflated values
        effective tax rate outside every statutory  and tampered amounts
        slab
======  ==========================================  =========================

Links 3 and 4 (supplier non-filing and under-reporting) are inherently
*comparative* — they need the client's books checked against GSTR-2A/2B — so
they live in ``reconciliation.py``. Circular trading is only visible across the
whole network and lives in ``api/graph.py``. This module deliberately covers
only what a single document can be judged on alone.

Every check errs toward silence: a compliance tool that cries wolf gets
ignored, so anything genuinely ambiguous is scored low or not raised at all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "hsn_sac.json"

# GSTIN check-digit alphabet: values 0-35 in order.
_GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# 01-38 are the state/UT codes; 97 is "other territory" and 99 is used for UN
# bodies and embassies.
_VALID_STATE_CODES = {f"{n:02d}" for n in range(1, 39)} | {"97", "99"}

_GSTIN_STRUCTURE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")
_PAN_STRUCTURE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# Invoice numbers that are obviously template/scratch values rather than a real
# document reference.
_PLACEHOLDER_INVOICE_NOS = {
    "TEST", "TESTING", "DUMMY", "SAMPLE", "DEMO", "NA", "N/A", "NIL", "NONE",
    "XXX", "XXXX", "ABC", "ABCD", "INVOICE", "INV", "0", "00", "000", "1234",
}

# Amount comparisons are in rupees; invoices routinely round to the nearest
# rupee, so the arithmetic check must tolerate that without flagging.
_ROUNDING_TOLERANCE = 1.0
_RATE_TOLERANCE = 0.6  # percentage points

def _is_disguised_repeat(a: str, b: str) -> bool:
    """True when two invoice numbers look like one number wearing a disguise.

    Plain fuzzy similarity is the wrong tool here: consecutive invoice numbers
    (INV-001 / INV-002) are ~83% alike, so a similarity threshold would flag
    ordinary same-day billing. What actually marks a re-entered claim is the
    *same numeric sequence* dressed differently (INV-002 vs INV-002-A), or one
    number extending the other. Differing digits mean genuinely different
    documents.
    """
    if not a or not b or a == b:
        return False
    digits_a = re.sub(r"\D", "", a)
    digits_b = re.sub(r"\D", "", b)
    if digits_a and digits_a == digits_b:
        return True
    return a.startswith(b) or b.startswith(a)


@dataclass
class Finding:
    """One thing wrong with an invoice."""

    code: str          # stable machine identifier, e.g. "GSTIN_CHECKSUM"
    check: str         # "format" | "gstin" | "hsn" | "totals" | "duplicate"
    link: int          # 1-4: which link in the ITC fraud chain this breaks
    weight: int        # 0-100 contribution to the document's risk score
    title: str
    detail: str

    @property
    def severity(self) -> str:
        if self.weight >= 50:
            return "critical"
        if self.weight >= 30:
            return "high"
        if self.weight >= 15:
            return "medium"
        return "low"

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "check": self.check,
            "link": self.link,
            "weight": self.weight,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
        }


@dataclass
class Assessment:
    """Aggregate verdict for one invoice."""

    score: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def failed_checks(self) -> list[str]:
        return sorted({f.check for f in self.findings})

    def reason(self) -> str:
        if not self.findings:
            return "no integrity issues"
        return ", ".join(f.title for f in sorted(self.findings, key=lambda f: -f.weight)[:3])


# --- reference data -----------------------------------------------------------


@lru_cache(maxsize=1)
def _reference() -> dict:
    """HSN/SAC master, generated by scripts/build_hsn_sac.py.

    Missing data must not break fraud detection, so an absent file degrades to
    "no code knowledge" rather than raising — the other three checks still run.
    """
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"hsn": {}, "sac": {}, "slabs": []}


def reference_loaded() -> bool:
    return bool(_reference().get("hsn"))


# --- helpers ------------------------------------------------------------------


def _text(value) -> str:
    return str(value or "").strip()


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(raw: str) -> date | None:
    raw = _text(raw)
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%b-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def implied_rate(taxable: float, gst: float) -> float | None:
    """Effective tax rate as a percentage, or None when it cannot be computed."""
    if taxable <= 0:
        return None
    return round(gst / taxable * 100, 3)


def is_statutory_slab(rate: float) -> bool:
    slabs = _reference().get("slabs") or []
    return any(abs(rate - slab) <= _RATE_TOLERANCE for slab in slabs)


# --- LINK 2: GSTIN validity ---------------------------------------------------


def gstin_check_digit(first_fourteen: str) -> str:
    """The 15th character required by the GSTIN mod-36 checksum."""
    factor, total, mod = 2, 0, len(_GSTIN_ALPHABET)
    for char in reversed(first_fourteen):
        product = factor * _GSTIN_ALPHABET.index(char)
        factor = 1 if factor == 2 else 2
        total += (product // mod) + (product % mod)
    return _GSTIN_ALPHABET[(mod - (total % mod)) % mod]


def check_gstin(gstin: str, *, label: str = "Supplier GSTIN") -> list[Finding]:
    """Validate a GSTIN offline: structure, state code, embedded PAN, checksum.

    The check digit is the important one — it makes an invented GSTIN fail with
    probability 35/36, so a fabricated supplier is caught without any call to
    the GST portal.
    """
    value = re.sub(r"[^A-Z0-9]", "", _text(gstin).upper())

    if not value:
        return [Finding("GSTIN_MISSING", "gstin", 2, 30, f"{label} missing",
                        "No GSTIN on the invoice, so the supplier cannot be identified or verified.")]

    if len(value) != 15:
        return [Finding("GSTIN_LENGTH", "gstin", 2, 55, f"{label} has wrong length",
                        f"A GSTIN is 15 characters; this one has {len(value)} ('{value}').")]

    findings: list[Finding] = []

    if not _GSTIN_STRUCTURE.match(value):
        findings.append(Finding(
            "GSTIN_STRUCTURE", "gstin", 2, 55, f"{label} is structurally invalid",
            f"'{value}' does not follow the 2-digit state + 10-character PAN + entity + Z + check-digit layout."))
        # Structure is broken, so the field-level checks below would be noise.
        return findings

    if value[:2] not in _VALID_STATE_CODES:
        findings.append(Finding(
            "GSTIN_STATE", "gstin", 2, 45, f"{label} has an unknown state code",
            f"'{value[:2]}' is not a valid GST state/UT code."))

    if not _PAN_STRUCTURE.match(value[2:12]):
        findings.append(Finding(
            "GSTIN_PAN", "gstin", 2, 45, f"{label} contains an invalid PAN",
            f"Characters 3-12 ('{value[2:12]}') are not a valid PAN."))

    expected = gstin_check_digit(value[:14])
    if expected != value[14]:
        findings.append(Finding(
            "GSTIN_CHECKSUM", "gstin", 2, 60, f"{label} fails its check digit",
            f"'{value}' should end in '{expected}'. A GSTIN that fails this test is "
            "almost certainly fabricated — real ones are self-validating."))

    return findings


# --- LINK 1: HSN / SAC classification ----------------------------------------


def check_hsn(code: str, taxable: float, gst: float) -> list[Finding]:
    """Validate an HSN/SAC code and cross-check it against the tax charged.

    A supplier misclassifying goods under a higher-rate code (or an invoice
    carrying a code that does not exist) is how an inflated ITC claim is
    dressed up as legitimate.
    """
    value = re.sub(r"[^0-9]", "", _text(code))
    reference = _reference()

    if not value:
        return [Finding("HSN_MISSING", "hsn", 1, 12, "No HSN/SAC code",
                        "The invoice carries no HSN/SAC code, so the goods or services cannot be "
                        "classified or their tax rate verified.")]

    if len(value) not in (2, 4, 6, 8):
        return [Finding("HSN_LENGTH", "hsn", 1, 25, "HSN/SAC code has an invalid length",
                        f"'{value}' is {len(value)} digits; HSN/SAC codes are 2, 4, 6 or 8 digits.")]

    is_service = value.startswith("99")
    table = reference.get("sac" if is_service else "hsn") or {}
    kind = "SAC" if is_service else "HSN"

    if not table:
        return []  # No reference data available; stay silent rather than guess.

    # Match the code, else its parent heading/chapter — an 8-digit tariff item
    # is valid when its 6- or 4-digit parent is in the schedule.
    permitted: list[float] | None = None
    for width in (len(value), 6, 4, 2):
        if width > len(value):
            continue
        candidate = value[:width]
        if candidate in table:
            permitted = table[candidate]
            break

    if permitted is None:
        return [Finding("HSN_UNKNOWN", "hsn", 1, 30, f"{kind} code not in the GST schedule",
                        f"'{value}' does not appear in the official {kind} rate schedule, "
                        "which suggests an invented or mistyped classification.")]

    rate = implied_rate(taxable, gst)
    if rate is None or not permitted:
        return []

    if not any(abs(rate - allowed) <= _RATE_TOLERANCE for allowed in permitted):
        allowed_text = ", ".join(f"{r:g}%" for r in permitted)
        return [Finding(
            "HSN_RATE_MISMATCH", "hsn", 1, 35, f"Tax charged contradicts the {kind} code",
            f"{kind} {value} is taxed at {allowed_text}, but this invoice charges "
            f"{rate:g}%. Either the classification or the tax amount is wrong.")]

    return []


# --- LINK 1: totals and arithmetic -------------------------------------------


def check_totals(taxable: float, gst: float, total: float) -> list[Finding]:
    """Verify the invoice adds up and its effective tax rate is lawful."""
    findings: list[Finding] = []

    if min(taxable, gst, total) < 0:
        findings.append(Finding(
            "AMOUNT_NEGATIVE", "totals", 1, 55, "Negative amount on the invoice",
            f"taxable {taxable:,.2f}, tax {gst:,.2f}, total {total:,.2f} — a tax invoice cannot "
            "carry negative values; a credit note should be used instead."))
        return findings

    if total <= 0:
        findings.append(Finding(
            "AMOUNT_ZERO", "totals", 1, 35, "Invoice total is zero",
            "An invoice with no value cannot support an input tax credit claim."))
        return findings

    expected = taxable + gst
    difference = abs(expected - total)
    if taxable > 0 and difference > max(_ROUNDING_TOLERANCE, 0.01 * total):
        findings.append(Finding(
            "TOTAL_MISMATCH", "totals", 1, 50, "Invoice does not add up",
            f"taxable {taxable:,.2f} + tax {gst:,.2f} = {expected:,.2f}, but the invoice total "
            f"reads {total:,.2f} (off by {difference:,.2f}). Tampered or mis-keyed amounts are a "
            "primary sign of an inflated invoice."))

    if gst > taxable and taxable > 0:
        findings.append(Finding(
            "TAX_EXCEEDS_TAXABLE", "totals", 1, 60, "Tax exceeds the taxable value",
            f"Tax of {gst:,.2f} on a taxable value of {taxable:,.2f} implies a rate above 100%, "
            "which no GST slab permits."))
        return findings

    rate = implied_rate(taxable, gst)
    if rate is not None and gst > 0 and not is_statutory_slab(rate):
        findings.append(Finding(
            "RATE_NOT_STATUTORY", "totals", 1, 40, "Effective tax rate is not a GST slab",
            f"The invoice implies a rate of {rate:g}%, which matches no statutory slab "
            "(0, 0.1, 0.25, 1, 1.5, 3, 5, 12, 18 or 28%)."))

    return findings


# --- LINK 1: format and missing-field patterns -------------------------------


def check_place_of_supply(invoice) -> list[Finding]:
    """Verify the tax heads match the geography of the supply.

    GST splits by where the supply lands: within one state it is CGST+SGST,
    across states it is IGST. Charging the wrong pair is a real compliance
    defect — and a common one on fabricated invoices, because it takes a
    supplier and recipient GSTIN that genuinely correspond to the tax heads to
    get right. Silent when the components were never captured.
    """
    supplier = re.sub(r"[^A-Z0-9]", "", _text(getattr(invoice, "supplier_gstin", "")).upper())
    recipient = re.sub(r"[^A-Z0-9]", "", _text(getattr(invoice, "recipient_gstin", "")).upper())
    place = _text(getattr(invoice, "place_of_supply", ""))

    cgst = _number(getattr(invoice, "cgst", 0))
    sgst = _number(getattr(invoice, "sgst", 0))
    igst = _number(getattr(invoice, "igst", 0))

    # Nothing to compare against.
    if len(supplier) < 2 or (cgst + sgst + igst) <= 0:
        return []

    supplier_state = supplier[:2]
    # The destination is the place of supply when stated, else the recipient's
    # own state code.
    destination = place[:2] if len(place) >= 2 else (recipient[:2] if len(recipient) >= 2 else "")
    if not destination:
        return []

    intra_state = supplier_state == destination

    if intra_state and igst > 0 and (cgst + sgst) == 0:
        return [Finding(
            "POS_IGST_ON_INTRASTATE", "totals", 1, 45, "IGST charged on an intra-state supply",
            f"Supplier and place of supply are both in state {supplier_state}, which attracts "
            f"CGST+SGST, but the invoice charges IGST of {igst:,.2f}.")]

    if not intra_state and (cgst + sgst) > 0 and igst == 0:
        return [Finding(
            "POS_CGST_ON_INTERSTATE", "totals", 1, 45, "CGST/SGST charged on an inter-state supply",
            f"Supply runs from state {supplier_state} to {destination}, which attracts IGST, but "
            f"the invoice charges CGST+SGST of {cgst + sgst:,.2f}.")]

    if intra_state and cgst > 0 and sgst > 0 and abs(cgst - sgst) > _ROUNDING_TOLERANCE:
        return [Finding(
            "POS_CGST_SGST_UNEQUAL", "totals", 1, 30, "CGST and SGST are not equal",
            f"CGST {cgst:,.2f} and SGST {sgst:,.2f} must be the same on an intra-state supply; "
            "they are always half of the total rate each.")]

    return []


def check_format(invoice, *, today: date | None = None) -> list[Finding]:
    """Look for the fingerprints of a fabricated or template invoice."""
    findings: list[Finding] = []
    today = today or date.today()

    invoice_no = _text(getattr(invoice, "invoice_no", ""))
    if not invoice_no:
        findings.append(Finding(
            "INVOICE_NO_MISSING", "format", 1, 40, "Invoice number missing",
            "Every tax invoice must carry a unique serial number; without one the document "
            "cannot be traced or matched to a GSTR filing."))
    else:
        stripped = re.sub(r"[^A-Z0-9]", "", invoice_no.upper())
        if stripped in _PLACEHOLDER_INVOICE_NOS:
            findings.append(Finding(
                "INVOICE_NO_PLACEHOLDER", "format", 1, 45, "Invoice number is a placeholder",
                f"'{invoice_no}' is a template value, not a real document reference."))
        elif len(set(stripped)) == 1 and len(stripped) > 2:
            findings.append(Finding(
                "INVOICE_NO_REPEATED", "format", 1, 30, "Invoice number is a repeated character",
                f"'{invoice_no}' looks like filler rather than a genuine serial number."))

    if not _text(getattr(invoice, "supplier", "")):
        findings.append(Finding(
            "SUPPLIER_MISSING", "format", 1, 15, "Supplier name missing",
            "The invoice does not name the supplier."))

    raw_date = _text(getattr(invoice, "invoice_date", ""))
    if not raw_date:
        findings.append(Finding(
            "DATE_MISSING", "format", 1, 20, "Invoice date missing",
            "Without a date the invoice cannot be assigned to a tax period."))
    else:
        parsed = _parse_date(raw_date)
        if parsed is None:
            findings.append(Finding(
                "DATE_UNPARSEABLE", "format", 1, 20, "Invoice date is not a valid date",
                f"'{raw_date}' could not be read as a date."))
        elif parsed > today:
            findings.append(Finding(
                "DATE_FUTURE", "format", 1, 45, "Invoice is dated in the future",
                f"Dated {parsed.isoformat()}, which is after today. A future-dated invoice cannot "
                "represent a supply that has already happened."))
        elif (today - parsed).days > 2200:  # ~6 years, beyond any GST time limit
            findings.append(Finding(
                "DATE_STALE", "format", 1, 15, "Invoice is implausibly old",
                f"Dated {parsed.isoformat()}, far outside the period in which ITC can be claimed."))

    return findings


# --- LINK 1 (scenario C): duplicate claims -----------------------------------


def check_duplicates(invoices) -> dict[int, list[Finding]]:
    """Find the same credit being claimed twice across a client's invoices.

    Two shapes are caught: the identical invoice ingested twice, and the same
    supplier billing an identical amount on the same day under different
    invoice numbers — the usual way a duplicate claim is disguised.
    """
    by_identity: dict[tuple, list] = {}
    by_shape: dict[tuple, list] = {}

    for invoice in invoices:
        gstin = re.sub(r"[^A-Z0-9]", "", _text(getattr(invoice, "supplier_gstin", "")).upper())
        number = re.sub(r"[^A-Z0-9]", "", _text(getattr(invoice, "invoice_no", "")).upper())
        source = _text(getattr(invoice, "source", ""))
        total = round(_number(getattr(invoice, "total", 0)), 2)
        when = _text(getattr(invoice, "invoice_date", ""))

        # Books and GSTR rows describe the same supply from two sides, so they
        # are never duplicates of each other.
        if gstin and number:
            by_identity.setdefault((source, gstin, number), []).append(invoice)
        if gstin and total > 0 and when:
            by_shape.setdefault((source, gstin, total, when), []).append(invoice)

    results: dict[int, list[Finding]] = {}

    for (_, gstin, number), group in by_identity.items():
        if len(group) < 2:
            continue
        for invoice in group[1:]:
            results.setdefault(id(invoice), []).append(Finding(
                "DUPLICATE_INVOICE", "duplicate", 1, 70, "Duplicate invoice",
                f"Invoice '{number}' from {gstin} appears {len(group)} times. Claiming the same "
                "credit more than once inflates ITC by the repeated amount."))

    for (_, gstin, total, when), group in by_shape.items():
        if len(group) < 2:
            continue
        # Identical amount, supplier and date is not suspicious on its own —
        # fixed-rate and subscription billing look exactly like that, and so do
        # consecutive invoice numbers. Only a number that is the same sequence
        # in different clothing is reported.
        for index, invoice in enumerate(group):
            number = re.sub(r"[^A-Z0-9]", "", _text(getattr(invoice, "invoice_no", "")).upper())
            twin = next(
                (
                    other for position, other in enumerate(group)
                    if position < index
                    and _is_disguised_repeat(
                        number, re.sub(r"[^A-Z0-9]", "", _text(getattr(other, "invoice_no", "")).upper())
                    )
                ),
                None,
            )
            if twin is None:
                continue
            twin_no = _text(getattr(twin, "invoice_no", ""))
            results.setdefault(id(invoice), []).append(Finding(
                "DUPLICATE_SHAPE", "duplicate", 1, 40, "Near-duplicate invoice",
                f"{gstin} billed {total:,.2f} on {when} under both '{twin_no}' and "
                f"'{_text(getattr(invoice, 'invoice_no', ''))}' — near-identical numbering on an "
                "otherwise identical supply is how a repeated claim is usually disguised."))

    return results


# --- public entry point -------------------------------------------------------


def assess_invoice(invoice, *, today: date | None = None) -> Assessment:
    """Run every single-document check and combine them into one score."""
    taxable = _number(getattr(invoice, "taxable", 0))
    gst = _number(getattr(invoice, "gst", 0))
    total = _number(getattr(invoice, "total", 0))

    findings: list[Finding] = []
    findings += check_format(invoice, today=today)
    findings += check_gstin(getattr(invoice, "supplier_gstin", ""))
    findings += check_hsn(getattr(invoice, "hsn", ""), taxable, gst)
    findings += check_totals(taxable, gst, total)
    findings += check_place_of_supply(invoice)

    return Assessment(score=score_findings(findings), findings=findings)


def score_findings(findings: list[Finding]) -> int:
    """Combine finding weights into a 0-100 score.

    Weights are combined probabilistically rather than added, so a document
    with several minor issues cannot reach the same score as one with a single
    disqualifying defect, and the total saturates instead of overflowing.
    """
    remaining = 1.0
    for finding in sorted(findings, key=lambda f: -f.weight):
        remaining *= 1.0 - min(max(finding.weight, 0), 100) / 100.0
    return int(round((1.0 - remaining) * 100))
