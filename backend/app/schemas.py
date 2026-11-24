from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_str(v: Any) -> Any:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, bool):
        raise ValueError("boolean not allowed")
    if isinstance(v, (int, float)):
        return str(v)
    raise ValueError("must be string or number")


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = None

    _coerce = field_validator("*", mode="before")(_to_str)


class Fields(BaseModel):
    """Structured extraction result. Missing values stay None - never invented."""

    model_config = ConfigDict(extra="forbid")
    document_number: str | None = None
    document_date: str | None = None  # ISO 8601 (YYYY-MM-DD) when parseable
    supplier_name: str | None = None
    customer_name: str | None = None
    currency: str | None = None
    subtotal: str | None = None
    tax: str | None = None
    discount: str | None = None
    total: str | None = None
    line_items: list[LineItem] | None = None

    _coerce = field_validator(
        "document_number", "document_date", "supplier_name", "customer_name",
        "currency", "subtotal", "tax", "discount", "total", mode="before",
    )(_to_str)


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    severity: str
    field: str | None
    message: str
    acknowledged: bool
    acknowledged_by: str | None
    acknowledged_note: str | None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    field: str | None
    old_value: Any = None
    new_value: Any = None
    actor: str
    details: dict | None
    created_at: datetime


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    doc_type: str | None
    classification_confidence: float | None
    retry_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    ocr_text: str | None
    ocr_method: str | None
    ocr_mean_confidence: float | None
    extractor: str | None
    extracted: dict | None
    data: dict | None
    confidence: dict | None
    issues: list[IssueOut]
    approved_by: str | None
    approved_at: datetime | None
    processed_at: datetime | None


class UploadResponse(BaseModel):
    duplicate: bool
    message: str
    document: DocumentSummary


class PatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: Fields | None = None
    doc_type: str | None = None
    actor: str = Field(default="reviewer", min_length=1, max_length=100)

    @field_validator("actor")
    @classmethod
    def actor_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("actor must not be blank")
        return value


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str = Field(default="reviewer", min_length=1, max_length=100)
    acknowledged_issue_ids: list[int] = []
    note: str | None = None

    @field_validator("actor")
    @classmethod
    def actor_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("actor must not be blank")
        return value
