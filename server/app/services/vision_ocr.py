"""Invoice OCR + field extraction via the local vision-language model.

This module is a thin adapter over ``extract.py`` at the repository root — the
standalone Qwen2.5-VL pipeline — rather than a second, simpler extractor.

It used to carry its own one-shot prompt asking for a dozen flat fields. On a
real invoice that prompt returned 12 fields and no line items where
``extract.py`` returned 22 fields and the full item table, and it got numbers
wrong: taxable and tax transposed, and a GSTIN assembled out of the supplier's
PAN. Wrong values are worse than missing ones here, because the integrity
checks then flag a perfectly good invoice for broken arithmetic and a bad
GSTIN checksum.

So there is now one extractor, and it is the good one. ``extract.py`` brings
its full schema, JSON repair for truncated model output, line-item column
realignment, multi-page merging and post-processing validation.

If it cannot be imported the module falls back to the old flat prompt, so a
missing dependency degrades the result instead of breaking ingestion.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

import httpx

from app.core.config import settings


REPO_ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _extractor():
    """Import the standalone pipeline from the repo root, or None."""
    try:
        # extract.py reads its context settings from the environment at import
        # time, and server/.env is loaded into settings rather than os.environ,
        # so the values are bridged across before the import happens.
        os.environ.setdefault("OCR_NUM_CTX", str(settings.ocr_num_ctx))
        os.environ.setdefault("OCR_NUM_PREDICT", str(settings.ocr_num_predict))
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        import extract as module  # noqa: PLC0415 - optional, imported lazily

        # Guard against importing something unrelated that happens to be named
        # "extract" earlier on the path.
        if not hasattr(module, "extract_with_qwen"):
            return None
        return module
    except Exception:  # noqa: BLE001 - any import failure degrades to fallback
        return None


def extractor_available() -> bool:
    return _extractor() is not None


# --- the rich path -----------------------------------------------------------


def _pil_image(image_bytes: bytes):
    from PIL import Image  # noqa: PLC0415 - only needed on this path

    image = Image.open(io.BytesIO(image_bytes))
    image.load()
    return image.convert("RGB")


def _extract_pages_sync(pages: list[bytes]) -> dict:
    """Run the full pipeline over every page and merge into one document."""
    module = _extractor()
    if module is None:
        raise RuntimeError("extract.py is unavailable")

    results = []
    images = []
    for index, raw in enumerate(pages, start=1):
        image = _pil_image(raw)
        images.append(image)
        label = str(index) if len(pages) > 1 else ""
        results.append(module.extract_with_qwen(image, label))

    merged = module._merge(results) if len(results) > 1 else (results[0] if results else {})
    if not merged:
        return {}

    # Post-processing repairs shifted item columns, derives totals and
    # validates — the part that makes the numbers trustworthy.
    try:
        merged = module.run_post_processing(
            merged, file_path=None, page_count=len(pages), image=images[0] if images else None
        )
    except Exception:  # noqa: BLE001 - keep the raw extraction if repair fails
        pass
    return merged or {}


# --- fallback: the original flat prompt --------------------------------------

FALLBACK_PROMPT = (
    "You are an expert at reading Indian GST tax invoices. "
    "Read every character of this invoice image carefully and extract its details. "
    "Respond with ONLY a JSON object using exactly these keys:\n"
    '  "invoice_no": string — the full invoice/bill number, copied character-for-character,\n'
    '  "supplier_name": string — the seller/supplier ("Sold By") legal or trade name,\n'
    '  "supplier_gstin": string — the seller\'s 15-character GSTIN, copied exactly as printed; '
    'do NOT build one out of the PAN; "" if truly absent,\n'
    '  "invoice_date": string — prefer YYYY-MM-DD,\n'
    '  "hsn": string — the HSN or SAC code of the main line item, digits only; "" if absent,\n'
    '  "taxable": number — the taxable/assessable value BEFORE tax,\n'
    '  "gst": number — total tax = CGST + SGST + IGST + cess (this is much smaller than the taxable value),\n'
    '  "cgst": number — the CGST amount only (0 if the invoice shows IGST instead),\n'
    '  "sgst": number — the SGST/UTGST amount only (0 if the invoice shows IGST instead),\n'
    '  "igst": number — the IGST amount only (0 if the invoice shows CGST+SGST instead),\n'
    '  "recipient_gstin": string — the buyer\'s ("Bill To") 15-character GSTIN; "" if absent,\n'
    '  "place_of_supply": string — the place of supply, preferably its 2-digit state code; "" if absent,\n'
    '  "total": number — the final invoice grand total.\n'
    "Rules: taxable + gst must equal total, and gst is always far smaller than taxable. "
    "Use 0 for any missing number and \"\" for any missing text. "
    "Do not add explanations, markdown, or any text outside the JSON object."
)


def _extract_json(text: str) -> dict:
    """Best-effort parse of the model's response into a dict."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return {}


async def _fallback_extract(image_bytes: bytes) -> dict:
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": settings.ollama_vision_model,
        "prompt": FALLBACK_PROMPT,
        "images": [image_b64],
        "stream": False,
        "format": "json",
        # num_ctx must fit a high-resolution invoice image plus the prompt;
        # the default 4096 overflows and truncates the JSON.
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1536},
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
        response.raise_for_status()
        body = response.json()
    return _extract_json(body.get("response", ""))


# --- public API ---------------------------------------------------------------


async def extract_invoice_from_pages(pages: list[bytes]) -> dict:
    """Extract one invoice from the pages of a single document.

    Pages are merged into one result rather than one invoice per page, matching
    how ``extract.py`` treats a document: a three-page invoice is one invoice.

    Raises httpx.HTTPError when Ollama is unreachable so callers can fall back.
    """
    if not pages:
        return {}
    if _extractor() is not None:
        # The pipeline is synchronous and long-running; keep the event loop free.
        return await asyncio.to_thread(_extract_pages_sync, pages)
    return await _fallback_extract(pages[0])


async def extract_invoice_from_image(image_bytes: bytes) -> dict:
    """Single-image convenience wrapper."""
    return await extract_invoice_from_pages([image_bytes])
