from collections import defaultdict
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ensure_client_scope, get_current_user, scoped_client_ids
from app.db.models import FraudAlert, Invoice, User
from app.db.session import get_db


router = APIRouter()

# How far back the trend chart looks. Twelve months is what the axis is laid
# out for, and older data says little about current compliance.
TREND_MONTHS = 12

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%b-%Y", "%Y/%m/%d")


def _invoice_month(raw: str) -> str:
    """``YYYY-MM`` for an invoice date, or "" when it cannot be read.

    Dates arrive already normalised to ISO by the parsers, but a row edited by
    hand or carried over from an older ingest may hold anything, so the other
    formats the parsers accept are tried too rather than dropping the row.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    return ""


def _recent_months(today: date, count: int = TREND_MONTHS) -> list[str]:
    """The last ``count`` months, oldest first, as ``YYYY-MM``."""
    months: list[str] = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(months))


def build_monthly_series(invoices: list[Invoice], today: date | None = None) -> list[dict]:
    """Reconciliation outcomes per month, for the dashboard trend chart.

    Only books rows are counted. A matched pair is one invoice seen from two
    sides, so counting the GSTR row as well would double every bar.

    Months with no invoices are still emitted, at zero: a gap silently closed
    up would make an idle quarter look like continuous activity.
    """
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"matched": 0, "mismatched": 0, "duplicates": 0})
    for invoice in invoices:
        if (invoice.source or "") == "gstr":
            continue
        month = _invoice_month(invoice.invoice_date)
        if not month:
            continue
        status = (invoice.status or "").lower()
        if status == "matched":
            counts[month]["matched"] += 1
        elif status == "mismatched":
            counts[month]["mismatched"] += 1
        elif status == "duplicate":
            counts[month]["duplicates"] += 1

    if not counts:
        return []

    window = _recent_months(today or date.today())
    # Normally the recent window, so an idle month still shows as a zero bar
    # rather than being closed up. When nothing in that window has data — an
    # archive, or a demo database older than a year — fall back to the months
    # that do, so the chart shows the data instead of twelve empty bars.
    months = window if any(month in counts for month in window) else sorted(counts)[-TREND_MONTHS:]

    series = []
    for month in months:
        bucket = counts.get(month, {"matched": 0, "mismatched": 0, "duplicates": 0})
        label = datetime.strptime(month, "%Y-%m").strftime("%b %Y")
        series.append({"month": label, **bucket})
    return series


@router.get("")
def dashboard(
    clientId: int | None = Query(None, description="Narrow every figure to one workspace"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    client_ids = scoped_client_ids(db, user)
    if clientId is not None:
        # Checked rather than intersected, so asking for someone else's
        # workspace is refused instead of quietly returning an empty dashboard.
        ensure_client_scope(db, user, clientId)
        client_ids = [clientId]

    invoices = db.query(Invoice).filter(Invoice.client_id.in_(client_ids)).all() if client_ids else []
    alerts = db.query(FraudAlert).filter(FraudAlert.client_id.in_(client_ids)).all() if client_ids else []
    return {
        "kpis": {
            "totalClients": len(client_ids),
            "uploadedInvoices": len(invoices),
            "matchedInvoices": len([item for item in invoices if item.status == "Matched"]),
            "mismatchedInvoices": len([item for item in invoices if item.status == "Mismatched"]),
            "duplicateInvoices": len([item for item in invoices if item.status == "Duplicate"]),
            "highRiskTransactions": len([item for item in alerts if item.risk >= 70]),
        },
        "monthlyData": build_monthly_series(invoices),
        "supplierRisk": [{"supplier": item.entity, "risk": item.risk, "amount": item.amount, "reason": item.reason} for item in alerts],
    }
