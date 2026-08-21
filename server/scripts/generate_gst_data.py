"""Generate a matched purchase register and GSTR-2B for demos and testing.

Real GST return data can only be downloaded for a GSTIN you are authorised on,
and nobody is going to hand over five thousand invoices for a project. This
builds the pair synthetically instead, in the official GSTR-2B JSON schema, so
the whole pipeline can be exercised end to end at realistic volume.

Everything it emits is deliberately declarable: uploads created from these
files should be tagged ``source_type=SIMULATED_GST``, so the origin of any
figure can be stated rather than implied.

The point is not volume for its own sake — it is that the data contains a
*known* number of each defect, so a demo can claim "the system should find
N mismatches and one trading ring" and then be checked against that claim.
Every planted case is written to a manifest alongside the data.

    server\\venv\\Scripts\\python.exe server/scripts/generate_gst_data.py --invoices 5000

Outputs into --out-dir (default server/data/generated/):
    purchase_register.csv   the books side, Tally-style columns
    gstr2b.json             the GST side, official schema
    manifest.json           what was planted, and where
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "server"))

from app.services.integrity import gstin_check_digit  # noqa: E402


HSN_SAC_PATH = REPO_ROOT / "server" / "app" / "data" / "hsn_sac.json"

# Real trade names, so the demo does not read as "Supplier 1, Supplier 2".
SUPPLIER_NAMES = [
    "Apex Steel Traders", "Northstar Logistics", "Sunrise Polymers",
    "Vardhman Textiles Depot", "Kaveri Electricals", "Deccan Packaging",
    "Sterling Auto Components", "Blue Ridge Chemicals", "Anand Hardware Mart",
    "Meridian Office Supplies", "Ganga Paper Products", "Crest Engineering Works",
    "Silverline Instruments", "Pioneer Rubber Industries", "Orbit Freight Movers",
    "Nova Print Solutions", "Everest Tools & Dies", "Sagar Marine Exports",
    "Highland Foods Trading", "Zenith Cable Systems",
]

# State codes used for supplier GSTINs. The buyer sits in 27 (Maharashtra), so
# anything from another state is an inter-state supply and must carry IGST.
STATE_CODES = ["24", "29", "33", "06", "09", "19", "36", "27"]

PAN_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def make_gstin(rng: random.Random, state: str) -> str:
    """A structurally valid, checksum-correct GSTIN."""
    pan = (
        "".join(rng.choice(PAN_LETTERS) for _ in range(5))
        + f"{rng.randint(0, 9999):04d}"
        + rng.choice(PAN_LETTERS)
    )
    prefix = f"{state}{pan}1Z"
    return prefix + gstin_check_digit(prefix)


def break_gstin(gstin: str) -> str:
    """Same GSTIN with a wrong check digit — what a fabricated one looks like."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    wrong = alphabet[(alphabet.index(gstin[14]) + 7) % 36]
    return gstin[:14] + wrong


def load_hsn_rates() -> list[tuple[str, float]]:
    """(code, rate) pairs from the generated GST schedule lookup."""
    try:
        data = json.loads(HSN_SAC_PATH.read_text(encoding="utf-8"))
    except OSError:
        print(f"[!] {HSN_SAC_PATH} not found — run scripts/build_hsn_sac.py first.")
        raise SystemExit(1)
    pairs = [
        (code, rates[0])
        for code, rates in data.get("hsn", {}).items()
        # Single-rate 4-digit headings keep the expected rate unambiguous, so a
        # planted rate contradiction is genuinely a contradiction.
        if len(code) == 4 and len(rates) == 1 and rates[0] in (5.0, 12.0, 18.0, 28.0)
    ]
    if not pairs:
        print("[!] No usable HSN codes in the lookup.")
        raise SystemExit(1)
    return pairs


class Supplier:
    def __init__(self, rng: random.Random, name: str, state: str):
        self.name = name
        self.state = state
        self.gstin = make_gstin(rng, state)


def money(value: float) -> float:
    return round(value + 1e-9, 2)


def split_tax(taxable: float, rate: float, inter_state: bool) -> dict:
    """Tax components. Inter-state carries IGST; intra-state splits CGST/SGST."""
    total_tax = money(taxable * rate / 100)
    if inter_state:
        return {"igst": total_tax, "cgst": 0.0, "sgst": 0.0, "cess": 0.0, "gst": total_tax}
    half = money(total_tax / 2)
    return {"igst": 0.0, "cgst": half, "sgst": money(total_tax - half), "cess": 0.0, "gst": total_tax}


class Invoice:
    """One supply, held in whichever of the two records it belongs to."""

    def __init__(self, number, supplier, day, taxable, rate, hsn, buyer_state="27"):
        self.number = number
        # Place of supply for goods is where they land — the recipient's
        # state. Using the supplier's would make every inter-state supply
        # look like IGST charged within one state.
        self.pos = buyer_state
        self.supplier = supplier
        self.date = day
        self.taxable = money(taxable)
        self.rate = rate
        self.hsn = hsn
        self.inter_state = supplier.state != buyer_state
        tax = split_tax(self.taxable, rate, self.inter_state)
        self.igst, self.cgst, self.sgst = tax["igst"], tax["cgst"], tax["sgst"]
        self.cess, self.gst = tax["cess"], tax["gst"]
        self.total = money(self.taxable + self.gst)
        # Set independently when books and GST must disagree.
        self.books_taxable = self.taxable
        self.books_gst = self.gst
        self.books_total = self.total
        self.books_gstin = supplier.gstin
        self.books_number = number
        self.books_hsn = hsn
        self.in_books = True
        self.in_gstr = True

    def books_row(self) -> dict:
        return {
            "Invoice No": self.books_number,
            "Supplier": self.supplier.name,
            "GSTIN": self.books_gstin,
            "Date": self.date.strftime("%d-%m-%Y"),
            "HSN Code": self.books_hsn,
            "Place of Supply": self.pos,
            "Taxable Value": f"{self.books_taxable:.2f}",
            "IGST": f"{self.igst if self.inter_state else 0:.2f}",
            "CGST": f"{0 if self.inter_state else self.cgst:.2f}",
            "SGST": f"{0 if self.inter_state else self.sgst:.2f}",
            "GST": f"{self.books_gst:.2f}",
            "Invoice Value": f"{self.books_total:.2f}",
        }

    def gstr_item(self) -> dict:
        # GSTR-2B spells the tax columns out flat, unlike 2A's itm_det.
        return {
            "num": 1, "rt": self.rate, "txval": self.taxable,
            "igst": self.igst, "cgst": self.cgst, "sgst": self.sgst,
            "cess": self.cess, "hsn": self.hsn,
        }

    def gstr_inv(self) -> dict:
        return {
            "inum": self.number,
            "typ": "R",
            "dt": self.date.strftime("%d-%m-%Y"),
            "val": self.total,
            "pos": self.pos,
            "rev": "N",
            "itcavl": "Y",
            "rsn": "",
            "diffprcnt": 1,
            "items": [self.gstr_item()],
        }


def build(count: int, seed: int, period: str, buyer_gstin: str) -> tuple[list, dict, dict]:
    """Build the invoice population and plant a known set of defects."""
    rng = random.Random(seed)
    hsn_rates = load_hsn_rates()
    suppliers = [Supplier(rng, name, rng.choice(STATE_CODES)) for name in SUPPLIER_NAMES]

    month = int(period[:2])
    year = int(period[2:])
    start = date(year, month, 1)

    invoices: list[Invoice] = []
    for index in range(count):
        supplier = rng.choice(suppliers)
        hsn, rate = rng.choice(hsn_rates)
        taxable = rng.choice([
            rng.randint(1_000, 20_000), rng.randint(20_000, 200_000),
            rng.randint(200_000, 900_000),
        ]) + rng.randint(0, 99) / 100
        invoices.append(Invoice(
            number=f"{supplier.name.split()[0][:3].upper()}/{year % 100}-{(year + 1) % 100}/{index + 1:05d}",
            supplier=supplier,
            day=start + timedelta(days=rng.randint(0, 27)),
            taxable=taxable, rate=rate, hsn=hsn,
        ))

    planted: dict[str, list[str]] = {k: [] for k in (
        "amount_mismatch", "missing_from_2b", "only_in_2b", "duplicate_in_books",
        "invalid_gstin", "hsn_rate_contradiction", "fuzzy_invoice_number",
        "circular_trading_ring",
    )}

    # Defects are carved out of distinct slices so no invoice carries two, which
    # would make the expected counts ambiguous.
    pool = list(range(count))
    rng.shuffle(pool)
    take = lambda n: [pool.pop() for _ in range(min(n, len(pool)))]  # noqa: E731

    # LINK 3B — supplier under-reported: books say more than the GST statement.
    for i in take(max(1, count // 25)):
        inv = invoices[i]
        inv.taxable = money(inv.books_taxable * rng.uniform(0.55, 0.85))
        tax = split_tax(inv.taxable, inv.rate, inv.inter_state)
        inv.igst, inv.cgst, inv.sgst, inv.gst = tax["igst"], tax["cgst"], tax["sgst"], tax["gst"]
        inv.total = money(inv.taxable + inv.gst)
        planted["amount_mismatch"].append(inv.number)

    # LINK 3A — supplier never filed: in books, absent from 2B.
    for i in take(max(1, count // 40)):
        invoices[i].in_gstr = False
        planted["missing_from_2b"].append(invoices[i].number)

    # In 2B but never recorded in books.
    for i in take(max(1, count // 60)):
        invoices[i].in_books = False
        planted["only_in_2b"].append(invoices[i].number)

    # LINK 1C — the same credit claimed twice.
    duplicates = []
    for i in take(max(1, count // 100)):
        duplicates.append(invoices[i])
        planted["duplicate_in_books"].append(invoices[i].number)

    # LINK 2 — a fabricated supplier GSTIN (fails its check digit).
    for i in take(max(1, count // 200)):
        invoices[i].books_gstin = break_gstin(invoices[i].supplier.gstin)
        planted["invalid_gstin"].append(invoices[i].number)

    # Misclassification: a real HSN taxed at a rate it never carries.
    for i in take(max(1, count // 150)):
        inv = invoices[i]
        wrong = 28.0 if inv.rate != 28.0 else 5.0
        inv.books_gst = money(inv.books_taxable * wrong / 100)
        inv.books_total = money(inv.books_taxable + inv.books_gst)
        planted["hsn_rate_contradiction"].append(inv.number)

    # An OCR-style O/0 confusion in the books number. Punctuation changes are
    # useless here: normalize_key strips them, so the pair would exact-match and
    # never exercise the fuzzy pass at all. A letter-for-digit slip survives
    # normalisation, cannot collide with a numeric invoice number, and is what
    # fuzzy matching exists for.
    for i in take(max(1, count // 120)):
        inv = invoices[i]
        head, _, tail = inv.number.rpartition("/")
        inv.books_number = f"{head}/O{tail[1:]}" if tail.startswith("0") else inv.number + "O"
        planted["fuzzy_invoice_number"].append(inv.number)

    # Circular trading: three shells billing each other in a loop, each buying
    # from the one before it. A ring is only visible when every member is a
    # client workspace, because the graph draws edges supplier -> buyer using
    # client GSTINs; billed into a single buyer they form a star, not a cycle.
    # They therefore get their own registers rather than joining the main one.
    ring = [Supplier(rng, n, "27") for n in ("Roundtrip Metals", "TechWorld Traders", "GadgetHub Exports")]
    ring_books: list[tuple[Supplier, Invoice]] = []
    for position, buyer_member in enumerate(ring):
        seller = ring[(position - 1) % len(ring)]  # buys from the previous member
        hsn, rate = rng.choice(hsn_rates)
        inv = Invoice(
            number=f"RING/{year % 100}/{position + 1:03d}", supplier=seller,
            day=start + timedelta(days=rng.randint(0, 27)),
            taxable=rng.randint(400_000, 900_000), rate=rate, hsn=hsn,
            buyer_state=buyer_member.state,
        )
        ring_books.append((buyer_member, inv))
        planted["circular_trading_ring"].append(inv.number)

    meta = {
        "buyer_gstin": buyer_gstin,
        "period": period,
        "seed": seed,
        "ring": [
            {"name": member.name, "gstin": member.gstin,
             "buys_from": ring[(i - 1) % len(ring)].name,
             "register": f"ring/{member.name.split()[0].lower()}_purchase_register.csv"}
            for i, member in enumerate(ring)
        ],
        "suppliers": len(suppliers),
    }
    return invoices + duplicates, planted, meta, ring_books


BOOKS_COLUMNS = [
    "Invoice No", "Supplier", "GSTIN", "Date", "HSN Code", "Place of Supply",
    "Taxable Value", "IGST", "CGST", "SGST", "GST", "Invoice Value",
]


def write_books(path: Path, invoices: list[Invoice]) -> int:
    rows = [inv.books_row() for inv in invoices if inv.in_books]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=BOOKS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def write_gstr2b(path: Path, invoices: list[Invoice], meta: dict) -> int:
    """Official GSTR-2B layout: docdata.b2b grouped by supplier GSTIN."""
    by_supplier: dict[str, list[Invoice]] = {}
    seen: set[tuple[str, str]] = set()
    for inv in invoices:
        if not inv.in_gstr:
            continue
        # A duplicate in the books appears once on the GST side — that is the
        # whole point of the duplicate case.
        key = (inv.supplier.gstin, inv.number)
        if key in seen:
            continue
        seen.add(key)
        by_supplier.setdefault(inv.supplier.gstin, []).append(inv)

    period = meta["period"]
    sections = []
    for gstin, group in sorted(by_supplier.items()):
        sections.append({
            "ctin": gstin,
            "trdnm": group[0].supplier.name,
            "supprd": period,
            "supfileddt": f"11-{int(period[:2]) % 12 + 1:02d}-{period[2:]}",
            "inv": [inv.gstr_inv() for inv in sorted(group, key=lambda i: i.number)],
        })

    document = {
        "gstin": meta["buyer_gstin"],
        "rtnprd": period,
        "version": "1.0",
        "gendt": f"14-{int(period[:2]) % 12 + 1:02d}-{period[2:]}",
        "docdata": {"b2b": sections},
    }
    path.write_text(json.dumps(document, indent=1), encoding="utf-8")
    return sum(len(s["inv"]) for s in sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--invoices", type=int, default=5000, help="how many supplies to generate (default 5000)")
    parser.add_argument("--seed", type=int, default=13, help="reproducibility seed (default 13)")
    parser.add_argument("--period", default="072026", help="return period MMYYYY (default 072026)")
    parser.add_argument("--buyer-gstin", default="", help="recipient GSTIN; generated if omitted")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "server" / "data" / "generated"))
    args = parser.parse_args()

    buyer = args.buyer_gstin or make_gstin(random.Random(args.seed), "27")
    invoices, planted, meta, ring_books = build(args.invoices, args.seed, args.period, buyer)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    books_path, gstr_path, manifest_path = (
        out / "purchase_register.csv", out / "gstr2b.json", out / "manifest.json")

    books_rows = write_books(books_path, invoices)
    gstr_rows = write_gstr2b(gstr_path, invoices, meta)

    # One register per ring member, to be uploaded under its own client.
    ring_dir = out / "ring"
    ring_dir.mkdir(exist_ok=True)
    for member, inv in ring_books:
        target = ring_dir / f"{member.name.split()[0].lower()}_purchase_register.csv"
        write_books(target, [inv])

    expected = {name: len(numbers) for name, numbers in planted.items()}
    manifest = {
        "_comment": "Synthetic data. Tag uploads from these files as SIMULATED_GST.",
        "generated": meta,
        "counts": {"books_rows": books_rows, "gstr2b_rows": gstr_rows},
        "expected_findings": expected,
        "planted": planted,
        "how_to_see_the_ring": (
            "Create one client workspace per entry in generated.ring, using that "
            "exact GSTIN, then upload its register from ring/. The cycle only "
            "appears once all three exist, because the graph joins clients."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    print(f"Wrote {out}")
    print(f"  purchase_register.csv  {books_rows:>6} rows")
    suppliers = len(json.loads(gstr_path.read_text(encoding="utf-8"))["docdata"]["b2b"])
    print(f"  gstr2b.json            {gstr_rows:>6} invoices across {suppliers} suppliers")
    print(f"  ring/                  {len(ring_books):>6} registers, one per ring member")
    print(f"  buyer GSTIN            {buyer}")
    print("\n  planted defects (the demo should find exactly these):")
    for name, total in sorted(expected.items()):
        print(f"    {name:26} {total:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
