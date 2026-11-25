# Assignment audit

Reviewed against `Gaviru_3_Day_Technical_Assessment.pdf` on 2026-11-24. Status describes evidence present in this workspace; it does not certify a fresh runtime run.

## Requirement-by-requirement status

| PDF section | Requirement | Status | Evidence / gap |
|---|---|---|---|
| 1 | Reusable service for business documents, extraction, inconsistency detection, human verification, future ERP/CRM/finance integration | Partially Done | Versioned REST API and JSON export provide an integration boundary. Authentication, tenant isolation and production deployment controls are explicitly absent. |
| 2 | Upload PDF/JPG/PNG and validate type and size | Completed | Magic bytes, extension, streamed size cap and safe content-addressed storage in `backend/app/storage.py`. |
| 2 | Classify invoice, receipt, purchase order and unknown | Completed | Weighted classifier and four `DocType` values; samples include all categories. Reviewers can now correct type in the review screen. |
| 2 | OCR or AI extraction of structured fields | Completed | PDF text layer/Tesseract plus optional LLM and rules fallback. Receipts remain classification-only and require manual entry, documented as allowed scope reduction. |
| 2 | Detect missing fields, invalid values and calculation errors | Completed | Decimal validation and issue codes in `backend/app/validation.py`. |
| 2 | Detect duplicate files by content hash | Completed | SHA-256 and unique DB constraint; duplicate response returns existing record. |
| 2 | Process asynchronously and expose status | Completed | Redis/Celery job queue, seven states, status/list/detail APIs. |
| 2 | Manual review and correction before approval | Completed | Review page and guarded PATCH endpoint; type and field changes are audited. |
| 2 | Record original values, changes and processing events | Completed | Separate `extracted` and `data` values and append-only audit events. Bulk exports now emit per-document export audit events. |
| 2 | Dashboard for status, errors and processing statistics | Completed | `/stats` and dashboard include status counts, failures, issue counts and timing. |
| 3 | Extract document number/date, parties, line items, quantities, unit prices, subtotal, tax, discount, total and currency from invoices/POs | Completed | Fields schema and extraction pipeline cover the requested fields; missing values remain null. |
| 3 | Field confidence when supported; otherwise unavailable | Completed | Tesseract confidence is attached to fields; PDF text-layer and LLM confidence is null and rendered as unavailable. |
| 3 | Never invent missing values | Completed | Rules are label anchored; LLM output is schema validated and every non-null value is checked against source text before validation. Unsupported values are nulled and create a blocking `UNGROUNDED_VALUE` issue. OCR mistakes and semantic misattribution remain human-review risks. |
| 4 | Incorrect invoice total flagged using decimal arithmetic | Completed | Decimal calculations with mismatch issues and approval gate. |
| 4 | Duplicate upload returns existing record without another job | Completed | Duplicate detection happens before queueing and is protected by unique hash. |
| 4 | Missing required fields route to manual review | Completed | `MISSING_FIELD` validation issue blocks automatic readiness. |
| 4 | Poor scan/incomplete extraction flagged | Completed | Confidence, OCR quality and unparsed-line flags; page-limit truncation now also creates `PDF_PAGE_LIMIT`. |
| 4 | Extractor outage falls back or routes to manual review | Completed | LLM-to-rules fallback; unavailable OCR/extractors create review issues. |
| 4 | Unexpected processing error recorded and controlled retry allowed | Completed | Failed state, audit record and retry on same document record. |
| 4 | Manual corrections preserve original and revised values | Completed | Original extraction is retained; edits create per-field audit records. |
| 4 | Approval requires unresolved issues fixed or explicitly reviewed before export | Completed | Approval gate requires issue IDs and a nonblank note for acknowledged issues; export routes require Approved. |
| 5 | Required upload-to-export workflow and suggested statuses | Completed | All seven suggested statuses are implemented. |
| 5 | Retry does not create duplicate records | Completed | Retry reuses the document row and worker claim is conditional/atomic. |
| 5 | JSON and CSV exports | Completed | Single and bulk export paths exist; CSV formula-injection mitigation is present. |
| 6 | React/Next.js, FastAPI, PostgreSQL, OCR, Redis/Celery, Compose, Swagger/OpenAPI, GitHub Actions | Completed | All are represented in source/configuration. Runtime topology still needs a local Compose run. |
| 6 | Keep secrets outside source control | Completed | `.env.example` and `.gitignore` are present. Verify `.env` is not submitted. |
| 6 | Use synthetic or public documents only | Completed | Included samples are synthetic. Do not add real customer documents to the repository. |
| 7 | Three-day plan: architecture/backend, business logic, then UI/testing/delivery | Completed | Implementation is organized across these concerns; timeline itself is guidance, not a separate artifact. |
| 8 | GitHub repository with meaningful commit history and complete source | Missing | The provided workspace has no `.git` directory, so this review cannot verify repository URL/history. Initialize/restore the actual submission repository and push meaningful commits. |
| 8 | Runnable Docker Compose, README and environment example | Partially Done | Files are present. Compose was not run in this environment; README local-development shell commands are Unix-specific. |
| 8 | Database schema, architecture diagram and API documentation | Completed | `docs/schema.sql`, Mermaid diagrams in `docs/ARCHITECTURE.md`, `docs/API.md`, and generated OpenAPI file. |
| 8 | At least 10 samples with expected and actual results | Completed | 15 sample files with expected/actual JSON and comparison report. The historical report is not a fresh run from this review. |
| 8 | Test report for success and failure scenarios | Partially Done | `docs/TEST_REPORT.md` reports 40 passing tests and integration runs, but these were not rerun during this review. |
| 8 | Five-minute demo video and known-limitations summary | Partially Done | Script and limitations summary exist; no recorded video is present in the workspace. |
| 9 | Existing/pretrained OCR/model allowed; no training required | Completed | Tesseract and optional hosted LLM are used; no model training is claimed. |
| 9 | Prioritize invoice workflow; receipt/PO scope may be limited if explained | Completed | Invoices and POs are extracted; receipt limitation is stated in `docs/LIMITATIONS.md`. |
| 9 | No hardcoded extraction results or fabricated values | Completed | Extraction operates on document text and expected fixtures are separate from pipeline output. |
| 9 | Prioritize reliability and accuracy over visual complexity | Completed | Validation, review gates and auditability support this; UI remains intentionally simple. |
| 9 | Candidate can explain code, decisions and trade-offs | Partially Done | Architecture and limitations documentation is a good basis; candidate must personally prepare and answer technical review questions. |

## Flaws addressed in this review

- The review page could edit fields but could not correct a mistaken classifier result. It now exposes the document-type selector for editable records and saves it through the existing audited endpoint.
- PDFs beyond the configured page cap were silently truncated. OCR now records a `PDF_PAGE_LIMIT` issue so partial extraction cannot look complete.
- Bulk export did not leave export events in document audit histories. It now records one event per exported document.
- Concurrent writes for the same content hash shared a fixed temporary filename. Storage now uses unique temporary files before atomic replacement.
- Windows-style path separators and control characters in uploaded names were not normalized for a Linux deployment. Names are reduced to a safe basename and control characters are removed.
- Original-file download returned a server error if the stored object was missing. It now returns a controlled 404.
- Reviewer names could exceed database column limits or contain only whitespace. Request schemas now enforce a nonblank name of at most 100 characters.

## Remaining limitations and risks

- No authentication or authorization: anyone who can reach the API can upload, correct, approve, read OCR text, and export. Keep the demo local; production use needs identity, roles and tenant isolation.
- Receipt extraction is intentionally unsupported; receipt documents are classified and routed for manual entry.
- Rule extraction is layout-sensitive; numeric dates are day-first; multi-currency/tax-inclusive/per-line tax formats are not fully modelled.
- Optional LLM success path, real browser click-through, and full Docker startup remain unverified in this review session.
- Workspace has no Git metadata and no demo recording. Those are submission deliverables outside the source-code fixes made here.

## Final submission actions

1. Restore or create the GitHub repository, review the diff, commit meaningful changes and verify the remote repository contains the complete source.
2. Run `docker compose up --build`, exercise upload, duplicate detection, correction/type correction, approval, and JSON/CSV export.
3. Re-run backend tests and sample generation, then update `docs/TEST_REPORT.md` and `docs/SAMPLE_RESULTS.md` only with actual results.
4. Record and include the five-minute demo; mention the limitations honestly.
5. Confirm `.env` and all real business documents are excluded from the submission.
