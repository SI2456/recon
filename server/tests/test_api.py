"""The endpoints the UI depends on, and the role gates around them.

Every route exercised here was missing from the FastAPI backend at some point
and returned a 404 or 405 to a button in the browser, so the point of these
tests is to notice if that happens again.
"""

from __future__ import annotations

from helpers import books_csv, make_gstin


def test_login_accepts_padded_and_mixed_case_email(client, make_user):
    user = make_user("business_user")
    response = client.post(
        "/api/auth/login",
        json={"email": f"  {user['email'].upper()}  ", "password": "Passw0rd!"},
    )
    assert response.status_code == 200, response.text


def test_reviewer_directory_requires_authentication(client, make_user):
    assert client.get("/api/ca/list").status_code == 401
    reader = make_user("business_user")
    assert client.get("/api/ca/list", headers=reader["headers"]).status_code == 200


class TestCreateClient:
    def test_reviewer_can_open_a_workspace(self, client, make_user):
        reviewer = make_user("tax_reviewer")
        response = client.post(
            "/api/clients",
            json={"name": "New Co", "gstin": make_gstin("29", "AAACA1234F"), "city": "Pune"},
            headers=reviewer["headers"],
        )
        assert response.status_code == 201, response.text
        assert response.json()["client"]["caId"] == reviewer["id"]

    def test_duplicate_gstin_is_rejected(self, client, make_user):
        reviewer = make_user("tax_reviewer")
        gstin = make_gstin("29", "BBACA1234F")
        first = client.post("/api/clients", json={"name": "A", "gstin": gstin}, headers=reviewer["headers"])
        assert first.status_code == 201, first.text
        second = client.post("/api/clients", json={"name": "B", "gstin": gstin}, headers=reviewer["headers"])
        assert second.status_code == 409, second.text

    def test_malformed_gstin_is_rejected(self, client, make_user):
        reviewer = make_user("tax_reviewer")
        response = client.post(
            "/api/clients", json={"name": "Bad", "gstin": "NOTAGSTIN"}, headers=reviewer["headers"]
        )
        assert response.status_code == 400, response.text

    def test_business_user_cannot_create(self, client, make_user):
        business = make_user("business_user")
        response = client.post(
            "/api/clients",
            json={"name": "X", "gstin": make_gstin("29", "CCACA1234F")},
            headers=business["headers"],
        )
        assert response.status_code == 403, response.text


class TestDeleteClient:
    def test_only_an_admin_may_delete(self, client, make_user):
        reviewer = make_user("tax_reviewer")
        admin = make_user("admin")
        created = client.post(
            "/api/clients",
            json={"name": "Doomed", "gstin": make_gstin("29", "DDACA1234F")},
            headers=reviewer["headers"],
        )
        workspace_id = created.json()["client"]["id"]

        assert client.delete(f"/api/clients/{workspace_id}", headers=reviewer["headers"]).status_code == 403
        assert client.delete(f"/api/clients/{workspace_id}", headers=admin["headers"]).status_code == 200
        assert client.delete(f"/api/clients/{workspace_id}", headers=admin["headers"]).status_code == 404


class TestCAChangeRequests:
    def test_full_request_lifecycle(self, client, make_user, make_workspace, link_profile, db):
        from app.db.models import Client as ClientModel

        current = make_user("tax_reviewer")
        target = make_user("tax_reviewer")
        business = make_user("business_user")
        admin = make_user("admin")
        workspace_id = make_workspace(
            gstin=make_gstin("27", "EEACA1234F"), email=business["email"], ca_id=current["id"]
        )
        link_profile(business["id"], current["id"])

        filed = client.post(
            "/api/ca-change-requests",
            json={"requestedCaId": target["id"], "reason": "moving"},
            headers=business["headers"],
        )
        assert filed.status_code == 201, filed.text
        request_id = filed.json()["requestId"]

        # One open request at a time.
        again = client.post(
            "/api/ca-change-requests",
            json={"requestedCaId": target["id"]},
            headers=business["headers"],
        )
        assert again.status_code == 409, again.text

        listed = client.get("/api/ca-change-requests", headers=business["headers"])
        assert listed.status_code == 200
        rows = [row for row in listed.json()["requests"] if row["id"] == request_id]
        assert len(rows) == 1
        # The admin table reads these keys; a rename here breaks that screen.
        for key in ("client_name", "client_email", "current_ca_name", "requested_ca_name", "status", "created_at"):
            assert key in rows[0], key

        assert (
            client.post(f"/api/ca-change-requests/{request_id}/approve", headers=current["headers"]).status_code
            == 403
        )
        approved = client.post(f"/api/ca-change-requests/{request_id}/approve", headers=admin["headers"])
        assert approved.status_code == 200, approved.text

        db.expire_all()
        assert db.get(ClientModel, workspace_id).ca_id == target["id"]

        # Deciding a settled request must not silently re-run the transfer.
        assert (
            client.post(f"/api/ca-change-requests/{request_id}/approve", headers=admin["headers"]).status_code
            == 409
        )

    def test_an_unrelated_user_sees_no_requests(self, client, make_user, make_workspace, link_profile):
        current = make_user("tax_reviewer")
        target = make_user("tax_reviewer")
        business = make_user("business_user")
        outsider = make_user("business_user")
        make_workspace(gstin=make_gstin("27", "FFACA1234F"), email=business["email"], ca_id=current["id"])
        link_profile(business["id"], current["id"])
        client.post(
            "/api/ca-change-requests",
            json={"requestedCaId": target["id"]},
            headers=business["headers"],
        )

        seen = client.get("/api/ca-change-requests", headers=outsider["headers"])
        assert seen.status_code == 200
        assert seen.json()["requests"] == []


class TestUploadLifecycle:
    def test_upload_process_and_delete(self, client, make_user, make_workspace):
        reviewer = make_user("tax_reviewer")
        business = make_user("business_user")
        supplier_gstin = make_gstin("27", "GGACA1234F")
        make_workspace(gstin=make_gstin("27", "HHACA1234F"), email=business["email"], ca_id=reviewer["id"])

        uploaded = client.post(
            "/api/ingestion/upload",
            data={"source": "books"},
            files={"file": ("books.csv", books_csv("INV-CI-1", supplier_gstin), "text/csv")},
            headers=business["headers"],
        )
        assert uploaded.status_code == 201, uploaded.text
        upload = uploaded.json()["upload"]
        # Keyed by content, so two files of the same name cannot overwrite.
        assert upload["checksum"][:16] in upload["objectKey"]

        processed = client.post(f"/api/ingestion/process/{upload['id']}", headers=reviewer["headers"])
        assert processed.status_code == 202, processed.text

        invoices = client.get("/api/invoices", headers=reviewer["headers"]).json()["invoices"]
        assert any(row["invoice_no"] == "INV-CI-1" for row in invoices)

        assert (
            client.delete(f"/api/ingestion/uploads/{upload['id']}", headers=business["headers"]).status_code == 403
        )
        deleted = client.delete(f"/api/ingestion/uploads/{upload['id']}", headers=reviewer["headers"])
        assert deleted.status_code == 200, deleted.text

        # The rows parsed out of a document do not outlive it.
        remaining = client.get("/api/invoices", headers=reviewer["headers"]).json()["invoices"]
        assert not any(row["invoice_no"] == "INV-CI-1" for row in remaining)

    def test_same_filename_does_not_overwrite(self, client, make_user, make_workspace):
        business = make_user("business_user")
        make_workspace(gstin=make_gstin("27", "IIACA1234F"), email=business["email"])
        supplier = make_gstin("27", "JJACA1234F")

        first = client.post(
            "/api/ingestion/upload",
            data={"source": "books"},
            files={"file": ("same.csv", books_csv("INV-A", supplier), "text/csv")},
            headers=business["headers"],
        )
        second = client.post(
            "/api/ingestion/upload",
            data={"source": "books"},
            files={"file": ("same.csv", books_csv("INV-B", supplier), "text/csv")},
            headers=business["headers"],
        )
        assert first.status_code == second.status_code == 201
        assert first.json()["upload"]["objectKey"] != second.json()["upload"]["objectKey"]


class TestDashboardScope:
    def test_client_filter_is_honoured_and_scoped(self, client, make_user, make_workspace):
        reviewer = make_user("tax_reviewer")
        outsider = make_user("business_user")
        workspace_id = make_workspace(gstin=make_gstin("27", "KKACA1234F"), ca_id=reviewer["id"])

        scoped = client.get(f"/api/dashboard?clientId={workspace_id}", headers=reviewer["headers"])
        assert scoped.status_code == 200, scoped.text
        assert scoped.json()["kpis"]["totalClients"] == 1

        # Asking for someone else's workspace is refused, not silently emptied.
        refused = client.get(f"/api/dashboard?clientId={workspace_id}", headers=outsider["headers"])
        assert refused.status_code == 403, refused.text
