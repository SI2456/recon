"""Fraud scoring for ReconAI.

Uses an unsupervised **Isolation Forest** to flag anomalous invoices and a
supervised **Logistic Regression** (trained on weak labels derived from
reconciliation outcomes) to estimate a fraud probability. Every flag is
explained with **SHAP** values — the real ``shap`` library when installed,
otherwise the exact closed-form SHAP values for the linear model.

The heavy ML libraries are imported lazily so a missing dependency degrades to
a transparent rule-based fallback instead of breaking the API at import time.
"""

from __future__ import annotations

import json
from collections import Counter

from sqlalchemy.orm import Session

from app.db.models import FraudAlert, Invoice
from app.services import integrity, purchase_orders
from app.services.integrity import Finding


# Feature order is fixed so coefficients / SHAP values line up with names.
FEATURE_NAMES = ["amount", "taxable", "gst_rate", "supplier_freq", "round_amount", "high_value", "anomaly"]

_FEATURE_PHRASES = {
    "amount": "invoice amount",
    "taxable": "taxable value",
    "gst_rate": "GST rate",
    "supplier_freq": "supplier activity",
    "round_amount": "round-number amount",
    "high_value": "high-value transaction",
    "anomaly": "anomaly pattern",
}

ALERT_THRESHOLD = 50
MIN_SAMPLES_FOR_ML = 8

# ALERT_THRESHOLD gates the *statistical* score, where 50 is a sensible bar for
# "unusual enough to look at". Deterministic findings are not likelihoods —
# "this HSN does not exist" or "this invoice is dated in the future" is simply
# true — so any finding at medium severity or above raises an alert on its own,
# even when the ML layer finds the invoice unremarkable. That is the point: a
# competent forgery is designed to look statistically ordinary.
REPORTABLE_FINDING_WEIGHT = 25


# --- optional dependency probes ----------------------------------------------


def _load_sklearn():
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        return np, IsolationForest, LogisticRegression, StandardScaler
    except ImportError:
        return None


def _load_shap():
    try:
        import shap

        return shap
    except ImportError:
        return None


# --- rule-based fallback (used when sklearn is unavailable or data is tiny) ---


def _rule_based_score(invoice: Invoice) -> tuple[int, list[str], str]:
    score = 20
    reasons: list[str] = []
    chips: list[str] = ["baseline risk"]

    if invoice.status == "Mismatched":
        score += 35
        reasons.append("reconciliation mismatch")
        chips.append("reconciliation mismatch")
    if invoice.status == "Duplicate":
        score += 45
        reasons.append("duplicate invoice")
        chips.append("duplicate invoice")
    if (invoice.total or 0) >= 100000:
        score += 20
        reasons.append("high invoice value")
        chips.append("high-value transaction")

    return min(score, 100), chips, ", ".join(reasons) or "baseline risk"


def _rule_floor(invoice: Invoice) -> int:
    """Domain guardrail so obvious cases are never scored as safe."""
    if invoice.status == "Duplicate":
        return 85
    if invoice.status == "Mismatched":
        return 55
    return 0


# --- feature engineering -----------------------------------------------------


def _raw_features(invoices: list[Invoice]) -> list[list[float]]:
    supplier_counts = Counter(inv.supplier_gstin for inv in invoices)
    rows: list[list[float]] = []
    for inv in invoices:
        taxable = float(inv.taxable or 0)
        gst = float(inv.gst or 0)
        total = float(inv.total or 0)
        rows.append(
            [
                total,
                taxable,
                (gst / taxable) if taxable else 0.0,
                float(supplier_counts[inv.supplier_gstin]),
                1.0 if total and total % 1000 == 0 else 0.0,
                1.0 if total >= 100000 else 0.0,
            ]
        )
    return rows


def _weak_labels(invoices: list[Invoice]) -> list[int]:
    # Reconciliation outcomes act as noisy fraud labels for the supervised model.
    return [1 if inv.status in ("Duplicate", "Mismatched") else 0 for inv in invoices]


# --- ML scoring --------------------------------------------------------------


def _score_with_ml(invoices: list[Invoice]) -> list[tuple[int, list[str], str]] | None:
    """Return per-invoice (risk, shap_chips, reason) or None to signal fallback."""
    libs = _load_sklearn()
    if libs is None or len(invoices) < MIN_SAMPLES_FOR_ML:
        return None

    np, IsolationForest, LogisticRegression, StandardScaler = libs

    base = np.array(_raw_features(invoices), dtype=float)  # (n, 6)

    # 1) Unsupervised anomaly detection.
    forest = IsolationForest(n_estimators=200, contamination="auto", random_state=42)
    forest.fit(base)
    # score_samples: higher = more normal. Invert so higher = more anomalous.
    anomaly = -forest.score_samples(base)
    a_min, a_max = float(anomaly.min()), float(anomaly.max())
    anomaly_norm = (anomaly - a_min) / (a_max - a_min) if a_max > a_min else np.zeros_like(anomaly)

    # Full feature matrix = raw features + anomaly signal, standardized.
    features = np.column_stack([base, anomaly_norm])  # (n, 7)
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)

    labels = np.array(_weak_labels(invoices))
    shap = _load_shap()

    # 2) Supervised probability when weak labels contain both classes.
    use_supervised = labels.min() != labels.max()
    if use_supervised:
        model = LogisticRegression(max_iter=1000, class_weight="balanced")
        model.fit(scaled, labels)
        proba = model.predict_proba(scaled)[:, 1]
        coef = model.coef_[0]
        shap_matrix = _shap_values(shap, model, scaled, coef)
        risks = (proba * 100).round().astype(int)
    else:
        # No supervised signal — drive risk purely off the anomaly percentile.
        proba = None
        shap_matrix = None
        risks = (anomaly_norm * 100).round().astype(int)

    results: list[tuple[int, list[str], str]] = []
    for i, inv in enumerate(invoices):
        risk = int(risks[i])
        risk = max(risk, _rule_floor(inv))
        risk = int(max(0, min(100, risk)))

        if shap_matrix is not None:
            chips, reason = _explain_from_shap(shap_matrix[i])
        else:
            chips, reason = _explain_from_anomaly(scaled[i], FEATURE_NAMES)
        results.append((risk, chips, reason))

    return results


def _shap_values(shap, model, scaled, coef):
    """Genuine SHAP values for the logistic model.

    Uses shap.LinearExplainer when the library is present; otherwise the exact
    closed-form: phi_ij = coef_j * (x_ij - mean_j) in log-odds space, which is
    what LinearExplainer computes for a linear model with independent features.
    """
    if shap is not None:
        try:
            explainer = shap.LinearExplainer(model, scaled)
            values = explainer.shap_values(scaled)
            # Some shap versions return a list per class.
            if isinstance(values, list):
                values = values[-1]
            return values
        except Exception:  # noqa: BLE001 - fall back to closed form
            pass
    means = scaled.mean(axis=0)
    return (scaled - means) * coef


def _explain_from_shap(row) -> tuple[list[str], str]:
    pairs = sorted(zip(FEATURE_NAMES, row), key=lambda kv: abs(kv[1]), reverse=True)
    chips: list[str] = []
    reasons: list[str] = []
    for name, value in pairs[:3]:
        if abs(value) < 1e-6:
            continue
        phrase = _FEATURE_PHRASES.get(name, name)
        sign = "+" if value >= 0 else "-"
        chips.append(f"{phrase} ({sign}{abs(value):.2f})")
        if value > 0:
            reasons.append(phrase)
    if not chips:
        chips = ["no dominant factor"]
    return chips, ", ".join(reasons) or "model-detected anomaly"


def _explain_from_anomaly(scaled_row, names) -> tuple[list[str], str]:
    # Rank features by how far they deviate from the mean (already standardized).
    pairs = sorted(zip(names, scaled_row), key=lambda kv: abs(kv[1]), reverse=True)
    chips: list[str] = []
    reasons: list[str] = []
    for name, z in pairs[:3]:
        if abs(z) < 0.5:
            continue
        phrase = _FEATURE_PHRASES.get(name, name)
        chips.append(f"{phrase} (z={z:+.2f})")
        reasons.append(phrase)
    if not chips:
        chips = ["mild anomaly"]
    return chips, ", ".join(reasons) or "anomalous transaction profile"


# --- public entry point ------------------------------------------------------


# Which failed check gives the alert its headline, most specific first.
_ALERT_TYPES = {
    "duplicate": "Duplicate Invoice",
    "purchase_order": "Purchase Order Discrepancy",
    "gstin": "Invalid Supplier GSTIN",
    "totals": "Amount / Tax Mismatch",
    "hsn": "HSN-SAC Classification",
    "format": "Invoice Format Defect",
}


def _alert_type(findings: list[Finding]) -> str:
    """Name the alert after its most serious deterministic finding."""
    if not findings:
        return "Invoice Risk"
    worst = max(findings, key=lambda f: f.weight)
    return _ALERT_TYPES.get(worst.check, "Invoice Risk")


def _combined_reason(findings: list[Finding], model_reason: str) -> str:
    """Lead with what is provably wrong, then what merely looks unusual."""
    if not findings:
        return model_reason
    ranked = sorted(findings, key=lambda f: -f.weight)
    text = "; ".join(f.title for f in ranked[:3])
    if len(ranked) > 3:
        text += f" (+{len(ranked) - 3} more)"
    return text


def run_fraud_detection(db: Session, client_id: int) -> list[FraudAlert]:
    """Score every invoice on two independent axes and raise the alerts.

    The statistical layer (``_score_with_ml``) answers "is this unusual?"; the
    integrity layer answers "is this document valid at all?". They are combined
    with ``max`` rather than averaged, because a provably invalid invoice stays
    high-risk however ordinary its numbers look — a well-forged invoice is
    designed to look unremarkable.
    """
    invoices = db.query(Invoice).filter(Invoice.client_id == client_id).all()
    if not invoices:
        return []

    existing_invoice_ids = {
        item.invoice_id
        for item in db.query(FraudAlert.invoice_id).filter(FraudAlert.client_id == client_id).all()
    }

    scored = _score_with_ml(invoices)
    if scored is None:
        scored = [_rule_based_score(inv) for inv in invoices]

    # Duplicate detection needs the whole set, so it runs once up front.
    duplicate_findings = integrity.check_duplicates(invoices)
    # Order evidence, when any orders have been uploaded at all.
    po_findings = purchase_orders.findings_for_client(db, client_id)

    created: list[FraudAlert] = []
    for invoice, (model_risk, chips, model_reason) in zip(invoices, scored):
        assessment = integrity.assess_invoice(invoice)
        findings = (
            assessment.findings
            + duplicate_findings.get(id(invoice), [])
            + po_findings.get(invoice.id, [])
        )
        integrity_risk = integrity.score_findings(findings)

        risk = max(int(model_risk), integrity_risk, _rule_floor(invoice))
        risk = int(max(0, min(100, risk)))

        if invoice.id in existing_invoice_ids:
            continue
        reportable = [f for f in findings if f.weight >= REPORTABLE_FINDING_WEIGHT]
        if risk < ALERT_THRESHOLD and not reportable:
            continue

        alert = FraudAlert(
            client_id=client_id,
            invoice_id=invoice.id,
            type=_alert_type(findings),
            entity=invoice.supplier,
            risk=risk,
            amount=invoice.total,
            reason=_combined_reason(findings, model_reason),
            shap_json=json.dumps(chips),
            findings_json=json.dumps([f.as_dict() for f in findings]),
        )
        db.add(alert)
        created.append(alert)

    db.commit()
    return created
