from __future__ import annotations

import argparse

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
    return parser


def main() -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

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
