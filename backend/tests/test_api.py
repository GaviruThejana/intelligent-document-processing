"""End-to-end API tests (inline queue, real PDFs/PNGs, real Tesseract where OCR is needed)."""
import shutil
import subprocess

import pytest

from app import extraction, ocr, pipeline
from app.db import SessionLocal
from app.models import DocType, Document
from tests import factory

U = "/api/v1/documents"


@pytest.fixture
def tesseract_available():
    binary = shutil.which("tesseract")
    if not binary:
        pytest.skip("Tesseract executable is required for OCR integration tests")
    langs = subprocess.run([binary, "--list-langs"], capture_output=True, text=True, check=False)
    if langs.returncode != 0 or "eng" not in langs.stdout.splitlines():
        pytest.skip("Tesseract English language data is required for OCR integration tests")


@pytest.fixture
def scanned_pdf_tools_available(tesseract_available):
    if not shutil.which("pdfinfo") or not shutil.which("pdftoppm"):
        pytest.skip("Poppler pdfinfo and pdftoppm are required for scanned-PDF integration tests")


def upload_ok(api, lines=None, **kw):
    r = api.upload(factory.render_pdf(lines or factory.invoice_lines()), **kw)
    assert r.status_code == 202, r.text
    return r.json()["document"]["id"]


# ---------------------------------------------------------------- upload validation
def test_rejects_unsupported_type(api):
    r = api.upload(b"hello world", "notes.txt", "text/plain")
    assert r.status_code == 415


def test_rejects_wrong_content_even_with_pdf_extension(api):
    assert api.upload(b"MZ\x90\x00 not a pdf", "evil.pdf").status_code == 415


def test_rejects_extension_content_mismatch(api):
    assert api.upload(factory.render_pdf(["x"]), "x.png", "image/png").status_code == 415


def test_rejects_empty_and_oversize(api):
    assert api.upload(b"", "a.pdf").status_code == 400
    assert api.upload(b"%PDF-" + b"0" * (2 * 1024 * 1024), "big.pdf").status_code == 413  # limit is 1 MB in tests


# ---------------------------------------------------------------- happy path
def test_clean_invoice_full_workflow(api, client):
    doc_id = upload_ok(api)
    d = api.doc(doc_id)
    assert d["status"] == "Ready for Approval" and d["doc_type"] == "invoice" and d["issues"] == []
    assert d["data"]["total"] == "100.10" and d["ocr_method"] == "pdf_text"
    assert client.get(f"{U}/{doc_id}/export").status_code == 409          # export blocked before approval
    r = client.post(f"{U}/{doc_id}/approve", json={"actor": "alice"})
    assert r.status_code == 200 and r.json()["status"] == "Approved"
    j = client.get(f"{U}/{doc_id}/export?format=json").json()
    assert j["fields"]["document_number"] == "INV-1001" and j["approved_by"] == "alice"
    csv_text = client.get(f"{U}/{doc_id}/export?format=csv").text.splitlines()
    assert len(csv_text) == 3 and "USB-C Cable" in csv_text[1] and csv_text[0].startswith("document_id,")
    types = [e["event_type"] for e in api.audit(doc_id)]
    for t in ("uploaded", "queued", "processing_started", "ocr_completed", "classified", "extraction_completed",
              "validation_completed", "status_changed", "exported"):
        assert t in types


def test_image_ocr_invoice(api, tesseract_available):
    r = api.upload(factory.render_image(factory.invoice_lines(), "PNG"), "scan.png", "image/png")
    d = api.doc(r.json()["document"]["id"])
    assert d["ocr_method"] == "tesseract" and d["doc_type"] == "invoice"
    assert d["data"]["document_number"] == "INV-1001" and d["data"]["total"] == "100.10"
    assert d["confidence"]["total"] is not None and d["ocr_mean_confidence"] > 80   # field-level confidence present


def test_scanned_pdf_rasterised(api, scanned_pdf_tools_available):
    r = api.upload(factory.render_scanned_pdf(factory.invoice_lines()), "scan.pdf")
    d = api.doc(r.json()["document"]["id"])
    assert d["ocr_method"] == "tesseract" and d["data"]["total"] == "100.10"


# ---------------------------------------------------------------- business scenarios
def test_incorrect_total_flagged_and_blocks_approval_until_acknowledged(api, client):
    doc_id = upload_ok(api, factory.invoice_lines(total="150.10"))
    d = api.doc(doc_id)
    assert d["status"] == "Needs Review" and [i["code"] for i in d["issues"]] == ["TOTAL_MISMATCH"]
    r = client.post(f"{U}/{doc_id}/approve", json={})
    assert r.status_code == 409 and r.json()["detail"]["unresolved"][0]["code"] == "TOTAL_MISMATCH"
    ids = [i["id"] for i in d["issues"]]
    assert client.post(f"{U}/{doc_id}/approve", json={"acknowledged_issue_ids": ids}).status_code == 422  # note required
    ok = client.post(f"{U}/{doc_id}/approve", json={"acknowledged_issue_ids": ids, "note": "Supplier confirmed by phone"})
    assert ok.status_code == 200 and ok.json()["issues"][0]["acknowledged_by"] == "reviewer"


def test_missing_fields_need_review_and_correction_is_audited(api, client):
    doc_id = upload_ok(api, factory.invoice_lines(number=None, date=None))
    d = api.doc(doc_id)
    assert d["status"] == "Needs Review" and d["data"]["document_number"] is None
    miss = {i["field"] for i in d["issues"] if i["code"] == "MISSING_FIELD"}
    assert miss == {"document_number", "document_date"}
    r = client.patch(f"{U}/{doc_id}", json={"fields": {"document_number": "INV-2002", "document_date": "2026-01-20"}, "actor": "bob"})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "Ready for Approval" and d["issues"] == []
    assert d["extracted"]["document_number"] is None          # original preserved
    assert d["data"]["document_number"] == "INV-2002"
    ev = [e for e in api.audit(doc_id) if e["event_type"] == "field_corrected"]
    assert {(e["field"], e["old_value"], e["new_value"], e["actor"]) for e in ev} == {
        ("document_number", None, "INV-2002", "bob"), ("document_date", None, "2026-01-20", "bob")}


def test_correcting_a_line_item_revalidates(api, client):
    doc_id = upload_ok(api, factory.invoice_lines(total="100.10", items=[("USB-C Cable", "10", "5.00", "55.00"), ("Laptop Stand", "2", "25.50", "51.00")]))
    d = api.doc(doc_id)
    assert "LINE_TOTAL_MISMATCH" in {i["code"] for i in d["issues"]}
    items = d["data"]["line_items"]; items[0]["amount"] = "50.00"
    r = client.patch(f"{U}/{doc_id}", json={"fields": {"line_items": items}}).json()
    assert r["status"] == "Ready for Approval"
    assert any(e["field"] == "line_items.0.amount" and e["old_value"] == "55.00" for e in api.audit(doc_id))


def test_duplicate_upload_creates_no_second_job(api, client):
    data = factory.render_pdf(factory.invoice_lines())
    first = api.upload(data, "a.pdf")
    second = api.upload(data, "renamed.pdf")
    assert first.status_code == 202 and second.status_code == 200 and second.json()["duplicate"] is True
    assert second.json()["document"]["id"] == first.json()["document"]["id"]
    assert client.get(U).json()["total"] == 1
    types = [e["event_type"] for e in api.audit(first.json()["document"]["id"])]
    assert types.count("queued") == 1 and types.count("processing_started") == 1 and "duplicate_upload_detected" in types
    assert client.get("/api/v1/stats").json()["duplicates_detected"] == 1


def test_unknown_and_receipt_go_to_manual_review(api):
    d = api.doc(upload_ok(api, factory.letter_lines()))
    assert d["status"] == "Needs Review" and d["doc_type"] == "unknown" and d["issues"][0]["code"] == "UNKNOWN_DOCUMENT_TYPE"
    d = api.doc(upload_ok(api, factory.receipt_lines()))
    assert d["doc_type"] == "receipt" and d["status"] == "Needs Review"
    assert "EXTRACTION_NOT_SUPPORTED" in {i["code"] for i in d["issues"]}


def test_unknown_document_type_can_be_corrected_and_audited(api, client):
    doc_id = upload_ok(api, factory.letter_lines())
    r = client.patch(f"{U}/{doc_id}", json={"doc_type": "invoice", "fields": {"document_number": "INV-3001"}})
    assert r.status_code == 200 and r.json()["doc_type"] == "invoice"
    events = api.audit(doc_id)
    assert any(e["event_type"] == "doc_type_corrected" and e["old_value"] == "unknown" and e["new_value"] == "invoice" for e in events)


def test_pdf_page_limit_routes_to_review(api, monkeypatch):
    from app.ocr import OcrLine, OcrResult
    lines = [OcrLine(line, None) for line in factory.invoice_lines()]
    monkeypatch.setattr(pipeline, "read_document", lambda *a: OcrResult(lines, "pdf_text", ["PDF_PAGE_LIMIT"]))
    d = api.doc(upload_ok(api))
    assert d["status"] == "Needs Review"
    assert "PDF_PAGE_LIMIT" in {i["code"] for i in d["issues"]}


def test_purchase_order_extracted(api):
    d = api.doc(upload_ok(api, factory.po_lines()))
    assert d["doc_type"] == "purchase_order" and d["data"]["document_number"] == "PO-7788" and d["status"] == "Ready for Approval"


def test_poor_quality_scan_is_flagged(api, tesseract_available):
    r = api.upload(factory.render_image(factory.invoice_lines(), "PNG", degrade=True), "bad.png", "image/png")
    d = api.doc(r.json()["document"]["id"])
    assert d["status"] == "Needs Review" and d["issues"], "uncertain/incomplete extraction must never auto-pass"


# ---------------------------------------------------------------- failure handling
def test_extraction_service_unavailable_falls_back(api, monkeypatch):
    monkeypatch.setattr(extraction.get_settings(), "anthropic_api_key", "sk-test")
    monkeypatch.setattr(extraction.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(extraction.httpx.ConnectError("down")))
    doc_id = upload_ok(api)
    d = api.doc(doc_id)
    assert d["extractor"] == "rules" and d["status"] == "Ready for Approval"
    ev = [e for e in api.audit(doc_id) if e["event_type"] == "extractor_failed"]
    assert ev and ev[0]["details"]["extractor"] == "llm"


def test_llm_ungrounded_values_are_nulled_and_block_approval(api, client, monkeypatch):
    from app.extraction import Extraction, rules_extract
    original = rules_extract([ocr.OcrLine(x, None) for x in factory.invoice_lines()], DocType.INVOICE)
    fabricated = dict(original.fields)
    fabricated["total"] = "999.99"
    fabricated["supplier_name"] = "Invented Holdings"
    monkeypatch.setattr(pipeline, "extract_with_fallback",
                        lambda *args: (Extraction(fabricated, {}, "llm"), []))
    doc_id = upload_ok(api)
    d = api.doc(doc_id)
    assert d["extractor"] == "llm" and d["data"]["total"] is None
    assert d["data"]["supplier_name"] is None
    assert {i["code"] for i in d["issues"]} >= {"UNGROUNDED_VALUE", "MISSING_FIELD"}
    assert d["status"] == "Needs Review"
    assert client.post(f"{U}/{doc_id}/approve", json={}).status_code == 409
    event = [e for e in api.audit(doc_id) if e["event_type"] == "llm_grounding_completed"][-1]
    assert set(event["details"]["rejected_fields"]) == {"total", "supplier_name"}


def test_all_extractors_down_means_manual_review(api, monkeypatch):
    monkeypatch.setattr(pipeline, "extract_with_fallback", lambda *a: (None, [{"extractor": "rules", "error": "boom"}]))
    d = api.doc(upload_ok(api))
    assert d["status"] == "Needs Review" and "EXTRACTION_UNAVAILABLE" in {i["code"] for i in d["issues"]}


def test_ocr_unavailable_means_manual_review(api, monkeypatch):
    def boom(*a): raise ocr.OcrUnavailable("tesseract missing")
    monkeypatch.setattr(pipeline, "read_document", boom)
    d = api.doc(upload_ok(api))
    assert d["status"] == "Needs Review" and {"EXTRACTION_UNAVAILABLE", "OCR_UNAVAILABLE"} <= {i["code"] for i in d["issues"]}


def test_unexpected_failure_then_controlled_retry_without_duplicates(api, client, monkeypatch):
    real = pipeline.read_document
    monkeypatch.setattr(pipeline, "read_document", lambda *a: (_ for _ in ()).throw(RuntimeError("disk exploded")))
    doc_id = upload_ok(api)
    d = api.doc(doc_id)
    assert d["status"] == "Failed" and "disk exploded" in d["error_message"]
    assert any(e["event_type"] == "processing_failed" for e in api.audit(doc_id))
    assert client.post(f"{U}/{doc_id}/approve", json={}).status_code == 409
    monkeypatch.setattr(pipeline, "read_document", real)
    r = client.post(f"{U}/{doc_id}/retry")
    assert r.status_code == 202
    d = api.doc(doc_id)
    assert d["status"] == "Ready for Approval" and d["retry_count"] == 1 and d["error_message"] is None
    assert client.get(U).json()["total"] == 1                                  # same record, no duplicate
    assert client.post(f"{U}/{doc_id}/retry").status_code == 409              # only Failed docs are retryable


def test_corrupt_pdf_fails_cleanly(api):
    r = api.upload(b"%PDF-1.4\nthis is not really a pdf", "broken.pdf")
    assert api.doc(r.json()["document"]["id"])["status"] == "Failed"


def test_redelivered_task_is_a_noop(api):
    doc_id = upload_ok(api)
    before = len(api.audit(doc_id))
    with SessionLocal() as db:
        pipeline.process(db, doc_id)       # simulate broker re-delivery after completion
    assert len(api.audit(doc_id)) == before


def test_broker_outage_keeps_document_retryable(api, client, monkeypatch):
    from app import jobs
    monkeypatch.setattr(jobs, "_dispatch", lambda _id: (_ for _ in ()).throw(ConnectionError("redis down")))
    r = api.upload(factory.render_pdf(factory.invoice_lines()))
    doc_id = r.json()["document"]["id"]
    assert api.doc(doc_id)["status"] == "Uploaded"
    monkeypatch.undo()
    assert client.post(f"{U}/{doc_id}/retry").status_code == 202
    assert api.doc(doc_id)["status"] == "Ready for Approval"


# ---------------------------------------------------------------- misc
def test_edit_and_approve_state_guards(api, client):
    doc_id = upload_ok(api)
    client.post(f"{U}/{doc_id}/approve", json={})
    assert client.patch(f"{U}/{doc_id}", json={"fields": {"total": "1"}}).status_code == 409
    assert client.post(f"{U}/{doc_id}/approve", json={}).status_code == 409
    assert client.patch(f"{U}/nope", json={}).status_code == 404
    assert client.post(f"{U}/{doc_id}/approve", json={"actor": " "}).status_code == 422
    assert client.post(f"{U}/{doc_id}/approve", json={"actor": "x" * 101}).status_code == 422


def test_bulk_export_is_audited(api, client):
    doc_id = upload_ok(api)
    client.post(f"{U}/{doc_id}/approve", json={})
    assert client.get("/api/v1/export?format=json").status_code == 200
    event = [e for e in api.audit(doc_id) if e["event_type"] == "exported"][-1]
    assert event["details"] == {"format": "json", "scope": "all"}


def test_csv_formula_injection_neutralised(api, client):
    doc_id = upload_ok(api, factory.invoice_lines(customer="=HYPERLINK(1)"))
    client.post(f"{U}/{doc_id}/approve", json={})
    assert "'=HYPERLINK" in client.get(f"{U}/{doc_id}/export?format=csv").text


def test_stats_and_listing(api, client):
    upload_ok(api); upload_ok(api, factory.invoice_lines(total="1.00")); upload_ok(api, factory.letter_lines())
    s = client.get("/api/v1/stats").json()
    assert s["total_documents"] == 3 and s["by_status"]["Ready for Approval"] == 1 and s["by_status"]["Needs Review"] == 2
    assert s["by_type"]["invoice"] == 2 and s["issues_by_code"]["TOTAL_MISMATCH"] == 1 and s["avg_processing_seconds"] is not None
    assert client.get(U, params={"status": "Needs Review"}).json()["total"] == 2
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").status_code == 200


def test_stalled_job_can_be_recovered(api, client, monkeypatch):
    from datetime import timedelta
    from app import jobs
    from app.models import Status
    monkeypatch.setattr(jobs, "_dispatch", lambda _id: None)            # task "lost": nothing ever processes it
    doc_id = api.upload(factory.render_pdf(factory.invoice_lines())).json()["document"]["id"]
    assert api.doc(doc_id)["status"] == "Queued"
    assert client.post(f"{U}/{doc_id}/retry").status_code == 409        # fresh job: not retryable yet
    with SessionLocal() as db:                                           # age it past the stale threshold
        d = db.get(Document, doc_id); d.updated_at = jobs.now() - timedelta(hours=1); db.commit()
    monkeypatch.undo()
    assert client.post(f"{U}/{doc_id}/retry").status_code == 202
    assert api.doc(doc_id)["status"] == "Ready for Approval" and client.get(U).json()["total"] == 1
