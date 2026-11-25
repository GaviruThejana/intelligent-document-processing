# Intelligent Document Processing & Validation System

Reusable document-processing service: upload invoices / purchase orders / receipts (PDF, JPG, PNG) -> duplicate check -> async OCR/AI extraction -> business validation -> human review -> approval -> JSON/CSV export. Built for the Neirah Tech Solutions 3-day assessment.

**Stack:** Next.js 16 · React 19 · FastAPI · PostgreSQL 16 · Redis 7 + Celery · Tesseract OCR + pdfplumber (optional LLM extractor) · Docker Compose · GitHub Actions.

## Quick start (Docker)
```bash
cp .env.example .env            # edit passwords if you like; never commit .env
docker compose up --build
```
* UI: http://localhost:3000 · API + Swagger: http://localhost:8000/docs
* Try the files in `samples/` (drag onto the dashboard). Stop Redis (`docker compose stop redis`) to see the outage/retry behaviour.

## Local development (no Docker)
The commands below use a Unix shell. For local frontend development, use Node.js 24. On Windows, from `backend`, create/activate the Python environment with `python -m venv .venv` and `.venv\Scripts\Activate.ps1`, then use `python -m pip install -r requirements-dev.txt`.
```bash
# backend (needs tesseract-ocr and poppler-utils installed on the OS)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests -v                 # 46 tests (OCR integration cases skip when system binaries are absent)
python -m scripts.run_samples             # regenerates samples/ + root and docs sample reports (expected vs actual)

# run API without Redis (processing happens inline in the request)
QUEUE_MODE=inline uvicorn app.main:app --reload
# or with Postgres + Redis running:
DATABASE_URL=postgresql+psycopg2://idp:idp@localhost/idp uvicorn app.main:app &
DATABASE_URL=... celery -A app.worker.celery_app worker -l info

# frontend
cd frontend && npm ci && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Repository layout
```
backend/app/    main.py (API) · pipeline.py · jobs.py · worker.py · ocr.py · classification.py
                extraction.py · validation.py · export.py · storage.py · models.py · schemas.py · audit.py
backend/tests/  test_units.py · test_api.py · factory.py (synthetic PDF/image generator)
backend/scripts/run_samples.py
frontend/       Next.js app (dashboard, upload, review/approval, audit trail)
samples/        15 synthetic documents + expected/ and actual/ JSON
docs/           ARCHITECTURE.md · API.md · schema.sql · openapi.json · SAMPLE_RESULTS.md · TEST_REPORT.md
                LIMITATIONS.md · REQUIREMENTS_MATRIX.md · DEMO_SCRIPT.md
```

## How it behaves (one paragraph)
Every upload is hashed; an identical file returns the existing document and creates no job. New files are stored content-addressed and queued; a Celery worker claims the job with an atomic status update, reads text (PDF text layer or Tesseract with per-line confidence), classifies and extracts. When LLM extraction is enabled, each returned field is checked against source text before validation; unverifiable values are nulled and routed to **Needs Review**. Rule extraction is the fallback. Money checks use `Decimal`. Reviewers correct fields (originals are kept; every change is audited), acknowledge remaining issues with a note, and approve. Only approved documents can be exported.

## Design choices, trade-offs, limitations
See `docs/ARCHITECTURE.md` (decisions) and `docs/LIMITATIONS.md` (honest list, e.g. receipts are classification-only, no auth).

## Assessment audit and final deliverables
See `docs/ASSIGNMENT_AUDIT.md` for a section-by-section audit against the supplied PDF, evidence, gaps and final submission actions. The recorded five-minute demo video and a pushed GitHub repository with meaningful commit history must be supplied by the candidate; neither is present in this workspace.

## Optional AI extractor
Set `ANTHROPIC_API_KEY` in `.env` to enable the optional LLM extractor (rules remain the fallback). LLM output is not trusted solely because it is valid JSON: scalar values and each line-item value must be found in source text, with numeric/date normalization. Unsupported output is cleared, confidence remains unavailable, and an `UNGROUNDED_VALUE` blocking issue is recorded. This deterministic evidence check reduces fabrication risk but does not prove semantic correctness; OCR can itself be wrong, so human review remains necessary. Without a key the system runs offline.

## Running all provided samples

With dependencies installed, run `python -m scripts.run_samples` from `backend`. The script regenerates actual JSON and both sample result reports. For real image/scanned-PDF OCR quality results, run it in the Docker Compose backend/worker image (which includes Tesseract and Poppler); host results without OCR must be labeled unavailable, not counted as OCR validation.
