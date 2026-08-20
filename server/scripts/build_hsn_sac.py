"""Build the HSN/SAC master lookup used by the invoice-integrity checks.

Reads the official GST rate schedules (HSN.xlsx / SAC.xlsx at the repo root)
and emits a compact ``server/app/data/hsn_sac.json`` mapping each code to the
set of GST rates it legitimately carries. The JSON is committed so the running
server never needs pandas/openpyxl — only this build step does.

Run after replacing either spreadsheet:

    server\\venv\\Scripts\\python.exe server/scripts/build_hsn_sac.py

Quirks in the source spreadsheets this handles:

* Excel stripped leading zeros from numeric cells, so "210" is really HSN
  0210. Codes are always an even number of digits, so an odd-length token is
  left-padded with one zero.
* A single rate entry spans several rows: the first row carries the serial
  number and the rates, continuation rows carry only more codes. Rows are
  therefore grouped on the serial-number column and their code cells joined
  before parsing.
* Codes appear as comma-separated lists and as ranges ("5106 to 5110"), and a
  range can straddle two rows ("5004 to" / "5012"). Joining the group first
  makes both forms parseable.
* Exclusions such as "[Except 050790]" are deliberately NOT honoured: the
  excluded code is still a real HSN, just at a different rate. Treating it as
  valid keeps the checker over-inclusive, which errs toward fewer false fraud
  flags.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = REPO_ROOT / "server" / "app" / "data" / "hsn_sac.json"

# Statutory GST rate slabs (percent). Anything outside this set cannot be a
# legitimate rate on a GST invoice.
GST_SLABS = [0.0, 0.1, 0.25, 1.0, 1.5, 3.0, 5.0, 6.0, 7.5, 12.0, 18.0, 28.0]

_RANGE = re.compile(r"(\d{2,8})\s*to\s*(\d{2,8})", re.I)
_TOKEN = re.compile(r"\d{2,8}")


def _normalize_code(token: str) -> str | None:
    """Even-length digit code, left-padded to undo Excel's stripped zeros."""
    digits = re.sub(r"\D", "", token)
    if not digits:
        return None
    if len(digits) % 2:
        digits = "0" + digits
    return digits if len(digits) in (2, 4, 6, 8) else None


def _codes_from_text(text: str) -> set[str]:
    """Pull every code out of a joined group of code cells, expanding ranges."""
    codes: set[str] = set()
    consumed: list[tuple[int, int]] = []

    for match in _RANGE.finditer(text):
        start, end = _normalize_code(match.group(1)), _normalize_code(match.group(2))
        consumed.append(match.span())
        if not start or not end or len(start) != len(end):
            continue
        lo, hi = int(start), int(end)
        # Guard against a mis-parse producing an absurd expansion.
        if lo <= hi and hi - lo <= 500:
            width = len(start)
            codes.update(str(value).zfill(width) for value in range(lo, hi + 1))

    # Standalone tokens outside any range expression.
    masked = list(text)
    for start, end in consumed:
        masked[start:end] = " " * (end - start)
    for match in _TOKEN.finditer("".join(masked)):
        code = _normalize_code(match.group(0))
        if code:
            codes.add(code)
    return codes


# A rate cell is only usable when it is a bare number or a short "A or B"
# alternation. The SAC sheet also holds prose ("Same rate of integrated tax as
# on supply of like goods...", "65 per cent. of the rate...") which pins no
# determinate rate — those codes are recorded with no rate constraint rather
# than a guessed one.
_NUMERIC_CELL = re.compile(r"^\s*\d+(?:\.\d+)?(?:\s*or\s*\d+(?:\.\d+)?)*\s*$", re.I)


def _cell_rates(value, scale: float) -> set[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return set()
    if isinstance(value, (int, float)):
        return {round(float(value) * scale, 3)}
    text = str(value).strip()
    if not _NUMERIC_CELL.match(text):
        return set()
    return {round(float(n) * scale, 3) for n in re.findall(r"\d+(?:\.\d+)?", text)}


def _rate_percent(row, scale: float) -> set[float]:
    """GST rates a record permits, as percentages (may be empty or multi-valued)."""
    rates = _cell_rates(row.get("igst"), scale)
    if rates:
        return rates
    # No IGST column value — reconstruct from the CGST/SGST halves.
    cgst = _cell_rates(row.get("cgst"), scale)
    sgst = _cell_rates(row.get("sgst"), scale)
    if cgst and sgst:
        return {round(c + s, 3) for c in cgst for s in sgst}
    if cgst:
        return {round(c * 2, 3) for c in cgst}
    return set()


def _grouped_records(frame: pd.DataFrame, scale: float) -> list[tuple[str, set[float]]]:
    """Collapse continuation rows into (joined code text, rates) records."""
    records: list[tuple[str, set[float]]] = []
    current: list[str] = []
    rates: set[float] = set()

    for _, row in frame.iterrows():
        starts_record = pd.notna(row.get("sno"))
        if starts_record and current:
            records.append((" ".join(current), rates))
            current = []
        if starts_record:
            rates = _rate_percent(row, scale)
        cell = row.get("code")
        if pd.notna(cell):
            current.append(str(cell))
    if current:
        records.append((" ".join(current), rates))
    return records


def _accumulate(records, into: dict[str, set[float]], code_filter=None) -> None:
    for text, rates in records:
        for code in _codes_from_text(text):
            if code_filter and not code_filter(code):
                continue
            into.setdefault(code, set()).update(rates)


def build_hsn() -> dict[str, set[float]]:
    frame = pd.read_excel(REPO_ROOT / "HSN.xlsx")
    frame.columns = ["sched", "sno", "code", "desc", "cgst", "sgst", "igst", "cess"]
    result: dict[str, set[float]] = {}
    _accumulate(_grouped_records(frame, scale=100.0), result)
    return result


def build_sac() -> dict[str, set[float]]:
    frame = pd.read_excel(REPO_ROOT / "SAC.xlsx")
    frame.columns = ["sno", "code", "desc", "cgst", "sgst", "igst", "cond"]
    # Only "Heading 9954" / "Chapter 99" cells hold codes. "Section 5" is a
    # section number, not a SAC, and the parenthesised cells are descriptions.
    frame = frame.copy()
    frame["code"] = frame["code"].where(
        frame["code"].astype(str).str.strip().str.match(r"(?i)^(heading|chapter)\b"), other=pd.NA
    )
    result: dict[str, set[float]] = {}
    # Every SAC lives under chapter 99.
    _accumulate(_grouped_records(frame, scale=1.0), result, code_filter=lambda c: c.startswith("99"))
    return result


def main() -> int:
    hsn, sac = build_hsn(), build_sac()
    # Chapter 99 genuinely has only ~31 service headings, so the SAC floor is
    # low by nature; the HSN schedule is the large one.
    if len(hsn) < 500 or len(sac) < 25:
        print(f"Refusing to write: implausible extraction (hsn={len(hsn)}, sac={len(sac)}).")
        return 1

    payload = {
        "_comment": "Generated by server/scripts/build_hsn_sac.py from HSN.xlsx / SAC.xlsx. Do not edit by hand.",
        "slabs": GST_SLABS,
        "hsn": {code: sorted(rates) for code, rates in sorted(hsn.items())},
        "sac": {code: sorted(rates) for code, rates in sorted(sac.items())},
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=1, sort_keys=False), encoding="utf-8")

    print(f"Wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    print(f"  HSN codes: {len(hsn)}   SAC codes: {len(sac)}")
    print(f"  size: {OUT_PATH.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
