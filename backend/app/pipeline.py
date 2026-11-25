"""Processing pipeline (runs in the Celery worker, or inline in tests).

Idempotent by construction: the Queued->Processing claim is one atomic UPDATE, so a duplicated or
re-delivered task is a no-op and a retry re-uses the SAME document row (never creates a second one).
"""
import copy
import traceback
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from . import audit
from .classification import classify
from .extraction import extract_with_fallback
from .grounding import ground_fields
from .models import DocType, Document, Status, ValidationIssue
from .ocr import OcrUnavailable, read_document
from .schemas import Fields
from .validation import Issue, validate


def now():
    return datetime.now(timezone.utc)


def set_status(db: Session, doc: Document, new: Status, *, actor="system", reason: str | None = None) -> None:
    old = doc.status
    doc.status = new.value
    audit.log(db, doc.id, "status_changed", old=old, new=new.value, actor=actor,
              details={"reason": reason} if reason else None)


def sync_issues(db: Session, doc: Document, new: list[Issue]) -> None:
    """Replace issue set; an acknowledgement survives only if the identical issue (same message) persists."""
    keep = {i.key for i in new}
    existing = {(i.code, i.field, i.message): i for i in doc.issues}
    for key, row in existing.items():
        if key not in keep:
            doc.issues.remove(row)
    for i in new:
        if i.key not in existing:
            doc.issues.append(ValidationIssue(code=i.code, severity=i.severity, field=i.field, message=i.message))


def review_status(doc: Document) -> Status:
    return Status.NEEDS_REVIEW if any(not i.acknowledged for i in doc.issues) else Status.READY


def claim(db: Session, doc_id: str) -> bool:
    res = db.execute(update(Document).where(Document.id == doc_id, Document.status == Status.QUEUED.value)
                     .values(status=Status.PROCESSING.value, processing_started_at=now()))
    db.commit()
    return res.rowcount == 1


def process(db: Session, doc_id: str) -> None:
    if not claim(db, doc_id):
        return  # not Queued (already processed / duplicate delivery): nothing to do
    doc = db.get(Document, doc_id)
    audit.log(db, doc_id, "processing_started", details={"attempt": doc.retry_count + 1})
    try:
        _run(db, doc)
    except Exception as e:  # unexpected failure: record, mark Failed, allow a controlled retry
        db.rollback()
        doc = db.get(Document, doc_id)
        doc.error_message = f"{type(e).__name__}: {e}"[:2000]
        audit.log(db, doc_id, "processing_failed",
                  details={"error": doc.error_message, "trace": traceback.format_exc()[-1500:]})
        set_status(db, doc, Status.FAILED, reason="unexpected processing error")
        doc.processed_at = now()
    db.commit()


def _run(db: Session, doc: Document) -> None:
    doc.error_message = None
    try:
        ocr = read_document(doc.storage_path, doc.content_type)
    except OcrUnavailable as e:
        # Extraction service unavailable and no fallback possible -> manual review (never silent failure)
        audit.log(db, doc.id, "ocr_unavailable", details={"error": str(e)})
        _finish(db, doc, DocType.UNKNOWN, 0.0, None, [], available=False,
                active_issues=[Issue("OCR_UNAVAILABLE", "error", None, f"OCR could not run: {e}")])
        return
    doc.ocr_text, doc.ocr_method, doc.ocr_mean_confidence = ocr.text, ocr.method, ocr.mean_confidence
    acquisition_issues = [Issue("PDF_PAGE_LIMIT", "warning", None,
                                "PDF exceeds the configured page limit; only the first pages were processed.")
                          for warning in ocr.warnings if warning == "PDF_PAGE_LIMIT"]
    audit.log(db, doc.id, "ocr_completed", details={"method": ocr.method, "lines": len(ocr.lines),
                                                    "mean_confidence": ocr.mean_confidence})
    if not ocr.lines:
        audit.log(db, doc.id, "no_text_found")

    dtype, cconf = classify([l.text for l in ocr.lines])
    audit.log(db, doc.id, "classified", new=dtype.value, details={"confidence": cconf})

    if dtype in (DocType.INVOICE, DocType.PURCHASE_ORDER):
        result, events = extract_with_fallback(ocr.lines, dtype)
        for ev in events:
            audit.log(db, doc.id, "extractor_failed", details=ev)
        if result is None:
            audit.log(db, doc.id, "extraction_unavailable")
            _finish(db, doc, dtype, cconf, None, [], available=False)
            return
        audit.log(db, doc.id, "extraction_completed", details={"extractor": result.extractor})
        fields = result.fields
        grounding_issues = []
        if result.extractor == "llm":
            fields, rejected = ground_fields(fields, ocr.text)
            grounding_issues = [Issue("UNGROUNDED_VALUE", "error", item.field,
                                      f"LLM value for '{item.field}' was removed because it could not be verified in source text.")
                                for item in rejected]
            for item in rejected:
                result.confidence[item.field] = None
            audit.log(db, doc.id, "llm_grounding_completed",
                      details={"rejected_fields": [item.field for item in rejected], "rejected_count": len(rejected)})
        _finish(db, doc, dtype, cconf, fields, result.confidence, extractor=result.extractor,
                active_issues=acquisition_issues + grounding_issues + [Issue("UNPARSED_LINE", "warning", "line_items", f"Could not parse line: '{u[:80]}'") for u in result.unparsed])
    else:  # receipt (classification only) / unknown -> blank fields, manual entry
        _finish(db, doc, dtype, cconf, None, [], extractor="none", active_issues=acquisition_issues)


def _finish(db, doc, dtype, cconf, fields, confidence, *, available=True, extractor=None, active_issues=()):
    blank = Fields().model_dump()
    doc.doc_type, doc.classification_confidence = dtype.value, cconf
    doc.extractor = extractor
    doc.extracted = copy.deepcopy(fields if fields is not None else blank)  # immutable original
    doc.data = copy.deepcopy(doc.extracted)
    doc.confidence = confidence or {}
    issues = validate(doc.doc_type, doc.data, doc.confidence, doc.ocr_mean_confidence, extraction_available=available) + list(active_issues)
    sync_issues(db, doc, issues)
    audit.log(db, doc.id, "validation_completed", details={"issues": len(issues), "codes": sorted({i.code for i in issues})})
    db.flush()
    doc.processed_at = now()
    set_status(db, doc, review_status(doc), reason=f"{len(issues)} validation issue(s)")
