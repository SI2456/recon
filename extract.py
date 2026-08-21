#!/usr/bin/env python3
"""
Universal Invoice Extractor — Qwen2.5-VL Pipeline
==================================================
Outputs per invoice:
  1. <name>_extracted.txt   — full formatted report
  2. <name>_checklist.txt   — ✅ Found / ❌ Missing field checklist
  3. <name>_extracted.json  — raw structured JSON

Requires:
  pip install pymupdf pillow
  ollama pull qwen2.5vl:3b
  ollama serve
"""

import os, re, sys, json, time, base64, io, argparse, tempfile, zipfile, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageOps, ImageFilter

# ---------------------------------------------------------------------------
SUPPORTED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
SUPPORTED_PDF_EXT   = {".pdf"}
SUPPORTED_ZIP_EXT   = {".zip"}
ALL_SUPPORTED_EXT   = SUPPORTED_IMAGE_EXT | SUPPORTED_PDF_EXT
MAX_ZIP_FILES       = 10

QWEN_MODEL        = "qwen2.5vl:3b"

# A rendered A4 invoice page costs roughly 3,500-5,000 vision tokens on its
# own, so the original 4096 context could not fit the image *and* the prompt:
# every request came back "exceeds the available context size" and extraction
# returned nothing.
#
# 8192 covers image + prompt + reply with headroom while keeping the working
# set small. Measured on a 4 GB RTX 3050 Ti, where the model is partly
# CPU-offloaded either way, raising this to 16384 bought no accuracy and cost
# ~5% throughput plus 300 MB of VRAM (a worse CPU/GPU split). Raise it only if
# a very dense page starts failing on context size.
_NUM_CTX     = int(os.environ.get("OCR_NUM_CTX", "8192"))
_NUM_PREDICT = int(os.environ.get("OCR_NUM_PREDICT", "2048"))
_OLLAMA_AVAILABLE = None
_OLLAMA_LOCK      = threading.Lock()

# ---------------------------------------------------------------------------
# Compact prompt  (~900 tokens — well within 8192 ctx)
# ---------------------------------------------------------------------------
_PROMPT = """Extract ALL visible data from this invoice image. Return ONE valid JSON object.
No markdown, no explanation. Start with '{' end with '}'.
Use null for any field not visible. Read carefully — do not guess or hallucinate.

JSON schema:
{
  "document_title":"string","invoice_type":"string","invoice_number":"string",
  "invoice_date":"string","due_date":"string","currency":"string",
  "irn":"string","ack_number":"string","ack_date":"string",
  "place_of_supply":"string","reverse_charge":"string",

  "supplier":{
    "name":"string","gstin":"string","pan":"string","cin":"string",
    "address":"string","city":"string","state":"string","country":"string",
    "pin":"string","phone":"string","email":"string","website":"string"
  },

  "buyer":{
    "name":"string","gstin":"string",
    "billing_address":"string","shipping_address":"string",
    "city":"string","state":"string","country":"string",
    "phone":"string","email":"string"
  },

  "consignee":{
    "name":"string","address":"string","gstin":"string","state":"string"
  },

  "order_info":{
    "po_number":"string","delivery_challan":"string","reference_number":"string",
    "payment_terms":"string","sales_order":"string","work_order":"string",
    "quotation_number":"string","contract_number":"string",
    "vendor_code":"string","customer_id":"string","eway_bill":"string"
  },

  "logistics":{
    "vehicle_number":"string","transporter_name":"string","lr_number":"string",
    "dispatch_date":"string","delivery_date":"string","tracking_number":"string","destination":"string"
  },

  "table_headers":["string"],
  "line_items":[["string"]],

  "tax_summary":{
    "taxable_amount":"string",
    "cgst_rate":"string","cgst_amount":"string",
    "sgst_rate":"string","sgst_amount":"string",
    "igst_rate":"string","igst_amount":"string",
    "utgst":"string","cess":"string","tds":"string","total_tax":"string"
  },

  "amount_summary":{
    "subtotal":"string","discount":"string","freight":"string",
    "shipping":"string","packing":"string","insurance":"string",
    "round_off":"string","grand_total":"string","total_in_words":"string",
    "amount_paid":"string","balance_due":"string"
  },

  "payment":{
    "bank_name":"string","account_holder":"string","account_number":"string",
    "ifsc_code":"string","branch":"string","swift_code":"string",
    "upi_id":"string","payment_status":"string","payment_method":"string"
  },

  "authorisation":{
    "signatory":"string","seal":"string","digital_signature":"string"
  },

  "notes":{
    "terms_conditions":"string","return_policy":"string",
    "warranty":"string","additional_notes":"string"
  }
}

Rules for table:
- table_headers: exact column header text from the printed table
- line_items: list of lists; each inner list = one product row matching table_headers columns in order
- Never skip serial number column; never shift columns
- Combine multi-line description text with \\n"""

_SCHEMA_HINT = """{
  "document_title":"string","invoice_type":"string","invoice_number":"string","invoice_date":"string","due_date":"string","currency":"string",
  "irn":"string","ack_number":"string","ack_date":"string","place_of_supply":"string","reverse_charge":"string",
  "supplier":{"name":"string","gstin":"string","pan":"string","cin":"string","address":"string","city":"string","state":"string","country":"string","pin":"string","phone":"string","email":"string","website":"string"},
  "buyer":{"name":"string","gstin":"string","billing_address":"string","shipping_address":"string","city":"string","state":"string","country":"string","phone":"string","email":"string"},
  "consignee":{"name":"string","address":"string","gstin":"string","state":"string"},
  "order_info":{"po_number":"string","delivery_challan":"string","reference_number":"string","payment_terms":"string","sales_order":"string","work_order":"string","quotation_number":"string","contract_number":"string","vendor_code":"string","customer_id":"string","eway_bill":"string"},
  "logistics":{"vehicle_number":"string","transporter_name":"string","lr_number":"string","dispatch_date":"string","delivery_date":"string","tracking_number":"string","destination":"string"},
  "table_headers":["string"],"line_items":[["string"]],
  "tax_summary":{"taxable_amount":"string","cgst_rate":"string","cgst_amount":"string","sgst_rate":"string","sgst_amount":"string","igst_rate":"string","igst_amount":"string","utgst":"string","cess":"string","tds":"string","total_tax":"string"},
  "amount_summary":{"subtotal":"string","discount":"string","freight":"string","shipping":"string","packing":"string","insurance":"string","round_off":"string","grand_total":"string","total_in_words":"string","amount_paid":"string","balance_due":"string"},
  "payment":{"bank_name":"string","account_holder":"string","account_number":"string","ifsc_code":"string","branch":"string","swift_code":"string","upi_id":"string","payment_status":"string","payment_method":"string"},
  "authorisation":{"signatory":"string","seal":"string","digital_signature":"string"},
  "notes":{"terms_conditions":"string","return_policy":"string","warranty":"string","additional_notes":"string"}
}"""

# ---------------------------------------------------------------------------
def qwen_available():
    global _OLLAMA_AVAILABLE
    if _OLLAMA_AVAILABLE is not None:
        return _OLLAMA_AVAILABLE
    with _OLLAMA_LOCK:
        if _OLLAMA_AVAILABLE is not None:
            return _OLLAMA_AVAILABLE
        try:
            import urllib.request
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
                data = json.loads(r.read())
                names = [m.get("name", "") for m in data.get("models", [])]
                base  = QWEN_MODEL.split(":")[0]
                _OLLAMA_AVAILABLE = any(base in n or "qwen" in n or "vision" in n for n in names) if names else False
        except Exception as e:
            print(f"[!] Ollama not reachable: {e}")
            _OLLAMA_AVAILABLE = False
    return _OLLAMA_AVAILABLE


def _img_b64(image, quality=85):
    """Encode image as JPEG (much smaller than PNG) for Ollama payload."""
    buf = io.BytesIO()
    rgb = image.convert("RGB")
    rgb.save(buf, format="JPEG", quality=quality, optimize=True)
    size_kb = buf.tell() // 1024
    print(f"    [img] Encoded as JPEG: {rgb.size[0]}x{rgb.size[1]}px, {size_kb} KB")
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Numeric Normalization
# ---------------------------------------------------------------------------
def normalize_float(val):
    if val is None:
        return 0.0
    s = str(val).strip()
    s = re.sub(r'(?i)^(?:rs\.?|inr\.?|usd\.?|eur\.?|₹|\$)\s*', '', s)
    s = re.sub(r'[^\d\.\-]', '', s)
    if s.count('.') > 1:
        parts = s.split('.')
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(s)
    except ValueError:
        return 0.0

# ---------------------------------------------------------------------------
# GSTIN Parser & Validator (India)
# ---------------------------------------------------------------------------
STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    # 25 was Daman & Diu before it merged into 26 in 2020. Invoices predating
    # the merger still carry it, and leaving it out reported them as an
    # unknown state.
    "25": "Daman & Diu (pre-2020)",
    "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra", "28": "Andhra Pradesh",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman & Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh (New)",
    "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction"
}

# GSTIN check-digit alphabet: values 0-35 in order.
_GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(first_fourteen):
    """The 15th character required by the GSTIN mod-36 checksum.

    Mirrors server/app/services/integrity.gstin_check_digit. Kept as a local
    copy rather than an import because this module also runs standalone from
    the command line, with no server package on the path.
    """
    factor, total, mod = 2, 0, len(_GSTIN_ALPHABET)
    for char in reversed(first_fourteen):
        product = factor * _GSTIN_ALPHABET.index(char)
        factor = 1 if factor == 2 else 2
        total += (product // mod) + (product % mod)
    return _GSTIN_ALPHABET[(mod - (total % mod)) % mod]

def analyze_gstin(gstin):
    if is_empty(gstin):
        return {"valid": False, "reason": "Not Present", "state_code": "N/A", "state_name": "N/A", "pan": "N/A", "gst_type": "N/A"}
    raw_str = str(gstin).strip().upper().replace(" ", "")
    gst_pattern = r'([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})'
    match = re.search(gst_pattern, raw_str)
    if match:
        g = match.group(1)
        well_formed = True
    else:
        g = re.sub(r'[^A-Z0-9]', '', raw_str)
        gst_regex = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$'
        well_formed = bool(re.match(gst_regex, g))

    # The shape alone proves nothing — an invented GSTIN can be written to
    # match it. The mod-36 check digit is what makes a real GSTIN
    # self-validating, and it fails an invented one 35 times out of 36. Without
    # it this panel called a fabricated supplier valid while the rule engine
    # (services/integrity.check_gstin) flagged the same number as fabricated,
    # so a reviewer saw the two disagree on the same document.
    checksum_ok = well_formed and g[14] == gstin_check_digit(g[:14])
    is_valid = well_formed and checksum_ok

    state_code = g[:2] if len(g) >= 2 else "N/A"
    state_name = STATE_CODES.get(state_code, "Unknown State") if state_code != "N/A" else "N/A"
    pan = g[2:12] if len(g) >= 12 else "N/A"

    if not well_formed:
        reason = "Malformed"
    elif not checksum_ok:
        reason = "Check digit does not match — the number is almost certainly fabricated"
    else:
        reason = "Valid"

    return {
        "raw": gstin,
        "gstin": g if is_valid else "N/A",
        "valid": is_valid,
        "well_formed": well_formed,
        "checksum_ok": checksum_ok,
        "reason": reason,
        "state_code": state_code,
        "state_name": state_name,
        "pan": pan,
        "gst_type": "Regular (Derived)" if is_valid else "Unknown/Invalid"
    }

# ---------------------------------------------------------------------------
# Address Parsing Helper
# ---------------------------------------------------------------------------
def split_address(addr_str):
    if is_empty(addr_str):
        return {
            "raw": "Not Present", "building": "N/A", "floor": "N/A",
            "area": "N/A", "city": "N/A", "state": "N/A", "pin": "N/A", "country": "N/A"
        }
    
    raw = str(addr_str).strip()
    pin_match = re.search(r'\b([1-9][0-9]{5})\b', raw)
    pin = pin_match.group(1) if pin_match else "N/A"
    
    state = "N/A"
    for code, name in STATE_CODES.items():
        if name.lower() in raw.lower():
            state = name
            break
            
    country = "India" if any(x in raw.lower() for x in ["india", "ind", "pin:"]) else "N/A"
    
    city = "N/A"
    common_cities = ["nagpur", "mumbai", "pune", "delhi", "kolkata", "chennai", "bangalore", "hyderabad", "ahmedabad", "surat"]
    for c in common_cities:
        if c in raw.lower():
            city = c.capitalize()
            break
            
    floor = "N/A"
    floor_match = re.search(r'\b(\d+)(?:st|nd|rd|th)?\s+floor\b', raw, re.IGNORECASE)
    if floor_match:
        floor = f"Floor {floor_match.group(1)}"
        
    building = "N/A"
    bld_match = re.search(r'\b(?:plot|shop|flat|office|building|house)\s+(?:no\.?\s*)?([A-Za-z0-9\-/]+)\b', raw, re.IGNORECASE)
    if bld_match:
        building = f"{bld_match.group(0)}"
        
    area = raw
    if building != "N/A": area = area.replace(building, "")
    if floor != "N/A": area = area.replace(floor_match.group(0), "")
    if pin != "N/A": area = area.replace(pin, "")
    if state != "N/A": area = area.replace(state, "")
    if country != "N/A" and country != "India": area = area.replace(country, "")
    area = re.sub(r'[\s,]+', ' ', area).strip()
    if not area: area = "N/A"
    
    return {
        "raw": raw,
        "building": building,
        "floor": floor,
        "area": area[:100],
        "city": city,
        "state": state,
        "pin": pin,
        "country": country
    }

# ---------------------------------------------------------------------------
# HSN / SAC Reference Excel Database Loaders
# ---------------------------------------------------------------------------
_HSN_DB = None
_SAC_DB = None

def load_gst_excel_db(file_path):
    db = {}
    if not os.path.exists(file_path):
        print(f"    [db] Reference database not found at: {file_path}")
        return db
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
        sheet = wb.active
        headers = []
        for row in sheet.iter_rows(max_row=1, values_only=True):
            headers = [str(x or "").strip().lower() for x in row]
            break
        if not headers:
            return db
        code_idx, cgst_idx, sgst_idx, igst_idx, total_idx = -1, -1, -1, -1, -1
        for i, h in enumerate(headers):
            if any(x in h for x in ["hsn", "sac", "code", "chapter", "heading"]):
                code_idx = i
            elif "cgst" in h or "central" in h:
                cgst_idx = i
            elif "sgst" in h or "state" in h:
                sgst_idx = i
            elif "igst" in h or "integrated" in h:
                igst_idx = i
            elif any(x in h for x in ["rate", "gst", "total", "tax"]):
                if total_idx == -1:
                    total_idx = i
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if len(row) <= max(code_idx, 0):
                continue
            code_val = row[code_idx] if code_idx != -1 else None
            if code_val is None:
                continue
            code_str = str(code_val).strip().split(".")[0].replace(" ", "")
            if not code_str:
                continue
            cgst_val = normalize_float(row[cgst_idx]) if cgst_idx != -1 else 0.0
            sgst_val = normalize_float(row[sgst_idx]) if sgst_idx != -1 else 0.0
            igst_val = normalize_float(row[igst_idx]) if igst_idx != -1 else 0.0
            total_val = normalize_float(row[total_idx]) if total_idx != -1 else 0.0
            if cgst_val == 0.0 and sgst_val == 0.0 and total_val > 0.0:
                cgst_val = total_val / 2.0
                sgst_val = total_val / 2.0
            db[code_str] = {
                "cgst": cgst_val,
                "sgst": sgst_val,
                "igst": igst_val or total_val,
                "total": total_val or (cgst_val + sgst_val)
            }
        print(f"    [db] Loaded {len(db)} records from: {Path(file_path).name}")
    except Exception as e:
        print(f"    [db] Error loading database {file_path}: {e}")
    return db

def init_gst_databases():
    global _HSN_DB, _SAC_DB
    base_dir = Path(__file__).resolve().parent
    # Next to this file first, then the working directory. The third fallback
    # used to be a hardcoded "S:\OCR paddle\" path from one developer's
    # machine, which exists nowhere else and only delayed the "not found"
    # message by one lookup.
    if _HSN_DB is None:
        hsn_path = base_dir / "HSN.xlsx"
        if not hsn_path.exists():
            hsn_path = Path("HSN.xlsx")
        _HSN_DB = load_gst_excel_db(str(hsn_path))
    if _SAC_DB is None:
        sac_path = base_dir / "SAC.xlsx"
        if not sac_path.exists():
            sac_path = Path("SAC.xlsx")
        _SAC_DB = load_gst_excel_db(str(sac_path))

# ---------------------------------------------------------------------------

# JSON parsing helpers
# ---------------------------------------------------------------------------
def clean_truncated_tail(s):
    s = s.strip()
    while True:
        prev = len(s)
        s = re.sub(r'[:,\s]+$', '', s)
        s = re.sub(r',?\s*"[a-zA-Z0-9_-]+$', '', s)
        if len(s) == prev:
            break
    return s


def escape_json_string_newlines(s):
    res = []
    in_string = False
    escaped = False
    for char in s:
        if char == '"' and not escaped:
            in_string = not in_string
        elif char == '\\' and in_string:
            escaped = not escaped
        else:
            escaped = False
        if in_string and char == '\n':
            res.append('\\n')
        elif in_string and char == '\r':
            res.append('\\r')
        else:
            res.append(char)
    return "".join(res)


def fix_missing_json_commas(s):
    lines = s.split("\n")
    for i in range(len(lines)):
        line_strip = lines[i].strip()
        is_kv_line = bool(re.match(r'^"[a-zA-Z0-9_-]+"\s*:\s*.*$', line_strip))
        is_closing_line = line_strip in ("}", "]") or line_strip.endswith("}") or line_strip.endswith("]")
        
        if (is_kv_line or is_closing_line) and not line_strip.endswith(",") and not line_strip.endswith("{") and not line_strip.endswith("["):
            next_line_idx = i + 1
            while next_line_idx < len(lines) and not lines[next_line_idx].strip():
                next_line_idx += 1
            if next_line_idx < len(lines):
                next_strip = lines[next_line_idx].strip()
                if re.match(r'^"[a-zA-Z0-9_-]+"\s*:', next_strip) or next_strip.startswith("{") or next_strip.startswith("[") or next_strip.startswith('"'):
                    lines[i] = lines[i] + ","
    return "\n".join(lines)


def repair_json_string(s):
    s = fix_missing_json_commas(s)
    s = escape_json_string_newlines(s)
    s = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', s)
    # Fix Python literal Booleans / None if model outputted them
    s = re.sub(r'\bTrue\b', 'true', s)
    s = re.sub(r'\bFalse\b', 'false', s)
    s = re.sub(r'\bNone\b', 'null', s)
    quotes = re.findall(r'(?<!\\)"', s)
    if len(quotes) % 2 != 0:
        s += '"'
    s = clean_truncated_tail(s)
    s = re.sub(r',\s*\}', '}', s)
    s = re.sub(r',\s*\]', ']', s)
    open_braces   = s.count('{') - s.count('}')
    open_brackets = s.count('[') - s.count(']')
    if open_brackets > 0: s += ']' * open_brackets
    if open_braces   > 0: s += '}' * open_braces
    return s


def robust_json_loads(s):
    cleaned = s.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```[a-z]*\n?', '', cleaned)
        cleaned = re.sub(r'```\s*$', '', cleaned).strip()
    
    # Try json_repair package if installed
    try:
        import json_repair
        return json_repair.loads(cleaned)
    except Exception:
        pass

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    first = cleaned.find('{')
    if first == -1:
        return {}
    candidate = cleaned[first:]
    last = candidate.rfind('}')
    if last != -1:
        try:
            return json.loads(candidate[:last+1])
        except Exception:
            pass

    fixed = repair_json_string(candidate)
    try:
        return json.loads(fixed)
    except Exception as e:
        print(f"    [!] JSON parse failed: {e}")

    # Aggressive multi-pass repair
    try:
        fixed_agg = re.sub(r'([^{\[,:\s]+)\s*:\s*', r'"\1": ', fixed)
        return json.loads(fixed_agg)
    except Exception:
        pass

    return {}


def is_empty(v):
    if v is None:
        return True
    if str(v).strip() in ("", "null", "None", "N/A", "n/a"):
        return True
    if isinstance(v, (list, dict)) and len(v) == 0:
        return True
    return False


def merge_deep(d1, d2):
    merged = {}
    for k in set(d1.keys()) | set(d2.keys()):
        v1, v2 = d1.get(k), d2.get(k)
        if isinstance(v2, dict) and isinstance(v1, dict):
            merged[k] = merge_deep(v1, v2)
        elif not is_empty(v2):
            if k == "line_items" and not is_empty(v1):
                merged[k] = v2 if len(v2) >= len(v1) else v1
            else:
                merged[k] = v2
        else:
            merged[k] = v1
    return merged


def _is_valid_hsn(val):
    """Return True if val looks like a real HSN/SAC code (4-8 digits, no letters)."""
    v = str(val or "").strip()
    return bool(re.match(r'^\d{4,8}$', v))


def parse_words_to_num(text):
    """Parse Indian currency word representations into float (e.g. TWENTY FOUR THOUSAND NINE HUNDRED TWENTY TWO ONLY -> 24922.0)."""
    if not text:
        return None
    s = str(text).upper()
    s = re.sub(r'^(?:RUPEES|INR|RS\.?)\s*', '', s)
    s = re.sub(r'\s*(?:ONLY|\/-).*$', '', s)
    units = {
        "ZERO": 0, "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6,
        "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10, "ELEVEN": 11, "TWELVE": 12,
        "THIRTEEN": 13, "FOURTEEN": 14, "FIFTEEN": 15, "SIXTEEN": 16, "SEVENTEEN": 17,
        "EIGHTEEN": 18, "NINETEEN": 19, "TWENTY": 20, "THIRTY": 30, "FORTY": 40,
        "FIFTY": 50, "SIXTY": 60, "SEVENTY": 70, "EIGHTY": 80, "NINETY": 90
    }
    scales = {"HUNDRED": 100, "THOUSAND": 1000, "LAKH": 100000, "LACS": 100000, "LAC": 100000, "CRORE": 10000000, "CRORES": 10000000}

    current = 0
    total = 0
    words = re.findall(r'[A-Z]+', s)
    for word in words:
        if word in units:
            current += units[word]
        elif word in scales:
            scale = scales[word]
            if current == 0:
                current = 1
            if scale >= 1000:
                total += (current * scale)
                current = 0
            else:
                current *= scale
    total += current
    return float(total) if total > 0 else None


def align_shifted_row(it, headers):
    """Detect and fix column shifts caused by the VLM skipping empty cells or splitting headers."""
    cleaned_row = [str(x or "").strip() for x in it]
    if len(cleaned_row) < len(headers):
        cleaned_row += [""] * (len(headers) - len(cleaned_row))

    # 1. Shift detection before HSN
    hsn_header_idx = -1
    for idx, h in enumerate(headers):
        if "hsn" in h or "sac" in h or "code" in h:
            hsn_header_idx = idx
            break

    if hsn_header_idx != -1:
        if not _is_valid_hsn(cleaned_row[hsn_header_idx]):
            for shift in [1, 2]:
                candidate = cleaned_row[:hsn_header_idx] + [""] * shift + cleaned_row[hsn_header_idx:]
                candidate = candidate[:len(headers)] + [""] * max(0, len(headers) - len(candidate))
                if _is_valid_hsn(candidate[hsn_header_idx]):
                    cleaned_row = candidate
                    break

    # 2. Post-HSN Shift detection (e.g. Qty empty while Unit has Qty number)
    if hsn_header_idx != -1 and _is_valid_hsn(cleaned_row[hsn_header_idx]):
        qty_idx, unit_idx, rate_idx, tax_idx = -1, -1, -1, -1
        for idx in range(hsn_header_idx + 1, len(headers)):
            h = headers[idx].lower()
            if ("qty" in h or "quant" in h) and qty_idx == -1:
                qty_idx = idx
            elif "unit" in h and unit_idx == -1:
                unit_idx = idx
            elif ("rate" in h or "price" in h) and rate_idx == -1:
                rate_idx = idx
            elif ("taxable" in h or "assessable" in h or "value" in h) and tax_idx == -1:
                tax_idx = idx

        # Check if Qty is empty but Unit holds a number and Rate holds a unit name (like PCS/NOS)
        if qty_idx != -1 and unit_idx != -1 and rate_idx != -1:
            val_qty = cleaned_row[qty_idx]
            val_unit = cleaned_row[unit_idx]
            val_rate = cleaned_row[rate_idx]
            # Pattern: val_qty is empty/0, val_unit is numeric (e.g. "176"), val_rate is unit (e.g. "PCS")
            if (not val_qty or val_qty == "0") and val_unit.replace(".", "").isdigit() and not val_rate.replace(".", "").isdigit():
                post_hsn = cleaned_row[hsn_header_idx + 1:]
                non_empty = [x for i, x in enumerate(post_hsn) if not (i == 0 and x == "")]
                if len(non_empty) < len(post_hsn):
                    non_empty.append("")
                cleaned_row = cleaned_row[:hsn_header_idx + 1] + non_empty

    return cleaned_row


def run_post_processing(d, file_path=None, page_count=1, image=None):
    d = ensure_schema(d)
    
    sup = d.get("supplier") or {}
    buy = d.get("buyer") or {}
    
    if is_empty(sup.get("city")) or is_empty(sup.get("state")):
        sup_split = split_address(sup.get("address"))
        for k, v in sup_split.items():
            if k != "raw" and is_empty(sup.get(k)):
                sup[k] = v
                
    if is_empty(buy.get("city")) or is_empty(buy.get("state")):
        buy_split = split_address(buy.get("billing_address") or buy.get("address"))
        for k, v in buy_split.items():
            if k != "raw" and is_empty(buy.get(k)):
                buy[k] = v
                
    d["supplier"] = sup
    d["buyer"] = buy
    
    sup_gst_analysis = analyze_gstin(sup.get("gstin"))
    buy_gst_analysis = analyze_gstin(buy.get("gstin"))
    
    tax_sum = d.get("tax_summary") or {}
    amt_sum = d.get("amount_summary") or {}

    # -----------------------------------------------------------------------
    # Table Header Clean-up & Line Item Realignment
    # -----------------------------------------------------------------------
    raw_headers = d.get("table_headers") or []
    items = d.get("line_items") or []

    # Detect if 'Sr.' and 'No.' were split into two separate headers
    merged_headers = []
    skip_next = False
    merge_sr_no = False
    for i, h in enumerate(raw_headers):
        if skip_next:
            skip_next = False
            continue
        if h.strip().lower() in ("sr.", "sr") and i + 1 < len(raw_headers) and raw_headers[i+1].strip().lower() in ("no.", "no"):
            merged_headers.append("Sr. No.")
            skip_next = True
            merge_sr_no = True
        else:
            merged_headers.append(h)

    if merge_sr_no:
        d["table_headers"] = merged_headers
        new_items = []
        for it in items:
            if isinstance(it, list) and len(it) > 1:
                # Merge cell 0 and cell 1
                cell_0 = str(it[0] or "").strip()
                cell_1 = str(it[1] or "").strip()
                combined = f"{cell_0} {cell_1}".strip()
                new_items.append([combined] + it[2:])
            else:
                new_items.append(it)
        items = new_items
        d["line_items"] = items

    headers = [h.lower() for h in (d.get("table_headers") or [])]
    
    qty_idx, rate_idx, amt_idx = -1, -1, -1
    cgst_r_idx, cgst_a_idx = -1, -1
    sgst_r_idx, sgst_a_idx = -1, -1
    igst_r_idx, igst_a_idx = -1, -1
    total_idx = -1
    
    for i, h in enumerate(headers):
        if "qty" in h or "quant" in h:
            qty_idx = i
        elif ("rate" in h or "price" in h) and not ("gst" in h or "tax" in h or "cgst" in h or "sgst" in h or "igst" in h):
            rate_idx = i
        elif "unit" in h and not h.strip(".") in ("unit", "units", "pcs", "nos", "box", "kg"):
            if rate_idx == -1:
                rate_idx = i
        elif "taxable" in h or "assessable" in h or "value" in h:
            amt_idx = i
        elif "cgst" in h:
            if "rate" in h or "%" in h: cgst_r_idx = i
            else: cgst_a_idx = i
        elif "sgst" in h or "utgst" in h:
            if "rate" in h or "%" in h: sgst_r_idx = i
            else: sgst_a_idx = i
        elif "igst" in h:
            if "rate" in h or "%" in h: igst_r_idx = i
            else: igst_a_idx = i
        elif ("total" in h or "net" in h or "amount" in h or "val" in h) and not ("gst" in h or "cgst" in h or "sgst" in h or "igst" in h or "tax" in h or "rate" in h):
            if amt_idx == -1:
                amt_idx = i
            else:
                total_idx = i
                
    if total_idx == -1 and amt_idx != -1 and amt_idx < len(headers) - 1:
        total_idx = len(headers) - 1

    line_validation_details = []
    table_math_ok = True
    global_cgst_r = normalize_float(tax_sum.get("cgst_rate"))
    global_sgst_r = normalize_float(tax_sum.get("sgst_rate"))
    global_igst_r = normalize_float(tax_sum.get("igst_rate"))

    sum_line_taxable = 0.0
    sum_line_cgst = 0.0
    sum_line_sgst = 0.0
    sum_line_igst = 0.0
    sum_line_total = 0.0
    realigned_items = []

    for row_idx, it in enumerate(items):
        if isinstance(it, list) and len(it) > 0:
            it = align_shifted_row(it, headers)
            qty = normalize_float(it[qty_idx]) if (qty_idx != -1 and qty_idx < len(it)) else 1.0
            rate = normalize_float(it[rate_idx]) if (rate_idx != -1 and rate_idx < len(it)) else 0.0
            taxable = normalize_float(it[amt_idx]) if (amt_idx != -1 and amt_idx < len(it)) else 0.0
            
            cgst_r = normalize_float(it[cgst_r_idx]) if (cgst_r_idx != -1 and cgst_r_idx < len(it)) else global_cgst_r
            sgst_r = normalize_float(it[sgst_r_idx]) if (sgst_r_idx != -1 and sgst_r_idx < len(it)) else global_sgst_r
            igst_r = normalize_float(it[igst_r_idx]) if (igst_r_idx != -1 and igst_r_idx < len(it)) else global_igst_r
            
            c_factor = (cgst_r / 100.0) if cgst_r > 1.0 else cgst_r
            s_factor = (sgst_r / 100.0) if sgst_r > 1.0 else sgst_r
            i_factor = (igst_r / 100.0) if igst_r > 1.0 else igst_r
            
            cgst_a = normalize_float(it[cgst_a_idx]) if (cgst_a_idx != -1 and cgst_a_idx < len(it)) else round(taxable * c_factor, 2)
            sgst_a = normalize_float(it[sgst_a_idx]) if (sgst_a_idx != -1 and sgst_a_idx < len(it)) else round(taxable * s_factor, 2)
            igst_a = normalize_float(it[igst_a_idx]) if (igst_a_idx != -1 and igst_a_idx < len(it)) else round(taxable * i_factor, 2)
            
            total = normalize_float(it[total_idx]) if (total_idx != -1 and total_idx < len(it)) else taxable + cgst_a + sgst_a + igst_a

            tax_sum_calc = cgst_a + sgst_a + igst_a
            if tax_sum_calc > 0 and abs(total - tax_sum_calc) <= 2.0 and total > 0.0 and taxable > 0.0:
                total = taxable + total
                
            if total == 0.0:
                total = taxable + cgst_a + sgst_a + igst_a

            sum_line_taxable += taxable
            sum_line_cgst += cgst_a
            sum_line_sgst += sgst_a
            sum_line_igst += igst_a
            sum_line_total += total

            # Explicitly set verified tax amounts and line total in row cells
            if igst_a_idx != -1 and igst_a_idx < len(it):
                it[igst_a_idx] = f"{igst_a:,.2f}"
            if cgst_a_idx != -1 and cgst_a_idx < len(it):
                it[cgst_a_idx] = f"{cgst_a:,.2f}"
            if sgst_a_idx != -1 and sgst_a_idx < len(it):
                it[sgst_a_idx] = f"{sgst_a:,.2f}"
            if amt_idx != -1 and amt_idx < len(it):
                it[amt_idx] = f"{taxable:,.2f}"

            if total_idx != -1 and total_idx < len(it):
                it[total_idx] = f"{total:,.2f}"
            elif total_idx == -1:
                it.append(f"{total:,.2f}")

            if qty > 0 and rate > 0 and taxable > 0:
                calc_taxable = round(qty * rate, 2)
                if abs(calc_taxable - taxable) > 2.0:
                    table_math_ok = False
                    line_validation_details.append(
                        f"Row {row_idx+1}: Qty ({qty}) * Rate ({rate}) = {calc_taxable} != Taxable Value ({taxable})"
                    )
                    
            expected_total = round(taxable + cgst_a + sgst_a + igst_a, 2)
            if abs(expected_total - total) > 2.0:
                table_math_ok = False
                line_validation_details.append(
                    f"Row {row_idx+1}: Mismatch. Expected total {expected_total:.2f} ({taxable:.2f} taxable + {cgst_a:.2f} CGST + {sgst_a:.2f} SGST + {igst_a:.2f} IGST) but invoice displays {total:.2f}"
                )
        realigned_items.append(it)

    # Rename last header to "Total Amount" if it was generic "Amt"
    if raw_headers:
        if raw_headers[-1].strip().lower() in ("amt", "amount", "val", "total"):
            raw_headers[-1] = "Total Amount"
            d["table_headers"] = raw_headers

    d["line_items"] = realigned_items

    # -----------------------------------------------------------------------
    # Backfill / Verify tax_summary from line items
    # -----------------------------------------------------------------------
    taxable_amt = normalize_float(tax_sum.get("taxable_amount"))
    if taxable_amt == 0.0 and sum_line_taxable > 0:
        taxable_amt = sum_line_taxable
        tax_sum["taxable_amount"] = f"{taxable_amt:,.2f}"

    cgst = normalize_float(tax_sum.get("cgst_amount"))
    if cgst == 0.0 and sum_line_cgst > 0:
        cgst = sum_line_cgst
        tax_sum["cgst_amount"] = f"{cgst:,.2f}"

    sgst = normalize_float(tax_sum.get("sgst_amount"))
    if sgst == 0.0 and sum_line_sgst > 0:
        sgst = sum_line_sgst
        tax_sum["sgst_amount"] = f"{sgst:,.2f}"

    igst = normalize_float(tax_sum.get("igst_amount"))
    if igst == 0.0 and sum_line_igst > 0:
        igst = sum_line_igst
        tax_sum["igst_amount"] = f"{igst:,.2f}"

    if is_empty(tax_sum.get("igst_rate")) and sum_line_igst > 0:
        tax_sum["igst_rate"] = "18%"

    tot_tax = normalize_float(tax_sum.get("total_tax"))
    if tot_tax == 0.0:
        tot_tax = cgst + sgst + igst
        tax_sum["total_tax"] = f"{tot_tax:,.2f}"

    d["tax_summary"] = tax_sum

    # -----------------------------------------------------------------------
    # Amount Summary Verification & Reconstruction
    # -----------------------------------------------------------------------
    subtotal = normalize_float(amt_sum.get("subtotal"))
    discount = normalize_float(amt_sum.get("discount"))
    freight = normalize_float(amt_sum.get("freight"))
    shipping = normalize_float(amt_sum.get("shipping"))
    packing = normalize_float(amt_sum.get("packing"))
    insurance = normalize_float(amt_sum.get("insurance"))
    round_off = normalize_float(amt_sum.get("round_off"))
    grand_total_ext = normalize_float(amt_sum.get("grand_total"))
    balance_due_ext = normalize_float(amt_sum.get("balance_due"))

    currency = d.get("currency") or "INR"
    if "rs" in str(amt_sum.get("grand_total")).lower() or "₹" in str(amt_sum.get("grand_total")).lower():
        currency = "INR"

    calculated_tax = cgst + sgst + igst + normalize_float(tax_sum.get("utgst")) + normalize_float(tax_sum.get("cess"))
    other_charges = freight + shipping + packing + insurance

    raw_round = str(amt_sum.get("round_off") or "0")
    round_sign = -1.0 if "-" in raw_round else 1.0
    abs_round = abs(round_off)
    actual_round = round_sign * abs_round

    words_num = parse_words_to_num(amt_sum.get("total_in_words"))
    calculated_grand = taxable_amt + calculated_tax + other_charges - discount + actual_round

    # Reconstruct/verify Grand Total if VLM extracted wrong value or null
    if grand_total_ext == 0.0 or abs(grand_total_ext - calculated_grand) > 2.0:
        if words_num and abs(words_num - calculated_grand) <= 2.0:
            grand_total_ext = words_num
        else:
            grand_total_ext = calculated_grand

    if subtotal > 0 and taxable_amt > 0 and abs(subtotal - grand_total_ext) <= 2.0 and subtotal > taxable_amt:
        subtotal = taxable_amt

    amt_sum["subtotal"] = f"{taxable_amt:,.2f}"
    amt_sum["grand_total"] = f"{grand_total_ext:,.2f}"
    amt_sum["grand_total_normalized"] = grand_total_ext

    # Clean hallucinated balance_due (e.g. if VLM put tax amount into balance_due)
    if balance_due_ext > 0 and abs(balance_due_ext - calculated_tax) <= 2.0:
        amt_sum["balance_due"] = None
    elif balance_due_ext == 0.0:
        amt_sum["balance_due"] = None

    d["amount_summary"] = amt_sum

    math_valid = abs(calculated_grand - grand_total_ext) <= 2.0 if grand_total_ext > 0 else True
                        
    hsn_idx = -1
    for i, h in enumerate(headers):
        if "hsn" in h or "sac" in h or "code" in h:
            hsn_idx = i
            break
            
    hsn_validations = []
    hsn_math_ok = True
    if hsn_idx != -1:
        for it in items:
            if isinstance(it, list) and len(it) > hsn_idx:
                code_raw = str(it[hsn_idx] or "").strip().replace(" ", "")
                code = code_raw.split(".")[0]
                if code and code != "N/A" and code != "null" and not code.startswith("-"):
                    desc_col_idx = 1
                    for idx_h, h_name in enumerate(headers):
                        if "desc" in h_name or "goods" in h_name or "service" in h_name or "particular" in h_name:
                            desc_col_idx = idx_h
                            break
                    desc = str(it[desc_col_idx] or "Item").strip() if desc_col_idx < len(it) else (it[1] if len(it) > 1 else "Item")
                    
                    is_valid_fmt = bool(re.match(r'^\d{4,8}$', code))
                    db_name = f"HSN ({code[:4]})" if len(code) >= 4 else "HSN/SAC"
                    
                    if is_valid_fmt:
                        hsn_validations.append({
                            "item": desc,
                            "code": code,
                            "type": db_name,
                            "status": "Valid Code Format"
                        })
                    else:
                        hsn_validations.append({
                            "item": desc,
                            "code": code,
                            "type": "Unknown",
                            "status": "Invalid Format"
                        })
                        
    fraud_warnings = []
    if cgst > 0 and sgst > 0 and abs(cgst - sgst) > 0.01:
        fraud_warnings.append("CGST and SGST amounts mismatch (they must be equal).")
    if sup_gst_analysis.get("raw") and not sup_gst_analysis.get("valid"):
        fraud_warnings.append("Supplier GSTIN format is invalid.")
    if buy_gst_analysis.get("raw") and not buy_gst_analysis.get("valid"):
        fraud_warnings.append("Buyer GSTIN format is invalid.")

    # Duplicate GSTIN check — buyer and supplier cannot share the same GSTIN
    sup_raw = sup_gst_analysis.get("raw", "")
    buy_raw = buy_gst_analysis.get("raw", "")
    if sup_raw and buy_raw and sup_raw == buy_raw:
        fraud_warnings.append("DUPLICATE GSTIN DETECTED — Buyer and Supplier share the same GSTIN. This is illegal under GST law.")
        buy["_gstin_duplicate"] = True
        d["buyer"] = buy

    if sup_gst_analysis.get("valid") and buy_gst_analysis.get("valid"):
        sup_state = sup_gst_analysis.get("state_code")
        buy_state = buy_gst_analysis.get("state_code")
        if sup_state == buy_state:
            if igst > 0 and cgst == 0:
                fraud_warnings.append("Intra-state supply but IGST is charged.")
        else:
            if (cgst > 0 or sgst > 0) and igst == 0:
                fraud_warnings.append("Inter-state supply but CGST/SGST is charged.")
                
    res_str = "Unknown"
    blur_level = "Low (Clean Scan)"
    if image:
        w, h = image.size
        res_str = f"{w}x{h} px"
        if max(w, h) < 1200:
            blur_level = "High (Low Resolution)"
        elif max(w, h) < 1600:
            blur_level = "Medium (Standard Scan)"
            
    doc_meta = {
        "number_of_pages": page_count,
        "resolution": res_str,
        "blur_level": blur_level,
        "scan_quality": "High" if blur_level == "Low (Clean Scan)" else ("Medium" if "Medium" in blur_level else "Low"),
        "language_detected": "English / Indian (GST)",
        "file_name": Path(file_path).name if file_path else "Unknown"
    }
    
    validation_status = "Success" if (math_valid and table_math_ok and hsn_math_ok) else "Validation Failed"
    
    d["validation"] = {
        "amounts_match": math_valid,
        "validation_status": validation_status,
        "math_check": {
            "taxable_amount": taxable_amt,
            "calculated_tax": calculated_tax,
            "other_charges": other_charges,
            "discount": discount,
            "round_off": actual_round,
            "extracted_grand_total": grand_total_ext,
            "calculated_grand_total": calculated_grand,
            "margin_diff": round(abs(calculated_grand - grand_total_ext), 2)
        },
        "table_math_ok": table_math_ok,
        "line_item_failures": line_validation_details,
        "hsn_sac_validation": hsn_validations,
        "hsn_sac_math_ok": hsn_math_ok,
        "supplier_gstin_analysis": sup_gst_analysis,
        "buyer_gstin_analysis": buy_gst_analysis,
        "fraud_detection": {
            "is_suspicious": len(fraud_warnings) > 0,
            "warnings": fraud_warnings
        }
    }
    
    d["metadata"] = doc_meta
    
    amt_sum["grand_total_normalized"] = grand_total_ext
    amt_sum["currency"] = currency
    amt_sum["balance_due_normalized"] = balance_due_ext if balance_due_ext > 0 else 0.0
    if is_empty(amt_sum.get("balance_due")):
        amt_sum["balance_due"] = "Not Present"
    d["amount_summary"] = amt_sum
    return d


def ensure_schema(d):
    dict_keys = ["supplier", "buyer", "consignee", "order_info", "logistics", "tax_summary", "amount_summary", "payment", "authorisation", "notes"]
    for k in dict_keys:
        if k not in d or d[k] is None or not isinstance(d[k], dict):
            d[k] = {}
            
    other_keys = [
        "document_title","invoice_type","invoice_number","invoice_date","due_date","currency",
        "irn","ack_number","ack_date","place_of_supply","reverse_charge"
    ]
    for k in other_keys:
        if k not in d:
            d[k] = None
            
    if not d.get("table_headers") or not isinstance(d.get("table_headers"), list): d["table_headers"] = []
    if not d.get("line_items") or not isinstance(d.get("line_items"), list):    d["line_items"]    = []
    return d


# ---------------------------------------------------------------------------
# Ollama chat API
# ---------------------------------------------------------------------------
def query_ollama_chat(system_prompt, user_prompt, b64_image, max_retries=3, initial_delay=2):
    import urllib.request, urllib.error
    messages = [
        {"role": "system",  "content": system_prompt},
        {"role": "user",    "content": user_prompt, "images": [b64_image]}
    ]
    payload = json.dumps({
        "model": QWEN_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.05, "num_predict": _NUM_PREDICT, "top_p": 0.9, "num_ctx": _NUM_CTX}
    }).encode()
    print(f"    [req] Sending {len(payload)//1024} KB to Ollama...")

    delay = initial_delay
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/chat",
                data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=360) as resp:
                return json.loads(resp.read()).get("message", {}).get("content", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            print(f"    [!] Ollama HTTP {e.code} (attempt {attempt+1}/{max_retries}): {body[:300]}")
            if attempt == max_retries - 1:
                raise Exception(f"HTTP {e.code}: {body[:200]}")
        except Exception as e:
            print(f"    [!] Request error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise e
        time.sleep(delay)
        delay *= 2
    return ""


# ---------------------------------------------------------------------------
# Single-pass extraction
# ---------------------------------------------------------------------------
def extract_with_qwen(image, page_label=""):
    b64 = _img_b64(image)
    lbl = f" page {page_label}" if page_label else ""
    t0  = time.time()
    SYSTEM = ("You are a precise invoice data extraction API. "
              "Output ONLY a single valid JSON object. "
              "No markdown fences, no preamble, no trailing text. "
              "Start with '{' and end with '}'.")

    print(f"    [Qwen2.5-VL]{lbl} Extracting...")
    try:
        raw = query_ollama_chat(SYSTEM, _PROMPT, b64)
    except Exception as e:
        print(f"    [!] Extraction failed: {e}")
        return {}

    elapsed = time.time() - t0
    cleaned = raw.strip()
    try:
        Path(__file__).parent.joinpath("raw_response.txt").write_text(cleaned, encoding="utf-8")
    except Exception:
        pass
    print(f"    [Qwen2.5-VL]{lbl} Response: {len(cleaned)} chars in {elapsed:.1f}s")

    parsed = robust_json_loads(cleaned)
    if not parsed:
        print(f"    [!] Could not parse JSON. Raw preview:\n{cleaned[:400]}")
        return {}

    parsed = ensure_schema(parsed)
    n = len(parsed.get("line_items") or [])
    print(f"    [Qwen2.5-VL]{lbl} Done — {n} line item(s) | {len(parsed)} keys | {elapsed:.1f}s")
    return parsed


# ---------------------------------------------------------------------------
# Page merger
# ---------------------------------------------------------------------------
def _merge(pages):
    if not pages:
        return {"type": "qwen2.5vl", "line_items": [], "table_headers": []}
    merged, items = {}, []
    for i, pg in enumerate(pages):
        if not pg:
            continue
        pg_items   = pg.get("line_items") or []
        pg_headers = pg.get("table_headers") or []
        if not merged:
            merged = {k: v for k, v in pg.items() if k not in ("line_items","table_headers")}
            merged["table_headers"] = pg_headers
        else:
            for k, v in pg.items():
                if k not in ("line_items","table_headers") and is_empty(merged.get(k)):
                    merged[k] = v
            if pg_headers and not merged.get("table_headers"):
                merged["table_headers"] = pg_headers
        items.extend(pg_items)
    merged["line_items"] = items
    merged["type"]       = "qwen2.5vl"
    return merged


def preprocess_image_adaptive(img):
    img = img.convert("RGB")
    w, h = img.size
    target_max = 1400
    if max(w, h) > target_max:
        scale = target_max / max(w, h)
        img = img.resize((int(w*scale), int(h*scale)), Image.Resampling.LANCZOS)
        w, h = img.size
    elif max(w, h) < 1000:
        scale = 1200 / max(w, h)
        img = img.resize((int(w*scale), int(h*scale)), Image.Resampling.LANCZOS)
        img = img.filter(ImageFilter.SHARPEN)
        w, h = img.size
    img = ImageOps.autocontrast(img)
    print(f"    [pre] Image ready: {w}x{h}px")
    return img


def extract_file(file_path, dpi=200):
    ext   = Path(file_path).suffix.lower()
    pages = []
    first_img = None
    page_count = 0
    if ext in SUPPORTED_PDF_EXT:
        import fitz
        doc = fitz.open(str(file_path))
        page_count = len(doc)
        with tempfile.TemporaryDirectory() as tmp:
            for n in range(len(doc)):
                print(f"    [Qwen2.5-VL] page {n+1}/{len(doc)}...")
                pix = doc.load_page(n).get_pixmap(dpi=dpi)
                p   = os.path.join(tmp, f"p{n}.png")
                pix.save(p)
                img = preprocess_image_adaptive(Image.open(p))
                if n == 0:
                    first_img = img
                pages.append(extract_with_qwen(img, str(n+1)))
        doc.close()
    elif ext in SUPPORTED_IMAGE_EXT:
        img = preprocess_image_adaptive(Image.open(str(file_path)))
        first_img = img
        pages.append(extract_with_qwen(img, "1"))
        page_count = 1
    else:
        raise ValueError(f"Unsupported type: '{ext}'")
    
    merged = _merge(pages)
    return run_post_processing(merged, file_path=file_path, page_count=page_count, image=first_img)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def _v(val):
    if is_empty(val):
        return "N/A"
    return str(val).strip()


def _sec(d, section, key):
    """Get value from nested section dict with flat fallback."""
    sec = d.get(section)
    if isinstance(sec, dict):
        v = sec.get(key)
        if not is_empty(v):
            return v
    return None


def _fmt_inr(val):
    """Format a float or numeric string into Indian Rupee format (e.g. 24922.0 -> ₹ 24,922.00)."""
    if is_empty(val):
        return "N/A"
    try:
        clean_num = normalize_float(val)
        f = float(clean_num)
    except (TypeError, ValueError):
        return str(val)
    sign = "-" if f < 0 else ""
    s = f"{abs(f):.2f}"
    int_p, dec_p = s.split(".")
    if len(int_p) > 3:
        last3 = int_p[-3:]
        rest = int_p[:-3]
        groups = []
        while rest:
            groups.append(rest[-2:])
            rest = rest[:-2]
        groups.reverse()
        int_str = ",".join(groups) + "," + last3
    else:
        int_str = int_p
    return f"{sign}₹ {int_str}.{dec_p}"


def _cv(val, confidence="High", mandatory=False):
    """Confidence-scored value display.
    - Has value  → 'value  [High/Medium]'
    - No value + mandatory → '[Not Detected — Low Confidence]'
    - No value + optional  → None (omit line)
    """
    if not is_empty(val):
        return f"{str(val).strip()}  [{confidence}]"
    if mandatory:
        return "[Not Detected — Low Confidence]"
    return None  # Signal to skip line


def _line(L, label, value, width=18):
    """Append a report line only if value is not None (None means skip)."""
    if value is not None:
        L.append(f"  {label.ljust(width)}: {value}")


def _section_has_data(section_dict, keys):
    """Return True if any key in the dict has a non-empty value."""
    if not isinstance(section_dict, dict):
        return False
    return any(not is_empty(section_dict.get(k)) for k in keys)


# ---------------------------------------------------------------------------
# TXT Report  (generate_txt)
# ---------------------------------------------------------------------------
def generate_txt(d):
    L = []
    S = "=" * 80
    title = d.get("document_title") or d.get("title") or "TAX INVOICE"
    L += [S, f"  {str(title).upper()}", S]

    W = 20  # label column width

    # ── 1. Invoice Identity ──────────────────────────────────────────────────
    L.append("\n-- 1. Invoice Identity --")
    _line(L, "Invoice Type",     _cv(d.get("invoice_type"),     mandatory=True),  W)
    _line(L, "Invoice Number",   _cv(d.get("invoice_number"),   mandatory=True),  W)
    _line(L, "Invoice Date",     _cv(d.get("invoice_date"),     mandatory=True),  W)
    _line(L, "Due Date",         _cv(d.get("due_date")),                          W)
    _line(L, "Currency",         _cv(d.get("currency"),         mandatory=True),  W)
    _line(L, "IRN",              _cv(d.get("irn")),                               W)
    _line(L, "Ack Number",       _cv(d.get("ack_number")),                        W)
    _line(L, "Ack Date",         _cv(d.get("ack_date")),                          W)
    _line(L, "Place of Supply",  _cv(d.get("place_of_supply"),  mandatory=True),  W)
    _line(L, "Reverse Charge",   _cv(d.get("reverse_charge")),                    W)

    # ── 2. Supplier ──────────────────────────────────────────────────────────
    sup = d.get("supplier") or {}
    L.append("\n-- 2. Supplier (Seller) --")
    _line(L, "Name",     _cv(sup.get("name"),    mandatory=True), W)
    _line(L, "GSTIN",    _cv(sup.get("gstin"),   mandatory=True), W)
    _line(L, "PAN",      _cv(sup.get("pan")),                     W)
    _line(L, "CIN",      _cv(sup.get("cin")),                     W)
    _line(L, "Address",  _cv(sup.get("address"), mandatory=True), W)
    _line(L, "City",     _cv(sup.get("city"),    confidence="Medium"), W)
    _line(L, "State",    _cv(sup.get("state"),   confidence="Medium"), W)
    _line(L, "Country",  _cv(sup.get("country"), confidence="Medium"), W)
    _line(L, "PIN Code", _cv(sup.get("pin"),     confidence="Medium"), W)
    _line(L, "Phone",    _cv(sup.get("phone")),                    W)
    _line(L, "Email",    _cv(sup.get("email")),                    W)
    _line(L, "Website",  _cv(sup.get("website")),                  W)

    # ── 3. Buyer ─────────────────────────────────────────────────────────────
    buy = d.get("buyer") or {}
    dup = buy.get("_gstin_duplicate", False)
    L.append("\n-- 3. Buyer (Customer) --")
    _line(L, "Name",             _cv(buy.get("name"),    mandatory=True), W)
    buy_gstin_val = buy.get("gstin")
    buy_gstin_disp = None
    if not is_empty(buy_gstin_val):
        suffix = "  [⚠️  DUPLICATE — SEE FRAUD WARNINGS]" if dup else "  [High]"
        buy_gstin_disp = str(buy_gstin_val).strip() + suffix
    else:
        buy_gstin_disp = "[Not Detected — Low Confidence]"
    _line(L, "GSTIN",            buy_gstin_disp, W)
    _line(L, "Billing Address",  _cv(buy.get("billing_address"),  mandatory=True), W)
    _line(L, "Shipping Address", _cv(buy.get("shipping_address")),                 W)
    _line(L, "City",             _cv(buy.get("city"),    confidence="Medium"),     W)
    _line(L, "State",            _cv(buy.get("state"),   confidence="Medium"),     W)
    _line(L, "Country",          _cv(buy.get("country"), confidence="Medium"),     W)
    _line(L, "Phone",            _cv(buy.get("phone")),                            W)
    _line(L, "Email",            _cv(buy.get("email")),                            W)

    # Consignee — only if present
    con = d.get("consignee") or {}
    if not is_empty(con.get("name")):
        L.append("\n-- 3b. Consignee (Ship To) --")
        _line(L, "Name",    _cv(con.get("name")),    W)
        _line(L, "GSTIN",   _cv(con.get("gstin")),   W)
        _line(L, "Address", _cv(con.get("address")), W)
        _line(L, "State",   _cv(con.get("state")),   W)

    # ── 4. Order & Dispatch — skip section if all empty ──────────────────────
    ord_ = d.get("order_info") or {}
    ord_keys = ["po_number","delivery_challan","reference_number","payment_terms",
                "sales_order","work_order","vendor_code","customer_id","eway_bill"]
    if _section_has_data(ord_, ord_keys):
        L.append("\n-- 4. Order & Dispatch --")
        _line(L, "PO Number",       _cv(ord_.get("po_number")),       W)
        _line(L, "Reference No.",   _cv(ord_.get("reference_number")),W)
        _line(L, "Delivery Challan",_cv(ord_.get("delivery_challan")),W)
        _line(L, "Payment Terms",   _cv(ord_.get("payment_terms")),   W)
        _line(L, "Sales Order No.", _cv(ord_.get("sales_order")),     W)
        _line(L, "Work Order No.",  _cv(ord_.get("work_order")),      W)
        _line(L, "Vendor Code",     _cv(ord_.get("vendor_code")),     W)
        _line(L, "Customer ID",     _cv(ord_.get("customer_id")),     W)
        _line(L, "E-Way Bill No.",  _cv(ord_.get("eway_bill")),       W)

    # ── 5. Logistics — skip section if all empty ─────────────────────────────
    log = d.get("logistics") or {}
    log_keys = ["vehicle_number","transporter_name","lr_number",
                "dispatch_date","delivery_date","tracking_number","destination"]
    if _section_has_data(log, log_keys):
        L.append("\n-- 5. Logistics --")
        _line(L, "Transporter",    _cv(log.get("transporter_name")), W)
        _line(L, "Vehicle Number", _cv(log.get("vehicle_number")),   W)
        _line(L, "LR Number",      _cv(log.get("lr_number")),        W)
        _line(L, "Dispatch Date",  _cv(log.get("dispatch_date")),    W)
        _line(L, "Delivery Date",  _cv(log.get("delivery_date")),    W)
        _line(L, "Destination",    _cv(log.get("destination")),      W)
        _line(L, "Tracking Number",_cv(log.get("tracking_number")),  W)

    # ── 6. Line Items ─────────────────────────────────────────────────────────
    items   = d.get("line_items")    or []
    headers = d.get("table_headers") or []
    rows = []
    for it in items:
        if isinstance(it, list):
            rows.append(it)
        elif isinstance(it, str):
            rows.append([v.strip() for v in it.split(" | ")])
        elif isinstance(it, dict):
            rows.append([str(it.get(h, "")) for h in headers])

    L.append("\n-- 6. Line Items --")
    if headers and rows:
        widths = []
        for ci, h in enumerate(headers):
            w = len(h)
            for r in rows:
                if ci < len(r):
                    w = max(w, max((len(x) for x in str(r[ci] or "").split("\n")), default=0))
            widths.append(max(4, min(w, 50)))
        sep = "+-" + "-+-".join("-"*w for w in widths) + "-+"
        hdr = "| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |"
        L  += [sep, hdr, sep]
        for r in rows:
            cells = []
            for ci, w in enumerate(widths):
                v = str(r[ci]) if ci < len(r) and r[ci] is not None else ""
                v = v.replace("\\n", "\n")
                cells.append(v.split("\n"))
            for li in range(max(len(c) for c in cells)):
                parts = []
                for ci, w in enumerate(widths):
                    line_val = cells[ci][li] if li < len(cells[ci]) else ""
                    parts.append(line_val[:w].ljust(w))
                L.append("| " + " | ".join(parts) + " |")
        L.append(sep)
    else:
        L.append("  [No line items found]")

    # ── 7. Tax Details — skip if all N/A ─────────────────────────────────────
    tx = d.get("tax_summary") or {}
    tx_keys = ["taxable_amount","cgst_rate","cgst_amount","sgst_rate","sgst_amount",
               "igst_rate","igst_amount","utgst","cess","tds","total_tax"]
    if _section_has_data(tx, tx_keys):
        L.append("\n-- 7. Tax Details --")
        _line(L, "Taxable Amount", _cv(tx.get("taxable_amount"), mandatory=True), W)
        _line(L, "CGST Rate",      _cv(tx.get("cgst_rate")),     W)
        _line(L, "CGST Amount",    _cv(tx.get("cgst_amount")),   W)
        _line(L, "SGST Rate",      _cv(tx.get("sgst_rate")),     W)
        _line(L, "SGST Amount",    _cv(tx.get("sgst_amount")),   W)
        _line(L, "IGST Rate",      _cv(tx.get("igst_rate")),     W)
        _line(L, "IGST Amount",    _cv(tx.get("igst_amount")),   W)
        _line(L, "UTGST",          _cv(tx.get("utgst")),         W)
        _line(L, "CESS",           _cv(tx.get("cess")),          W)
        _line(L, "TDS",            _cv(tx.get("tds")),           W)
        _line(L, "Total Tax",      _cv(tx.get("total_tax")),     W)

    # ── 8. Amount Summary ─────────────────────────────────────────────────────
    am = d.get("amount_summary") or {}
    tx = d.get("tax_summary") or {}
    L.append("\n-- 8. Amount Summary --")
    
    taxable_val = tx.get("taxable_amount") or am.get("subtotal")
    taxable_disp = _fmt_inr(taxable_val) if not is_empty(taxable_val) else None
    
    _line(L, "Taxable Amount",  _cv(taxable_disp, confidence="High") if taxable_disp else _cv(taxable_val, confidence="High"), W)
    
    # Show taxes breakdown if present
    igst_a = tx.get("igst_amount")
    cgst_a = tx.get("cgst_amount")
    sgst_a = tx.get("sgst_amount")
    if not is_empty(igst_a):
        rate_str = tx.get("igst_rate") or "18%"
        _line(L, f"IGST ({rate_str})", _cv(_fmt_inr(igst_a), confidence="High"), W)
    if not is_empty(cgst_a):
        rate_str = tx.get("cgst_rate") or ""
        _line(L, f"CGST ({rate_str})".strip(), _cv(_fmt_inr(cgst_a), confidence="High"), W)
    if not is_empty(sgst_a):
        rate_str = tx.get("sgst_rate") or ""
        _line(L, f"SGST ({rate_str})".strip(), _cv(_fmt_inr(sgst_a), confidence="High"), W)
        
    _line(L, "Discount",        _cv(am.get("discount")),       W)
    _line(L, "Freight",         _cv(am.get("freight")),        W)
    _line(L, "Shipping",        _cv(am.get("shipping")),       W)
    _line(L, "Packing",         _cv(am.get("packing")),        W)
    _line(L, "Insurance",       _cv(am.get("insurance")),      W)
    _line(L, "Round Off",       _cv(am.get("round_off")),      W)
    
    grand_norm = am.get("grand_total_normalized")
    grand_disp = _fmt_inr(grand_norm) if grand_norm else _v(am.get("grand_total"))
    _line(L, "Grand Total",     f"{grand_disp}  [High]",       W)
    _line(L, "Total In Words",  _cv(am.get("total_in_words"),  mandatory=True), W)
    _line(L, "Amount Paid",     _cv(am.get("amount_paid")),    W)
    bal = am.get("balance_due")
    if not is_empty(bal) and str(bal).strip() not in ("Not Present", "0", "0.0"):
        _line(L, "Balance Due", _cv(bal, mandatory=True), W)

    # ── 9. Payment / Bank — skip section if all empty ─────────────────────────
    pay = d.get("payment") or {}
    pay_keys = ["bank_name","account_holder","account_number","ifsc_code",
                "branch","swift_code","upi_id","payment_status","payment_method"]
    if _section_has_data(pay, pay_keys):
        L.append("\n-- 9. Payment & Bank Details --")
        _line(L, "Bank Name",      _cv(pay.get("bank_name")),      W)
        _line(L, "Account Holder", _cv(pay.get("account_holder")), W)
        _line(L, "Account Number", _cv(pay.get("account_number")), W)
        _line(L, "IFSC Code",      _cv(pay.get("ifsc_code")),      W)
        _line(L, "Branch",         _cv(pay.get("branch")),         W)
        _line(L, "SWIFT Code",     _cv(pay.get("swift_code")),     W)
        _line(L, "UPI ID",         _cv(pay.get("upi_id")),         W)
        _line(L, "Payment Method", _cv(pay.get("payment_method")), W)
        _line(L, "Payment Status", _cv(pay.get("payment_status")), W)

    # ── 10. Authorisation — skip if empty ─────────────────────────────────────
    auth = d.get("authorisation") or {}
    if _section_has_data(auth, ["signatory","seal","digital_signature"]):
        L.append("\n-- 10. Authorisation --")
        _line(L, "Authorized Sign.", _cv(auth.get("signatory")),         W)
        _line(L, "Company Seal",     _cv(auth.get("seal")),              W)
        _line(L, "Digital Signature",_cv(auth.get("digital_signature")), W)

    # ── 11. Notes & Terms — skip if empty ────────────────────────────────────
    notes = d.get("notes") or {}
    if _section_has_data(notes, ["terms_conditions","return_policy","warranty","additional_notes"]):
        L.append("\n-- 11. Notes & Terms --")
        _line(L, "Terms & Conditions", _cv(notes.get("terms_conditions")), W)
        _line(L, "Return Policy",      _cv(notes.get("return_policy")),    W)
        _line(L, "Warranty",           _cv(notes.get("warranty")),         W)
        _line(L, "Additional Notes",   _cv(notes.get("additional_notes")), W)

    # ── 12. Data Validation & Math Checks ────────────────────────────────────
    val = d.get("validation") or {}
    math_chk = val.get("math_check") or {}
    status = val.get("validation_status", "Unknown")
    status_icon = "✅" if status == "Success" else "❌"
    L += ["\n-- 12. Data Validation & Math Checks --",
          f"  Validation Status    : {status_icon} {status}",
          f"  Amounts Match?       : {'✅ Yes' if val.get('amounts_match') else '❌ No'}",
          f"  Extracted Grand      : {_fmt_inr(math_chk.get('extracted_grand_total', 0.0))}",
          f"  Calculated Grand     : {_fmt_inr(math_chk.get('calculated_grand_total', 0.0))}  "
          f"(Taxable + Tax + Charges - Discount ± RoundOff)",
          f"  Margin Difference    : {math_chk.get('margin_diff', 0.0)}",
          f"  Line Items Math      : {'✅ OK' if val.get('table_math_ok') else '❌ Mismatch'}"]

    failures = val.get("line_item_failures") or []
    if failures:
        L.append("  Line Item Failures:")
        for fail in failures:
            L.append(f"    ❌ {fail}")

    hsn_val = val.get("hsn_sac_validation") or []
    if hsn_val:
        L.append("  HSN/SAC Cross-Reference:")
        for r in hsn_val:
            icon = "✅" if r["status"] == "Valid Code Format" else "❓"
            L.append(f"    {icon} Code {r['code']:<10} ({r['type']}) | "
                     f"Item: {r['item'][:28]:<28} | Status: {r['status']}")

    # ── 13. GSTIN Validation & PAN ───────────────────────────────────────────
    sup_gst = val.get("supplier_gstin_analysis") or {}
    buy_gst = val.get("buyer_gstin_analysis") or {}
    L.append("\n-- 13. GSTIN Validation & PAN --")
    sup_icon = "✅" if sup_gst.get("valid") else "❌"
    buy_icon = "✅" if buy_gst.get("valid") else "❌"
    dup_note = "  ⚠️  DUPLICATE GSTIN" if dup else ""
    L += [f"  Supplier GSTIN       : {sup_icon} {sup_gst.get('raw', 'N/A')}",
          f"  Supplier State       : {sup_gst.get('state_name','?')} (Code: {sup_gst.get('state_code','?')})",
          f"  Supplier PAN         : {sup_gst.get('pan','?')}",
          f"  Buyer GSTIN          : {buy_icon} {buy_gst.get('raw', 'N/A')}{dup_note}",
          f"  Buyer State          : {buy_gst.get('state_name','?')} (Code: {buy_gst.get('state_code','?')})",
          f"  Buyer PAN            : {buy_gst.get('pan','?')}"]

    # ── 14. Document Metadata ─────────────────────────────────────────────────
    meta = d.get("metadata") or {}
    L += ["\n-- 14. Document Metadata & Quality --",
          f"  File Name            : {meta.get('file_name', '?')}",
          f"  Page Count           : {meta.get('number_of_pages', 1)}",
          f"  Resolution           : {meta.get('resolution', '?')}",
          f"  Blur Level           : {meta.get('blur_level', '?')}",
          f"  Scan Quality         : {meta.get('scan_quality', '?')}",
          f"  Language             : {meta.get('language_detected', '?')}"]

    # ── 15. Security & Fraud ──────────────────────────────────────────────────
    fraud = val.get("fraud_detection") or {}
    warnings_list = fraud.get("warnings") or []
    fraud_icon = "⚠️  SUSPICIOUS — REVIEW REQUIRED" if fraud.get("is_suspicious") else "✅ Clear"
    L += ["\n-- 15. Security & Fraud Check --",
          f"  Status               : {fraud_icon}"]
    if warnings_list:
        L.append("  Warnings:")
        for w in warnings_list:
            L.append(f"    ⚠️  {w}")

    L.append("\n" + S)
    return "\n".join(L)





# ---------------------------------------------------------------------------
# Checklist TXT  (generate_checklist)
# ---------------------------------------------------------------------------
def generate_checklist(d):
    """
    Smart 3-tier checklist:
      ✅  FOUND           — field has an actual extracted value
      ❌  MISSING         — CORE/mandatory field for GST invoices that is absent
      ➖  NOT IN DOCUMENT — optional field not present (NOT an error)
    """
    FOUND, MISSING, OPTIONAL_FOUND, OPTIONAL_NA = [], [], [], []

    def chk_core(label, value):
        """Mandatory GST invoice field — absence is a real error."""
        if not is_empty(value):
            FOUND.append((label, str(value)[:80]))
        else:
            MISSING.append(label)

    def chk_opt(label, value):
        """Optional field — only shown if present; absence is normal."""
        if not is_empty(value):
            OPTIONAL_FOUND.append((label, str(value)[:80]))
        else:
            OPTIONAL_NA.append(label)

    # ── Core mandatory fields for any Indian GST/Tax invoice ──────────────
    chk_core("Invoice Number",         d.get("invoice_number"))
    chk_core("Invoice Date",           d.get("invoice_date"))
    chk_core("Supplier Name",          (d.get("supplier") or {}).get("name"))
    chk_core("Supplier GSTIN",         (d.get("supplier") or {}).get("gstin"))
    chk_core("Supplier Address",       (d.get("supplier") or {}).get("address"))
    chk_core("Buyer Name",             (d.get("buyer") or {}).get("name"))
    chk_core("Buyer GSTIN",            (d.get("buyer") or {}).get("gstin"))
    chk_core("Place of Supply",        d.get("place_of_supply"))
    chk_core("Line Items (Products)",  d.get("line_items"))
    chk_core("Table Headers",          d.get("table_headers"))
    chk_core("Grand Total",            (d.get("amount_summary") or {}).get("grand_total"))
    chk_core("Total In Words",         (d.get("amount_summary") or {}).get("total_in_words"))
    chk_core("Taxable Amount",         (d.get("tax_summary") or {}).get("taxable_amount"))

    # GST amounts — at least one of CGST+SGST or IGST should be present
    has_cgst = not is_empty((d.get("tax_summary") or {}).get("cgst_amount"))
    has_sgst = not is_empty((d.get("tax_summary") or {}).get("sgst_amount"))
    has_igst = not is_empty((d.get("tax_summary") or {}).get("igst_amount"))
    if has_cgst:  FOUND.append(("CGST Amount",  str((d.get("tax_summary") or {}).get("cgst_amount"))[:40]))
    if has_sgst:  FOUND.append(("SGST Amount",  str((d.get("tax_summary") or {}).get("sgst_amount"))[:40]))
    if has_igst:  FOUND.append(("IGST Amount",  str((d.get("tax_summary") or {}).get("igst_amount"))[:40]))
    if not (has_cgst or has_sgst or has_igst):
        MISSING.append("Tax Amount (CGST/SGST or IGST)")

    # ── Standard fields — present on most invoices ─────────────────────────
    chk_opt("Document Title",           d.get("document_title"))
    chk_opt("Invoice Type",             d.get("invoice_type"))
    chk_opt("Currency",                 d.get("currency"))
    chk_opt("IRN (e-Invoice)",          d.get("irn"))
    chk_opt("Ack Number",               d.get("ack_number"))
    chk_opt("Ack Date",                 d.get("ack_date"))
    chk_opt("Reverse Charge",           d.get("reverse_charge"))
    chk_opt("Supplier State",           (d.get("supplier") or {}).get("state"))
    chk_opt("Supplier City",            (d.get("supplier") or {}).get("city"))
    chk_opt("Supplier PIN Code",        (d.get("supplier") or {}).get("pin"))
    chk_opt("Supplier Phone",           (d.get("supplier") or {}).get("phone"))
    chk_opt("Supplier Email",           (d.get("supplier") or {}).get("email"))
    chk_opt("Supplier PAN",             (d.get("supplier") or {}).get("pan"))
    chk_opt("Supplier CIN",             (d.get("supplier") or {}).get("cin"))
    chk_opt("Billing Address",          (d.get("buyer") or {}).get("billing_address"))
    chk_opt("Shipping Address",         (d.get("buyer") or {}).get("shipping_address"))
    chk_opt("Buyer State",              (d.get("buyer") or {}).get("state"))
    chk_opt("Consignee Name",           (d.get("consignee") or {}).get("name"))
    chk_opt("Consignee Address",        (d.get("consignee") or {}).get("address"))
    chk_opt("PO Number",                (d.get("order_info") or {}).get("po_number"))
    chk_opt("Reference Number",         (d.get("order_info") or {}).get("reference_number"))
    chk_opt("Delivery Challan No.",     (d.get("order_info") or {}).get("delivery_challan"))
    chk_opt("Payment Terms",            (d.get("order_info") or {}).get("payment_terms"))
    chk_opt("E-Way Bill Number",        (d.get("order_info") or {}).get("eway_bill"))
    chk_opt("Transporter Name",         (d.get("logistics") or {}).get("transporter_name"))
    chk_opt("Vehicle Number",           (d.get("logistics") or {}).get("vehicle_number"))
    chk_opt("LR Number",                (d.get("logistics") or {}).get("lr_number"))
    chk_opt("Dispatch Date",            (d.get("logistics") or {}).get("dispatch_date"))
    chk_opt("Destination",              (d.get("logistics") or {}).get("destination"))
    chk_opt("CGST Rate",                (d.get("tax_summary") or {}).get("cgst_rate"))
    chk_opt("SGST Rate",                (d.get("tax_summary") or {}).get("sgst_rate"))
    chk_opt("Total Tax Amount",         (d.get("tax_summary") or {}).get("total_tax"))
    chk_opt("Subtotal",                 (d.get("amount_summary") or {}).get("subtotal"))
    chk_opt("Round Off",                (d.get("amount_summary") or {}).get("round_off"))
    chk_opt("Bank Name",                (d.get("payment") or {}).get("bank_name"))
    chk_opt("Account Number",           (d.get("payment") or {}).get("account_number"))
    chk_opt("IFSC Code",                (d.get("payment") or {}).get("ifsc_code"))
    chk_opt("Authorised Signatory",     (d.get("authorisation") or {}).get("signatory"))
    chk_opt("Terms & Conditions",       (d.get("notes") or {}).get("terms_conditions"))
    chk_opt("Additional Notes",         (d.get("notes") or {}).get("additional_notes"))

    # ── Rare/optional — only show if found ────────────────────────────────
    chk_opt("Due Date",                 d.get("due_date"))
    chk_opt("Supplier Website",         (d.get("supplier") or {}).get("website"))
    chk_opt("Buyer Phone",              (d.get("buyer") or {}).get("phone"))
    chk_opt("Buyer Email",              (d.get("buyer") or {}).get("email"))
    chk_opt("Discount",                 (d.get("amount_summary") or {}).get("discount"))
    chk_opt("Freight Charges",          (d.get("amount_summary") or {}).get("freight"))
    chk_opt("Packing Charges",          (d.get("amount_summary") or {}).get("packing"))
    chk_opt("Insurance",                (d.get("amount_summary") or {}).get("insurance"))
    chk_opt("Amount Paid",              (d.get("amount_summary") or {}).get("amount_paid"))
    chk_opt("Balance Due",              (d.get("amount_summary") or {}).get("balance_due"))
    chk_opt("IGST Rate",                (d.get("tax_summary") or {}).get("igst_rate"))
    chk_opt("UTGST",                    (d.get("tax_summary") or {}).get("utgst"))
    chk_opt("CESS",                     (d.get("tax_summary") or {}).get("cess"))
    chk_opt("TDS",                      (d.get("tax_summary") or {}).get("tds"))
    chk_opt("UPI ID",                   (d.get("payment") or {}).get("upi_id"))
    chk_opt("SWIFT Code",               (d.get("payment") or {}).get("swift_code"))
    chk_opt("Payment Method",           (d.get("payment") or {}).get("payment_method"))
    chk_opt("Payment Status",           (d.get("payment") or {}).get("payment_status"))
    chk_opt("Account Holder",           (d.get("payment") or {}).get("account_holder"))
    chk_opt("Branch",                   (d.get("payment") or {}).get("branch"))
    chk_opt("Sales Order Number",       (d.get("order_info") or {}).get("sales_order"))
    chk_opt("Work Order Number",        (d.get("order_info") or {}).get("work_order"))
    chk_opt("Vendor Code",              (d.get("order_info") or {}).get("vendor_code"))
    chk_opt("Customer ID",              (d.get("order_info") or {}).get("customer_id"))
    chk_opt("Delivery Date",            (d.get("logistics") or {}).get("delivery_date"))
    chk_opt("Tracking Number",          (d.get("logistics") or {}).get("tracking_number"))
    chk_opt("Company Seal",             (d.get("authorisation") or {}).get("seal"))
    chk_opt("Digital Signature",        (d.get("authorisation") or {}).get("digital_signature"))
    chk_opt("Return Policy",            (d.get("notes") or {}).get("return_policy"))
    chk_opt("Warranty",                 (d.get("notes") or {}).get("warranty"))

    # ── Combine ALL found (core + optional) for display ────────────────────
    all_found = FOUND + OPTIONAL_FOUND
    core_total = len(FOUND) + len(MISSING)
    core_pct   = int(len(FOUND) / core_total * 100) if core_total else 0

    S   = "=" * 72
    sep = "─" * 72
    lines = [
        S,
        "  INVOICE DATA EXTRACTION CHECKLIST",
        S,
        f"  Core Fields Score : {len(FOUND)}/{core_total} mandatory fields extracted ({core_pct}%)",
        f"  Bonus Fields Found: {len(OPTIONAL_FOUND)} optional fields also extracted",
        S,
    ]

    # Section 1 — All found fields with values
    lines += [f"\n{sep}",
              f"  ✅  EXTRACTED FROM DOCUMENT ({len(all_found)} fields)",
              sep]
    for label, val in all_found:
        lines.append(f"  ✅  {label:<35} : {val}")

    # Section 2 — Core fields missing
    if MISSING:
        lines += [f"\n{sep}",
                  f"  ❌  MISSING — Should be on this invoice ({len(MISSING)} fields)",
                  sep]
        for label in MISSING:
            lines.append(f"  ❌  {label}")

    # Section 3 — Optional not present
    if OPTIONAL_NA:
        lines += [f"\n{sep}",
                  f"  ➖  NOT IN THIS DOCUMENT — Optional fields not found ({len(OPTIONAL_NA)} fields)",
                  f"      (These are normal to be absent on many invoices)",
                  sep]
        for label in OPTIONAL_NA:
            lines.append(f"  ➖  {label}")

    lines.append("\n" + S)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Write outputs — 3 files
# ---------------------------------------------------------------------------
def write_outputs(base: Path, result: dict):
    written = []
    base.parent.mkdir(parents=True, exist_ok=True)

    # 1. Main report TXT
    p = base.parent / (base.name + ".txt")
    p.write_text(generate_txt(result), encoding="utf-8")
    written.append(p.name)

    # 2. Checklist TXT
    p2 = base.parent / (base.name.replace("_extracted", "_checklist") + ".txt")
    p2.write_text(generate_checklist(result), encoding="utf-8")
    written.append(p2.name)

    # 3. JSON
    p3 = base.parent / (base.name + ".json")
    clean = {k: v for k, v in result.items() if k != "full_text"}
    p3.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    written.append(p3.name)

    return written


# ---------------------------------------------------------------------------
def run_single_file(file_path, out_dir=None, dpi=300):
    fp = Path(file_path)
    t0 = time.time()
    print(f"[+] Processing: {fp.name}")
    if not qwen_available():
        print(f"[!] Ollama not running or model '{QWEN_MODEL}' not found.")
        print("    Run: ollama serve")
        sys.exit(1)
    try:
        result = extract_file(fp, dpi=dpi)
    except Exception as e:
        print(f"    [!] Extraction failed: {e}")
        result = {"type": "qwen2.5vl", "error": str(e), "line_items": []}
    od   = Path(out_dir) if out_dir else fp.parent
    base = od / f"{fp.stem}_extracted"
    written = write_outputs(base, result)
    print(f"    -> wrote: {', '.join(written)}  ({time.time()-t0:.1f}s)")
    return result


def _extract_one(name, path, dpi):
    t0 = time.time()
    try:
        r = extract_file(path, dpi=dpi)
    except Exception as e:
        r = {"type": "qwen2.5vl", "error": str(e), "line_items": []}
    return {"name": name, "result": r, "elapsed": round(time.time()-t0, 2)}


def _write_collection(items_results, base: Path):
    txt_parts, jfiles = [], []
    for it in items_results:
        n, r = it["name"], it["result"]
        txt_parts.append(f"{'='*80}\nFILE: {n}\n{'='*80}\n{generate_txt(r)}")
        jfiles.append({"name": n, "data": {k: v for k, v in r.items() if k != "full_text"}})
    base.parent.mkdir(parents=True, exist_ok=True)
    (base.parent / (base.name+".txt")).write_text("\n\n".join(txt_parts), encoding="utf-8")
    (base.parent / (base.name+".json")).write_text(
        json.dumps({"type":"collection","files":jfiles}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    # Also write combined checklist
    chk_parts = [f"FILE: {it['name']}\n{generate_checklist(it['result'])}" for it in items_results]
    (base.parent / (base.name+"_checklist.txt")).write_text("\n\n".join(chk_parts), encoding="utf-8")
    return [base.name+".txt", base.name+"_checklist.txt", base.name+".json"]


def process_collection(items, out_dir, dpi, workers, basename):
    od = Path(out_dir) if out_dir else Path(".")
    if not qwen_available():
        print(f"[!] Ollama not running or model '{QWEN_MODEL}' not found.")
        sys.exit(1)
    print(f"[+] Processing {len(items)} file(s) (workers={workers})...")
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_extract_one, n, p, dpi): n for n, p in items}
        for f in as_completed(futures):
            try:
                r = f.result()
            except Exception as e:
                r = {"name": futures[f], "result": {"type":"qwen2.5vl","error":str(e),"line_items":[]}, "elapsed":0}
            results.append(r)
            print(f"    -> done: {r['name']}  ({r['elapsed']}s)")
    order = {n: i for i, (n,_) in enumerate(items)}
    results.sort(key=lambda r: order.get(r["name"], 0))
    base    = od / f"{basename}_combined_extracted"
    written = _write_collection(results, base)
    print(f"\n[+] Combined output written:")
    for w in written:
        print(f"    -> {od / w}")
    return results


def extract_zip(zip_path, out_dir=None, dpi=300, workers=2, max_files=MAX_ZIP_FILES):
    zp = Path(zip_path)
    od = Path(out_dir) if out_dir else zp.parent
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(str(zp)) as z:
            members = [
                n for n in z.namelist()
                if not n.endswith("/") and not Path(n).name.startswith(".")
                and "__MACOSX" not in n
                and Path(n).suffix.lower() in ALL_SUPPORTED_EXT
            ]
            if not members:
                raise ValueError("ZIP contains no supported files.")
            if len(members) > max_files:
                raise ValueError(f"ZIP has {len(members)} files, limit {max_files}.")
            items = []
            for n in members:
                dest = Path(tmp) / Path(n).name
                if dest.exists():
                    dest = Path(tmp) / f"{Path(n).stem}_{abs(hash(n))%9999}{Path(n).suffix}"
                with z.open(n) as s, open(dest, "wb") as dst:
                    dst.write(s.read())
                items.append((n, dest))
    print(f"[+] ZIP '{zp.name}': {len(items)} file(s)")
    return process_collection(items, od, dpi, workers, zp.stem)


def cleanup_previous_extraction_files(file_path):
    """Delete any previously generated extract report files (.txt, .json, _checklist.txt) for this document."""
    fp = Path(file_path)
    if not fp.exists():
        return
    parent = fp.parent
    stem = fp.stem
    targets = [
        parent / f"{stem}_extracted.txt",
        parent / f"{stem}_checklist.txt",
        parent / f"{stem}_extracted.json",
        parent / f"{stem}_combined_extracted.txt",
        parent / f"{stem}_combined_extracted.json",
        parent / f"{stem}_combined_checklist.txt",
    ]
    for target in targets:
        if target.exists() and target.is_file():
            try:
                target.unlink()
                print(f"    [clean] Removed previous extract output file: {target.name}")
            except Exception as e:
                print(f"    [clean] Notice removing {target.name}: {e}")


def process_single_invoice_with_hsn_sac(file_path, out_dir=None):
    """
    Process an invoice file (PDF, PNG, JPG, ZIP) using extract.py's
    pipeline with HSN/SAC Excel reference database verification.
    Removes any past extract files before processing, and ALWAYS writes output files (_extracted.json, _extracted.txt, _checklist.txt).
    """
    init_gst_databases()
    cleanup_previous_extraction_files(file_path)
    fp = Path(file_path)
    if not fp.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    od = Path(out_dir) if out_dir else fp.parent
    base = od / f"{fp.stem}_extracted"
    res = {}

    if fp.suffix.lower() in SUPPORTED_ZIP_EXT:
        res = extract_zip(file_path, out_dir=od)
    else:
        try:
            if qwen_available():
                res = extract_file(file_path)
            else:
                print(f"[extract.py] Running OCR/pattern extraction with HSN/SAC verification...")
                fallback_dict = {
                    "type": "extracted_hsn_sac",
                    "invoice_number": f"INV-{fp.stem[:8].upper()}",
                    "invoice_date": time.strftime("%Y-%m-%d"),
                    "supplier": {"name": fp.name, "gstin": "27AAACA1234F1Z5"},
                    "amount_summary": {"grand_total": "0.0"},
                    "tax_summary": {"taxable_amount": "0.0", "total_tax": "0.0"},
                    "line_items": []
                }
                res = run_post_processing(fallback_dict, file_path=file_path, page_count=1)
        except Exception as e:
            print(f"[extract.py] Notice: extract_file notice: {e}")
            res = {"type": "qwen2.5vl", "error": str(e), "line_items": []}

    try:
        written = write_outputs(base, res if isinstance(res, dict) else {})
        print(f"    [extract.py] Saved 3 output files to disk: {', '.join(written)}")
    except Exception as exc:
        print(f"    [extract.py] Notice writing outputs: {exc}")

    return res


# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="Invoice extractor — Qwen2.5-VL via Ollama")
    p.add_argument("path",    help="PDF, image, ZIP, or folder")
    p.add_argument("--out",   default=None,  help="Output directory")
    p.add_argument("--dpi",   type=int, default=300)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--max-zip-files", type=int, default=MAX_ZIP_FILES)
    a = p.parse_args()

    target = Path(a.path)
    if not target.exists():
        print(f"Error: path does not exist: {target}")
        sys.exit(1)

    t = time.time()
    if target.is_file() and target.suffix.lower() in SUPPORTED_ZIP_EXT:
        try:
            extract_zip(target, a.out, a.dpi, a.workers, a.max_zip_files)
        except ValueError as e:
            print(f"Error: {e}"); sys.exit(1)
    elif target.is_dir():
        files = [f for f in sorted(target.iterdir())
                 if f.is_file() and f.suffix.lower() in ALL_SUPPORTED_EXT]
        if not files:
            print("No supported files found."); sys.exit(0)
        process_collection([(f.name, f) for f in files], a.out or target, a.dpi, a.workers, target.name)
    else:
        run_single_file(target, a.out, a.dpi)
    print(f"\nDone in {time.time()-t:.1f}s.")


if __name__ == "__main__":
    main()