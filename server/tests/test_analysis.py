"""Reconciliation, fraud re-scoring, and the supplier graph.

These run against the real database because each covers something that only
goes wrong across two runs or across a whole set of invoices.
"""

from __future__ import annotations

import json

from app.db.models import FraudAlert, Invoice, ReconciliationJob
from app.services.ml import run_fraud_detection
from app.services.reconciliation import normalize_key, run_reconciliation
from helpers import make_gstin


def _add_invoice(db, client_id: int, **kwargs) -> Invoice:
    defaults = {
        "invoice_no": "INV-1",
        "supplier": "Apex Steel",
        "supplier_gstin": make_gstin("27", "AAACA1234F"),
        "invoice_date": "2026-07-01",
        "taxable": 1000.0,
        "gst": 180.0,
        "total": 1180.0,
        "hsn": "7214",
        "source": "books",
        "status": "Pending",
        "risk": "Low",
    }
    defaults.update(kwargs)
    defaults["normalized_key"] = normalize_key(defaults["invoice_no"], defaults["supplier_gstin"])
    invoice = Invoice(client_id=client_id, **defaults)
    db.add(invoice)
    db.commit()
    return invoice


class TestReconciliationSummary:
    def test_the_stored_summary_is_readable_json(self, db, make_user, make_workspace):
        """The column is named summary_json but held a Python repr.

        str({...}) uses single quotes, so json.loads raised on every row ever
        written — a latent break for anything that reads the job history back.
        """
        reviewer = make_user("tax_reviewer")
        workspace_id = make_workspace(gstin=make_gstin("27", "RRACA1234F"), ca_id=reviewer["id"])
        _add_invoice(db, workspace_id, invoice_no="REC-1")

        result = run_reconciliation(db, workspace_id, reviewer["id"])

        job = db.get(ReconciliationJob, result["jobId"])
        parsed = json.loads(job.summary_json)
        assert parsed["total"] == 1
        assert parsed == result["summary"]


class TestFraudRescoring:
    def test_correcting_an_invoice_updates_its_alert(self, db, make_user, make_workspace):
        """The reviewer's whole workflow is: correct the OCR, then re-run.

        The alert used to be skipped once it existed, so a corrected invoice
        kept accusing itself of the defect that had just been fixed.
        """
        reviewer = make_user("tax_reviewer")
        workspace_id = make_workspace(gstin=make_gstin("27", "SSACA1234F"), ca_id=reviewer["id"])

        # A fabricated GSTIN: fails the mod-36 check digit, so it alerts.
        good = make_gstin("27", "TTACA1234F")
        bad = good[:14] + ("B" if good[14] != "B" else "C")
        invoice = _add_invoice(db, workspace_id, invoice_no="FIX-1", supplier_gstin=bad)

        created = run_fraud_detection(db, workspace_id)
        assert len(created) == 1
        alert_id = created[0].id
        first_risk = created[0].risk
        assert "GSTIN" in created[0].type

        # The reviewer corrects the misread GSTIN and re-runs.
        invoice.supplier_gstin = good
        invoice.normalized_key = normalize_key(invoice.invoice_no, good)
        db.commit()

        run_fraud_detection(db, workspace_id)

        db.expire_all()
        alert = db.get(FraudAlert, alert_id)
        assert alert is not None, "the alert must be refreshed, not deleted"
        assert alert.risk < first_risk
        codes = {finding["code"] for finding in json.loads(alert.findings_json)}
        assert "GSTIN_CHECKSUM" not in codes

    def test_a_rerun_does_not_duplicate_alerts(self, db, make_user, make_workspace):
        reviewer = make_user("tax_reviewer")
        workspace_id = make_workspace(gstin=make_gstin("27", "UUACA1234F"), ca_id=reviewer["id"])
        bad = make_gstin("27", "VVBCA1234F")
        bad = bad[:14] + ("B" if bad[14] != "B" else "C")
        _add_invoice(db, workspace_id, invoice_no="DUP-1", supplier_gstin=bad)

        run_fraud_detection(db, workspace_id)
        run_fraud_detection(db, workspace_id)

        count = db.query(FraudAlert).filter(FraudAlert.client_id == workspace_id).count()
        assert count == 1

    def test_a_reviewers_triage_survives_a_rerun(self, db, make_user, make_workspace):
        """`status` is the reviewer's decision, not a model output."""
        reviewer = make_user("tax_reviewer")
        workspace_id = make_workspace(gstin=make_gstin("27", "WWACA1234F"), ca_id=reviewer["id"])
        bad = make_gstin("27", "XXACA1234F")
        bad = bad[:14] + ("B" if bad[14] != "B" else "C")
        _add_invoice(db, workspace_id, invoice_no="TRIAGE-1", supplier_gstin=bad)

        alert_id = run_fraud_detection(db, workspace_id)[0].id
        db.get(FraudAlert, alert_id).status = "Resolved"
        db.commit()

        run_fraud_detection(db, workspace_id)

        db.expire_all()
        assert db.get(FraudAlert, alert_id).status == "Resolved"


class TestGraphItcAtRisk:
    def test_an_edge_on_two_rings_is_counted_once(self, client, db, make_user, make_workspace):
        """ITC at risk is the headline figure a reviewer would quote.

        Summing per-cycle totals counted a shared edge's GST once per ring, so
        the number overstated the exposure.
        """
        reviewer = make_user("tax_reviewer")
        a = make_gstin("27", "AAACA1234F")
        b = make_gstin("27", "BBACA1234F")
        c = make_gstin("27", "CCACA1234F")
        d = make_gstin("27", "DDACA1234F")

        # Three workspaces the reviewer owns, so the graph spans them.
        wa = make_workspace(gstin=a, ca_id=reviewer["id"], name="A Ltd")
        wb = make_workspace(gstin=b, ca_id=reviewer["id"], name="B Ltd")
        wc = make_workspace(gstin=c, ca_id=reviewer["id"], name="C Ltd")
        wd = make_workspace(gstin=d, ca_id=reviewer["id"], name="D Ltd")

        # Two rings sharing the A->B edge: A->B->C->A and A->B->D->A.
        _add_invoice(db, wb, invoice_no="AB", supplier_gstin=a, gst=100.0)  # A bills B
        _add_invoice(db, wc, invoice_no="BC", supplier_gstin=b, gst=10.0)   # B bills C
        _add_invoice(db, wa, invoice_no="CA", supplier_gstin=c, gst=10.0)   # C bills A
        _add_invoice(db, wd, invoice_no="BD", supplier_gstin=b, gst=10.0)   # B bills D
        _add_invoice(db, wa, invoice_no="DA", supplier_gstin=d, gst=10.0)   # D bills A

        response = client.get(f"/api/graph?clientId={wa}", headers=reviewer["headers"])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["metrics"]["cyclesDetected"] >= 2

        # Every distinct suspicious edge counted once: 100 + 10 + 10 + 10 + 10.
        # The old sum-per-cycle double-counted A->B and reported 240.
        assert body["metrics"]["itcAtRisk"] == 140
