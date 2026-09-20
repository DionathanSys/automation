from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from automation.config import settings
from automation.db.schema import (
    clients_table,
    db_metadata,
    events_table,
    job_attempts_table,
    job_results_table,
    jobs_table,
    nonces_table,
    system_state_table,
    webhook_deliveries_table,
)


TERMINAL_JOB_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


def utc_now() -> datetime:
    """Return a UTC datetime compatible with SQLAlchemy DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return uuid4().hex


class AutomationRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ensure_schema(self) -> None:
        db_metadata.create_all(self.engine)

    def ensure_configured_client(self) -> None:
        client_id = settings.automation.client_id.strip()
        client_secret = settings.automation.client_secret
        if not client_id or not client_secret:
            return

        now = utc_now()
        secret_hash = hashlib.sha256(client_secret.encode("utf-8")).hexdigest()
        previous_secret_hash = (
            hashlib.sha256(settings.automation.previous_client_secret.encode("utf-8")).hexdigest()
            if settings.automation.previous_client_secret
            else None
        )
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(clients_table.c.id).where(clients_table.c.code == client_id)
            ).first()
            values = {
                "name": client_id,
                "secret_hash": secret_hash,
                "previous_secret_hash": previous_secret_hash,
                "is_active": True,
                "allowed_collectors": ["*"],
                "scopes": [
                    "jobs:read",
                    "jobs:write",
                    "collectors:read",
                    "system:read",
                    "system:control",
                ],
                "callback_url": settings.automation.callback_url or None,
                "updated_at": now,
            }
            if existing is None:
                connection.execute(
                    clients_table.insert().values(
                        id=new_id(),
                        code=client_id,
                        created_at=now,
                        **values,
                    )
                )
            else:
                connection.execute(
                    clients_table.update()
                    .where(clients_table.c.code == client_id)
                    .values(values)
                )

    def get_client(self, code: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(clients_table).where(clients_table.c.code == code)
            ).mappings().first()
        return dict(row) if row is not None else None

    def get_client_by_id(self, client_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(clients_table).where(clients_table.c.id == client_id)
            ).mappings().first()
        return dict(row) if row is not None else None

    def find_job_by_idempotency(
        self,
        client_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(jobs_table).where(
                    and_(
                        jobs_table.c.client_id == client_id,
                        jobs_table.c.idempotency_key == idempotency_key,
                    )
                )
            ).mappings().first()
        return dict(row) if row is not None else None

    def insert_job(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        try:
            with self.engine.begin() as connection:
                connection.execute(jobs_table.insert().values(values))
        except IntegrityError:
            existing = self.find_job_by_idempotency(
                values["client_id"], values["idempotency_key"]
            )
            if existing is None:
                raise
            return existing, False

        result = self.get_job(values["id"], values["client_id"])
        if result is None:
            raise RuntimeError("Job criado, mas nao foi possivel recupera-lo.")
        return result, True

    def get_job(self, job_id: str, client_id: str | None = None) -> dict[str, Any] | None:
        conditions = [jobs_table.c.id == job_id]
        if client_id is not None:
            conditions.append(jobs_table.c.client_id == client_id)
        with self.engine.connect() as connection:
            row = connection.execute(select(jobs_table).where(and_(*conditions))).mappings().first()
        return dict(row) if row is not None else None

    def claim_job(self, job_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(jobs_table).where(
                    and_(jobs_table.c.id == job_id, jobs_table.c.status == "QUEUED")
                ).with_for_update()
            ).mappings().first()
            if row is None:
                return None

            attempt_number = int(row["attempts"]) + 1
            connection.execute(
                jobs_table.update()
                .where(jobs_table.c.id == job_id)
                .values(
                    status="RUNNING",
                    attempts=attempt_number,
                    started_at=now,
                    updated_at=now,
                    error_code=None,
                    error_message=None,
                )
            )
            connection.execute(
                job_attempts_table.insert().values(
                    id=new_id(),
                    job_id=job_id,
                    attempt_number=attempt_number,
                    worker_id=settings.queue.worker_id,
                    status="RUNNING",
                    started_at=now,
                    finished_at=None,
                    error_code=None,
                    error_message=None,
                    diagnostic_metadata_json={},
                )
            )

        claimed = self.get_job(job_id)
        if claimed is None:
            raise RuntimeError("Job reservado, mas nao foi possivel recupera-lo.")
        return claimed

    def update_progress(
        self,
        job_id: str,
        current: int,
        total: int | None,
        message: str | None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                jobs_table.update()
                .where(jobs_table.c.id == job_id)
                .values(
                    progress_current=current,
                    progress_total=total,
                    progress_message=message,
                    updated_at=utc_now(),
                )
            )

    def is_cancellation_requested(self, job_id: str) -> bool:
        with self.engine.connect() as connection:
            value = connection.execute(
                select(jobs_table.c.cancellation_requested).where(jobs_table.c.id == job_id)
            ).scalar_one_or_none()
        return bool(value)

    def clear_results(self, job_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(job_results_table.delete().where(job_results_table.c.job_id == job_id))

    def save_result_page(
        self,
        job_id: str,
        sequence: int,
        payload: list[dict[str, Any]],
        checksum: str,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                job_results_table.insert().values(
                    id=new_id(),
                    job_id=job_id,
                    sequence=sequence,
                    payload_json=payload,
                    checksum=checksum,
                    record_count=len(payload),
                    created_at=utc_now(),
                )
            )

    def complete_job(
        self,
        job_id: str,
        attempt_number: int,
        result_count: int,
        result_checksum: str,
    ) -> None:
        now = utc_now()
        with self.engine.begin() as connection:
            connection.execute(
                jobs_table.update()
                .where(jobs_table.c.id == job_id)
                .values(
                    status="COMPLETED",
                    finished_at=now,
                    updated_at=now,
                    result_count=result_count,
                    result_checksum=result_checksum,
                    progress_current=result_count,
                    progress_total=result_count,
                    progress_message="Concluido",
                )
            )
            connection.execute(
                job_attempts_table.update()
                .where(
                    and_(
                        job_attempts_table.c.job_id == job_id,
                        job_attempts_table.c.attempt_number == attempt_number,
                    )
                )
                .values(status="COMPLETED", finished_at=now)
            )

    def fail_job(
        self,
        job_id: str,
        attempt_number: int,
        error_code: str,
        error_message: str,
        retry: bool,
    ) -> None:
        now = utc_now()
        next_status = "RETRYING" if retry else "FAILED"
        with self.engine.begin() as connection:
            connection.execute(
                jobs_table.update()
                .where(jobs_table.c.id == job_id)
                .values(
                    status=next_status,
                    finished_at=None if retry else now,
                    updated_at=now,
                    error_code=error_code,
                    error_message=error_message[:1000],
                )
            )
            connection.execute(
                job_attempts_table.update()
                .where(
                    and_(
                        job_attempts_table.c.job_id == job_id,
                        job_attempts_table.c.attempt_number == attempt_number,
                    )
                )
                .values(
                    status="RETRYING" if retry else "FAILED",
                    finished_at=now,
                    error_code=error_code,
                    error_message=error_message[:1000],
                )
            )

    def cancel_running_job(self, job_id: str, attempt_number: int) -> None:
        now = utc_now()
        with self.engine.begin() as connection:
            connection.execute(
                jobs_table.update()
                .where(jobs_table.c.id == job_id)
                .values(
                    status="CANCELLED",
                    finished_at=now,
                    updated_at=now,
                    progress_message="Cancelado",
                )
            )
            connection.execute(
                job_attempts_table.update()
                .where(
                    and_(
                        job_attempts_table.c.job_id == job_id,
                        job_attempts_table.c.attempt_number == attempt_number,
                    )
                )
                .values(status="CANCELLED", finished_at=now)
            )

    def requeue_job(self, job_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                jobs_table.update()
                .where(jobs_table.c.id == job_id)
                .values(status="QUEUED", updated_at=utc_now())
            )

    def request_cancel(self, job_id: str, client_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(jobs_table).where(
                    and_(jobs_table.c.id == job_id, jobs_table.c.client_id == client_id)
                ).with_for_update()
            ).mappings().first()
            if row is None:
                return None
            status = row["status"]
            if status == "QUEUED":
                connection.execute(
                    jobs_table.update()
                    .where(jobs_table.c.id == job_id)
                    .values(
                        status="CANCELLED",
                        cancellation_requested=True,
                        finished_at=now,
                        updated_at=now,
                    )
                )
            elif status == "RUNNING":
                connection.execute(
                    jobs_table.update()
                    .where(jobs_table.c.id == job_id)
                    .values(cancellation_requested=True, updated_at=now)
                )

        return self.get_job(job_id, client_id)

    def set_system_mode(self, mode: str, reason: str | None, client_id: str | None) -> None:
        now = utc_now()
        values = {
            "id": "global",
            "mode": mode,
            "reason": reason,
            "changed_by_client_id": client_id,
            "changed_at": now,
        }
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(system_state_table.c.id).where(system_state_table.c.id == "global")
            ).first()
            if existing is None:
                connection.execute(system_state_table.insert().values(values))
            else:
                connection.execute(
                    system_state_table.update()
                    .where(system_state_table.c.id == "global")
                    .values({key: value for key, value in values.items() if key != "id"})
                )

    def get_system_state(self) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(system_state_table).where(system_state_table.c.id == "global")
            ).mappings().first()
        if row is not None:
            return dict(row)
        return {
            "id": "global",
            "mode": "RUNNING",
            "reason": None,
            "changed_by_client_id": None,
            "changed_at": None,
        }

    def complete_pause_if_idle(self) -> None:
        with self.engine.begin() as connection:
            state = connection.execute(
                select(system_state_table.c.mode).where(system_state_table.c.id == "global")
            ).scalar_one_or_none()
            if state != "PAUSING":
                return
            running = connection.execute(
                select(jobs_table.c.id).where(jobs_table.c.status == "RUNNING").limit(1)
            ).first()
            if running is None:
                connection.execute(
                    system_state_table.update()
                    .where(system_state_table.c.id == "global")
                    .values(mode="PAUSED", changed_at=utc_now())
                )

    def insert_event(self, event: dict[str, Any]) -> bool:
        try:
            with self.engine.begin() as connection:
                connection.execute(events_table.insert().values(event))
        except IntegrityError:
            return False
        return True

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(events_table).where(events_table.c.event_id == event_id)
            ).mappings().first()
        return dict(row) if row is not None else None

    def create_webhook_delivery(self, event_id: str, attempt_number: int) -> str:
        delivery_id = new_id()
        with self.engine.begin() as connection:
            connection.execute(
                webhook_deliveries_table.insert().values(
                    id=delivery_id,
                    event_id=event_id,
                    attempt_number=attempt_number,
                    status="DELIVERING",
                    http_status=None,
                    next_attempt_at=None,
                    response_excerpt=None,
                    started_at=utc_now(),
                    finished_at=None,
                )
            )
        return delivery_id

    def finish_webhook_delivery(
        self,
        delivery_id: str,
        status: str,
        http_status: int | None,
        response_excerpt: str | None,
        next_attempt_at: datetime | None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                webhook_deliveries_table.update()
                .where(webhook_deliveries_table.c.id == delivery_id)
                .values(
                    status=status,
                    http_status=http_status,
                    response_excerpt=(response_excerpt or "")[:500],
                    next_attempt_at=next_attempt_at,
                    finished_at=utc_now(),
                )
            )

    def next_webhook_attempt(self, event_id: str) -> int:
        from sqlalchemy import func

        with self.engine.connect() as connection:
            value = connection.execute(
                select(func.max(webhook_deliveries_table.c.attempt_number)).where(
                    webhook_deliveries_table.c.event_id == event_id
                )
            ).scalar_one()
        return int(value or 0) + 1

    def list_result_page(
        self,
        job_id: str,
        sequence: int,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], tuple[int, int] | None]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(job_results_table)
                .where(
                    and_(
                        job_results_table.c.job_id == job_id,
                        job_results_table.c.sequence >= sequence,
                    )
                )
                .order_by(job_results_table.c.sequence.asc())
            ).mappings().all()
        data: list[dict[str, Any]] = []
        for row in rows:
            payload = row["payload_json"]
            if not isinstance(payload, list):
                continue
            start = offset if int(row["sequence"]) == sequence else 0
            available = payload[start:]
            remaining = limit - len(data)
            data.extend(available[:remaining])
            if len(available) > remaining:
                return data, (int(row["sequence"]), start + remaining)
            offset = 0

        return data, None

    def save_event_for_job(self, job: dict[str, Any], event_type: str) -> str:
        event_id = f"evt_{new_id()}"
        payload = {
            "event_id": event_id,
            "event": event_type,
            "occurred_at": utc_now().isoformat() + "Z",
            "job": {
                "id": job["id"],
                "collector": job["collector"],
                "collector_version": job["collector_version"],
                "status": job["status"],
                "result_count": job.get("result_count"),
                "result_checksum": job.get("result_checksum"),
            },
        }
        self.insert_event(
            {
                "event_id": event_id,
                "job_id": job["id"],
                "client_id": job["client_id"],
                "event_type": event_type,
                "payload_json": payload,
                "occurred_at": utc_now(),
                "created_at": utc_now(),
            }
        )
        return event_id

    def nonce_exists(self, client_id: str, nonce: str) -> bool:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(nonces_table.c.nonce).where(
                    and_(
                        nonces_table.c.client_id == client_id,
                        nonces_table.c.nonce == nonce,
                        nonces_table.c.expires_at >= utc_now(),
                    )
                )
            ).first()
        return row is not None

    def save_nonce(self, client_id: str, nonce: str, ttl_seconds: int) -> bool:
        try:
            with self.engine.begin() as connection:
                now = utc_now()
                connection.execute(
                    nonces_table.delete().where(
                        and_(
                            nonces_table.c.client_id == client_id,
                            nonces_table.c.nonce == nonce,
                            nonces_table.c.expires_at < now,
                        )
                    )
                )
                connection.execute(
                    nonces_table.insert().values(
                        client_id=client_id,
                        nonce=nonce,
                        expires_at=now + timedelta(seconds=ttl_seconds),
                    )
                )
        except IntegrityError:
            return False
        return True

    def purge_expired_nonces(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(nonces_table.delete().where(nonces_table.c.expires_at < utc_now()))
