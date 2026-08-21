"""Unit tests for the pure logic behind the analysis layers.

No database and no HTTP — these cover the functions where a wrong answer is a
wrong figure on a compliance report rather than an error anyone would notice.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.api.dashboard import build_monthly_series
from app.services import integrity
from app.services.parsing import _row_from_vlm
from helpers import make_gstin


def _invoice(invoice_date: str, status: str, source: str = "books"):
    return SimpleNamespace(invoice_date=invoice_date, status=status, source=source)


class TestMonthlySeries:
    def test_a_matched_pair_is_counted_once(self):
        """Books and GSTR rows are one supply seen from two sides."""
        series = build_monthly_series(
            [_invoice("2026-07-01", "Matched"), _invoice("2026-07-01", "Matched", "gstr")],
            today=date(2026, 8, 21),
        )
        july = next(row for row in series if row["month"] == "Jul 2026")
        assert july["matched"] == 1

    def test_quiet_months_stay_in_the_series(self):
        """A closed-up gap would read as continuous activity."""
        series = build_monthly_series([_invoice("2026-07-01", "Matched")], today=date(2026, 8, 21))
        assert len(series) == 12
        assert next(row for row in series if row["month"] == "Jun 2026")["matched"] == 0

    def test_undated_and_unparseable_rows_are_skipped(self):
        series = build_monthly_series(
            [_invoice("", "Matched"), _invoice("not a date", "Matched")], today=date(2026, 8, 21)
        )
        assert series == []

    def test_no_invoices_yields_no_series(self):
        assert build_monthly_series([], today=date(2026, 8, 21)) == []

    def test_data_older_than_the_window_is_still_shown(self):
        series = build_monthly_series([_invoice("2020-03-02", "Matched")], today=date(2026, 8, 21))
        assert series == [{"month": "Mar 2020", "matched": 1, "mismatched": 0, "duplicates": 0}]


class TestGstinChecksum:
    def test_a_well_formed_gstin_passes_every_check(self):
        assert integrity.check_gstin(make_gstin()) == []

    def test_a_tampered_check_digit_is_caught(self):
        gstin = make_gstin()
        wrong = gstin[:14] + ("B" if gstin[14] != "B" else "C")
        codes = {finding.code for finding in integrity.check_gstin(wrong)}
        assert "GSTIN_CHECKSUM" in codes

    def test_a_missing_gstin_is_reported_not_ignored(self):
        codes = {finding.code for finding in integrity.check_gstin("")}
        assert codes == {"GSTIN_MISSING"}


class TestVisionRowMapping:
    def test_absent_po_number_stays_empty(self):
        """It used to come back as the literal string "None".

        A precedence slip made the conditional bind more loosely than the `or`
        chain, so an order_info block without a po_number yielded None and
        str() stringified it — an invoice citing a purchase order called
        "None", which then raised PO_NOT_FOUND against a clean document.
        """
        row = _row_from_vlm(
            {"invoice_number": "INV-1", "order_info": {}, "amount_summary": {"grand_total": 1180}}
        )
        assert row.po_number == ""

    def test_a_real_po_number_is_carried_through(self):
        row = _row_from_vlm(
            {
                "invoice_number": "INV-1",
                "order_info": {"po_number": "PO-42"},
                "amount_summary": {"grand_total": 1180},
            }
        )
        assert row.po_number == "PO-42"

    def test_a_flat_po_number_is_accepted_too(self):
        row = _row_from_vlm({"invoice_number": "INV-1", "po_number": "PO-7", "total": 500})
        assert row.po_number == "PO-7"


class TestTotalsChecks:
    def test_arithmetic_that_does_not_add_up_is_flagged(self):
        codes = {finding.code for finding in integrity.check_totals(1000, 180, 9999)}
        assert "TOTAL_MISMATCH" in codes

    def test_rounding_to_the_rupee_is_tolerated(self):
        assert integrity.check_totals(1000, 180, 1180) == []

    def test_tax_above_the_taxable_value_is_flagged(self):
        codes = {finding.code for finding in integrity.check_totals(100, 500, 600)}
        assert "TAX_EXCEEDS_TAXABLE" in codes


class TestExtractPipelineGstin:
    """extract.py is imported by services/vision_ocr, so its verdict is shown
    to reviewers alongside the rule engine's. The two have to agree."""

    def test_it_agrees_with_the_rule_engine_on_a_valid_gstin(self):
        import extract

        gstin = make_gstin()
        assert extract.analyze_gstin(gstin)["valid"] is True
        assert integrity.check_gstin(gstin) == []

    def test_a_fabricated_gstin_is_rejected_by_both(self):
        """The regex alone used to pass it, so the OCR panel called a
        fabricated supplier valid while the rule engine flagged it."""
        import extract

        gstin = make_gstin()
        fabricated = gstin[:14] + ("B" if gstin[14] != "B" else "C")

        result = extract.analyze_gstin(fabricated)
        assert result["valid"] is False
        assert result["well_formed"] is True  # shape is fine; the checksum is not
        assert "GSTIN_CHECKSUM" in {finding.code for finding in integrity.check_gstin(fabricated)}

    def test_every_state_code_the_rule_engine_accepts_has_a_name(self):
        """A gap here reported a real invoice's state as "Unknown State"."""
        import extract

        for code in sorted(integrity._VALID_STATE_CODES):
            assert code in extract.STATE_CODES, code
