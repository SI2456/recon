# ReconAI — GST Reconciliation & Compliance-Risk Analysis

ReconAI is a GST reconciliation and compliance-risk analysis platform that
consolidates business accounting records, user-provided GST statements and
invoice documents. It reconciles transactions, validates GST-related fields and
ITC conditions against configurable rules, identifies anomalous transaction and
supplier patterns using ML and graph analytics, and provides an evidence-based
review workflow for finance and tax professionals.

**Scope.** ReconAI analyses the GST and accounting evidence a business already
has. It does not connect to, reproduce or simulate government systems: GST data
enters the platform as a file the authorized user exported from the GST portal,
or as clearly-labelled test data. Every upload records its `source_type`
(`USER_UPLOAD`, `GST_EXPORT`, `ACCOUNTING_EXPORT`, `OCR_DOCUMENT`,
`SIMULATED_GST`) so the origin of any figure can be stated rather than assumed.

> **Group 13** · Information Technology Department · Birla Vishvakarma
> Mahavidyalaya Engineering College · AY 2026-27, Semester 7
> Team: Hitarth Shah (23IT412, Lead), Siddhraj Rajput (22IT446),
> Sujal Patel (23IT401), Krunal Rohit (23IT419)

---

## Features

| Area | What it does |
| --- | --- |
| **Ingestion** | Parses Tally **CSV**, GSTR-2A/2B **JSON**, digital **PDF**, and scanned/image invoices into a unified invoice schema |
| **OCR (hybrid)** | Digital PDFs → fast `pypdf` text extraction; scanned PDFs & images → local **vision-LLM OCR** (Ollama `qwen2.5vl:3b`) that returns structured fields in one step |
| **Reconciliation** | Two-pass matching — exact `GSTIN:invoice_no` key, then **fuzzy** matching (RapidFuzz) for typos / OCR slips / formatting differences, with amount-tolerance checks |
| **Fraud detection** | **Isolation Forest** (unsupervised anomaly) + **Logistic Regression** (supervised) risk scoring, explained with **SHAP** values |
| **Graph analytics** | Directed supplier→buyer network with **DFS circular-trading (ITC fraud ring) detection** and ITC-at-risk tallies |
| **GSTIN verification** | Live GST-portal validation (captcha-free), plus full taxpayer details (legal name, address) via a captcha flow |
| **Document workflow** | Business user uploads → Reviewer **Processes** (runs OCR/extraction) → Reviewer controls per-document **visibility** back to the business user |
| **RBAC** | Admin / Tax & Compliance Reviewer / Business-Finance User roles with scoped data access and email-OTP verification |

Planned / in progress: RAG assistant with a ChromaDB vector store (an
Ollama-backed assistant endpoint exists today), and richer PDF/Excel report
export.

## Tech stack

- **Frontend:** React 18 + TypeScript + Vite, Tailwind, shadcn/ui, Recharts
- **Backend:** FastAPI (Python 3.11+), SQLAlchemy
- **Database:** PostgreSQL (SQLite supported for offline dev)
- **ML:** scikit-learn (Isolation Forest, Logistic Regression), SHAP, RapidFuzz
- **OCR / LLM:** Ollama (local) — `qwen2.5vl:3b` for vision OCR; `pypdf` + `PyMuPDF` for PDF text/rendering
- **Storage:** Cloudflare R2 (S3-compatible) with local-disk fallback

## Repository layout

```
├── src/                     # React frontend (App.tsx, components/, lib/api.ts)
├── server/                  # FastAPI backend
│   ├── app/
│   │   ├── api/             # Route modules (auth, ingestion, reconciliation, fraud, graph, …)
│   │   ├── services/        # parsing, vision_ocr, reconciliation, ml, gstverify, storage, rag
│   │   ├── db/              # SQLAlchemy models & session
│   │   └── core/            # config, security
│   ├── requirements*.txt
│   └── README.md            # Backend setup, DB, endpoints (details)
└── README.md
```

## Quick start

### 1. Frontend

```bash
npm install
npm run dev          # Vite dev server on http://localhost:5173
npm run typecheck    # TypeScript check (the Vite build does not type-check)
```

`npm test` runs the backend suite (`server/tests/`). CI runs the typecheck, the
build and that suite on every pull request — see `.github/workflows/ci.yml`.

### 2. Backend

```bash
python -m venv server/venv        # the npm scripts expect server/venv
npm run backend:install           # core dependencies
npm run backend:install-ml        # optional: scikit-learn, shap (fraud scoring)
npm run backend:install-postgres  # PostgreSQL driver
npm run db:up                     # starts PostgreSQL + Redis via Docker (optional)
npm run backend:seed              # seed demo users & data
npm run backend                   # FastAPI on http://localhost:4000
```

These scripts run the same on Windows, macOS and Linux — `server/scripts/py.js`
resolves the virtualenv's interpreter for the platform it is on. `npm run
dev:full` starts the API and the Vite dev server together.

See [`server/README.md`](server/README.md) for full database, `.env`, and endpoint details.

### 3. OCR model (for scanned / image invoices)

OCR for scanned documents uses a local vision-language model through
[Ollama](https://ollama.com). Digital PDFs and CSV/JSON do **not** need it.

```bash
ollama pull qwen2.5vl:3b
```

Ensure Ollama is running on `http://localhost:11434`. Configure a different
model with `OLLAMA_VISION_MODEL` in `server/.env` if desired.

## Demo logins

| Role | Email | Password |
| --- | --- | --- |
| Admin | `admin.demo@reconai.local` | `Demo@123` |
| Tax & Compliance Reviewer | `ca.demo@reconai.local` | `Demo@123` |
| Business / Finance User | `client.demo@reconai.local` | `Demo@123` |

## How the document flow works

1. A **business / finance user** uploads a document (CSV / JSON / PDF / image)
   with its GSTIN, financial year and tax period — it is stored, not yet
   processed.
2. The **tax & compliance reviewer** sees it in the Upload Center and clicks
   **Process** — this runs OCR/parsing, extracts invoice rows into the
   canonical model, and feeds reconciliation and the risk checks.
3. The reviewer runs **reconciliation** (exact + fuzzy), works through the
   **exceptions** raised by the rule, ML and graph layers, and inspects the
   evidence behind each one.
4. The reviewer toggles **visibility** on any document to share it back; the
   business user only sees documents the reviewer has shared.
