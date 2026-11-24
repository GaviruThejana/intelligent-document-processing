import csv
import io
from decimal import Decimal, InvalidOperation

from .models import Document

COLUMNS = ["document_id", "doc_type", "document_number", "document_date", "supplier_name", "customer_name",
           "currency", "subtotal", "tax", "discount", "total", "line_no", "description", "quantity",
           "unit_price", "amount", "approved_by", "approved_at"]


def to_json(doc: Document) -> dict:
    return {
        "document_id": doc.id, "filename": doc.filename, "sha256": doc.sha256, "doc_type": doc.doc_type,
        "fields": doc.data, "original_extraction": doc.extracted, "field_confidence": doc.confidence,
        "acknowledged_issues": [{"code": i.code, "field": i.field, "message": i.message,
                                 "acknowledged_by": i.acknowledged_by, "note": i.acknowledged_note}
                                for i in doc.issues if i.acknowledged],
        "approved_by": doc.approved_by, "approved_at": doc.approved_at.isoformat() if doc.approved_at else None,
    }


def _safe(v):
    """Neutralise CSV/Excel formula injection for text cells (numbers such as -5.00 are left alone)."""
    if v is None:
        return ""
    v = str(v)
    if v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        try:
            Decimal(v)
        except InvalidOperation:
            return "'" + v
    return v


def to_csv(docs: list[Document]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    for d in docs:
        data = d.data or {}
        base = {"document_id": d.id, "doc_type": d.doc_type, "approved_by": d.approved_by,
                "approved_at": d.approved_at.isoformat() if d.approved_at else ""}
        for k in ("document_number", "document_date", "supplier_name", "customer_name", "currency",
                  "subtotal", "tax", "discount", "total"):
            base[k] = data.get(k)
        items = data.get("line_items") or [{}]
        for n, it in enumerate(items, 1):
            row = {**base, "line_no": n if it else "", **{k: it.get(k) for k in ("description", "quantity", "unit_price", "amount")}}
            w.writerow({k: _safe(row.get(k)) for k in COLUMNS})
    return buf.getvalue()
