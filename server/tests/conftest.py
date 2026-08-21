"""Shared test setup.

Every test runs against a throwaway SQLite database and a throwaway upload
directory. Both have to be pointed somewhere temporary *before* the app is
imported, because ``app.core.config`` reads settings and ``app.db.session``
builds its engine at import time — so the environment is set at module scope
here, above the imports that depend on it.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "server") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "server"))

_TMP_DIR = Path(tempfile.mkdtemp(prefix="reconai-tests-"))

# A private database, so a developer's working data is never read or written.
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP_DIR / 'test.sqlite3').as_posix()}"
# No mail transport and an explicitly development environment, which is the
# only combination in which registration echoes the OTP back for the tests to
# use. Cleared rather than inherited so a developer's real SMTP settings in
# server/.env cannot make the suite send mail.
os.environ["ENVIRONMENT"] = "development"
os.environ["EMAIL_HOST"] = ""
os.environ["EMAIL_HOST_USER"] = ""
# No object storage: uploads go to the temporary directory below.
os.environ["R2_ENDPOINT_URL"] = ""
os.environ["R2_ACCESS_KEY_ID"] = ""
os.environ["R2_SECRET_ACCESS_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.models import CAProfile, Client, ClientProfile, User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services import storage  # noqa: E402

PASSWORD = "Passw0rd!"


@pytest.fixture(scope="session", autouse=True)
def _upload_root():
    """Keep uploaded bytes out of the working tree."""
    root = _TMP_DIR / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    storage.UPLOAD_ROOT = root
    yield root


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def unique(request):
    """A per-test suffix, so tests sharing one database cannot collide.

    The engine is built once at import time, so the database is shared across
    the session; giving each test its own email addresses is what keeps them
    independent without tearing the schema down between them.
    """
    counter = {"n": 0}

    def make(prefix: str = "") -> str:
        counter["n"] += 1
        return f"{prefix}{abs(hash(request.node.nodeid)) % 100000}x{counter['n']}"

    return make


@pytest.fixture
def make_user(db, unique):
    """Create a verified account, returning it with an auth header."""

    def create(role: str, *, gstin: str = "", name: str = "Test User") -> dict:
        email = f"{unique('u')}@test.local"
        user = User(
            name=name,
            email=email,
            password_hash=hash_password(PASSWORD),
            role=role,
            gstin=gstin,
            email_verified=True,
            status="active",
        )
        db.add(user)
        db.flush()
        if role == "tax_reviewer":
            db.add(CAProfile(user_id=user.id, is_verified=True))
        db.commit()
        user_id = user.id
        return {"id": user_id, "email": email, "headers": _login(email)}

    def _login(email: str) -> dict:
        from fastapi.testclient import TestClient as _TC

        with _TC(app) as api:
            response = api.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    return create


@pytest.fixture
def make_workspace(db, unique):
    """Create a client workspace owned by a business user."""

    def create(*, gstin: str, email: str = "", ca_id: int | None = None, name: str = "Test Ltd") -> int:
        workspace = Client(name=name, gstin=gstin, email=email, ca_id=ca_id)
        db.add(workspace)
        db.commit()
        return workspace.id

    return create


@pytest.fixture
def link_profile(db):
    def create(user_id: int, ca_id: int | None) -> None:
        db.add(ClientProfile(user_id=user_id, selected_ca_id=ca_id))
        db.commit()

    return create
