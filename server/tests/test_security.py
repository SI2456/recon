"""Regressions for the authentication and tenant-scoping defects.

Each of these passed silently before the fix, which is exactly why they are
worth pinning: none of them produce an error, they just quietly hand out access
or accept a guessable code.
"""

from __future__ import annotations

from app.db.models import Client as ClientModel
from app.db.models import EmailOtp
from helpers import make_gstin


class TestOtp:
    def test_failed_attempts_are_persisted_and_cap_the_code(self, client, db, unique):
        """The attempt counter used to be rolled back with the failed request.

        It was incremented on the record and then discarded when the route
        raised before its commit, so OTP_MAX_ATTEMPTS never took effect and the
        six-digit code could be walked through exhaustively.
        """
        email = f"{unique('otp')}@test.local"
        registered = client.post(
            "/api/auth/register",
            json={"name": "Reg", "email": email, "password": "Passw0rd!", "role": "business_user"},
        )
        assert registered.status_code == 201, registered.text
        real_otp = registered.json().get("devOtp")
        assert real_otp and real_otp.isdigit() and len(real_otp) == 6

        for _ in range(5):
            client.post("/api/auth/verify-otp", json={"email": email, "otp": "000000"})

        record = (
            db.query(EmailOtp).filter(EmailOtp.email == email).order_by(EmailOtp.id.desc()).first()
        )
        db.refresh(record)
        assert record.attempts >= 5

        # Even the correct code is refused once the cap is reached.
        blocked = client.post("/api/auth/verify-otp", json={"email": email, "otp": real_otp})
        assert blocked.status_code == 429, blocked.text

    def test_codes_are_not_predictable(self, client, unique):
        """Guards the move off `random`, whose state is reconstructible."""
        codes = set()
        for _ in range(12):
            response = client.post(
                "/api/auth/register",
                json={
                    "name": "R",
                    "email": f"{unique('rng')}@test.local",
                    "password": "Passw0rd!",
                    "role": "business_user",
                },
            )
            codes.add(response.json().get("devOtp"))
        assert len(codes) == 12


class TestTenantScoping:
    def test_verify_gstin_cannot_claim_another_tenants_workspace(
        self, client, db, make_user, make_workspace
    ):
        """A GSTIN is public, so it must not be usable as a claim of ownership.

        The lookup used to match any workspace holding the submitted number,
        which let an attacker attach themselves to it and read its invoices.
        """
        victim_gstin = make_gstin("27", "VVACA1234F")
        victim = make_user("business_user", gstin=victim_gstin, name="Victim")
        workspace_id = make_workspace(gstin=victim_gstin, email=victim["email"], name="Victim Ltd")
        attacker = make_user("business_user", name="Attacker")

        response = client.post(
            "/api/client/verify-gstin", json={"gstin": victim_gstin}, headers=attacker["headers"]
        )
        assert response.status_code == 409, response.text

        db.expire_all()
        assert db.get(ClientModel, workspace_id).name == "Victim Ltd"
        assert client.get("/api/invoices", headers=attacker["headers"]).json()["invoices"] == []

    def test_an_unverified_gstin_matches_no_workspace(self, client, make_user, make_workspace):
        """``Client.gstin == ""`` used to match every unverified workspace."""
        make_workspace(gstin="", email="somebody-else@test.local", name="Blank One")
        newcomer = make_user("business_user")  # no GSTIN yet

        response = client.get("/api/clients", headers=newcomer["headers"])
        assert response.status_code == 200
        assert response.json()["clients"] == []
