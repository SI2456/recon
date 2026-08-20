from collections.abc import Generator

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


# Repo root, resolved from this file rather than the process CWD.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_sqlite_url(url: str) -> str:
    """Anchor a relative sqlite path to the repo root.

    ``sqlite:///./server/data/reconai-dev.sqlite3`` is relative to the working
    directory, so starting the server from ``server/`` instead of the repo root
    would silently create a *second*, empty database. Resolving against the
    repo root makes the file land in the same place either way.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw = url[len(prefix):]
    # "" is in-memory; a leading "/" is an already-absolute POSIX path.
    if not raw or raw.startswith("/"):
        return url
    path = Path(raw)
    if path.is_absolute():  # e.g. "C:/..." on Windows
        return url
    resolved = (_REPO_ROOT / path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{resolved.as_posix()}"


if settings.database_url.startswith("sqlite"):
    engine = create_engine(
        _resolve_sqlite_url(settings.database_url),
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
else:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# Lightweight additive migrations for columns added after a table already
# exists (create_all only creates missing tables, never alters columns).
_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "uploads": {
        "visible_to_client": "BOOLEAN NOT NULL DEFAULT false",
        "gstin": "VARCHAR(20) NOT NULL DEFAULT ''",
        "financial_year": "VARCHAR(12) NOT NULL DEFAULT ''",
        "tax_period": "VARCHAR(12) NOT NULL DEFAULT ''",
        "document_type": "VARCHAR(40) NOT NULL DEFAULT ''",
        "source_type": "VARCHAR(32) NOT NULL DEFAULT 'USER_UPLOAD'",
        "checksum": "VARCHAR(64) NOT NULL DEFAULT ''",
    },
    "invoices": {
        "hsn": "VARCHAR(12) NOT NULL DEFAULT ''",
        "cgst": "FLOAT NOT NULL DEFAULT 0",
        "sgst": "FLOAT NOT NULL DEFAULT 0",
        "igst": "FLOAT NOT NULL DEFAULT 0",
        "cess": "FLOAT NOT NULL DEFAULT 0",
        "recipient_gstin": "VARCHAR(20) NOT NULL DEFAULT ''",
        "place_of_supply": "VARCHAR(4) NOT NULL DEFAULT ''",
        "document_type": "VARCHAR(24) NOT NULL DEFAULT 'invoice'",
    },
    "fraud_alerts": {"findings_json": "TEXT NOT NULL DEFAULT '[]'"},
}

# One-time data migrations that are safe to re-run.
_ROLE_RENAMES = {"ca": "tax_reviewer", "client": "business_user"}


def ensure_role_values() -> None:
    """Move stored roles onto their canonical names.

    Reads still accept the old values (see app.core.roles), so this is a
    tidying step rather than a hard cutover — running it twice changes
    nothing.
    """
    inspector = inspect(engine)
    if "users" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        for old, new in _ROLE_RENAMES.items():
            conn.execute(text("UPDATE users SET role = :new WHERE role = :old"), {"new": new, "old": old})


def ensure_schema() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, columns in _ADDITIVE_COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name in present:
                continue
            # SQLite doesn't accept "NOT NULL DEFAULT false" cleanly on ALTER; use 0.
            column_ddl = ddl.replace("false", "0") if engine.dialect.name == "sqlite" else ddl
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {column_ddl}"))
