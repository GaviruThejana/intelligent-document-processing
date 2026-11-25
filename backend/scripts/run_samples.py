"""Generates synthetic sample documents, pushes them through the REAL API pipeline and writes
expected-vs-actual results. Usage (from backend/):  python -m scripts.run_samples"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/app") if Path("/app/app").exists() else Path(__file__).resolve().parents[2]
tmp = tempfile.mkdtemp(prefix="idp-samples-")
os.environ.update(DATABASE_URL=f"sqlite:///{tmp}/s.db", UPLOAD_DIR=f"{tmp}/up", QUEUE_MODE="inline", ANTHROPIC_API_KEY="")
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from tests import factory as F  # noqa: E402

ITEMS5 = [("Printer Paper A4 (500)", "20", "1,200.00", "24,000.00"), ("Ink Cartridge Black", "4", "3,500.00", "14,000.00"),
          ("Stapler Heavy Duty", "3", "950.00", "2,850.00"), ("Whiteboard Marker Set", "10", "420.00", "4,200.00"),
          ("File Folder (Pack of 10)", "6", "600.00", "3,600.00")]


def truth(lines_kw, items=None):
    """Ground truth derived from the generator parameters (what a perfect extractor returns)."""
    kw = dict(lines_kw)
    items = items if items is not None else [("USB-C Cable", "10", "5.00", "50.00"), ("Laptop Stand", "2", "25.50", "51.00")]
    norm = lambda s: None if s is None else s.replace("Rs.", "").replace(",", "")
    return {"document_number": kw.get("number", "INV-1001"), "document_date": kw.get("iso_date", kw.get("date", "2026-01-15")),
            "supplier_name": kw.get("supplier", "Acme Supplies Ltd"), "customer_name": kw.get("customer", "Beta Traders (Pvt) Ltd"),
            "currency": kw.get("currency", "USD"), "subtotal": norm(kw.get("subtotal", "101.00")), "discount": norm(kw.get("discount", "10.00")),
            "tax": norm(kw.get("tax", "9.10")), "total": norm(kw.get("total", "100.10")),
            "line_items": [{"description": d, "quantity": norm(q), "unit_price": norm(u), "amount": norm(a)} for d, q, u, a in items]}


def inv(**kw):
    iso = kw.pop("iso_date", None)
    items = kw.get("items")
    return F.invoice_lines(**kw), truth({**kw, **({"iso_date": iso} if iso else {})}, items)


S = []  # (filename, bytes, mime, expected_fields|None, expected_doc_type, expected_status, expected_issue_codes, note)
l, t = inv(); S.append(("01_clean_invoice.pdf", F.render_pdf(l), "application/pdf", t, "invoice", "Ready for Approval", [], "Text-layer PDF, all fields present"))
S.append(("02_invoice_image.png", F.render_image(l, "PNG"), "image/png", t, "invoice", "Ready for Approval", [], "PNG, Tesseract OCR with word confidences"))
l3, t3 = inv(number="INV-3003", date="2026-02-10", supplier="Lanka Parts Co", customer="Gamma Works", currency="EUR", subtotal="200.00", discount="20.00", tax="18.00", total="198.00",
             items=[("Bearing 6204", "8", "12.50", "100.00"), ("Hydraulic Seal Kit", "4", "25.00", "100.00")])
S.append(("03_invoice_photo.jpg", F.render_image(l3, "JPEG"), "image/jpeg", t3, "invoice", "Ready for Approval", [], "JPEG (lossy) OCR, EUR, discount + tax"))
S.append(("04_scanned_invoice.pdf", F.render_scanned_pdf(l), "application/pdf", t, "invoice", "Needs Review", ["LOW_CONFIDENCE"], "Image-only PDF: rasterise + OCR. OCR misread a decimal point (25:50); it is repaired but forced to human verification"))
l5, t5 = inv(number="INV-5005", total="150.10"); S.append(("05_incorrect_total.pdf", F.render_pdf(l5), "application/pdf", t5 | {"total": "150.10"}, "invoice", "Needs Review", ["TOTAL_MISMATCH"], "Stated total 150.10 vs calculated 100.10"))
l6, t6 = inv(number=None, date=None); S.append(("06_missing_fields.pdf", F.render_pdf(l6), "application/pdf", t6 | {"document_number": None, "document_date": None}, "invoice", "Needs Review", ["MISSING_FIELD"], "No invoice number / date: must stay null"))
S.append(("07_purchase_order.pdf", F.render_pdf(F.po_lines()), "application/pdf", truth({"number": "PO-7788", "subtotal": "101.00", "discount": "0.00", "tax": "0.00", "total": "101.00"}), "purchase_order", "Ready for Approval", [], "Purchase order, same schema"))
S.append(("08_receipt.pdf", F.render_pdf(F.receipt_lines()), "application/pdf", None, "receipt", "Needs Review", ["EXTRACTION_NOT_SUPPORTED", "MISSING_FIELD"], "Receipt: classification only (documented limitation)"))
S.append(("09_unknown_letter.pdf", F.render_pdf(F.letter_lines()), "application/pdf", None, "unknown", "Needs Review", ["UNKNOWN_DOCUMENT_TYPE"], "Non-business letter"))
lp, tp = inv(number="INV-1010")
S.append(("10_poor_scan.png", F.render_image(lp, "PNG", degrade=True), "image/png", tp, "unknown", "Needs Review", ["POOR_SCAN_QUALITY"], "Severely degraded scan (low-res, blur, skew, noise): nothing usable is read - must be flagged, never silently accepted"))
lm, tm = inv(number="INV-1011")
S.append(("15_moderate_scan.png", F.render_image(lm, "PNG", degrade="moderate"), "image/png", tm, "invoice", "Needs Review", [], "Moderately degraded scan: partially readable, any doubt must route to review"))
l11, t11 = inv(number="LK-2026-044", date="15/03/2026", iso_date="2026-03-15", supplier="Colombo Stationers (Pvt) Ltd", customer="Kandy Education Trust", currency="LKR",
               items=ITEMS5, subtotal="Rs.48,650.00", discount="Rs.0.00", tax="Rs.0.00", total="Rs.48,650.00", date_label="Date")
S.append(("11_lkr_invoice_5_items.pdf", F.render_pdf(l11), "application/pdf", t11, "invoice", "Ready for Approval", [], "LKR, 'Rs.' prefixes, thousands separators, DD/MM/YYYY date, 5 lines"))
S.append(("12_duplicate_of_01.pdf", S[0][1], "application/pdf", None, "invoice", "(duplicate)", [], "Byte-identical to #1: must return existing document, no new job"))
l13, t13 = inv(number="INV-1313", items=[("USB-C Cable", "10", "5.00", "55.00"), ("Laptop Stand", "2", "25.50", "51.00")], subtotal="106.00", discount="10.00", tax="9.60", total="105.60")
S.append(("13_line_total_mismatch.pdf", F.render_pdf(l13), "application/pdf", t13 | {"line_items": [{"description": "USB-C Cable", "quantity": "10", "unit_price": "5.00", "amount": "55.00"}, {"description": "Laptop Stand", "quantity": "2", "unit_price": "25.50", "amount": "51.00"}]}, "invoice", "Needs Review", ["LINE_TOTAL_MISMATCH"], "Line 1: 10 x 5.00 != 55.00"))
l14, t14 = inv(number="INV-1414", discount=None, tax=None, subtotal="101.00", total="101.00")
S.append(("14_no_tax_no_discount.pdf", F.render_pdf(l14), "application/pdf", t14 | {"discount": None, "tax": None}, "invoice", "Ready for Approval", [], "Optional fields absent -> null, not 0"))


S.sort(key=lambda s: s[0])


def main():
    out_s = ROOT / "samples"
    (out_s / "expected").mkdir(parents=True, exist_ok=True); (out_s / "actual").mkdir(exist_ok=True)
    rows, detail, passed, ids = [], [], 0, {}
    with TestClient(app) as c:
        for name, data, mime, exp, etype, estatus, ecodes, note in S:
            (out_s / name).write_bytes(data)
            count_before = c.get("/api/v1/documents?limit=200").json()["total"]
            r = c.post("/api/v1/documents", files={"file": (name, data, mime)})
            body = r.json()
            if body.get("duplicate"):
                duplicate_id = body.get("document", {}).get("id")
                count_after = c.get("/api/v1/documents?limit=200").json()["total"]
                prior_id = ids.get("01_clean_invoice.pdf")
                ok = estatus == "(duplicate)" and duplicate_id == prior_id and count_after == count_before
                ids[name] = duplicate_id
                rows.append((name, etype, "-", f"duplicate (HTTP {r.status_code}, existing id; count {count_before}->{count_after})", "-", "-", "PASS" if ok else "FAIL")); passed += ok
                (out_s / "actual" / f"{name}.json").write_text(json.dumps(body, indent=2)); continue
            if r.status_code != 202 or "document" not in body:
                rows.append((name, "-", estatus + " -> upload failed", f"HTTP {r.status_code}", "-", "-", "FAIL"))
                detail.append(f"### {name}\nUpload failed: HTTP {r.status_code}: {body}\n")
                continue
            ids[name] = body["document"]["id"]
            d = c.get(f"/api/v1/documents/{body['document']['id']}").json()
            (out_s / "expected" / f"{name}.json").write_text(json.dumps({"doc_type": etype, "status": estatus, "issue_codes_include": ecodes, "fields": exp, "note": note}, indent=2))
            (out_s / "actual" / f"{name}.json").write_text(json.dumps({k: d[k] for k in ("doc_type", "status", "ocr_method", "ocr_mean_confidence", "extractor", "data", "confidence", "issues")}, indent=2))
            acts = {i["code"] for i in d["issues"]}
            fields_ok = fields_n = 0; wrong = []
            for k, v in (exp or {}).items():
                fields_n += 1
                if (d.get("data") or {}).get(k) == v: fields_ok += 1
                else: wrong.append(f"`{k}`: expected `{json.dumps(v)[:70]}` got `{json.dumps((d.get('data') or {}).get(k))[:70]}`")
            # Image/scanned-PDF cases cannot be counted as successful extraction expectations
            # when OCR itself is unavailable, even if their fallback status happens to match.
            ocr_ready = "OCR_UNAVAILABLE" not in acts
            ok = ocr_ready and (d["doc_type"] == etype or (name[:2] in ("10", "15") and d["doc_type"] == "unknown")) and d["status"] == estatus and set(ecodes) <= acts and (fields_ok == fields_n or name[:2] in ("10", "15"))
            passed += ok
            acc = f"{fields_ok}/{fields_n}" if exp else "n/a"
            conf_label = (f"{d['ocr_mean_confidence']}%" if d["ocr_mean_confidence"] is not None else
                          "n/a (PDF text layer)" if d["ocr_method"] == "pdf_text" else
                          "unavailable (OCR failed)" if "OCR_UNAVAILABLE" in acts else
                          "unavailable (no OCR confidence)")
            rows.append((name, d["doc_type"], estatus + " -> **" + d["status"] + "**", ", ".join(sorted(acts)) or "none", acc, conf_label, "PASS" if ok else "FAIL"))
            if wrong or not ok:
                detail.append(f"### {name}\n{note}\n" + "\n".join(f"- {w}" for w in wrong) + f"\n- issues: {sorted(acts)}\n")
    workflow = []
    with TestClient(app) as c:
        # Exercise the human-review path and approved-only export gate using real generated samples.
        for name, correction in (
            ("05_incorrect_total.pdf", {"total": "100.10"}),
            ("06_missing_fields.pdf", {"document_number": "INV-6006", "document_date": "2026-01-15"}),
        ):
            doc_id = ids.get(name)
            if not doc_id:
                workflow.append((f"correct and approve {name}", False, "sample upload produced no document id"))
                continue
            before = c.get(f"/api/v1/documents/{doc_id}").json()
            blocked = c.get(f"/api/v1/documents/{doc_id}/export?format=json").status_code == 409
            edited = c.patch(f"/api/v1/documents/{doc_id}", json={"fields": correction, "actor": "sample-reviewer"})
            current = edited.json() if edited.status_code == 200 else {}
            approved = c.post(f"/api/v1/documents/{doc_id}/approve", json={"actor": "sample-reviewer"})
            final = approved.json() if approved.status_code == 200 else {}
            audit = c.get(f"/api/v1/documents/{doc_id}/audit").json()
            ok = (blocked and edited.status_code == 200 and final.get("status") == "Approved"
                  and current.get("extracted") == before.get("extracted")
                  and any(e["event_type"] == "field_corrected" for e in audit))
            workflow.append((f"correct and approve {name}", ok,
                             f"pre-export blocked={blocked}; patch HTTP {edited.status_code}; final={final.get('status')}; original preserved={current.get('extracted') == before.get('extracted')}; correction audited={any(e['event_type'] == 'field_corrected' for e in audit)}"))

        clean_id = ids.get("01_clean_invoice.pdf")
        if clean_id:
            doc = c.get(f"/api/v1/documents/{clean_id}").json()
            approval = c.post(f"/api/v1/documents/{clean_id}/approve", json={"actor": "sample-reviewer"})
            j = c.get(f"/api/v1/documents/{clean_id}/export?format=json")
            csv = c.get(f"/api/v1/documents/{clean_id}/export?format=csv")
            bulk_json = c.get("/api/v1/export?format=json")
            bulk_csv = c.get("/api/v1/export?format=csv")
            ok = (doc.get("status") == "Ready for Approval" and approval.status_code == 200
                  and j.status_code == 200 and j.json().get("fields", {}).get("document_number") == "INV-1001"
                  and csv.status_code == 200 and "USB-C Cable" in csv.text
                  and bulk_json.status_code == 200 and any(x.get("document_id") == clean_id for x in bulk_json.json())
                  and bulk_csv.status_code == 200 and clean_id in bulk_csv.text)
            workflow.append(("approved clean invoice JSON/CSV export", ok,
                             f"approval HTTP {approval.status_code}; single JSON/CSV HTTP {j.status_code}/{csv.status_code}; bulk JSON/CSV HTTP {bulk_json.status_code}/{bulk_csv.status_code}"))
        else:
            workflow.append(("approved clean invoice JSON/CSV export", False, "clean sample upload produced no document id"))

    stamp = datetime.now(ZoneInfo("Asia/Colombo")).isoformat(timespec="seconds")
    tesseract = shutil.which("tesseract")
    try:
        import PIL
        pillow_version = PIL.__version__
    except Exception:
        pillow_version = "unavailable"
    workflow_passed = sum(bool(item[1]) for item in workflow)
    md = ["# Sample extraction results (expected vs actual)", "",
          f"Fresh run: {stamp} (Asia/Colombo). Python {sys.version.split()[0]}, Pillow {pillow_version}, Tesseract executable: {tesseract or 'not found'}.",
          "Generated by `python -m scripts.run_samples` through the FastAPI + SQLite inline pipeline. OCR-backed sample results depend on the reported Tesseract availability.",
          "Expected values come from the generator parameters (ground truth); actual values are what the system extracted. Raw JSON for each: `samples/expected/` and `samples/actual/`.", "",
          f"**{passed}/{len(S)} sample ingestion/extraction expectations passed.**", "",
          "| # | Sample | Classified | Status (expected -> actual) | Validation issues raised | Field accuracy | Mean OCR conf. | Result |", "|---|---|---|---|---|---|---|---|"]
    for i, (n, t_, st, codes, acc, conf, res) in enumerate(rows, 1):
        md.append(f"| {i} | {n} | {t_} | {st} | {codes} | {acc} | {conf} | {res} |")
    md += ["", "## Review, approval and exports", "",
           f"Workflow checks passed: {workflow_passed}/{len(workflow)}.", "",
           "| Workflow check | Result | Details |", "|---|---|---|"]
    for label, ok, notes in workflow:
        md.append(f"| {label} | {'PASS' if ok else 'FAIL'} | {notes} |")
    md += ["", "## Runtime caveat", ""]
    if not tesseract:
        md.append("Tesseract was not installed on this host. The five OCR-dependent samples (02, 03, 04, 10, 15) therefore produced `EXTRACTION_UNAVAILABLE`/`unknown` and did not validate image/scanned-PDF OCR accuracy. This is an environment-blocked OCR run, not a passing OCR result. Install Tesseract with English data and rerun this script to measure those five samples.")
    else:
        md.append(f"Tesseract executable resolved to `{tesseract}`; image and scanned-PDF samples exercised OCR.")
    md += ["", "## Deviations / notes", ""] + (detail or ["None."])
    report = "\n".join(md) + "\n"
    (ROOT / "docs" / "SAMPLE_RESULTS.md").write_text(report)
    (ROOT / "SAMPLE_RESULTS.md").write_text(report)
    print(report); print(f"\nSamples: {passed}/{len(S)}; workflow: {workflow_passed}/{len(workflow)} passed")
    sys.exit(0 if passed == len(S) and workflow_passed == len(workflow) else 1)


main()
