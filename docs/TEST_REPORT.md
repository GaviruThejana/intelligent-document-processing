# Test report

## Fresh verification — 2026-11-24

Test run: **2026-11-24 18:26:11–18:26:25 Asia/Colombo**. Command: `python -m pytest tests -q` from `backend/`. Environment: Windows, Python 3.13.9, pytest 9.2.0, Pillow 13.0.0.

**Backend result: 43 collected, 40 passed, 3 skipped, 0 failed.** The three skipped API tests require a Tesseract executable; this host has Poppler but no `tesseract.exe`. The tests now skip explicitly when that external prerequisite is missing, rather than falsely exercising the OCR-unavailable fallback. Added Starlette's recommended `httpx2` testing transport; the fresh run completed without warnings.

Python dependency install from the pinned `backend/requirements-dev.txt` succeeded in an ignored `.venv`; `pip check` reported no broken requirements. The `pillow==13.0.0.post1` pin was invalid for Pillow and has been corrected to `pillow==13.0.0`.

**Frontend:** `npm ci --no-audit --no-fund` succeeded; `npm run build` passed on Node 24.11.1 with Next.js 16.4.6 and React 19.3.1. `npm audit --json` reported **0 vulnerabilities** after updating the previous Next.js 14.2.15 dependency and its vulnerable transitive PostCSS.

**Fresh sample pipeline:** `python -m scripts.run_samples` ran through FastAPI `TestClient` + SQLite + inline processing on **2026-11-24 18:21:19–18:21:25 Asia/Colombo**. It passed **10/15** ingestion/extraction expectations and **3/3** review/approval/export checks. Five OCR samples did not match expectations because Tesseract was unavailable; see both current sample reports at [`SAMPLE_RESULTS.md`](../SAMPLE_RESULTS.md) and [`docs/SAMPLE_RESULTS.md`](SAMPLE_RESULTS.md). The workflow checks verified duplicate same-ID/no-extra-record handling, blocked pre-approval exports, corrections preserving original values and writing audit events, approval, and single/bulk JSON and CSV export paths.

**Not verified in this environment:** Docker Compose startup/health and real PostgreSQL + Redis + Celery integration; Docker is not installed here. The sample runner uses SQLite/inline queue and does not substitute for the full Compose topology. This workspace also has no `.git` directory, so repository history/status checks were unavailable.

## Current acceptance coverage

| Scenario | Fresh status | Evidence / caveat |
|---|---|---|
| Wrong total, missing fields, duplicate, retry, correction, approval gate and exports | PASS | Fresh API suite and sample workflow; see 40 passing tests and 3/3 sample workflow checks above. |
| Image and scanned-PDF OCR | SKIPPED / ENVIRONMENT BLOCKED | Requires Tesseract; executable is absent. Five OCR sample rows show the actual unavailable-extractor behavior. |
| Noisy scan treatment | SKIPPED / ENVIRONMENT BLOCKED | OCR-specific API test skipped; sample rows show fallback output, not OCR accuracy. |
| Frontend production compilation | PASS | `npm run build` on Next 16.4.6 / React 19.3.1. |
| Frontend package audit | PASS | `npm audit --json`: zero vulnerabilities. |
| Docker + production queue integration | NOT RUN | Docker unavailable on this host. |

## Earlier verification record (historical; not the fresh result above)

The previous run reported 40/40 tests passing on Python 3.12.3 with Tesseract 5.3.4. Its integration run used Redis 7, PostgreSQL 16 and Celery. The old coverage/test-name tables below are retained as historical evidence; use the fresh results above for this workspace execution.

### Historical acceptance coverage

| Scenario | Tests | Result |
|---|---|---|
| Incorrect invoice total | `test_total_mismatch_detected`, `test_decimal_arithmetic_not_float`, `test_incorrect_total_flagged_and_blocks_approval_until_acknowledged`, `test_line_and_subtotal_mismatch` | PASS |
| Duplicate upload | `test_duplicate_upload_creates_no_second_job` | PASS |
| Missing required fields | `test_missing_required_and_invalid_values`, `test_missing_fields_need_review_and_correction_is_audited`, `test_rules_never_invent_missing_values` | PASS |
| Poor-quality scan | `test_low_confidence_flagged`, `test_poor_quality_scan_is_flagged`, `test_poor_scan_flag_raised_even_if_unclassifiable`, `test_ocr_decimal_repair_forces_verification`, `test_unparseable_item_row_is_reported_not_dropped` | PASS |
| Extraction service unavailable | `test_extraction_service_unavailable_falls_back`, `test_all_extractors_down_means_manual_review`, `test_ocr_unavailable_means_manual_review` | PASS |
| Unexpected failure + controlled retry | `test_unexpected_failure_then_controlled_retry_without_duplicates`, `test_corrupt_pdf_fails_cleanly`, `test_redelivered_task_is_a_noop`, `test_broker_outage_keeps_document_retryable`, `test_stalled_job_can_be_recovered` | PASS |
| Manual correction (audit) | `test_missing_fields_need_review_and_correction_is_audited`, `test_correcting_a_line_item_revalidates` | PASS |
| Approval gating / export | `test_clean_invoice_full_workflow`, `test_incorrect_total_flagged_and_blocks_approval_until_acknowledged`, `test_edit_and_approve_state_guards`, `test_csv_formula_injection_neutralised` | PASS |
| Upload validation (type/size) | `test_rejects_unsupported_type`, `test_rejects_wrong_content_even_with_pdf_extension`, `test_rejects_extension_content_mismatch`, `test_rejects_empty_and_oversize` | PASS |

## All tests

| File | Test | Time (s) | Result |
|---|---|---|---|
| test_api | `test_rejects_unsupported_type` | 0.03 | PASS |
| test_api | `test_rejects_wrong_content_even_with_pdf_extension` | 0.02 | PASS |
| test_api | `test_rejects_extension_content_mismatch` | 0.03 | PASS |
| test_api | `test_rejects_empty_and_oversize` | 0.05 | PASS |
| test_api | `test_clean_invoice_full_workflow` | 0.14 | PASS |
| test_api | `test_image_ocr_invoice` | 1.08 | PASS |
| test_api | `test_scanned_pdf_rasterised` | 0.95 | PASS |
| test_api | `test_incorrect_total_flagged_and_blocks_approval_until_acknowledged` | 0.07 | PASS |
| test_api | `test_missing_fields_need_review_and_correction_is_audited` | 0.07 | PASS |
| test_api | `test_correcting_a_line_item_revalidates` | 0.06 | PASS |
| test_api | `test_duplicate_upload_creates_no_second_job` | 0.11 | PASS |
| test_api | `test_unknown_and_receipt_go_to_manual_review` | 0.12 | PASS |
| test_api | `test_purchase_order_extracted` | 0.07 | PASS |
| test_api | `test_poor_quality_scan_is_flagged` | 15.68 | PASS |
| test_api | `test_extraction_service_unavailable_falls_back` | 0.06 | PASS |
| test_api | `test_all_extractors_down_means_manual_review` | 0.06 | PASS |
| test_api | `test_ocr_unavailable_means_manual_review` | 0.04 | PASS |
| test_api | `test_unexpected_failure_then_controlled_retry_without_duplicates` | 0.09 | PASS |
| test_api | `test_corrupt_pdf_fails_cleanly` | 0.05 | PASS |
| test_api | `test_redelivered_task_is_a_noop` | 0.06 | PASS |
| test_api | `test_broker_outage_keeps_document_retryable` | 0.07 | PASS |
| test_api | `test_edit_and_approve_state_guards` | 0.06 | PASS |
| test_api | `test_csv_formula_injection_neutralised` | 0.06 | PASS |
| test_api | `test_stats_and_listing` | 0.14 | PASS |
| test_api | `test_stalled_job_can_be_recovered` | 0.07 | PASS |
| test_units | `test_valid_invoice_has_no_issues` | 0.02 | PASS |
| test_units | `test_total_mismatch_detected` | 0.02 | PASS |
| test_units | `test_decimal_arithmetic_not_float` | 0.02 | PASS |
| test_units | `test_line_and_subtotal_mismatch` | 0.02 | PASS |
| test_units | `test_missing_required_and_invalid_values` | 0.02 | PASS |
| test_units | `test_low_confidence_flagged` | 0.02 | PASS |
| test_units | `test_unknown_type_flagged` | 0.02 | PASS |
| test_units | `test_parse_helpers` | 0.02 | PASS |
| test_units | `test_rules_extract_clean_invoice` | 0.02 | PASS |
| test_units | `test_rules_never_invent_missing_values` | 0.02 | PASS |
| test_units | `test_due_date_is_not_document_date` | 0.02 | PASS |
| test_units | `test_classification` | 0.02 | PASS |
| test_units | `test_ocr_decimal_repair_forces_verification` | 0.02 | PASS |
| test_units | `test_unparseable_item_row_is_reported_not_dropped` | 0.01 | PASS |
| test_units | `test_poor_scan_flag_raised_even_if_unclassifiable` | 0.01 | PASS |

## Manual integration run (production topology, not part of pytest)

Executed in the build sandbox with **real Redis 7, PostgreSQL 16, a Celery worker (2 processes) and uvicorn** (no Docker available there):

| Check | Observed |
|---|---|
| Upload clean PDF, PNG (sent with a wrong `Content-Type` header), wrong-total PDF | all accepted, processed asynchronously by the Celery worker; statuses Ready / Ready / Needs Review |
| Re-upload of an already-uploaded file | HTTP 200 `duplicate: true`, same document id, no second task (`/stats` -> `duplicates_detected: 1`) |
| Redis stopped, then a document uploaded | HTTP 202, document stays `Uploaded`, audit shows `uploaded, queued, enqueue_failed` (nothing lost) |
| Redis restarted, `POST /retry` | document re-queued on the same record (`retry_count = 1`), total document count unchanged |
| `pg_dump -s` | produced `docs/schema.sql` (tables, constraints, indexes) |

## Not verified in the build sandbox (be transparent in your submission)

- `docker compose up --build` (Docker was unavailable there); the Compose file was validated as YAML only. Run it once yourself before submitting.
- The Next.js UI was verified to **compile** (`next build`) but not clicked through in a browser.
- The optional LLM extractor was exercised only through its failure/fallback path (mocked network error); the success path needs a real `ANTHROPIC_API_KEY`.
