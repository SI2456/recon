# ReconAI Backend

FastAPI backend for the ReconAI GST reconciliation app.

## Run

```bash
python -m venv server/venv          # the npm scripts look for it here
npm run backend:install             # core dependencies
npm run backend:install-postgres    # PostgreSQL driver
npm run backend:install-ml          # optional: scikit-learn / SHAP fraud scoring
npm run db:up                       # optional: PostgreSQL + Redis via Docker
npm run backend:seed
npm run backend
```

The `backend:*` and `db:*` scripts locate the interpreter through
`server/scripts/py.js`, which resolves `server/venv` on Windows, macOS and
Linux alike and falls back to `python3` on PATH when no virtualenv exists.

The API starts at `http://localhost:4000`. Development now uses PostgreSQL by default:

```bash
DATABASE_URL=postgresql+psycopg://reconai:reconai@localhost:5432/reconai
```

If Docker Desktop is installed, `npm run db:up` starts PostgreSQL and Redis from `server/docker-compose.yml`.
If Docker is not installed, install PostgreSQL manually and create a database/user/password named `reconai`.

Useful database commands:

```bash
npm run backend:install-postgres
npm run db:check
npm run db:migrate
npm run db:up
npm run db:down
```

After adding authentication/profile fields, run:

```bash
npm run db:migrate
npm run backend:seed
```

## Tests

```bash
npm run backend:install-dev   # pytest
npm test                      # or: python -m pytest server -q
```

`server/tests/` runs the real FastAPI app against a throwaway SQLite database
and a throwaway upload directory, both created in a temp dir by
`tests/conftest.py` — so the suite needs no database service, reads nothing
from `server/.env`, and leaves the working tree untouched. CI runs it on
Python 3.11 and 3.12.

Email OTP uses SMTP settings from `server/.env`. In development, if `EMAIL_HOST` is empty, the OTP is printed in the backend terminal and returned as `devOtp` for testing.

GSTIN verification uses GSTVerify from the backend only. Add your key to `server/.env`:

```bash
GSTVERIFY_API_KEY=your_secret_key_here
GSTVERIFY_BASE_URL=https://api.gstverify.dubey.app/api/v1
```

Clients verify a GSTIN from Client Settings in two ways:

- **Captcha-free validation** — confirms the GSTIN is registered/active against the GST portal (no credits, no captcha).
- **Full details** — the client solves a portal captcha (fetched via `GET /api/client/gstin-captcha`), and the backend fetches and saves the legal name, trade name, status, and address on the client record so both the client and assigned CA can see the verified business.

> Note: `config.py` loads `server/.env` by an absolute path, so the key loads regardless of which directory the server is started from.

If `npm run db:check` says the `reconai` password is wrong, open Command Prompt and run:

```bash
npm run db:init
```

Enter the PostgreSQL `postgres` password you set during installation. This runs:

```sql
ALTER ROLE reconai WITH PASSWORD 'reconai';
ALTER ROLE reconai CREATEDB;
GRANT ALL PRIVILEGES ON DATABASE reconai TO reconai;
```

You can also run the SQL file manually:

```bash
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d postgres -f server/scripts/init_postgres.sql
```

For quick offline testing only, you can temporarily switch `server/.env` back to SQLite:

```bash
DATABASE_URL=sqlite:///./server/data/reconai-dev.sqlite3
```

Install ML packages (Isolation Forest, SHAP, RapidFuzz, etc.) with:

```bash
pip install -r server/requirements-ml.txt
```

## OCR for scanned / image invoices

Digital PDFs use `pypdf` text extraction and CSV/JSON are parsed directly — no
model needed. **Scanned PDFs and image uploads** are OCR'd by a local
vision-language model via [Ollama](https://ollama.com):

```bash
ollama pull qwen2.5vl:3b
```

Ollama must be running on `http://localhost:11434`. Relevant `server/.env` keys:

```bash
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_VISION_MODEL=qwen2.5vl:3b
```

Uploads are stored first and processed on demand: the CA presses **Process**
(`POST /api/ingestion/process/{id}`), which runs the hybrid pypdf/VLM pipeline,
extracts invoice rows, and makes them available to reconciliation and fraud
detection. If Ollama is unavailable, digital PDFs still extract via pypdf.

## Demo Login

- Admin: `admin.demo@reconai.local` / `Demo@123`
- CA: `ca.demo@reconai.local` / `Demo@123`
- Client: `client.demo@reconai.local` / `Demo@123`

Use the returned `token` as a bearer token:

```bash
Authorization: Bearer <token>
```

## Main Endpoints

- `GET /api/health`
- `POST /api/auth/login`
- `POST /api/auth/register`
- `GET /api/dashboard`
- `POST /api/ingestion/upload` (store a document)
- `POST /api/ingestion/process/{id}` (CA/admin — run OCR/parsing)
- `PATCH /api/ingestion/uploads/{id}/visibility` (CA/admin — share with client)
- `GET /api/ingestion/uploads` (CA sees all; client sees only shared)
- `GET /api/client/gstin-captcha` · `POST /api/client/verify-gstin`
- `POST /api/clients` (reviewer/admin — open a workspace)
- `DELETE /api/clients/{id}` (admin — remove a workspace and its records)
- `DELETE /api/ingestion/uploads/{id}` (reviewer/admin — remove a document and its parsed rows)
- `GET /api/ca-change-requests` · `POST /api/ca-change-requests`
- `POST /api/ca-change-requests/{id}/approve` · `POST /api/ca-change-requests/{id}/reject` (admin)
- `POST /api/reconciliation/run`
- `GET /api/fraud/alerts`
- `POST /api/fraud/run`
- `GET /api/graph`
- `POST /api/assistant/ask`
- `POST /api/reports`
- `GET /api/reports`
- `GET /api/admin/users`
- `GET /api/admin/audit-logs`
- `GET /api/admin/system`

The SQLite prototype remains in `server/app.py` for reference only; the active
backend is `server/app/main.py`, which is what both `npm run backend` and
`npm run dev:full` start.
