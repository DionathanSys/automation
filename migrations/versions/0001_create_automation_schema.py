"""create automation operational schema

Revision ID: 0001_create_automation_schema
Revises:
Create Date: 2026-09-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_create_automation_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_clients",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_secret_hash", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("allowed_collectors", sa.JSON(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("callback_url", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "automation_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("collector", sa.String(length=150), nullable=False),
        sa.Column("collector_version", sa.String(length=50), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("progress_message", sa.String(length=500), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("result_checksum", sa.String(length=128), nullable=True),
        sa.Column("retry_of_job_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "idempotency_key", name="uq_automation_job_idempotency"),
    )
    op.create_index("ix_automation_jobs_client_id", "automation_jobs", ["client_id"])
    op.create_index("ix_automation_jobs_status", "automation_jobs", ["status"])
    op.create_index("ix_automation_jobs_requested_at", "automation_jobs", ["requested_at"])

    op.create_table(
        "automation_job_attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("diagnostic_metadata_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automation_job_attempts_job_id", "automation_job_attempts", ["job_id"])

    op.create_table(
        "automation_job_results",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "sequence", name="uq_automation_job_result_sequence"),
    )
    op.create_index("ix_automation_job_results_job_id", "automation_job_results", ["job_id"])

    op.create_table(
        "automation_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_automation_events_job_id", "automation_events", ["job_id"])
    op.create_index("ix_automation_events_client_id", "automation_events", ["client_id"])

    op.create_table(
        "automation_webhook_deliveries",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("response_excerpt", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automation_webhook_deliveries_event_id", "automation_webhook_deliveries", ["event_id"])

    op.create_table(
        "automation_system_state",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("changed_by_client_id", sa.String(length=64), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "automation_hmac_nonces",
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("client_id", "nonce"),
    )
    op.create_index("ix_automation_hmac_nonces_expires_at", "automation_hmac_nonces", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_automation_hmac_nonces_expires_at", table_name="automation_hmac_nonces")
    op.drop_table("automation_hmac_nonces")
    op.drop_table("automation_system_state")
    op.drop_index("ix_automation_webhook_deliveries_event_id", table_name="automation_webhook_deliveries")
    op.drop_table("automation_webhook_deliveries")
    op.drop_index("ix_automation_events_client_id", table_name="automation_events")
    op.drop_index("ix_automation_events_job_id", table_name="automation_events")
    op.drop_table("automation_events")
    op.drop_index("ix_automation_job_results_job_id", table_name="automation_job_results")
    op.drop_table("automation_job_results")
    op.drop_index("ix_automation_job_attempts_job_id", table_name="automation_job_attempts")
    op.drop_table("automation_job_attempts")
    op.drop_index("ix_automation_jobs_requested_at", table_name="automation_jobs")
    op.drop_index("ix_automation_jobs_status", table_name="automation_jobs")
    op.drop_index("ix_automation_jobs_client_id", table_name="automation_jobs")
    op.drop_table("automation_jobs")
    op.drop_table("automation_clients")
