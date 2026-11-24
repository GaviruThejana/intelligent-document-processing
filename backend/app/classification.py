"""Transparent keyword-scoring classifier (title lines weigh double). Returns (doc_type, confidence 0..1)."""
import re

from .models import DocType

RULES: dict[DocType, list[tuple[str, int]]] = {
    DocType.INVOICE: [(r"\btax invoice\b", 3), (r"\binvoice\b", 2), (r"\binvoice\s*(?:no|number|#)", 3),
                      (r"\bbill(?:ed)?\s*to\b", 1), (r"\bamount due\b", 1), (r"\bdue date\b", 1)],
    DocType.PURCHASE_ORDER: [(r"\bpurchase order\b", 3), (r"\bp\.?o\.?\s*(?:no|number|#)", 3),
                             (r"\bship\s*to\b", 1), (r"\bdeliver(?:y)? date\b", 1), (r"\border date\b", 1)],
    DocType.RECEIPT: [(r"\breceipt\b", 3), (r"\bthank you for (?:your )?(?:purchase|shopping|visit)", 2),
                      (r"\bchange(?: due)?\b", 1), (r"\b(?:cash|card) (?:tendered|payment)\b", 2),
                      (r"\bcashier\b", 2)],
}
MIN_SCORE = 3


def classify(lines: list[str]) -> tuple[DocType, float]:
    scores = {t: 0 for t in RULES}
    for idx, line in enumerate(lines):
        weight = 2 if idx < 6 else 1  # header region matters most
        low = line.lower()
        for t, rules in RULES.items():
            for pattern, pts in rules:
                if re.search(pattern, low):
                    scores[t] += pts * weight
    best = max(scores, key=scores.get)
    top, total = scores[best], sum(scores.values())
    if top < MIN_SCORE:
        return DocType.UNKNOWN, 0.0
    return best, round((top / total) * min(1.0, top / 8), 2)
