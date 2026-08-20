import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine


def main() -> None:
    try:
        with engine.connect() as connection:
            value = connection.execute(text("select 1")).scalar_one()
    except OperationalError as exc:
        message = str(exc.orig if hasattr(exc, "orig") else exc)
        print("Database connection failed.")
        if "password authentication failed" in message:
            print("Reason: PostgreSQL username/password is wrong.")
            print("Fix: create/reset the reconai user password, or update DATABASE_URL in server/.env.")
        elif "Connection refused" in message or "actively refused" in message:
            print("Reason: PostgreSQL is not running on localhost:5432.")
            print("Fix: start PostgreSQL service or install/start Docker Desktop and run npm run db:up.")
        else:
            print(message)
        raise SystemExit(1) from exc

    print(f"Database connection OK: {engine.url}")
    print(f"Test query returned: {value}")


if __name__ == "__main__":
    main()
