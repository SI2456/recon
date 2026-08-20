"""Canonical user roles.

The platform was originally built around a Chartered Accountant acting for
client businesses. It is now positioned as a reconciliation and
compliance-risk tool that a business runs on its own data, with a professional
reviewing the exceptions it raises — so the roles are:

``business_user``
    The finance/accounts person who actually holds the purchase register,
    sales register, invoices and ITC workings, and uploads them.
``tax_reviewer``
    The Tax & Compliance Reviewer who works through exceptions, ITC issues and
    risk cases. Deliberately *not* called a government tax officer: this is a
    professional reviewing evidence, not an official exercising statutory
    audit powers.
``admin``
    Users, configuration, audit logs, system health.

The previous ``ca`` and ``client`` values are still accepted everywhere and
map onto the new names, so tokens issued before the rename and rows not yet
migrated keep working.
"""

from __future__ import annotations


ADMIN = "admin"
BUSINESS_USER = "business_user"
TAX_REVIEWER = "tax_reviewer"

ALL_ROLES: tuple[str, ...] = (ADMIN, BUSINESS_USER, TAX_REVIEWER)

# Roles a visitor may register as. Admin is provisioned, never self-selected.
SELF_SERVICE_ROLES: frozenset[str] = frozenset({BUSINESS_USER, TAX_REVIEWER})

# Legacy value -> canonical value.
LEGACY_ALIASES: dict[str, str] = {
    "ca": TAX_REVIEWER,
    "client": BUSINESS_USER,
    "reviewer": TAX_REVIEWER,
    "business": BUSINESS_USER,
    "business_owner": BUSINESS_USER,
}

# Human-facing names, so the UI and API agree on wording.
LABELS: dict[str, str] = {
    ADMIN: "System Admin",
    BUSINESS_USER: "Business / Finance User",
    TAX_REVIEWER: "Tax & Compliance Reviewer",
}


def normalize(role: str | None) -> str:
    """Map any accepted spelling of a role onto its canonical value."""
    value = (role or "").strip().lower()
    value = LEGACY_ALIASES.get(value, value)
    return value if value in ALL_ROLES else ""


def label(role: str | None) -> str:
    return LABELS.get(normalize(role), "")


def is_reviewer(role: str | None) -> bool:
    """Reviewers and admins share the exception-review surface."""
    return normalize(role) in (TAX_REVIEWER, ADMIN)


def stored_values(role: str) -> list[str]:
    """Every value a row might hold for this role, canonical plus legacy.

    SQL filters compare against the raw column, so a query written only
    against the canonical name would miss rows that predate the migration.
    """
    canonical = normalize(role)
    if not canonical:
        return []
    legacy = [old for old, new in LEGACY_ALIASES.items() if new == canonical]
    return [canonical, *legacy]


def reviewer_role_values() -> list[str]:
    return stored_values(TAX_REVIEWER)


def business_role_values() -> list[str]:
    return stored_values(BUSINESS_USER)
