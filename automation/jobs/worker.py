from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from urllib.parse import urlparse

from automation.config import settings
from automation.db.automation_repository import AutomationRepository
from automation.db.connection import create_mysql_engine
from automation.jobs.collector_registry import COLLECTOR_REGISTRY
from automation.services.collector import CollectorCancelled, CollectorService
from automation.services.webhook_service import WebhookService
from automation.utils.logger import get_logger


logger = get_logger(__name__)

try:
    import dramatiq
    from dramatiq.brokers.redis import RedisBroker
except ImportError:  # pragma: no cover - exercised only before dependency installation
    dramatiq = None
    RedisBroker = None


def _redis_broker():
    if RedisBroker is None:
        raise RuntimeError("Dramatiq nao instalado. Execute pip install -r requirements.txt.")
    parsed = urlparse(settings.queue.redis_url)
    return RedisBroker(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        db=int((parsed.path or "/0").strip("/") or 0),
        password=parsed.password,
        namespace=settings.queue.queue_name,
    )


if dramatiq is not None:
    dramatiq.set_broker(_redis_broker())


def enqueue_job(job_id: str, delay_ms: int = 0) -> None:
    if dramatiq is None:
        raise RuntimeError("Dramatiq nao instalado. Execute pip install -r requirements.txt.")
    execute_job.send_with_options(args=(job_id,), delay=delay_ms)


def enqueue_webhook(event_id: str, delay_ms: int = 0) -> None:
    if dramatiq is None:
        raise RuntimeError("Dramatiq nao instalado. Execute pip install -r requirements.txt.")
    deliver_webhook.send_with_options(args=(event_id,), delay=delay_ms)


class JobExecutor:
    def __init__(self) -> None:
        engine = create_mysql_engine()
        self.repository = AutomationRepository(engine)
        self.repository.ensure_schema()
        self.collector = CollectorService(repository=None)

    def execute(self, job_id: str) -> None:
        if self.repository.get_system_state()["mode"] != "RUNNING":
            logger.info("Job mantido na fila porque o servico esta pausado. job_id=%s", job_id)
            return

        job = self.repository.claim_job(job_id)
        if job is None:
            return

        definition = COLLECTOR_REGISTRY.get(str(job["collector"]))
        if definition is None:
            self.repository.fail_job(
                job_id,
                int(job["attempts"]),
                "COLLECTOR_NOT_FOUND",
                "Collector nao registrado.",
                retry=False,
            )
            failed = self.repository.get_job(job_id)
            if failed:
                self._emit_event(failed, "job.failed")
            return

        attempt_number = int(job["attempts"])
        self.repository.clear_results(job_id)

        try:
            rows = definition.execute(
                job["parameters_json"] or {},
                self.collector,
                lambda current, total, message: self.repository.update_progress(
                    job_id, current, total, message
                ),
                lambda: self.repository.is_cancellation_requested(job_id),
            )
            if self.repository.is_cancellation_requested(job_id):
                raise CollectorCancelled()

            result_checksum = self._persist_results(job_id, rows)
            self.repository.complete_job(
                job_id,
                attempt_number,
                len(rows),
                result_checksum,
            )
            completed = self.repository.get_job(job_id)
            if completed:
                self._emit_event(completed, "job.completed")
            self.repository.complete_pause_if_idle()
        except CollectorCancelled:
            self.repository.cancel_running_job(job_id, attempt_number)
            cancelled = self.repository.get_job(job_id)
            if cancelled:
                self._emit_event(cancelled, "job.cancelled")
            self.repository.complete_pause_if_idle()
        except Exception as exc:
            retry = attempt_number < int(job["max_attempts"])
            error_code = self._error_code(exc)
            self.repository.fail_job(
                job_id,
                attempt_number,
                error_code,
                str(exc),
                retry=retry,
            )
            if retry:
                self.repository.requeue_job(job_id)
                try:
                    enqueue_job(job_id, delay_ms=self._retry_delay(attempt_number))
                except Exception:
                    logger.exception("Falha ao reenfileirar job_id=%s", job_id)
            failed = self.repository.get_job(job_id)
            if failed and not retry:
                self._emit_event(failed, "job.failed")
            self.repository.complete_pause_if_idle()
            logger.exception("Falha na execucao do job_id=%s", job_id)

    def _emit_event(self, job: dict, event_type: str) -> None:
        event_id = self.repository.save_event_for_job(job, event_type)
        try:
            enqueue_webhook(event_id)
        except Exception:
            logger.exception("Falha ao enfileirar webhook. event_id=%s", event_id)

    def _persist_results(self, job_id: str, rows: list[dict]) -> str:
        page_size = settings.automation.max_result_page_size
        digest = hashlib.sha256()
        for sequence, start in enumerate(range(0, len(rows), page_size)):
            page = [_json_safe(row) for row in rows[start : start + page_size]]
            encoded = json.dumps(page, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            page_checksum = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            self.repository.save_result_page(job_id, sequence, page, page_checksum)
            digest.update(encoded.encode("utf-8"))
        return f"sha256:{digest.hexdigest()}"

    @staticmethod
    def _error_code(exc: Exception) -> str:
        name = exc.__class__.__name__.upper()
        if "TIMEOUT" in name:
            return "PLAYWRIGHT_TIMEOUT"
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return "DEPENDENCY_UNAVAILABLE"
        if isinstance(exc, ValueError):
            return "VALIDATION_ERROR"
        return "COLLECTOR_ERROR"

    @staticmethod
    def _retry_delay(attempt_number: int) -> int:
        return min(60 * (2 ** max(attempt_number - 1, 0)) * 1000, 3600000)


def _json_safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


if dramatiq is not None:

    @dramatiq.actor(max_retries=0, queue_name=settings.queue.queue_name)
    def execute_job(job_id: str) -> None:
        JobExecutor().execute(job_id)

else:

    def execute_job(job_id: str) -> None:
        raise RuntimeError("Dramatiq nao instalado. Execute pip install -r requirements.txt.")


if dramatiq is not None:

    @dramatiq.actor(max_retries=0, queue_name=settings.queue.queue_name)
    def deliver_webhook(event_id: str) -> None:
        engine = create_mysql_engine()
        repository = AutomationRepository(engine)
        repository.ensure_schema()
        WebhookService(repository, enqueue=enqueue_webhook).deliver(event_id)

else:

    def deliver_webhook(event_id: str) -> None:
        raise RuntimeError("Dramatiq nao instalado. Execute pip install -r requirements.txt.")
