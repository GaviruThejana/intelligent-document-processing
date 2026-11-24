"""Database schema. Money is never stored as float: values live in JSON as decimal strings."""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Status(str, enum.Enum):
    UPLOADED = "Uploaded"
    QUEUED = "Queued"
    PROCESSING = "Processing"
    NEEDS_REVIEW = "Needs Review"
    READY = "Ready for Approval"
    APPROVED = "Approved"
    FAILED = "Failed"


class DocType(str, enum.Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    PURCHASE_ORDER = "purchase_order"
    UNKNOWN = "unknown"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # duplicate detection
    storage_path: Mapped[str] = mapped_column(String(512))

    status: Mapped[str] = mapped_column(String(20), index=True, default=Status.UPLOADED.value)
    doc_type: Mapped[str | None] = mapped_column(String(20), index=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    ocr_text: Mapped[str | None] = mapped_column(Text)
    ocr_method: Mapped[str | None] = mapped_column(String(20))
    ocr_mean_confidence: Mapped[float | None] = mapped_column(Float)  # null = unavailable
    extractor: Mapped[str | None] = mapped_column(String(20))

    extracted: Mapped[dict | None] = mapped_column(JsonType)   # ORIGINAL machine output (never modified)
    data: Mapped[dict | None] = mapped_column(JsonType)        # CURRENT values (after human corrections)
    confidence: Mapped[dict | None] = mapped_column(JsonType)  # field path -> 0..100 or null (unavailable)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(100))

    issues: Mapped[list["ValidationIssue"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="ValidationIssue.id"
    )
    events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="AuditEvent.id"
    )


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(10))  # error | warning
    field: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(100))
    acknowledged_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="issues")


class AuditEvent(Base):
    """Append-only log: processing events, original->revised values, approvals."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    field: Mapped[str | None] = mapped_column(String(100))
    old_value: Mapped[dict | list | str | None] = mapped_column(JsonType)
    new_value: Mapped[dict | list | str | None] = mapped_column(JsonType)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    details: Mapped[dict | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    document: Mapped[Document] = relationship(back_populates="events")
