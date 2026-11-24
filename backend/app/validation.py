"""Business validation. ALL money arithmetic uses decimal.Decimal - never float."""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .config import get_settings
from .models import DocType

REQUIRED = {
    DocType.INVOICE: ["document_number", "document_date", "supplier_name", "customer_name", "currency", "total", "line_items"],
    DocType.PURCHASE_ORDER: ["document_number", "document_date", "supplier_name", "customer_name", "currency", "total", "line_items"],
    DocType.RECEIPT: ["document_date", "supplier_name", "currency", "total"],
}
MONEY_FIELDS = ["subtotal", "tax", "discount", "total"]


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # error | warning
    field: str | None
    message: str

    @property
    def key(self) -> tuple:
        return (self.code, self.field, self.message)


def dec(v) -> Decimal | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def q(d: Decimal) -> str:
    return f"{d.quantize(Decimal('0.01')):.2f}"


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v == []


def validate(doc_type: str | None, data: dict | None, confidence: dict | None,
             ocr_mean: float | None, extraction_available: bool = True) -> list[Issue]:
    s = get_settings()
    tol = Decimal(s.amount_tolerance)
    data, confidence = data or {}, confidence or {}
    issues: list[Issue] = []
    dt = DocType(doc_type) if doc_type in {t.value for t in DocType} else DocType.UNKNOWN

    if ocr_mean is not None and ocr_mean < s.ocr_min_confidence:
        issues.append(Issue("POOR_SCAN_QUALITY", "warning", None,
                            f"Mean OCR confidence is {ocr_mean:.0f}% (threshold {s.ocr_min_confidence:.0f}%); extraction may be unreliable."))
    if not extraction_available:
        issues.append(Issue("EXTRACTION_UNAVAILABLE", "error", None,
                            "No extraction service was available; fields must be entered manually."))
    if dt == DocType.UNKNOWN:
        issues.append(Issue("UNKNOWN_DOCUMENT_TYPE", "error", "doc_type",
                            "Document could not be classified as an invoice, receipt or purchase order."))
        return issues
    if dt == DocType.RECEIPT and extraction_available:
        issues.append(Issue("EXTRACTION_NOT_SUPPORTED", "warning", None,
                            "Automatic field extraction is not implemented for receipts; verify or enter fields manually."))

    # 1. required fields
    for f in REQUIRED[dt]:
        if _blank(data.get(f)):
            issues.append(Issue("MISSING_FIELD", "error", f, f"Required field '{f}' is missing."))

    # 2. value validity
    if not _blank(data.get("document_date")):
        try:
            d = date.fromisoformat(str(data["document_date"]))
            if d > date.today() + timedelta(days=1):
                issues.append(Issue("FUTURE_DATE", "warning", "document_date", f"Document date {d} is in the future."))
        except ValueError:
            issues.append(Issue("INVALID_VALUE", "error", "document_date",
                                f"'{data['document_date']}' is not a valid date (expected YYYY-MM-DD)."))
    cur = data.get("currency")
    if not _blank(cur) and not re.fullmatch(r"[A-Z]{3}", str(cur)):
        issues.append(Issue("INVALID_VALUE", "error", "currency", f"'{cur}' is not a valid ISO 4217 code."))
    for f in MONEY_FIELDS:
        v = data.get(f)
        if _blank(v):
            continue
        d = dec(v)
        if d is None:
            issues.append(Issue("INVALID_VALUE", "error", f, f"'{v}' is not a valid number."))
        elif d < 0:
            issues.append(Issue("INVALID_VALUE", "error", f, f"'{f}' must not be negative (got {v})."))

    # 3. line items
    items = data.get("line_items") or []
    line_amounts: list[Decimal | None] = []
    for i, it in enumerate(items):
        qty, unit, amt = (dec(it.get(k)) for k in ("quantity", "unit_price", "amount"))
        for k, parsed in (("quantity", qty), ("unit_price", unit), ("amount", amt)):
            raw = it.get(k)
            if _blank(raw):
                continue
            if parsed is None:
                issues.append(Issue("INVALID_VALUE", "error", f"line_items.{i}.{k}", f"Line {i + 1}: '{raw}' is not a valid number."))
            elif parsed < 0 or (k == "quantity" and parsed == 0):
                issues.append(Issue("INVALID_VALUE", "error", f"line_items.{i}.{k}", f"Line {i + 1}: {k} must be positive (got {raw})."))
        if _blank(it.get("description")):
            issues.append(Issue("MISSING_FIELD", "error", f"line_items.{i}.description", f"Line {i + 1}: description is missing."))
        calc = qty * unit if qty is not None and unit is not None else None
        if calc is not None and amt is not None and abs(calc - amt) > tol:
            issues.append(Issue("LINE_TOTAL_MISMATCH", "error", f"line_items.{i}.amount",
                                f"Line {i + 1}: stated amount {q(amt)} but quantity x unit price = {q(calc)}."))
        line_amounts.append(amt if amt is not None else calc)

    line_sum = sum(line_amounts, Decimal(0)) if items and all(a is not None for a in line_amounts) else None
    subtotal, tax, disc, total = (dec(data.get(k)) for k in ("subtotal", "tax", "discount", "total"))

    # 4. calculation checks
    if line_sum is not None and subtotal is not None and abs(line_sum - subtotal) > tol:
        issues.append(Issue("SUBTOTAL_MISMATCH", "error", "subtotal",
                            f"Stated subtotal {q(subtotal)} but line items sum to {q(line_sum)}."))
    base = subtotal if subtotal is not None else line_sum
    if base is not None and total is not None:
        expected = base - (disc or Decimal(0)) + (tax or Decimal(0))
        if abs(expected - total) > tol:
            issues.append(Issue("TOTAL_MISMATCH", "error", "total",
                                f"Stated total {q(total)} but calculated total is {q(expected)} "
                                f"(subtotal {q(base)} - discount {q(disc or Decimal(0))} + tax {q(tax or Decimal(0))})."))

    # 5. uncertain extraction (field level)
    for path, c in sorted(confidence.items()):
        if c is not None and c < s.field_min_confidence:
            issues.append(Issue("LOW_CONFIDENCE", "warning", path, f"Field '{path}' was read with low confidence ({c:.0f}%); please verify."))
    return issues
