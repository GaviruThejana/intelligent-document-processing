"""Enqueue helper. A broker outage never loses the document: it stays 'Uploaded' and can be retried."""
import logging

from datetime import timedelta

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .db import SessionLocal
from .models import Document, Status
from .pipeline import now, process

log = logging.getLogger(__name__)


def _dispatch(doc_id: str) -> None:
    if get_settings().queue_mode == "inline":
        with SessionLocal() as db:
            process(db, doc_id)
    else:
        from .worker import process_document_task

        process_document_task.delay(doc_id)


def enqueue(db: Session, doc_id: str, *, retry: bool = False, actor: str = "system") -> bool:
    """Atomically Uploaded|Failed|stale Queued/Processing -> Queued, then dispatch. Returns False if the doc was not enqueueable."""
    cond = Document.status == Status.UPLOADED.value
    if retry:
        stale = and_(Document.status.in_([Status.QUEUED.value, Status.PROCESSING.value]),
                     Document.updated_at < now() - timedelta(minutes=get_settings().stale_job_minutes))
        cond = or_(cond, Document.status == Status.FAILED.value, stale)
    values = {"status": Status.QUEUED.value, "queued_at": now(), "error_message": None}
    if retry:
        values["retry_count"] = Document.retry_count + 1
    res = db.execute(update(Document).where(Document.id == doc_id, cond).values(**values))
    if res.rowcount != 1:
        db.rollback()
        return False
    audit.log(db, doc_id, "retry_requested" if retry else "queued", actor=actor)
    db.commit()
    try:
        _dispatch(doc_id)
    except Exception as e:
        log.exception("enqueue failed")
        db.rollback()
        db.execute(update(Document).where(Document.id == doc_id, Document.status == Status.QUEUED.value)
                   .values(status=Status.UPLOADED.value))
        audit.log(db, doc_id, "enqueue_failed", details={"error": f"{type(e).__name__}: {e}"})
        db.commit()
    return True
