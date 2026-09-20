from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreateJobRequest(BaseModel):
    collector: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetryJobRequest(BaseModel):
    requested_by: str | None = None


class PauseRequest(BaseModel):
    reason: str | None = None


class JobProgressResponse(BaseModel):
    current: int
    total: int | None
    percentage: int | None
    message: str | None


class JobResponse(BaseModel):
    id: str
    collector: str
    collector_version: str
    schema_version: str
    status: str
    progress: JobProgressResponse
    attempts: int
    max_attempts: int
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    requested_by: str | None
    error: dict[str, str] | None


class CancelResponse(BaseModel):
    id: str
    cancellation_requested: bool
