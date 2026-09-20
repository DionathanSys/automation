from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Integer, MetaData, String, Table, Text, UniqueConstraint

automation_metadata = MetaData()


clients_table = Table(
    "automation_clients",
    automation_metadata,
    Column("id", String(64), primary_key=True),
    Column("code", String(100), nullable=False, unique=True),
    Column("name", String(255), nullable=False),
    Column("secret_hash", String(64), nullable=False),
    Column("previous_secret_hash", String(64)),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("allowed_collectors", JSON, nullable=False),
    Column("scopes", JSON, nullable=False),
    Column("callback_url", String(2048)),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)


jobs_table = Table(
    "automation_jobs",
    automation_metadata,
    Column("id", String(64), primary_key=True),
    Column("client_id", String(64), nullable=False),
    Column("collector", String(150), nullable=False),
    Column("collector_version", String(50), nullable=False),
    Column("schema_version", String(50), nullable=False),
    Column("status", String(30), nullable=False),
    Column("parameters_json", JSON, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("requested_by", String(255)),
    Column("idempotency_key", String(255), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("progress_current", Integer, nullable=False, default=0),
    Column("progress_total", Integer),
    Column("progress_message", String(500)),
    Column("requested_at", DateTime, nullable=False),
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False, default=3),
    Column("cancellation_requested", Boolean, nullable=False, default=False),
    Column("error_code", String(100)),
    Column("error_message", String(1000)),
    Column("result_count", Integer),
    Column("result_checksum", String(128)),
    Column("retry_of_job_id", String(64)),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    UniqueConstraint("client_id", "idempotency_key", name="uq_automation_job_idempotency"),
)


job_attempts_table = Table(
    "automation_job_attempts",
    automation_metadata,
    Column("id", String(64), primary_key=True),
    Column("job_id", String(64), nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("worker_id", String(255)),
    Column("status", String(30), nullable=False),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
    Column("error_code", String(100)),
    Column("error_message", String(1000)),
    Column("diagnostic_metadata_json", JSON),
)


job_results_table = Table(
    "automation_job_results",
    automation_metadata,
    Column("id", String(64), primary_key=True),
    Column("job_id", String(64), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("payload_json", JSON, nullable=False),
    Column("checksum", String(128), nullable=False),
    Column("record_count", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False),
    UniqueConstraint("job_id", "sequence", name="uq_automation_job_result_sequence"),
)


events_table = Table(
    "automation_events",
    automation_metadata,
    Column("event_id", String(64), primary_key=True),
    Column("job_id", String(64), nullable=False),
    Column("client_id", String(64), nullable=False),
    Column("event_type", String(100), nullable=False),
    Column("payload_json", JSON, nullable=False),
    Column("occurred_at", DateTime, nullable=False),
    Column("created_at", DateTime, nullable=False),
)


webhook_deliveries_table = Table(
    "automation_webhook_deliveries",
    automation_metadata,
    Column("id", String(64), primary_key=True),
    Column("event_id", String(64), nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("status", String(30), nullable=False),
    Column("http_status", Integer),
    Column("next_attempt_at", DateTime),
    Column("response_excerpt", Text),
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
)


system_state_table = Table(
    "automation_system_state",
    automation_metadata,
    Column("id", String(32), primary_key=True),
    Column("mode", String(30), nullable=False),
    Column("reason", String(1000)),
    Column("changed_by_client_id", String(64)),
    Column("changed_at", DateTime, nullable=False),
)


nonces_table = Table(
    "automation_hmac_nonces",
    automation_metadata,
    Column("client_id", String(64), primary_key=True),
    Column("nonce", String(255), primary_key=True),
    Column("expires_at", DateTime, nullable=False),
)


Index("ix_automation_jobs_client_id", jobs_table.c.client_id)
Index("ix_automation_jobs_status", jobs_table.c.status)
Index("ix_automation_jobs_requested_at", jobs_table.c.requested_at)
Index("ix_automation_job_attempts_job_id", job_attempts_table.c.job_id)
Index("ix_automation_job_results_job_id", job_results_table.c.job_id)
Index("ix_automation_events_job_id", events_table.c.job_id)
Index("ix_automation_events_client_id", events_table.c.client_id)
Index("ix_automation_webhook_deliveries_event_id", webhook_deliveries_table.c.event_id)
Index("ix_automation_hmac_nonces_expires_at", nonces_table.c.expires_at)
