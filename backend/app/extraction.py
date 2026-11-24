"""Structured extraction. Chain: LLM extractor (if configured) -> rule-based extractor -> manual review.

Rules of the road (from the brief): never invent values (absent => None), report confidence per field
where the source provides it (Tesseract word confidences) and None ("unavailable") otherwise.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

import httpx

from .config import get_settings
from .models import DocType
from .ocr import OcrLine
from .schemas import Fields


class ExtractorUnavailable(Exception):
    pass


@dataclass
class Extraction:
    fields: dict
    confidence: dict[str, float | None] = field(default_factory=dict)
    extractor: str = "rules"
    unparsed: list[str] = field(default_factory=list)  # item-region lines we could not parse (-> warning)


# ---------------------------------------------------------------- helpers
NUM = re.compile(r"^(?:Rs\.?|LKR|USD|EUR|GBP|[$€£])?\(?-?\d[\d,]*(?:\.\d+)?\)?$", re.I)
MONEY_TOKEN = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")
PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")
CURRENCY_CODES = r"USD|EUR|GBP|LKR|INR|AUD|CAD|SGD|JPY|CNY|AED"


def to_number_str(token: str) -> str | None:
    """'Rs.1,250.50' -> '1250.50', '(5.00)' -> '-5.00'. Decimal-validated, returned as string."""
    t = re.sub(r"^(?:Rs\.?|LKR|USD|EUR|GBP|[$€£])", "", token.strip(), flags=re.I)
    neg = t.startswith("(") and t.endswith(")") or t.startswith("-")
    t = t.strip("()-").replace(",", "")
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    return format(-d if neg else d, "f")


def last_amount(text: str) -> str | None:
    cleaned = PERCENT.sub(" ", text)
    toks = MONEY_TOKEN.findall(cleaned)
    return to_number_str(toks[-1]) if toks else None


DATE_PATTERNS = [
    (re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"), ["%Y-%m-%d"], False),
    (re.compile(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}\b"), ["%d/%m/%Y"], True),  # numeric = DAY-FIRST (documented)
    (re.compile(r"\b\d{1,2}\s+[A-Za-z]{3,9}\.?,?\s+\d{4}\b"), ["%d %B %Y", "%d %b %Y"], False),
    (re.compile(r"\b[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}\b"), ["%B %d %Y", "%b %d %Y"], False),
]


def parse_date(text: str) -> str | None:
    """ISO date if valid; the raw matched text if it looks like a date but is invalid (validation flags it)."""
    for rx, fmts, numeric in DATE_PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        raw = m.group(0)
        norm = re.sub(r"[/.\-]", "/", raw) if numeric else raw.replace(",", "").replace(".", "")
        for f in fmts:
            try:
                return datetime.strptime(norm, f).date().isoformat()
            except ValueError:
                continue
        return raw
    return None


def _labeled(lines: list[OcrLine], label: str, *, sep_optional: bool = False) -> tuple[str, float | None] | None:
    """Value after `Label:` on the same line, or the next non-empty line if the value is empty."""
    sep = r"[:#.\-]*" if sep_optional else r"[:#.\-]+"
    rx = re.compile(rf"^\W*(?:{label})\s*(?:{sep}\s*(.*))?$", re.I)
    for i, ln in enumerate(lines):
        m = rx.match(ln.text)
        if not m:
            continue
        val = (m.group(1) or "").strip()
        if val:
            return val, ln.confidence
        if i + 1 < len(lines):
            return lines[i + 1].text.strip(), lines[i + 1].confidence
    return None


# ---------------------------------------------------------------- rule-based extractor
LABELS_NUMBER = {
    DocType.INVOICE: r"tax\s+invoice\s*(?:no\.?|number|num|#)|invoice\s*(?:no\.?|number|num|#)|inv\s*(?:no\.?|#)",
    DocType.PURCHASE_ORDER: r"purchase\s+order\s*(?:no\.?|number|num|#)|p\.?o\.?\s*(?:no\.?|number|num|#)|order\s*(?:no\.?|number|#)",
}
SUBTOTAL_RX = re.compile(r"^\W*sub[\s\-]*total\b", re.I)
TAX_RX = re.compile(r"^\W*(?:total\s+)?(?:tax|vat|gst|sales\s+tax)\b(?!\s+invoice)", re.I)
DISCOUNT_RX = re.compile(r"^\W*(?:total\s+)?discount\b", re.I)
TOTAL1_RX = re.compile(r"^\W*(?:grand\s+total|total\s+due|total\s+amount|net\s+total|total)\b(?!\s+(?:qty|quantity|items?|units?))", re.I)
TOTAL2_RX = re.compile(r"^\W*(?:amount\s+due|balance\s+due)\b", re.I)
HEADER_RX = re.compile(r"\b(?:description|item|particulars)\b.*\b(?:qty|quantity)\b", re.I)


def _is_totals_line(text: str) -> bool:
    return any(rx.match(text) for rx in (SUBTOTAL_RX, TAX_RX, DISCOUNT_RX, TOTAL1_RX, TOTAL2_RX))


def _parse_item(line: OcrLine) -> dict | None:
    toks = line.text.split()
    nums: list[str] = []
    while toks and len(nums) < 3 and NUM.match(toks[-1]):
        nums.insert(0, toks.pop())
    if len(nums) < 2:
        return None
    desc = re.sub(r"^\d+[.)]?\s+(?=\D)", "", " ".join(toks)).strip()
    if not desc:
        return None
    vals = [to_number_str(n) for n in nums]
    qty, unit, amount = (vals + [None])[:3] if len(vals) == 2 else vals
    return {"description": desc, "quantity": qty, "unit_price": unit, "amount": amount}


OCR_DECIMAL_FIX = re.compile(r"(?<=\d)[:;](?=\d{2}\b)")
REPAIRED_CONFIDENCE = 50.0


def repair_ocr_numbers(lines: list[OcrLine]) -> list[OcrLine]:
    """OCR often reads the decimal point as ':' or ';' ('25:50'). Repair it, but cap the line's confidence so a
    human is asked to verify the value (LOW_CONFIDENCE) instead of trusting a silent guess."""
    out = []
    for ln in lines:
        fixed = OCR_DECIMAL_FIX.sub(".", ln.text)
        if fixed != ln.text and ln.confidence is not None:
            out.append(OcrLine(fixed, min(ln.confidence, REPAIRED_CONFIDENCE)))
        else:
            out.append(OcrLine(fixed, ln.confidence))
    return out


def rules_extract(lines: list[OcrLine], doc_type: DocType) -> Extraction:
    lines = repair_ocr_numbers(lines)
    unparsed: list[str] = []
    f: dict = {k: None for k in Fields.model_fields}
    conf: dict[str, float | None] = {}

    def put(key: str, value, c: float | None):
        if value not in (None, ""):
            f[key] = value
            conf[key] = c

    # document number
    labels = LABELS_NUMBER.get(doc_type, LABELS_NUMBER[DocType.INVOICE])
    if (hit := _labeled(lines, labels, sep_optional=True)):
        m = re.match(r"[A-Za-z0-9][\w\-/]*", hit[0])
        if m:
            put("document_number", m.group(0), hit[1])

    # document date (specific labels first, never "due"/"delivery" dates)
    for pat in (r"(?<!due )(?<!delivery )(?<!ship )(?<!payment )\b(?:invoice|issue|order|document)\s+date\b",
                r"\bdate\s+of\s+issue\b",
                r"(?<!due )(?<!delivery )(?<!ship )(?<!payment )(?<!expiry )\bdate\b"):
        done = False
        for ln in lines:
            m = re.search(pat + r"\s*[:\-]?\s*(.*)$", ln.text, re.I)
            if m and (d := parse_date(m.group(1))):
                put("document_date", d, ln.confidence)
                done = True
                break
        if done:
            break

    for key, label in (("supplier_name", r"from|supplier|vendor|seller|issued\s+by|sold\s+by"),
                       ("customer_name", r"bill(?:ed)?\s*to|customer|buyer|sold\s+to|client")):
        if (hit := _labeled(lines, rf"(?:{label})(?:\s+name)?")):
            put(key, hit[0], hit[1])

    # currency: explicit field > ISO code in text > symbol
    full = "\n".join(l.text for l in lines)
    cur = re.search(rf"\bcurrency\s*[:\-]?\s*({CURRENCY_CODES})\b", full, re.I)
    codes = re.findall(rf"\b({CURRENCY_CODES})\b", full)
    if cur:
        code = cur.group(1).upper()
    elif codes:
        code = max(set(codes), key=codes.count)
    elif re.search(r"\bRs\.?\s*\d", full):
        code = "LKR"
    elif "€" in full:
        code = "EUR"
    elif "£" in full:
        code = "GBP"
    elif "$" in full:
        code = "USD"
    else:
        code = None
    if code:
        src = next((l for l in lines if code in l.text.upper() or {"LKR": "RS", "EUR": "€", "GBP": "£", "USD": "$"}.get(code, "\0") in l.text.upper()), None)
        put("currency", code, src.confidence if src else None)

    # totals
    tot1 = tot2 = None
    for ln in lines:
        t = ln.text
        if SUBTOTAL_RX.match(t):
            put("subtotal", last_amount(t), ln.confidence)
        elif TAX_RX.match(t):
            put("tax", last_amount(t), ln.confidence)
        elif DISCOUNT_RX.match(t):
            a = last_amount(t)
            put("discount", a.lstrip("-") if a else a, ln.confidence)
        elif TOTAL1_RX.match(t):
            tot1 = (last_amount(t), ln.confidence)
        elif TOTAL2_RX.match(t):
            tot2 = (last_amount(t), ln.confidence)
    if (tot1 and tot1[0]) or (tot2 and tot2[0]):
        v, c = tot1 if tot1 and tot1[0] else tot2
        put("total", v, c)

    # line items
    start = next((i for i, l in enumerate(lines) if HEADER_RX.search(l.text)), None)
    if start is not None:
        items, item_conf = [], []
        for ln in lines[start + 1:]:
            if _is_totals_line(ln.text):
                break
            row = _parse_item(ln)
            if row:
                items.append(row)
                item_conf.append(ln.confidence)
            elif items and not any(ch.isdigit() for ch in ln.text):
                items[-1]["description"] += " " + ln.text.strip()  # wrapped description
            elif ln.text.strip():
                unparsed.append(ln.text.strip())  # never drop a row silently
        if items:
            f["line_items"] = items
            for i, (row, c) in enumerate(zip(items, item_conf)):
                for k, v in row.items():
                    if v is not None:
                        conf[f"line_items.{i}.{k}"] = c
    return Extraction(f, conf, "rules", unparsed)


# ---------------------------------------------------------------- optional LLM extractor
LLM_PROMPT = """Extract invoice / purchase order data from the OCR text below. Respond with ONLY a JSON object with keys:
document_number, document_date (YYYY-MM-DD), supplier_name, customer_name, currency (ISO 4217),
subtotal, tax, discount, total (plain decimal strings, no currency symbols or thousands separators),
line_items (list of {{description, quantity, unit_price, amount}}).
Use null for anything not present in the text. NEVER guess or calculate missing values.

TEXT:
{text}"""


def llm_extract(lines: list[OcrLine], doc_type: DocType) -> Extraction:
    s = get_settings()
    if not s.anthropic_api_key:
        raise ExtractorUnavailable("No ANTHROPIC_API_KEY configured")
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": s.anthropic_model, "max_tokens": 2000,
                  "messages": [{"role": "user", "content": LLM_PROMPT.format(text="\n".join(l.text for l in lines))}]},
            timeout=s.llm_timeout_s,
        )
        r.raise_for_status()
        raw = "".join(b.get("text", "") for b in r.json()["content"])
        parsed = Fields.model_validate(json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()))
    except Exception as e:  # network, HTTP, JSON or schema errors all mean "service unavailable"
        raise ExtractorUnavailable(f"LLM extractor failed: {type(e).__name__}: {e}") from e
    f = parsed.model_dump()
    conf = {k: None for k, v in f.items() if k != "line_items" and v is not None}  # LLM gives no confidence
    for i, row in enumerate(f["line_items"] or []):
        conf.update({f"line_items.{i}.{k}": None for k, v in row.items() if v is not None})
    return Extraction(f, conf, "llm")


def extract_with_fallback(lines: list[OcrLine], doc_type: DocType) -> tuple[Extraction | None, list[dict]]:
    """Returns (result or None, events). None => no extractor could run => manual review."""
    events: list[dict] = []
    for name, fn in (("llm", llm_extract), ("rules", rules_extract)):
        try:
            return fn(lines, doc_type), events
        except ExtractorUnavailable as e:
            events.append({"extractor": name, "error": str(e)})
        except Exception as e:  # unexpected extractor bug: try next, record it
            events.append({"extractor": name, "error": f"{type(e).__name__}: {e}"})
    return None, events
