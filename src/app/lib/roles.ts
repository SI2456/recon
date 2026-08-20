/**
 * Canonical user roles — the frontend mirror of server/app/core/roles.py.
 *
 * The platform is positioned as a reconciliation and compliance-risk tool a
 * business runs on its own data, with a professional reviewing the exceptions
 * it raises. So the roles are the business/finance user who holds the records,
 * the tax & compliance reviewer who works through exceptions, and the admin.
 *
 * The earlier `ca` / `client` values are still accepted, because a session
 * stored in localStorage before the rename will still carry them.
 */

export type Role = "admin" | "business_user" | "tax_reviewer";

export const ADMIN: Role = "admin";
export const BUSINESS_USER: Role = "business_user";
export const TAX_REVIEWER: Role = "tax_reviewer";

const LEGACY_ALIASES: Record<string, Role> = {
  ca: TAX_REVIEWER,
  reviewer: TAX_REVIEWER,
  client: BUSINESS_USER,
  business: BUSINESS_USER,
  business_owner: BUSINESS_USER,
};

const ALL: Role[] = [ADMIN, BUSINESS_USER, TAX_REVIEWER];

/** Map any accepted spelling onto its canonical value. */
export function normalizeRole(role: string | null | undefined): Role | "" {
  const value = (role || "").trim().toLowerCase();
  const mapped = LEGACY_ALIASES[value] ?? (value as Role);
  return ALL.includes(mapped) ? mapped : "";
}

export const ROLE_LABELS: Record<Role, string> = {
  admin: "System Admin",
  business_user: "Business / Finance User",
  tax_reviewer: "Tax & Compliance Reviewer",
};

/** Shorter label for chips and table cells. */
export const ROLE_SHORT_LABELS: Record<Role, string> = {
  admin: "Admin",
  business_user: "Business User",
  tax_reviewer: "Tax Reviewer",
};

export function roleLabel(role: string | null | undefined): string {
  const normalized = normalizeRole(role);
  return normalized ? ROLE_LABELS[normalized] : "";
}

export function roleShortLabel(role: string | null | undefined): string {
  const normalized = normalizeRole(role);
  return normalized ? ROLE_SHORT_LABELS[normalized] : "";
}

export function isReviewer(role: string | null | undefined): boolean {
  const normalized = normalizeRole(role);
  return normalized === TAX_REVIEWER || normalized === ADMIN;
}
