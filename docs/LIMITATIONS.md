# Known limitations (documented as required by the brief)

**Incomplete by design (brief allows it)**
1. **Receipts**: classified only. They always land in `Needs Review` (`EXTRACTION_NOT_SUPPORTED`) so a human can type the fields in the review screen. Invoices and purchase orders share one extraction schema and are fully supported.

**Extraction**
2. The rule extractor assumes the common layout *Description | Qty | Unit price | Amount* (right-to-left numeric columns) and **labelled** headers (`Invoice No:`, `From:`, `Bill To:`...). Unlabelled supplier names (e.g. a logo/letterhead) are left `null` rather than guessed. Multi-line rows, merged cells and other column orders are not handled; unparsed rows are reported as `UNPARSED_LINE`.
3. Numeric dates (`03/04/2026`) are read **day-first**; `1.234,56` (European decimals) is not supported. `$` maps to USD when no ISO code is present.
4. The optional LLM extractor is text-only (works on OCR/PDF text, not page images) and gives no field confidence (reported as "unavailable"). Its success path was not exercised without an API key; only the failure/fallback path is tested.
5. OCR quality depends on Tesseract (English model). Badly degraded scans may yield text that is wrong but plausible; the system mitigates this with confidence thresholds, arithmetic cross-checks and mandatory review, but cannot guarantee detection of every misread digit (see `samples/` #4, #10, #15).
6. Multi-currency documents, tax-inclusive pricing and per-line tax are not modelled; PDFs are capped at 20 pages and now carry a `PDF_PAGE_LIMIT` warning when truncated.

**Platform**
7. **No authentication/authorisation**: reviewer names are self-declared. Production needs SSO/JWT and per-tenant isolation, plus virus scanning of uploads.
8. Schema is created with `create_all`; production should use Alembic migrations. Uploads are stored on a local volume (swap `storage.py` for S3/GCS).
9. `/stats` computes average processing time in Python over all processed rows (fine at assessment scale; use a SQL aggregate/materialised view at volume).
10. Dashboard uses 3-second polling rather than WebSockets/SSE.
11. Not verified in the build sandbox: `docker compose up` (no Docker there) and browser click-through of the UI. See `docs/TEST_REPORT.md`.
