# 5-minute demo video script (you must record this yourself)

Prep: `docker compose up --build`, open http://localhost:3000 and http://localhost:8000/docs. Have `samples/` open in a file window.

| Time | Show | Say |
|---|---|---|
| 0:00-0:30 | Architecture diagram (`docs/ARCHITECTURE.md`) | Stack, async pipeline, why Celery/Redis/Postgres, "fail towards a human". |
| 0:30-1:15 | Upload `01_clean_invoice.pdf`, `02_invoice_image.png`, `04_scanned_invoice.pdf` | Status goes Queued -> Processing -> Ready/Needs Review. PDF text layer vs Tesseract; field confidence shown; "n/a" for text layers. |
| 1:15-1:45 | Upload `12_duplicate_of_01.pdf` (or re-upload #1) | Duplicate banner, existing id, dashboard "Duplicates blocked" +1, no new job (show audit). |
| 1:45-2:45 | `05_incorrect_total.pdf` -> open it | TOTAL_MISMATCH with stated vs calculated (Decimal). Try Approve -> blocked with 409 message. Correct the total, Save -> issue disappears, status flips to Ready; show original value + audit trail row (old -> new, actor). |
| 2:45-3:15 | `06_missing_fields.pdf` | Missing number/date stay empty (never invented); Needs Review. |
| 3:15-3:45 | `10_poor_scan.png`, `15_moderate_scan.png` | POOR_SCAN_QUALITY / LOW_CONFIDENCE; garbage is flagged, not trusted. |
| 3:45-4:15 | Approve a document, then export JSON + CSV | Export blocked before approval; JSON contains original + final + acknowledged issues. |
| 4:15-4:40 | Failure handling: `docker compose stop redis`, upload (stays Uploaded) -> `start redis` -> Retry | Controlled retry, same record, no duplicates. |
| 4:40-5:00 | Dashboard, `pytest` summary (40 passing), `docs/LIMITATIONS.md` | Honest limitations: receipts classification-only, layout assumptions, no auth. |
