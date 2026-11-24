# API reference
Interactive Swagger UI: **http://localhost:8000/docs** (ReDoc: `/redoc`). Machine-readable spec: `docs/openapi.json`. All routes are under `/api/v1`.

| Method & path | Purpose | Notable responses |
|---|---|---|
| `POST /documents` (multipart `file`) | Upload PDF/JPG/PNG | **202** accepted; **200** `{duplicate:true}` for an identical file (no new job); 400 empty; 413 too large; 415 bad type/content |
| `GET /documents?status=&doc_type=&q=&limit=&offset=` | List/filter | `{total, items[]}` |
| `GET /documents/{id}` | Full detail: status, `extracted` (original), `data` (current), per-field `confidence`, `issues`, OCR text | 404 |
| `GET /documents/{id}/file` | Download original | 404 if the stored original is missing |
| `PATCH /documents/{id}` `{fields, doc_type?, actor}` | Correct fields; revalidates; writes `field_corrected` audit events | 409 if not Needs Review / Ready |
| `POST /documents/{id}/retry` | Controlled retry of Failed / Uploaded / stalled documents (same record) | **202**; 409 otherwise |
| `POST /documents/{id}/approve` `{actor, acknowledged_issue_ids[], note}` | Approve | **409** lists unresolved issues; 422 if acknowledging without a note |
| `GET /documents/{id}/audit` | Full audit trail | |
| `GET /documents/{id}/export?format=json\|csv` | Export one **approved** document | 409 until Approved |
| `GET /export?format=json\|csv` | Export all approved documents; each document gets an export audit event | |
| `GET /stats` | Dashboard statistics: by status/type, duplicates, avg processing time, issue codes, recent failures | |
| `GET /health` (no prefix) | Liveness + DB check | |

Example:
```bash
curl -F "file=@samples/01_clean_invoice.pdf" localhost:8000/api/v1/documents
curl localhost:8000/api/v1/documents/<id>
curl -X POST localhost:8000/api/v1/documents/<id>/approve -H 'content-type: application/json' -d '{"actor":"alice"}'
curl "localhost:8000/api/v1/documents/<id>/export?format=csv"
```
