import re
from datetime import date

import httpx
from fastapi import HTTPException, status

from app.core.config import settings


GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def normalize_gstin(gstin: str) -> str:
    value = re.sub(r"[^A-Z0-9]", "", gstin.upper())
    if not GSTIN_PATTERN.match(value):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid GSTIN format.")
    return value


def _headers() -> dict[str, str]:
    if not settings.gstverify_api_key:
        raise HTTPException(status_code=500, detail="GSTVerify API key is not configured on the server.")
    return {"X-API-Key": settings.gstverify_api_key}


def _current_fy_year() -> str:
    """Indian financial year start year (April–March), as the API expects it."""
    today = date.today()
    return str(today.year if today.month >= 4 else today.year - 1)


def _extract_message(body: dict) -> str:
    detail = body.get("detail")
    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("error") or ""
    elif isinstance(detail, str):
        message = detail
    else:
        message = body.get("message") or ""
    # The API sometimes returns the literal string "None"/"null" as its detail.
    return "" if message.strip().lower() in ("none", "null") else message


async def verify_gstin_profile(gstin: str) -> dict:
    """Validate a GSTIN against the live GST portal (via GSTVerify).

    Uses the captcha-free profile endpoint, which confirms whether a GSTIN is
    registered (``data.status == 1``) and returns its QRMP filing preferences.
    Full taxpayer details (legal name, address) require the captcha-gated
    ``/gst/details`` endpoint and are intentionally not fetched here.
    """
    clean_gstin = normalize_gstin(gstin)
    fy = _current_fy_year()

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{settings.gstverify_base_url}/gst/profile/{clean_gstin}",
            headers=_headers(),
            params={"fy": fy},
        )

    body = response.json() if response.content else {}
    if response.status_code >= 400:
        message = _extract_message(body) or "GSTIN verification failed."
        raise HTTPException(status_code=response.status_code, detail=message)

    data = body.get("data") or {}
    portal_status = data.get("status")

    if portal_status == 0:
        error = data.get("error") or {}
        raise HTTPException(status_code=400, detail=error.get("message") or "Invalid GSTIN.")
    if portal_status != 1:
        raise HTTPException(
            status_code=502,
            detail=_extract_message(body) or "GST portal is temporarily unavailable. Please try again.",
        )

    preferences = (data.get("data") or {}).get("response") or []
    return {
        "gstin": clean_gstin,
        "legalName": "",
        "tradeName": "",
        "status": "Active",
        "taxpayerType": "",
        "registrationDate": "",
        "address": "",
        "filingPreferences": preferences,
        "financialYear": fy,
        "raw": body,
    }


def _pick(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return ""


def _format_address(pradr) -> str:
    """Turn the GST portal's principal-address object into a single line."""
    if not isinstance(pradr, dict):
        return str(pradr or "")
    if pradr.get("adr"):
        return str(pradr["adr"])
    addr = pradr.get("addr")
    if isinstance(addr, dict):
        parts = [addr.get(k) for k in ("bno", "bnm", "flno", "st", "loc", "dst", "stcd", "pncd")]
        return ", ".join(str(p) for p in parts if p)
    return ""


def _normalize_taxpayer(data: dict) -> dict:
    return {
        "gstin": _pick(data, "gstin", "GSTIN"),
        "legalName": _pick(data, "lgnm", "legalName", "legal_name", "name"),
        "tradeName": _pick(data, "tradeNam", "tradeName", "trade_name"),
        "status": _pick(data, "sts", "status", "gstinStatus"),
        "taxpayerType": _pick(data, "ctb", "taxpayerType", "dty"),
        "registrationDate": _pick(data, "rgdt", "registrationDate"),
        "address": _format_address(data.get("pradr") or data.get("principalAddress")),
    }


async def fetch_gstin_captcha() -> dict:
    """Get a captcha image + session id the user must solve to fetch full details."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{settings.gstverify_base_url}/gst/captcha", headers=_headers())
    body = response.json() if response.content else {}
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=_extract_message(body) or "Could not load captcha.")
    return {"sessionId": body.get("sessionId", ""), "image": body.get("image", "")}


async def verify_gstin_details(gstin: str, session_id: str, captcha: str) -> dict:
    """Fetch full taxpayer details (legal name, address, status) via the
    captcha-gated portal endpoint. Requires a session id + solved captcha."""
    clean_gstin = normalize_gstin(gstin)
    if not session_id or not captcha:
        raise HTTPException(status_code=400, detail="Captcha session and text are required.")

    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post(
            f"{settings.gstverify_base_url}/gst/details",
            headers=_headers(),
            json={"sessionId": session_id, "GSTIN": clean_gstin, "captcha": captcha, "full": True},
        )

    body = response.json() if response.content else {}
    if response.status_code >= 400:
        # A 400 here almost always means a wrong/expired captcha.
        fallback = "Incorrect captcha or the session expired. Please refresh the captcha and try again." if response.status_code == 400 else "GSTIN verification failed."
        raise HTTPException(status_code=response.status_code, detail=_extract_message(body) or fallback)

    data = body.get("data") or {}
    if data.get("status") == 0:
        error = data.get("error") or {}
        raise HTTPException(status_code=400, detail=error.get("message") or "Invalid GSTIN or captcha. Please retry.")

    # The taxpayer object may be nested one level deeper than the status wrapper.
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=502, detail="GSTIN details are unavailable right now. Please retry.")

    normalized = _normalize_taxpayer(payload)
    normalized["gstin"] = normalized["gstin"] or clean_gstin
    normalized["raw"] = body
    return normalized
