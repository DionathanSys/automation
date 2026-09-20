from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

import uvicorn
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine

from automation.api_schemas import CreateJobRequest, PauseRequest, RetryJobRequest
from automation.config import settings
from automation.db.automation_repository import AutomationRepository, new_id
from automation.db.connection import create_mysql_engine
from automation.jobs.collector_registry import COLLECTOR_REGISTRY
from automation.jobs.service import JobService, JobServiceError
from automation.utils.logger import get_logger
from automation.security.hmac import HmacAuthenticationError, HmacAuthenticator
from automation.db.schema import jobs_table
from automation.jobs.worker import enqueue_job


logger = get_logger(__name__)


def create_app(
    engine: Engine | None = None,
    enqueue: Callable[[str], None] | None = None,
) -> FastAPI:
    engine = engine or create_mysql_engine()
    automation_repository = AutomationRepository(engine)
    authenticator = HmacAuthenticator(automation_repository)
    job_service = JobService(automation_repository, enqueue=enqueue or enqueue_job)

    app = FastAPI(title="Automation API", version="1.0.0")

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or f"req_{new_id()}"
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.on_event("startup")
    def on_startup() -> None:
        try:
            automation_repository.ensure_schema()
            automation_repository.ensure_configured_client()
        except Exception:
            logger.exception("Falha ao inicializar o banco operacional.")

    @app.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def readiness() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "unavailable"

        try:
            from redis import Redis

            Redis.from_url(settings.queue.redis_url).ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "unavailable"

        ready = all(value == "ok" for value in checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ok" if ready else "not_ready", "checks": checks},
        )

    @app.exception_handler(JobServiceError)
    async def handle_job_service_error(request: Request, exc: JobServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": getattr(request.state, "request_id", str(uuid4())),
                }
            },
        )

    @app.exception_handler(HmacAuthenticationError)
    async def handle_hmac_error(request: Request, exc: HmacAuthenticationError) -> JSONResponse:
        return JSONResponse(
            status_code=401 if exc.code in {"INVALID_SIGNATURE", "REPLAY_DETECTED"} else 403,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": getattr(request.state, "request_id", str(uuid4())),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details: dict[str, list[str]] = {}
        for error_item in exc.errors():
            location = ".".join(str(part) for part in error_item.get("loc", []))
            details.setdefault(location, []).append(str(error_item.get("msg", "Valor invalido.")))
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Os parametros informados sao invalidos.",
                    "details": details,
                    "request_id": getattr(request.state, "request_id", str(uuid4())),
                }
            },
        )

    def authenticated_client(scope: str | None = None):
        async def dependency(
            request: Request,
            x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
            x_timestamp: str | None = Header(default=None, alias="X-Timestamp"),
            x_nonce: str | None = Header(default=None, alias="X-Nonce"),
            x_signature: str | None = Header(default=None, alias="X-Signature"),
            x_signature_version: str | None = Header(default=None, alias="X-Signature-Version"),
        ) -> dict[str, Any]:
            path_with_query = request.url.path
            if request.url.query:
                path_with_query = f"{path_with_query}?{request.url.query}"
            client = authenticator.authenticate(
                client_code=x_client_id,
                timestamp=x_timestamp,
                nonce=x_nonce,
                signature=x_signature,
                signature_version=x_signature_version,
                method=request.method,
                path_with_query=path_with_query,
                raw_body=await request.body(),
            )
            if scope and scope not in client.scopes:
                raise HmacAuthenticationError("CLIENT_FORBIDDEN", "Escopo insuficiente.")
            return {
                "id": client.id,
                "code": client.code,
                "scopes": list(client.scopes),
                "allowed_collectors": list(client.allowed_collectors),
                "callback_url": client.callback_url,
            }

        return dependency

    @app.post("/api/v1/jobs", status_code=202)
    def create_job(
        payload: CreateJobRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        client: dict[str, Any] = Depends(authenticated_client("jobs:write")),
    ) -> JSONResponse:
        if not idempotency_key:
            raise JobServiceError("VALIDATION_ERROR", "Idempotency-Key obrigatoria.", 422)
        job, created = job_service.create_job(
            client=client,
            collector_name=payload.collector,
            parameters=payload.parameters,
            requested_by=payload.requested_by,
            metadata=payload.metadata,
            idempotency_key=idempotency_key,
        )
        return JSONResponse(
            status_code=202 if created else 200,
            content={"data": _serialize_job(job)},
        )

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(
        job_id: str,
        client: dict[str, Any] = Depends(authenticated_client("jobs:read")),
    ) -> dict[str, Any]:
        return {"data": _serialize_job(job_service.get_job(client, job_id))}

    @app.get("/api/v1/jobs/{job_id}/result")
    def get_job_result(
        job_id: str,
        cursor: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1),
        client: dict[str, Any] = Depends(authenticated_client("jobs:read")),
    ) -> dict[str, Any]:
        return job_service.get_result(client, job_id, cursor, limit)

    @app.post("/api/v1/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(
        job_id: str,
        client: dict[str, Any] = Depends(authenticated_client("jobs:write")),
    ) -> dict[str, Any]:
        job = job_service.cancel_job(client, job_id)
        return {
            "data": {
                "id": job["id"],
                "cancellation_requested": bool(job["cancellation_requested"]),
            }
        }

    @app.post("/api/v1/jobs/{job_id}/retry", status_code=202)
    def retry_job(
        job_id: str,
        payload: RetryJobRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        client: dict[str, Any] = Depends(authenticated_client("jobs:write")),
    ) -> JSONResponse:
        if not idempotency_key:
            raise JobServiceError("VALIDATION_ERROR", "Idempotency-Key obrigatoria.", 422)
        job, created = job_service.retry_job(
            client=client,
            job_id=job_id,
            idempotency_key=idempotency_key,
            requested_by=payload.requested_by,
        )
        return JSONResponse(
            status_code=202 if created else 200,
            content={"data": _serialize_job(job)},
        )

    @app.get("/api/v1/collectors")
    def list_collectors(
        client: dict[str, Any] = Depends(authenticated_client("collectors:read")),
    ) -> dict[str, Any]:
        allowed = set(client.get("allowed_collectors") or [])
        definitions = [
            {
                "name": definition.name,
                "version": definition.version,
                "schema_version": definition.schema_version,
                "enabled": True,
                "max_concurrency": definition.max_concurrency,
            }
            for definition in COLLECTOR_REGISTRY.values()
            if not allowed or "*" in allowed or definition.name in allowed
        ]
        return {"data": definitions}

    @app.get("/api/v1/system/status")
    def system_status(
        client: dict[str, Any] = Depends(authenticated_client("system:read")),
    ) -> dict[str, Any]:
        automation_repository.complete_pause_if_idle()
        state = automation_repository.get_system_state()
        with engine.connect() as connection:
            queued = connection.execute(
                select(func.count()).select_from(jobs_table).where(jobs_table.c.status == "QUEUED")
            ).scalar_one()
            running = connection.execute(
                select(func.count()).select_from(jobs_table).where(jobs_table.c.status == "RUNNING")
            ).scalar_one()
        return {
            "data": {
                "mode": state["mode"],
                "queued_jobs": queued,
                "running_jobs": running,
                "workers": {"online": 1, "expected": 1},
                "last_worker_heartbeat_at": None,
            }
        }

    @app.post("/api/v1/system/pause", status_code=202)
    def pause_system(
        payload: PauseRequest,
        client: dict[str, Any] = Depends(authenticated_client("system:control")),
    ) -> dict[str, Any]:
        job_service.set_system_mode(client, "PAUSING", payload.reason)
        return {"data": automation_repository.get_system_state()}

    @app.post("/api/v1/system/resume", status_code=202)
    def resume_system(
        client: dict[str, Any] = Depends(authenticated_client("system:control")),
    ) -> dict[str, Any]:
        job_service.set_system_mode(client, "RUNNING", None)
        return {"data": automation_repository.get_system_state()}

    return app


def run_api() -> None:
    uvicorn.run(
        "automation.api:create_app",
        factory=True,
        host=settings.api.host,
        port=settings.api.port,
    )


def _serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    total = job.get("progress_total")
    current = int(job.get("progress_current") or 0)
    percentage = None
    if total and total > 0:
        percentage = min(100, int(current * 100 / total))

    error = None
    if job.get("error_code") or job.get("error_message"):
        error = {
            "code": str(job.get("error_code") or "JOB_ERROR"),
            "message": str(job.get("error_message") or "Falha na execucao."),
        }

    def serialize_datetime(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat() + "Z"
        return str(value)

    return {
        "id": str(job["id"]),
        "collector": str(job["collector"]),
        "collector_version": str(job["collector_version"]),
        "schema_version": str(job["schema_version"]),
        "status": str(job["status"]),
        "progress": {
            "current": current,
            "total": total,
            "percentage": percentage,
            "message": job.get("progress_message"),
        },
        "attempts": int(job.get("attempts") or 0),
        "max_attempts": int(job.get("max_attempts") or 0),
        "requested_at": serialize_datetime(job.get("requested_at")),
        "started_at": serialize_datetime(job.get("started_at")),
        "finished_at": serialize_datetime(job.get("finished_at")),
        "requested_by": job.get("requested_by"),
        "error": error,
    }
