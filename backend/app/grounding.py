"""Conservative source grounding for values returned by an LLM.

This is a deterministic evidence check, not a semantic truth guarantee. A value must
be present in OCR/PDF text (or be a documented numeric/date normalization of it).
Unverified values are nulled before validation and always produce a blocking issue.
"""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .extraction import parse_date


@dataclass(frozen=True)
class GroundingIssue:
    field: str
    value: str
    reason: str


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _number(value: str) -> Decimal | None:
    cleaned = value.strip().replace(",", "")
    cleaned = re.sub(r"^(?:rs\.?|lkr|usd|eur|gbp|[$€£])\s*", "", cleaned, flags=re.I)
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    try:
        result = Decimal(cleaned)
        return -result if negative else result
    except InvalidOperation:
        return None


def _grounded(value: str, source: str, *, kind: str = "text") -> bool:
    if not value.strip():
        return False
    if kind == "date":
        wanted = parse_date(value)
        if not wanted:
            return False
        for candidate in re.findall(
            r"\b(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\.?[,]?\s+\d{4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})\b", source
        ):
            if parse_date(candidate) == wanted:
                return True
        return False
    if kind == "number":
        wanted = _number(value)
        if wanted is None:
            return False
        # Boundaries avoid matching 10 inside 100; Decimal permits harmless formatting changes.
        for candidate in re.findall(r"(?<![\w.])(?:\(?-?\d[\d,]*(?:\.\d+)?\)?)(?![\w.])", source):
            if _number(candidate) == wanted:
                return True
        return False
    if kind == "currency":
        aliases = {"LKR": ("LKR", "Rs", "Rs."), "USD": ("USD", "$"), "EUR": ("EUR", "€"),
                   "GBP": ("GBP", "£"), "INR": ("INR", "₹"), "JPY": ("JPY", "¥")}
        code = value.upper()
        if code not in aliases:
            return bool(re.search(rf"\b{re.escape(code)}\b", source, re.I))
        return any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", source, re.I) for alias in aliases[code])
    wanted = _norm(value)
    return bool(wanted and f" {wanted} " in f" {_norm(source)} ")


def ground_fields(fields: dict, source: str) -> tuple[dict, list[GroundingIssue]]:
    """Return a copy with every unsupported non-null leaf replaced by None."""
    result = {**fields}
    issues: list[GroundingIssue] = []
    scalar_kinds = {
        "document_number": "text", "document_date": "date", "supplier_name": "text",
        "customer_name": "text", "currency": "currency", "subtotal": "number",
        "tax": "number", "discount": "number", "total": "number",
    }
    for key, kind in scalar_kinds.items():
        value = result.get(key)
        if value is not None and not _grounded(str(value), source, kind=kind):
            result[key] = None
            issues.append(GroundingIssue(key, str(value), "value not found in source text"))
    rows = result.get("line_items")
    if rows is not None:
        grounded_rows = []
        for index, item in enumerate(rows):
            row = dict(item)
            description = row.get("description")
            # A line's numbers must be evidenced on that same source line/description
            # region, not merely somewhere else in the invoice (e.g. a total).
            evidence = ""
            if description and _grounded(str(description), source):
                wanted = _norm(str(description))
                source_lines = source.splitlines()
                line_index = next((i for i, line in enumerate(source_lines)
                                   if f" {_norm(line)} ".find(f" {wanted} ") >= 0), None)
                if line_index is not None:
                    evidence = source_lines[line_index]
            for key, kind in (("description", "text"), ("quantity", "number"),
                              ("unit_price", "number"), ("amount", "number")):
                value = row.get(key)
                path = f"line_items.{index}.{key}"
                evidence_text = source if key == "description" else evidence
                if value is not None and not _grounded(str(value), evidence_text, kind=kind):
                    row[key] = None
                    issues.append(GroundingIssue(path, str(value), "value not found in source text"))
            grounded_rows.append(row)
        result["line_items"] = grounded_rows
    return result, issues
