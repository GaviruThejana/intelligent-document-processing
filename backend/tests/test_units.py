"""Unit tests: validation arithmetic, parsing, classification."""
from decimal import Decimal

from app.classification import classify
from app.extraction import last_amount, parse_date, rules_extract, to_number_str
from app.models import DocType
from app.ocr import OcrLine
from app.validation import validate
from tests import factory


def L(lines, conf=None):
    return [OcrLine(t, conf) for t in lines if t.strip()]


def good():
    return {"document_number": "1", "document_date": "2026-01-15", "supplier_name": "A", "customer_name": "B",
            "currency": "USD", "subtotal": "101.00", "discount": "10.00", "tax": "9.10", "total": "100.10",
            "line_items": [{"description": "x", "quantity": "10", "unit_price": "5.00", "amount": "50.00"},
                           {"description": "y", "quantity": "2", "unit_price": "25.50", "amount": "51.00"}]}


def codes(d, **kw):
    return {i.code for i in validate("invoice", d, kw.get("conf", {}), kw.get("ocr"))}


def test_valid_invoice_has_no_issues():
    assert validate("invoice", good(), {}, None) == []


def test_total_mismatch_detected():
    d = good(); d["total"] = "110.10"
    issues = [i for i in validate("invoice", d, {}, None) if i.code == "TOTAL_MISMATCH"]
    assert issues and "110.10" in issues[0].message and "100.10" in issues[0].message


def test_decimal_arithmetic_not_float():
    # float: 0.1 + 0.2 != 0.3 ; Decimal must treat it as exact
    d = {"document_number": "1", "document_date": "2026-01-01", "supplier_name": "A", "customer_name": "B", "currency": "USD",
         "subtotal": "0.30", "total": "0.30",
         "line_items": [{"description": "a", "quantity": "1", "unit_price": "0.10", "amount": "0.10"},
                        {"description": "b", "quantity": "1", "unit_price": "0.20", "amount": "0.20"}]}
    assert validate("invoice", d, {}, None) == []
    assert 0.1 + 0.2 != 0.3 and Decimal("0.1") + Decimal("0.2") == Decimal("0.3")


def test_line_and_subtotal_mismatch():
    d = good(); d["line_items"][0]["amount"] = "55.00"
    assert {"LINE_TOTAL_MISMATCH", "SUBTOTAL_MISMATCH"} <= codes(d)


def test_missing_required_and_invalid_values():
    d = good(); d["document_number"] = None; d["line_items"] = None
    d["document_date"] = "2026-02-31"; d["currency"] = "usd"; d["tax"] = "abc"; d["discount"] = "-5"
    c = codes(d)
    assert {"MISSING_FIELD", "INVALID_VALUE"} <= c
    fields = {(i.code, i.field) for i in validate("invoice", d, {}, None)}
    assert ("MISSING_FIELD", "document_number") in fields and ("MISSING_FIELD", "line_items") in fields
    assert ("INVALID_VALUE", "document_date") in fields and ("INVALID_VALUE", "tax") in fields
    assert ("INVALID_VALUE", "currency") in fields and ("INVALID_VALUE", "discount") in fields


def test_low_confidence_flagged():
    assert {"POOR_SCAN_QUALITY", "LOW_CONFIDENCE"} <= codes(good(), conf={"total": 40.0}, ocr=45.0)
    assert "LOW_CONFIDENCE" not in codes(good(), conf={"total": None})  # unavailable != low


def test_unknown_type_flagged():
    assert [i.code for i in validate("unknown", {}, {}, None)] == ["UNKNOWN_DOCUMENT_TYPE"]


def test_parse_helpers():
    assert to_number_str("Rs.1,250.50") == "1250.50" and to_number_str("(5.00)") == "-5.00"
    assert last_amount("Tax (10%): 9.10") == "9.10"
    assert parse_date("15/01/2026") == "2026-01-15" and parse_date("15 Jan 2026") == "2026-01-15"
    assert parse_date("January 15, 2026") == "2026-01-15" and parse_date("31/02/2026") == "31/02/2026"
    assert parse_date("no date here") is None


def test_rules_extract_clean_invoice():
    r = rules_extract(L(factory.invoice_lines()), DocType.INVOICE)
    f = r.fields
    assert (f["document_number"], f["document_date"], f["supplier_name"]) == ("INV-1001", "2026-01-15", "Acme Supplies Ltd")
    assert (f["customer_name"], f["currency"]) == ("Beta Traders (Pvt) Ltd", "USD")
    assert (f["subtotal"], f["discount"], f["tax"], f["total"]) == ("101.00", "10.00", "9.10", "100.10")
    assert f["line_items"][1] == {"description": "Laptop Stand", "quantity": "2", "unit_price": "25.50", "amount": "51.00"}
    assert all(v is None for v in r.confidence.values())  # no OCR confidence on text input


def test_rules_never_invent_missing_values():
    r = rules_extract(L(factory.invoice_lines(number=None, date=None, discount=None, tax=None)), DocType.INVOICE)
    assert r.fields["document_number"] is None and r.fields["document_date"] is None
    assert r.fields["discount"] is None and r.fields["tax"] is None


def test_due_date_is_not_document_date():
    lines = factory.invoice_lines(date=None) + ["Due Date: 2026-03-01"]
    assert rules_extract(L(lines), DocType.INVOICE).fields["document_date"] is None


def test_classification():
    assert classify(factory.invoice_lines())[0] == DocType.INVOICE
    assert classify(factory.po_lines())[0] == DocType.PURCHASE_ORDER
    assert classify(factory.receipt_lines())[0] == DocType.RECEIPT
    assert classify(factory.letter_lines())[0] == DocType.UNKNOWN


def test_ocr_decimal_repair_forces_verification():
    lines = [OcrLine(t, 94.0) for t in ["Description Qty Unit Price Amount", "Laptop Stand 2 25:50 51.00", "Subtotal: 51.00"]]
    r = rules_extract(lines, DocType.INVOICE)
    assert r.fields["line_items"][0]["unit_price"] == "25.50"
    assert r.confidence["line_items.0.unit_price"] <= 50.0          # capped -> LOW_CONFIDENCE -> human check
    assert any(i.code == "LOW_CONFIDENCE" for i in validate("invoice", r.fields, r.confidence, 94.0))


def test_unparseable_item_row_is_reported_not_dropped():
    lines = L(["Description Qty Unit Price Amount", "USB-C Cable 10 5.00 50.00", "Mystery thing ?? 7", "Subtotal: 50.00"])
    r = rules_extract(lines, DocType.INVOICE)
    assert len(r.fields["line_items"]) == 1 and r.unparsed == ["Mystery thing ?? 7"]


def test_poor_scan_flag_raised_even_if_unclassifiable():
    codes = {i.code for i in validate("unknown", {}, {}, 23.0)}
    assert {"POOR_SCAN_QUALITY", "UNKNOWN_DOCUMENT_TYPE"} <= codes
