# ReconAI — Automated GST Reconciliation & Fraud Detection

AI-powered GST tax-compliance platform for Government Tax Authorities & Tax Officers. ReconAI
automates the reconciliation of a client's books (Tally) against their GST
returns (GSTR-2A/2B), detects fraud with machine learning, and surfaces
circular-trading rings — turning a manual, days-long process into minutes.

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
| **Document workflow** | Clients upload → Tax Officer reviews & **Processes** (runs OCR/extraction) → Tax Officer controls per-document **visibility** to the client |
| **RBAC** | Admin / Tax Officer / Client roles with scoped data access and email-OTP verification |

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
```

### 2. Backend

```bash
cd server
python -m venv .venv
.venv\Scripts\activate            # Windows (use source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
pip install -r requirements-ml.txt        # scikit-learn, shap, rapidfuzz, etc.
pip install -r requirements-postgres.txt  # PostgreSQL driver
cd ..
npm run db:up          # starts PostgreSQL + Redis via Docker (optional)
npm run backend:seed   # seed demo users & data
npm run backend        # FastAPI on http://localhost:4000
```

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
| Tax Officer | `ca.demo@reconai.local` | `Demo@123` |
| Client | `client.demo@reconai.local` | `Demo@123` |

## How the document flow works

1. A **client** uploads a document (CSV / JSON / PDF / image) — it is stored,
   not yet processed.
2. The **CA** sees it in the Upload Center and clicks **Process** — this runs
   OCR/parsing, extracts invoice rows, and feeds reconciliation & fraud
   detection.
3. The CA runs **reconciliation** (exact + fuzzy) and **fraud detection**, and
   reviews the **graph** for circular-trading rings.
4. The CA toggles **Visible to client** on any document to share it back; the
   client only sees documents the CA has shared.
