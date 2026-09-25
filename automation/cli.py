from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from typing import Any

from automation.api import run_api
from automation.config import settings
from automation.db.automation_repository import AutomationRepository
from automation.db.connection import create_mysql_engine
from automation.db.migrations import upgrade_database
from automation.jobs.collector_registry import COLLECTOR_REGISTRY
from automation.utils.logger import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Servico de automacao sob demanda via API"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Lista os collectors disponiveis para jobs da API",
    )
    parser.add_argument("--serve-api", action="store_true", help="Inicia a API HTTP")
    parser.add_argument(
        "--init-automation-db",
        action="store_true",
        help="Executa as migrations operacionais no MySQL",
    )
    parser.add_argument(
        "--list-jobs",
        action="store_true",
        help="Lista os jobs recentes do cliente configurado",
    )
    parser.add_argument(
        "--inspect-job",
        metavar="JOB_ID",
        help="Mostra job, tentativas, eventos e entregas de webhook em JSON",
    )
    parser.add_argument(
        "--watch-job",
        metavar="JOB_ID",
        help="Acompanha o status de um job ate um estado terminal",
    )
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=2.0,
        help="Intervalo em segundos do --watch-job (padrao: 2)",
    )
    parser.add_argument("--job-status", help="Filtra --list-jobs por status")
    parser.add_argument("--job-collector", help="Filtra --list-jobs por collector")
    parser.add_argument("--limit", type=int, default=50, help="Limite do --list-jobs")
    return parser


def main() -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    if args.list_jobs:
        repository = _repository()
        jobs = repository.list_jobs(
            settings.automation.client_id,
            status=args.job_status,
            collector=args.job_collector,
            limit=max(1, min(args.limit, 100)),
        )
        print(json.dumps(jobs, ensure_ascii=False, indent=2, default=_json_default))
        return 0

    if args.inspect_job:
        repository = _repository()
        job = repository.get_job(args.inspect_job)
        if job is None:
            print(f"Job nao encontrado: {args.inspect_job}")
            return 2
        print(
            json.dumps(
                {"job": job, **repository.get_job_diagnostics(args.inspect_job)},
                ensure_ascii=False,
                indent=2,
                default=_json_default,
            )
        )
        return 0

    if args.watch_job:
        return _watch_job(args.watch_job, args.watch_interval)

    if args.init_automation_db:
        automation_repository = AutomationRepository(create_mysql_engine())
        upgrade_database()
        automation_repository.ensure_schema()
        automation_repository.ensure_configured_client()
        print("Banco operacional da automacao inicializado.")
        return 0

    if args.serve_api:
        run_api()
        return 0

    if args.list:
        for definition in COLLECTOR_REGISTRY.values():
            print(
                f"{definition.name} version={definition.version} "
                f"schema={definition.schema_version} "
                f"max_concurrency={definition.max_concurrency}"
            )
        return 0

    parser.print_help()
    return 1


def _repository() -> AutomationRepository:
    repository = AutomationRepository(create_mysql_engine())
    repository.ensure_schema()
    return repository


def _watch_job(job_id: str, interval: float) -> int:
    repository = _repository()
    interval = max(interval, 0.5)
    previous_snapshot: tuple[Any, ...] | None = None
    terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}

    while True:
        job = repository.get_job(job_id)
        if job is None:
            print(f"Job nao encontrado: {job_id}")
            return 2

        snapshot = (
            job.get("status"),
            job.get("attempts"),
            job.get("progress_current"),
            job.get("progress_total"),
            job.get("progress_message"),
            job.get("error_code"),
            job.get("error_message"),
        )
        if snapshot != previous_snapshot:
            current = job.get("progress_current") or 0
            total = job.get("progress_total")
            progress = f"{current}/{total}" if total else str(current)
            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] "
                f"status={job.get('status')} attempts={job.get('attempts')} "
                f"progress={progress} message={job.get('progress_message') or '-'} "
                f"error={job.get('error_code') or '-'}"
            )
            previous_snapshot = snapshot

        if job.get("status") in terminal_statuses:
            return 0 if job.get("status") == "COMPLETED" else 1
        time.sleep(interval)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    return str(value)
