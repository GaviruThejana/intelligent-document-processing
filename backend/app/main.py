"""FastAPI application. Interactive docs (Swagger) at /docs, OpenAPI JSON at /openapi.json."""
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from . import audit, export, storage
from .config import get_settings
from .db import Base, SessionLocal, engine, get_db
from .jobs import enqueue
from .models import AuditEvent, DocType, Document, Status, ValidationIssue
from .pipeline import now, review_status, set_status, sync_issues
from .schemas import (ApproveRequest, AuditOut, DocumentDetail, DocumentSummary, Fields, PatchRequest,
                      UploadResponse)
from .validation import validate

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    for attempt in range(30):  # wait for Postgres on cold start
        try:
            Base.metadata.create_all(engine)
            break
        except OperationalError:
            if attempt == 29:
                raise
            time.sleep(1)
    yield


app = FastAPI(title="Intelligent Document Processing & Validation API", version="1.0.0", lifespan=lifespan,
              description="Upload -> duplicate check -> async OCR/AI extraction -> validation -> human review -> approval -> export.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])
router = APIRouter(prefix="/api/v1")


def _get(db: Session, doc_id: str) -> Document:
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


def _flatten(data: dict | None) -> dict:
    out = {}
    for k, v in (data or {}).items():
        if k == "line_items":
            for i, it in enumerate(v or []):
                for kk, vv in it.items():
                    out[f"line_items.{i}.{kk}"] = vv
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------ upload
@router.post("/documents", response_model=UploadResponse, status_code=202, tags=["documents"],
             summary="Upload a PDF/JPG/PNG (duplicates return the existing document, no new job)")
async def upload(response: Response, file: UploadFile | None = None, db: Session = Depends(get_db)):
    if file is None:
        raise HTTPException(422, "multipart field 'file' is required")
    data = await storage.read_limited(file, settings.max_upload_mb * 1024 * 1024)
    name, mime, ext = storage.validate_upload(file.filename, data)
    sha = storage.sha256_hex(data)

    def duplicate(existing: Document) -> UploadResponse:
        audit.log(db, existing.id, "duplicate_upload_detected", details={"filename": name})
        db.commit()
        response.status_code = 200
        return UploadResponse(duplicate=True, document=existing,
                              message=f"Identical file already uploaded as document {existing.id}; no new job created.")

    if (existing := db.scalar(select(Document).where(Document.sha256 == sha))):
        return duplicate(existing)
    doc = Document(filename=name, content_type=mime, size_bytes=len(data), sha256=sha,
                   storage_path=storage.save(data, sha, ext), status=Status.UPLOADED.value)
    db.add(doc)
    try:
        db.flush()
        audit.log(db, doc.id, "uploaded", details={"filename": name, "size_bytes": len(data), "content_type": mime})
        db.commit()
    except IntegrityError:  # concurrent identical upload won the race
        db.rollback()
        return duplicate(db.scalar(select(Document).where(Document.sha256 == sha)))
    enqueue(db, doc.id)
    db.refresh(doc)
    return UploadResponse(duplicate=False, document=doc, message="Accepted for processing.")



# ------------------------------------------------------------------ read
@router.get("/documents", tags=["documents"])
def list_documents(status: str | None = None, doc_type: str | None = None, q: str | None = None,
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    stmt = select(Document)
    if status:
        stmt = stmt.where(Document.status == status)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if q:
        stmt = stmt.where(Document.filename.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [DocumentSummary.model_validate(r) for r in rows]}


@router.get("/documents/{doc_id}", response_model=DocumentDetail, tags=["documents"])
def get_document(doc_id: str, db: Session = Depends(get_db)):
    return _get(db, doc_id)


@router.get("/documents/{doc_id}/file", tags=["documents"], summary="Download the original file")
def get_file(doc_id: str, db: Session = Depends(get_db)):
    doc = _get(db, doc_id)
    if not Path(doc.storage_path).is_file():
        raise HTTPException(404, "Original file is missing from storage")
    return FileResponse(doc.storage_path, media_type=doc.content_type, filename=doc.filename)


@router.get("/documents/{doc_id}/audit", response_model=list[AuditOut], tags=["audit"])
def get_audit(doc_id: str, db: Session = Depends(get_db)):
    _get(db, doc_id)
    return db.scalars(select(AuditEvent).where(AuditEvent.document_id == doc_id).order_by(AuditEvent.id)).all()


# ------------------------------------------------------------------ review
@router.patch("/documents/{doc_id}", response_model=DocumentDetail, tags=["review"],
              summary="Correct extracted fields (originals preserved in `extracted` + audit trail)")
def correct(doc_id: str, body: PatchRequest, db: Session = Depends(get_db)):
    doc = _get(db, doc_id)
    if doc.status not in (Status.NEEDS_REVIEW.value, Status.READY.value):
        raise HTTPException(409, f"Document in status '{doc.status}' cannot be edited")
    old_flat = _flatten(doc.data)
    new_data = dict(doc.data or Fields().model_dump())
    if body.fields is not None:
        new_data.update(body.fields.model_dump(exclude_unset=True))
    if body.doc_type is not None:
        if body.doc_type not in {t.value for t in DocType}:
            raise HTTPException(422, f"doc_type must be one of {[t.value for t in DocType]}")
        if body.doc_type != doc.doc_type:
            audit.log(db, doc.id, "doc_type_corrected", field="doc_type", old=doc.doc_type, new=body.doc_type, actor=body.actor)
            doc.doc_type = body.doc_type
    new_flat = _flatten(new_data)
    conf = dict(doc.confidence or {})
    for path in sorted(set(old_flat) | set(new_flat)):
        if old_flat.get(path) != new_flat.get(path):
            audit.log(db, doc.id, "field_corrected", field=path, old=old_flat.get(path), new=new_flat.get(path), actor=body.actor)
            conf[path] = None  # human-verified value: machine confidence no longer applies
    doc.data, doc.confidence = new_data, conf
    sync_issues(db, doc, validate(doc.doc_type, doc.data, doc.confidence, doc.ocr_mean_confidence,
                                  extraction_available=doc.extractor is not None or doc.ocr_text is not None))
    db.flush()
    new_status = review_status(doc)
    if new_status.value != doc.status:
        set_status(db, doc, new_status, actor=body.actor, reason="revalidated after correction")
    db.commit()
    return doc


@router.post("/documents/{doc_id}/retry", response_model=DocumentSummary, status_code=202, tags=["review"],
             summary="Controlled retry of a Failed (or never-queued) document; re-uses the same record")
def retry(doc_id: str, db: Session = Depends(get_db)):
    _get(db, doc_id)
    if not enqueue(db, doc_id, retry=True, actor="user"):
        raise HTTPException(409, "Only Failed, Uploaded or stalled (Queued/Processing too long) documents can be retried")
    return db.get(Document, doc_id)


@router.post("/documents/{doc_id}/approve", response_model=DocumentDetail, tags=["review"],
             summary="Approve; every open validation issue must be fixed or explicitly acknowledged")
def approve(doc_id: str, body: ApproveRequest, db: Session = Depends(get_db)):
    doc = _get(db, doc_id)
    if doc.status not in (Status.NEEDS_REVIEW.value, Status.READY.value):
        raise HTTPException(409, f"Document in status '{doc.status}' cannot be approved")
    open_issues = [i for i in doc.issues if not i.acknowledged]
    unresolved = [i for i in open_issues if i.id not in set(body.acknowledged_issue_ids)]
    if unresolved:
        raise HTTPException(409, {"message": "Unresolved validation issues must be corrected or acknowledged before approval",
                                  "unresolved": [{"id": i.id, "code": i.code, "field": i.field, "message": i.message} for i in unresolved]})
    to_ack = [i for i in open_issues if i.id in set(body.acknowledged_issue_ids)]
    if to_ack and not (body.note and body.note.strip()):
        raise HTTPException(422, "A note is required when acknowledging validation issues")
    res = db.execute(update(Document).where(Document.id == doc.id, Document.status.in_([Status.NEEDS_REVIEW.value, Status.READY.value]))
                     .values(status=Status.APPROVED.value, approved_by=body.actor, approved_at=now()))
    if res.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Document state changed; reload and retry")
    for i in to_ack:
        i.acknowledged, i.acknowledged_by, i.acknowledged_note = True, body.actor, body.note
        audit.log(db, doc.id, "issue_acknowledged", field=i.field, actor=body.actor, details={"code": i.code, "note": body.note})
    audit.log(db, doc.id, "status_changed", old=doc.status, new=Status.APPROVED.value, actor=body.actor, details={"reason": "approved"})
    db.commit()
    db.refresh(doc)
    return doc


# ------------------------------------------------------------------ export
@router.get("/documents/{doc_id}/export", tags=["export"], summary="Export an APPROVED document as JSON or CSV")
def export_one(doc_id: str, format: Literal["json", "csv"] = "json", db: Session = Depends(get_db)):
    doc = _get(db, doc_id)
    if doc.status != Status.APPROVED.value:
        raise HTTPException(409, "Only approved documents can be exported")
    audit.log(db, doc.id, "exported", details={"format": format})
    db.commit()
    if format == "csv":
        return PlainTextResponse(export.to_csv([doc]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{doc.id}.csv"'})
    return export.to_json(doc)


@router.get("/export", tags=["export"], summary="Export ALL approved documents")
def export_all(format: Literal["json", "csv"] = "json", db: Session = Depends(get_db)):
    docs = db.scalars(select(Document).where(Document.status == Status.APPROVED.value).order_by(Document.approved_at)).all()
    for doc in docs:
        audit.log(db, doc.id, "exported", actor="system", details={"format": format, "scope": "all"})
    if docs:
        db.commit()
    if format == "csv":
        return PlainTextResponse(export.to_csv(list(docs)), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="approved_documents.csv"'})
    return [export.to_json(d) for d in docs]


# ------------------------------------------------------------------ dashboard
@router.get("/stats", tags=["dashboard"], summary="Status counts, error and processing statistics")
def stats(db: Session = Depends(get_db)):
    by_status = {s.value: 0 for s in Status}
    by_status.update(dict(db.execute(select(Document.status, func.count()).group_by(Document.status)).all()))
    by_type = dict(db.execute(select(func.coalesce(Document.doc_type, "pending"), func.count()).group_by(Document.doc_type)).all())
    total = sum(by_status.values())
    durations = [(p - s).total_seconds() for s, p in db.execute(
        select(Document.processing_started_at, Document.processed_at).where(Document.processed_at.is_not(None),
                                                                             Document.processing_started_at.is_not(None))).all()]
    codes = db.execute(select(ValidationIssue.code, func.count()).group_by(ValidationIssue.code).order_by(func.count().desc())).all()
    failed = db.scalars(select(Document).where(Document.status == Status.FAILED.value).order_by(Document.updated_at.desc()).limit(5)).all()
    return {
        "total_documents": total, "by_status": by_status, "by_type": by_type,
        "duplicates_detected": db.scalar(select(func.count()).where(AuditEvent.event_type == "duplicate_upload_detected")),
        "avg_processing_seconds": round(sum(durations) / len(durations), 2) if durations else None,
        "approval_rate": round(by_status["Approved"] / total, 3) if total else None,
        "needs_attention": by_status["Needs Review"] + by_status["Failed"],
        "issues_by_code": {c: n for c, n in codes},
        "recent_failures": [{"id": d.id, "filename": d.filename, "error": d.error_message, "retry_count": d.retry_count} for d in failed],
    }


@app.get("/health", tags=["system"])
def health():
    with SessionLocal() as db:
        db.execute(select(1))
    return {"status": "ok"}


app.include_router(router)
