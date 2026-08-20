import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password
from app.db.models import CAProfile, Client, ClientProfile, Invoice, User
from app.db.session import Base, SessionLocal, engine
from app.services.reconciliation import normalize_key


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).count():
            print("Seed skipped: users already exist.")
            return

        admin = User(name="System Admin", email="admin.demo@reconai.local", password_hash=hash_password("Demo@123"), role="admin", email_verified=True)
        ca = User(
            name="Demo Chartered Accountant",
            email="ca.demo@reconai.local",
            password_hash=hash_password("Demo@123"),
            role="tax_reviewer",
            firm_name="ReconAI Audit LLP",
            icai_number="CA123456",
            email_verified=True,
        )
        client_user = User(
            name="Demo Client",
            email="client.demo@reconai.local",
            password_hash=hash_password("Demo@123"),
            role="business_user",
            firm_name="ReconAI Audit LLP",
            gstin="27AAACA1234F1ZA",
            email_verified=True,
        )
        db.add_all([admin, ca, client_user])
        db.flush()

        db.add(CAProfile(user_id=ca.id, specialization="GST", experience="8 Years", city="Ahmedabad", rating=4.8, is_verified=True))

        client = Client(name="Demo Client", gstin="27AAACA1234F1ZA", email=client_user.email, ca_id=ca.id, city="Mumbai", compliance=92)
        db.add(client)
        db.flush()
        db.add(ClientProfile(user_id=client_user.id, selected_ca_id=ca.id))

        # HSN codes are chosen so their statutory rate matches the 18% these
        # rows imply — the demo data should not trip its own integrity checks.
        invoices = [
            ("INV-2026-001", "Apex Steel Traders", "27BBBCD4321P1ZG", "2026-07-01", 42000, 7560, 49560, "books", "7214"),
            ("INV-2026-001", "Apex Steel Traders", "27BBBCD4321P1ZG", "2026-07-01", 42000, 7560, 49560, "gstr", "7214"),
            ("INV-2026-002", "Northstar Logistics", "27CCCDD9876K1ZQ", "2026-07-03", 76000, 13680, 89680, "books", "9967"),
            ("INV-2026-003", "Roundtrip Metals", "27DDDEE1111A1Z8", "2026-07-05", 120000, 21600, 141600, "books", "7204"),
            ("INV-2026-003", "Roundtrip Metals", "27DDDEE1111A1Z8", "2026-07-05", 118000, 21240, 139240, "gstr", "7204"),
        ]
        for invoice_no, supplier, supplier_gstin, invoice_date, taxable, gst, total, source, hsn in invoices:
            db.add(
                Invoice(
                    client_id=client.id,
                    invoice_no=invoice_no,
                    supplier=supplier,
                    supplier_gstin=supplier_gstin,
                    invoice_date=invoice_date,
                    taxable=taxable,
                    gst=gst,
                    total=total,
                    hsn=hsn,
                    cgst=round(gst / 2, 2),
                    sgst=round(gst / 2, 2),
                    place_of_supply="27",
                    recipient_gstin="27AAACA1234F1ZA",
                    source=source,
                    normalized_key=normalize_key(invoice_no, supplier_gstin),
                )
            )

        db.commit()
        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
