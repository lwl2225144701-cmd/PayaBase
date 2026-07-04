"""Shared Celery app — all task modules import from here."""

from celery import Celery

from core.config import settings

celery_app = Celery(
    "training_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_prefetch_multiplier=1,
)

# Import task modules so @celery_app.task decorators register
from core.tasks import indexing  # noqa: F401, E402
from core.tasks import ppt_generation  # noqa: F401, E402
from core.tasks import pdf_generation  # noqa: F401, E402
