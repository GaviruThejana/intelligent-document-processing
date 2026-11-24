"""Celery app + task. Start with: celery -A app.worker.celery_app worker -l info"""
from celery import Celery

from .config import get_settings
from .db import SessionLocal
from .pipeline import process

s = get_settings()
celery_app = Celery("idp", broker=s.redis_url, backend=s.redis_url)
celery_app.conf.update(
    task_acks_late=True,                 # re-deliver if the worker dies mid-task (pipeline is idempotent)
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"max_retries": 2, "interval_start": 0, "interval_step": 0.2, "socket_connect_timeout": 2},
)


@celery_app.task(name="idp.process_document")
def process_document_task(doc_id: str) -> None:
    with SessionLocal() as db:
        process(db, doc_id)
