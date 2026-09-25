from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Callable

from automation.config import settings
from automation.db.automation_repository import AutomationRepository, new_id, utc_now
from automation.jobs.collector_registry import COLLECTOR_REGISTRY


class JobServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class JobService:
    def __init__(
        self,
        repository: AutomationRepository,
        enqueue: Callable[[str], None] | None = None,
    ) -> None:
        self.repository = repository
        self._enqueue = enqueue

    def create_job(
        self,
        *,
        client: dict[str, Any],
        collector_name: str,
        parameters: dict[str, Any],
        requested_by: str | None,
        metadata: dict[str, Any],
        idempotency_key: str,
        retry_of_job_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        definition = COLLECTOR_REGISTRY.get(collector_name)
        if definition is None:
            raise JobServiceError("VALIDATION_ERROR", "Collector desconhecido.", 422)
        self._ensure_collector_allowed(client, collector_name)
        if not idempotency_key.strip():
            raise JobServiceError("VALIDATION_ERROR", "Idempotency-Key obrigatoria.", 422)

        request_hash = self._request_hash(collector_name, parameters, requested_by, metadata)
        existing = self.repository.find_job_by_idempotency(str(client["id"]), idempotency_key)
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise JobServiceError(
                    "IDEMPOTENCY_CONFLICT",
                    "A chave de idempotencia ja foi usada com outro conteudo.",
                    409,
                )
            return existing, False

        now = utc_now()
        job, created = self.repository.insert_job(
            {
                "id": new_id(),
                "client_id": client["id"],
                "collector": definition.name,
                "collector_version": definition.version,
                "schema_version": definition.schema_version,
                "status": "QUEUED",
                "parameters_json": parameters,
                "metadata_json": metadata,
                "requested_by": requested_by,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "progress_current": 0,
                "progress_total": None,
                "progress_message": None,
                "requested_at": now,
                "started_at": None,
                "finished_at": None,
                "attempts": 0,
                "max_attempts": settings.automation.default_max_attempts,
                "cancellation_requested": False,
                "error_code": None,
                "error_message": None,
                "result_count": None,
                "result_checksum": None,
                "retry_of_job_id": retry_of_job_id,
                "created_at": now,
                "updated_at": now,
            }
        )
        if created and self._enqueue is not None:
            self._enqueue_or_raise(job["id"])
        return job, created

    def _enqueue_or_raise(self, job_id: str) -> None:
        try:
            self._enqueue(job_id)  # type: ignore[misc]
        except Exception as exc:
            raise JobServiceError(
                "DEPENDENCY_UNAVAILABLE",
                "Nao foi possivel enfileirar o job.",
                503,
            ) from exc

    def retry_job(
        self,
        *,
        client: dict[str, Any],
        job_id: str,
        idempotency_key: str,
        requested_by: str | None,
    ) -> tuple[dict[str, Any], bool]:
        original = self.repository.get_job(job_id, str(client["id"]))
        if original is None:
            raise JobServiceError("JOB_NOT_FOUND", "Job nao encontrado.", 404)
        if original["status"] not in {"FAILED", "CANCELLED"}:
            raise JobServiceError(
                "JOB_NOT_RETRYABLE",
                "Somente jobs FAILED ou CANCELLED podem ser repetidos.",
                409,
            )
        return self.create_job(
            client=client,
            collector_name=str(original["collector"]),
            parameters=original["parameters_json"] or {},
            requested_by=requested_by,
            metadata={
                **(original["metadata_json"] or {}),
                "retry_of_job_id": original["id"],
            },
            idempotency_key=idempotency_key,
            retry_of_job_id=str(original["id"]),
        )

    def get_job(self, client: dict[str, Any], job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id, str(client["id"]))
        if job is None:
            raise JobServiceError("JOB_NOT_FOUND", "Job nao encontrado.", 404)
        return job

    def list_jobs(
        self,
        client: dict[str, Any],
        status: str | None,
        collector: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        bounded_limit = min(max(limit, 1), 100)
        return self.repository.list_jobs(
            str(client["id"]),
            status=status,
            collector=collector,
            limit=bounded_limit,
        )

    def get_diagnostics(self, client: dict[str, Any], job_id: str) -> dict[str, Any]:
        job = self.get_job(client, job_id)
        return {
            "job": job,
            **self.repository.get_job_diagnostics(job_id),
        }

    def cancel_job(self, client: dict[str, Any], job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id, str(client["id"]))
        if job is None:
            raise JobServiceError("JOB_NOT_FOUND", "Job nao encontrado.", 404)
        if job["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise JobServiceError(
                "JOB_NOT_CANCELLABLE",
                "O job esta em um estado terminal.",
                409,
            )
        updated = self.repository.request_cancel(job_id, str(client["id"]))
        if updated is None:
            raise JobServiceError("JOB_NOT_FOUND", "Job nao encontrado.", 404)
        return updated

    def get_result(
        self,
        client: dict[str, Any],
        job_id: str,
        cursor: str | None,
        limit: int,
    ) -> dict[str, Any]:
        job = self.get_job(client, job_id)
        if job["status"] != "COMPLETED":
            raise JobServiceError(
                "RESULT_NOT_AVAILABLE",
                "O resultado ainda nao esta disponivel.",
                409,
            )
        bounded_limit = min(max(limit, 1), settings.automation.max_result_page_size)
        sequence, offset = self._decode_cursor(cursor)
        data, next_position = self.repository.list_result_page(
            job_id,
            sequence,
            offset,
            bounded_limit,
        )
        next_cursor = self._encode_cursor(*next_position) if next_position else None
        return {
            "data": data,
            "meta": {
                "job_id": job["id"],
                "collector": job["collector"],
                "schema_version": job["schema_version"],
                "count": len(data),
                "total": job["result_count"] or 0,
                "next_cursor": next_cursor,
                "checksum": job["result_checksum"],
            },
        }

    def set_system_mode(self, client: dict[str, Any], mode: str, reason: str | None) -> None:
        self._require_scope(client, "system:control")
        self.repository.set_system_mode(mode, reason, str(client["id"]))

    @staticmethod
    def _request_hash(
        collector: str,
        parameters: dict[str, Any],
        requested_by: str | None,
        metadata: dict[str, Any],
    ) -> str:
        payload = {
            "collector": collector,
            "parameters": parameters,
            "requested_by": requested_by,
            "metadata": metadata,
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _ensure_collector_allowed(client: dict[str, Any], collector_name: str) -> None:
        allowed = set(client.get("allowed_collectors") or [])
        if "*" not in allowed and collector_name not in allowed:
            raise JobServiceError("CLIENT_FORBIDDEN", "Collector nao permitido para o cliente.", 403)

    @staticmethod
    def _require_scope(client: dict[str, Any], scope: str) -> None:
        if scope not in set(client.get("scopes") or []):
            raise JobServiceError("CLIENT_FORBIDDEN", "Escopo insuficiente.", 403)

    @staticmethod
    def _encode_cursor(sequence: int, offset: int = 0) -> str:
        value = f"{sequence}:{offset}"
        return base64.urlsafe_b64encode(value.encode("ascii")).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> tuple[int, int]:
        if not cursor:
            return 0, 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            sequence_text, offset_text = base64.urlsafe_b64decode(
                padded.encode("ascii")
            ).decode("ascii").split(":", 1)
            sequence = int(sequence_text)
            offset = int(offset_text)
        except (ValueError, UnicodeDecodeError) as exc:
            raise JobServiceError("VALIDATION_ERROR", "Cursor invalido.", 422) from exc
        if sequence < 0 or offset < 0:
            raise JobServiceError("VALIDATION_ERROR", "Cursor invalido.", 422)
        return sequence, offset
