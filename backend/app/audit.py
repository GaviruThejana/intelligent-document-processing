from sqlalchemy.orm import Session

from .models import AuditEvent


def log(db: Session, doc_id: str, event_type: str, *, field=None, old=None, new=None,
        actor: str = "system", details: dict | None = None) -> None:
    db.add(AuditEvent(document_id=doc_id, event_type=event_type, field=field,
                      old_value=old, new_value=new, actor=actor, details=details))
