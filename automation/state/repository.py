from __future__ import annotations

import sqlite3
import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from automation.models import ReportCheckpoint


class SQLiteStateRepository:
    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path)
        if self.database_path.parent != Path("."):
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get_checkpoint(self, report_name: str) -> ReportCheckpoint | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT report_name, checkpoint_date, last_trip_number, updated_at
                FROM report_checkpoints
                WHERE report_name = ?
                """,
                (report_name,),
            ).fetchone()

        if row is None:
            return None

        return ReportCheckpoint(
            report_name=row[0],
            checkpoint_date=row[1],
            last_trip_number=row[2],
            updated_at=datetime.fromisoformat(row[3]),
        )

    def save_checkpoint(self, report_name: str, checkpoint_date: str, last_trip_number: int | None) -> None:
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO report_checkpoints (report_name, checkpoint_date, last_trip_number, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(report_name) DO UPDATE SET
                    checkpoint_date = excluded.checkpoint_date,
                    last_trip_number = excluded.last_trip_number,
                    updated_at = excluded.updated_at
                """,
                (report_name, checkpoint_date, last_trip_number, updated_at),
            )
            connection.commit()

    def record_closed_trips(self, trips: list[dict[str, object]]) -> list[dict[str, object]]:
        """Persiste a versao coletada e retorna somente viagens que precisam de envio."""
        if not trips:
            return []

        now = datetime.now(UTC).isoformat()
        pending: list[dict[str, object]] = []
        with self._connect() as connection:
            for trip in trips:
                trip_number = str(trip["numero_viagem"])
                payload = json.dumps(trip, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                existing = connection.execute(
                    "SELECT payload_hash, api_status FROM closed_trips WHERE trip_number = ?",
                    (trip_number,),
                ).fetchone()
                should_send = existing is None or existing[0] != payload_hash or existing[1] != "accepted"
                connection.execute(
                    """
                    INSERT INTO closed_trips (
                        trip_number, competence_date, payload, payload_hash, source_first_seen_at,
                        source_last_seen_at, api_status, api_accepted_at, last_attempt_at,
                        attempt_count, last_error, last_lote_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, NULL, NULL)
                    ON CONFLICT(trip_number) DO UPDATE SET
                        competence_date = excluded.competence_date,
                        payload = excluded.payload,
                        payload_hash = excluded.payload_hash,
                        source_last_seen_at = excluded.source_last_seen_at,
                        api_status = CASE
                            WHEN closed_trips.payload_hash != excluded.payload_hash THEN 'pending'
                            ELSE closed_trips.api_status
                        END,
                        api_accepted_at = CASE
                            WHEN closed_trips.payload_hash != excluded.payload_hash THEN NULL
                            ELSE closed_trips.api_accepted_at
                        END,
                        last_error = CASE
                            WHEN closed_trips.payload_hash != excluded.payload_hash THEN NULL
                            ELSE closed_trips.last_error
                        END
                    """,
                    (
                        trip_number,
                        str(trip["data_competencia"]),
                        payload,
                        payload_hash,
                        now,
                        now,
                        "pending",
                    ),
                )
                if should_send:
                    pending.append(trip)
            connection.commit()
        return pending

    def mark_closed_trips_accepted(self, trip_numbers: list[str], lote_id: str) -> None:
        self._update_closed_trip_delivery(trip_numbers, lote_id, "accepted", None)

    def mark_closed_trips_failed(self, trip_numbers: list[str], lote_id: str, error_message: str) -> None:
        self._update_closed_trip_delivery(trip_numbers, lote_id, "failed", error_message)

    def list_pending_closed_trips(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM closed_trips
                WHERE api_status IN ('pending', 'failed')
                ORDER BY competence_date, trip_number
                """
            ).fetchall()

        pending: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row[0])
            if not isinstance(payload, dict):
                raise RuntimeError("Payload armazenado de viagem encerrada invalido.")
            pending.append(payload)
        return pending

    def missing_closed_trip_numbers(self, trip_numbers: list[str]) -> list[str]:
        if not trip_numbers:
            return []
        placeholders = ", ".join("?" for _ in trip_numbers)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT trip_number FROM closed_trips WHERE trip_number IN ({placeholders})",
                trip_numbers,
            ).fetchall()
        existing = {row[0] for row in rows}
        return [trip_number for trip_number in trip_numbers if trip_number not in existing]

    def list_closed_trip_statuses(self, competence_date: str | None = None) -> list[dict[str, object]]:
        query = "SELECT trip_number, competence_date, api_status, api_accepted_at, last_attempt_at, attempt_count, last_error, last_lote_id FROM closed_trips"
        params: tuple[str, ...] = ()
        if competence_date:
            query += " WHERE competence_date = ?"
            params = (competence_date,)
        query += " ORDER BY competence_date, trip_number"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        fields = ("numero_viagem", "data_competencia", "status_api", "aceita_em", "ultima_tentativa_em", "tentativas", "ultimo_erro", "lote_id")
        return [dict(zip(fields, row, strict=True)) for row in rows]

    def _update_closed_trip_delivery(
        self,
        trip_numbers: list[str],
        lote_id: str,
        api_status: str,
        error_message: str | None,
    ) -> None:
        if not trip_numbers:
            return
        now = datetime.now(UTC).isoformat()
        placeholders = ", ".join("?" for _ in trip_numbers)
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE closed_trips
                SET api_status = ?,
                    api_accepted_at = CASE WHEN ? = 'accepted' THEN ? ELSE api_accepted_at END,
                    last_attempt_at = ?,
                    attempt_count = attempt_count + 1,
                    last_error = ?,
                    last_lote_id = ?
                WHERE trip_number IN ({placeholders})
                """,
                (api_status, api_status, now, now, error_message, lote_id, *trip_numbers),
            )
            connection.commit()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS report_checkpoints (
                    report_name TEXT PRIMARY KEY,
                    checkpoint_date TEXT NOT NULL,
                    last_trip_number INTEGER,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS closed_trips (
                    trip_number TEXT PRIMARY KEY,
                    competence_date TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    source_first_seen_at TEXT NOT NULL,
                    source_last_seen_at TEXT NOT NULL,
                    api_status TEXT NOT NULL CHECK(api_status IN ('pending', 'accepted', 'failed')),
                    api_accepted_at TEXT,
                    last_attempt_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    last_lote_id TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_closed_trips_competence_date ON closed_trips(competence_date)"
            )
            connection.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        try:
            yield connection
        finally:
            connection.close()
