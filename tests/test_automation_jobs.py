from __future__ import annotations

import hashlib
import json
import time
import unittest
from unittest.mock import Mock, patch
from sqlalchemy import create_engine

from automation.db.automation_repository import AutomationRepository, new_id, utc_now
from automation.db.schema import clients_table
from automation.db.schema import events_table, webhook_deliveries_table
from automation.api import create_app
from automation.api_schemas import CreateJobRequest
from automation.config import settings
from automation.jobs.service import JobService, JobServiceError
from automation.security.hmac import HmacAuthenticator, HmacAuthenticationError, HmacSigner
from automation.services.webhook_service import WebhookService


class AutomationRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        self.repository = AutomationRepository(self.engine)
        self.repository.create_schema_for_tests()
        self.client = {
            "id": new_id(),
            "code": "test-client",
            "allowed_collectors": ["*"],
            "scopes": ["jobs:read", "jobs:write"],
        }
        now = utc_now()
        with self.engine.begin() as connection:
            connection.execute(
                clients_table.insert().values(
                    id=self.client["id"],
                    code=self.client["code"],
                    name="Test client",
                    secret_hash=hashlib.sha256(b"test-secret").hexdigest(),
                    is_active=True,
                    allowed_collectors=self.client["allowed_collectors"],
                    scopes=self.client["scopes"],
                    callback_url=None,
                    created_at=now,
                    updated_at=now,
                )
            )

    def test_job_creation_is_idempotent_and_conflicts_on_changed_body(self) -> None:
        queued: list[str] = []
        service = JobService(self.repository, enqueue=queued.append)

        job, created = service.create_job(
            client=self.client,
            collector_name="site_alpha_monitoring_trips",
            parameters={"vehicle": "ABC1D23"},
            requested_by="user:1",
            metadata={},
            idempotency_key="request-1",
        )
        repeated, repeated_created = service.create_job(
            client=self.client,
            collector_name="site_alpha_monitoring_trips",
            parameters={"vehicle": "ABC1D23"},
            requested_by="user:1",
            metadata={},
            idempotency_key="request-1",
        )

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(job["id"], repeated["id"])
        self.assertEqual([job["id"]], queued)

        with self.assertRaisesRegex(JobServiceError, "chave de idempotencia"):
            service.create_job(
                client=self.client,
                collector_name="site_alpha_monitoring_trips",
                parameters={"vehicle": "XYZ9Z99"},
                requested_by="user:1",
                metadata={},
                idempotency_key="request-1",
            )

    def test_result_cursor_is_stable_and_opaque(self) -> None:
        service = JobService(self.repository, enqueue=lambda _: None)
        job, _ = service.create_job(
            client=self.client,
            collector_name="site_alpha_monitoring_trips",
            parameters={},
            requested_by=None,
            metadata={},
            idempotency_key="result-1",
        )
        claimed = self.repository.claim_job(job["id"])
        assert claimed is not None
        self.repository.save_result_page(job["id"], 0, [{"external_id": "1"}, {"external_id": "2"}], "one")
        self.repository.save_result_page(job["id"], 1, [{"external_id": "3"}], "two")
        self.repository.complete_job(job["id"], 1, 3, "sha256:all")

        first = service.get_result(self.client, job["id"], None, 2)
        second = service.get_result(self.client, job["id"], first["meta"]["next_cursor"], 2)

        self.assertEqual(["1", "2"], [row["external_id"] for row in first["data"]])
        self.assertEqual(["3"], [row["external_id"] for row in second["data"]])
        self.assertIsNone(second["meta"]["next_cursor"])

    def test_lists_jobs_and_exposes_diagnostics(self) -> None:
        service = JobService(self.repository, enqueue=lambda _: None)
        job, _ = service.create_job(
            client=self.client,
            collector_name="site_alpha_monitoring_trips",
            parameters={"vehicle": "ABC1D23"},
            requested_by="user:1",
            metadata={"source": "filament"},
            idempotency_key="diagnostics-1",
        )
        claimed = self.repository.claim_job(job["id"])
        assert claimed is not None
        self.repository.complete_job(job["id"], 1, 0, "sha256:empty")
        completed = self.repository.get_job(job["id"])
        assert completed is not None
        event_id = self.repository.save_event_for_job(completed, "job.completed")

        listed = service.list_jobs(self.client, "COMPLETED", None, 10)
        diagnostics = service.get_diagnostics(self.client, job["id"])

        self.assertEqual([job["id"]], [item["id"] for item in listed])
        self.assertEqual("COMPLETED", diagnostics["job"]["status"])
        self.assertEqual("COMPLETED", diagnostics["attempts"][0]["status"])
        self.assertEqual(event_id, diagnostics["events"][0]["event_id"])
        self.assertEqual([], diagnostics["webhook_deliveries"])

    def test_post_accepts_daily_trip_summary_payload(self) -> None:
        queued: list[str] = []
        app = create_app(self.engine, enqueue=queued.append)
        route = next(
            route
            for route in app.routes
            if getattr(route, "path", None) == "/api/v1/jobs"
            and "POST" in getattr(route, "methods", set())
        )

        response = route.endpoint(
            CreateJobRequest(
                collector="daily_trip_summary",
                parameters={"date": "2026-09-19"},
                requested_by="user:1",
                metadata={
                    "local_job_id": "5",
                    "report_key": "daily_trip_summary",
                    "collector_version": "1.0.0",
                    "schema_version": "1.0",
                },
            ),
            "daily-trip-summary-2026-09-19-5",
            self.client,
        )

        self.assertEqual(202, response.status_code)
        body = json.loads(response.body)
        self.assertEqual("daily_trip_summary", body["data"]["collector"])
        self.assertEqual("1.0.0", body["data"]["collector_version"])
        self.assertEqual("1.0", body["data"]["schema_version"])
        self.assertEqual("QUEUED", body["data"]["status"])
        self.assertEqual([body["data"]["id"]], queued)

        collectors_route = next(
            route
            for route in app.routes
            if getattr(route, "path", None) == "/api/v1/collectors"
            and "GET" in getattr(route, "methods", set())
        )
        collectors_response = collectors_route.endpoint(self.client)
        collector_names = {item["name"] for item in collectors_response["data"]}
        self.assertIn("daily_trip_summary", collector_names)
        daily_definition = next(
            item
            for item in collectors_response["data"]
            if item["name"] == "daily_trip_summary"
        )
        self.assertEqual("1.0.0", daily_definition["version"])
        self.assertEqual("1.0", daily_definition["schema_version"])

    def test_empty_allowed_collectors_does_not_grant_access(self) -> None:
        restricted_client = {**self.client, "allowed_collectors": []}
        service = JobService(self.repository, enqueue=lambda _: None)

        with self.assertRaisesRegex(JobServiceError, "Collector nao permitido"):
            service.create_job(
                client=restricted_client,
                collector_name="daily_trip_summary",
                parameters={"date": "2026-09-19"},
                requested_by="user:1",
                metadata={},
                idempotency_key="restricted-1",
            )


class HmacTest(unittest.TestCase):
    def test_canonical_signature_and_nonce_replay(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        repository = AutomationRepository(engine)
        repository.create_schema_for_tests()
        now = utc_now()
        with engine.begin() as connection:
            connection.execute(
                clients_table.insert().values(
                    id="client-id",
                    code="configured-client",
                    name="Configured",
                    secret_hash=hashlib.sha256(b"configured-secret").hexdigest(),
                    is_active=True,
                    allowed_collectors=["*"],
                    scopes=["jobs:read"],
                    callback_url=None,
                    created_at=now,
                    updated_at=now,
                )
            )

        # The authenticator reads the configured credentials from the process environment.
        import automation.security.hmac as hmac_module

        original = hmac_module.settings.automation
        object.__setattr__(
            hmac_module.settings,
            "automation",
            original.__class__(
                client_id="configured-client",
                client_secret="configured-secret",
                hmac_timestamp_tolerance_seconds=300,
                nonce_ttl_seconds=600,
                max_result_page_size=500,
                default_max_attempts=3,
            ),
        )
        try:
            timestamp = str(int(time.time()))
            nonce = "nonce-1"
            body = b'{"collector":"site_alpha_monitoring_trips"}'
            signature = HmacSigner.sign(
                "configured-secret",
                "POST",
                "/api/v1/jobs",
                timestamp,
                nonce,
                body,
            )
            authenticator = HmacAuthenticator(repository)
            client = authenticator.authenticate(
                client_code="configured-client",
                timestamp=timestamp,
                nonce=nonce,
                signature=signature,
                signature_version="v1",
                method="POST",
                path_with_query="/api/v1/jobs",
                raw_body=body,
            )
            self.assertEqual("configured-client", client.code)
            with self.assertRaises(HmacAuthenticationError) as context:
                authenticator.authenticate(
                    client_code="configured-client",
                    timestamp=timestamp,
                    nonce=nonce,
                    signature=signature,
                    signature_version="v1",
                    method="POST",
                    path_with_query="/api/v1/jobs",
                    raw_body=body,
                )
            self.assertEqual("REPLAY_DETECTED", context.exception.code)
        finally:
            object.__setattr__(hmac_module.settings, "automation", original)


class WebhookTest(unittest.TestCase):
    def test_delivers_signed_event_and_records_attempt(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        repository = AutomationRepository(engine)
        repository.create_schema_for_tests()
        now = utc_now()
        with engine.begin() as connection:
            connection.execute(
                clients_table.insert().values(
                    id="client-id",
                    code="laravel-client",
                    name="Laravel",
                    secret_hash=hashlib.sha256(b"client-secret").hexdigest(),
                    previous_secret_hash=None,
                    is_active=True,
                    allowed_collectors=["*"],
                    scopes=["jobs:read"],
                    callback_url="https://laravel.test/api/integrations/automation/v1/webhooks",
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                events_table.insert().values(
                    event_id="evt_1",
                    job_id="job-1",
                    client_id="client-id",
                    event_type="job.completed",
                    payload_json={"event_id": "evt_1", "event": "job.completed"},
                    occurred_at=now,
                    created_at=now,
                )
            )

        import automation.services.webhook_service as webhook_module

        original = settings.automation
        object.__setattr__(
            settings,
            "automation",
            original.__class__(
                client_id=original.client_id,
                client_secret=original.client_secret,
                previous_client_secret=original.previous_client_secret,
                callback_url=original.callback_url,
                webhook_client_id="automation_prod",
                webhook_secret="webhook-secret",
                previous_webhook_secret="",
                hmac_timestamp_tolerance_seconds=300,
                nonce_ttl_seconds=600,
                max_result_page_size=500,
                default_max_attempts=3,
            ),
        )
        response = Mock(status=202)
        response.read.return_value = b'{"received":true}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        try:
            with patch.object(webhook_module.request, "urlopen", return_value=response) as urlopen:
                WebhookService(repository).deliver("evt_1")
            self.assertTrue(urlopen.called)
            with engine.connect() as connection:
                delivery = connection.execute(
                    webhook_deliveries_table.select()
                ).mappings().one()
            self.assertEqual("DELIVERED", delivery["status"])
            self.assertEqual(202, delivery["http_status"])
        finally:
            object.__setattr__(settings, "automation", original)


if __name__ == "__main__":
    unittest.main()
