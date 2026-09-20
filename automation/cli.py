from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from automation.api import run_api
from automation.config import settings
from automation.db.automation_repository import AutomationRepository
from automation.db.connection import create_mysql_engine
from automation.db.repository import MySQLRepository
from automation.jobs.interval import register_interval_job
from automation.jobs.registry import JOB_REGISTRY
from automation.reports import REPORT_REGISTRY
from automation.jobs.scheduler import start_automation_scheduler, start_scheduler
from automation.services.collector import CollectorService
from automation.services.push_client import AppPushClient
from automation.services.sascar_sync import SascarSyncService
from automation.services.site_alpha_sync import SiteAlphaSyncService
from automation.sites import SITE_REGISTRY
from automation.state import SQLiteStateRepository
from automation.utils.logger import configure_logging
from playwright.sync_api import sync_playwright


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automacao de relatorios com Playwright")
    parser.add_argument("--list", action="store_true", help="Lista sites e relatorios registrados")
    parser.add_argument("--site", help="Nome do site registrado")
    parser.add_argument("--report", help="Nome do relatorio registrado")
    parser.add_argument("--filters", help="Filtros em JSON para execucao manual")
    parser.add_argument("--run-all", action="store_true", help="Executa todos os jobs habilitados")
    parser.add_argument("--scheduler", action="store_true", help="Inicia o scheduler")
    parser.add_argument(
        "--automation-scheduler",
        action="store_true",
        help="Inicia o scheduler que enfileira jobs de automacao",
    )
    parser.add_argument("--test-login", action="store_true", help="Testa apenas o login de um site")
    parser.add_argument(
        "--test-monitoring-trips",
        action="store_true",
        help="Testa a leitura das viagens em andamento do monitoramento do site_alpha",
    )
    parser.add_argument(
        "--test-daily-trip-summary",
        action="store_true",
        help="Testa a leitura do resumo diario de viagens encerradas do site_alpha",
    )
    parser.add_argument("--serve-api", action="store_true", help="Inicia a API HTTP")
    parser.add_argument(
        "--init-automation-db",
        action="store_true",
        help="Cria as tabelas operacionais da automacao no MySQL",
    )
    parser.add_argument(
        "--poll-monitoring-trips",
        action="store_true",
        help="Atualiza continuamente os relatorios habilitados por intervalo no .env",
    )
    parser.add_argument(
        "--poll-reports",
        action="store_true",
        help="Alias para executar os relatorios habilitados por intervalo no .env",
    )
    parser.add_argument(
        "--push-monitoring-trips",
        action="store_true",
        help="Coleta o monitoramento atual e envia o payload para a app principal",
    )
    parser.add_argument(
        "--sync-closed-trips",
        action="store_true",
        help="Sincroniza viagens encerradas pendentes ou alteradas em lotes para a app principal",
    )
    parser.add_argument(
        "--audit-closed-trips",
        action="store_true",
        help="Compara viagens encerradas da Softlog com o historico local em um periodo",
    )
    parser.add_argument("--start-date", help="Data inicial no formato DD/MM/AAAA")
    parser.add_argument("--end-date", help="Data final no formato DD/MM/AAAA")
    parser.add_argument(
        "--closed-trips-status",
        action="store_true",
        help="Lista o status de recebimento pela API das viagens encerradas armazenadas localmente",
    )
    parser.add_argument(
        "--competence-date",
        help="Filtra --closed-trips-status pela data de competencia no formato AAAA-MM-DD",
    )
    parser.add_argument(
        "--test-movimento-diario",
        action="store_true",
        help="Testa a leitura do relatorio Movimento Diario da Sascar para um veiculo",
    )
    parser.add_argument(
        "--push-movimento-diario",
        action="store_true",
        help="Coleta o Movimento Diario da Sascar para o dia atual completo e envia para a app principal",
    )
    parser.add_argument(
        "--test-distancia-percorrida",
        action="store_true",
        help="Testa a leitura do relatorio Distancia Percorrida da Sascar sem enviar",
    )
    parser.add_argument(
        "--push-distancia-percorrida",
        action="store_true",
        help="Coleta o KM final de hoje para a filial Sascar e envia para a app principal",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Coleta e monta os payloads sem enviar para a API (usar junto com os flags de sincronizacao)",
    )
    return parser


def main() -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    if args.test_login:
        if not args.site:
            parser.error("--test-login exige --site.")
        _test_login(args.site)
        return 0

    if args.test_monitoring_trips:
        if not args.site:
            parser.error("--test-monitoring-trips exige --site.")
        _test_monitoring_trips(args.site)
        return 0

    if args.test_daily_trip_summary:
        if not args.site:
            parser.error("--test-daily-trip-summary exige --site.")
        _test_daily_trip_summary(args.site)
        return 0

    if args.test_movimento_diario:
        _test_movimento_diario()
        return 0

    if args.push_movimento_diario:
        _push_movimento_diario(args.dry_run)
        return 0

    if args.test_distancia_percorrida:
        _push_distancia_percorrida(dry_run=True)
        return 0

    if args.push_distancia_percorrida:
        _push_distancia_percorrida(args.dry_run)
        return 0

    if args.serve_api:
        run_api()
        return 0

    if args.init_automation_db:
        automation_repository = AutomationRepository(create_mysql_engine())
        automation_repository.ensure_schema()
        automation_repository.ensure_configured_client()
        print("Banco operacional da automacao inicializado.")
        return 0

    if args.automation_scheduler:
        automation_repository = AutomationRepository(create_mysql_engine())
        start_automation_scheduler(automation_repository)
        return 0

    state_repository = SQLiteStateRepository(settings.state_store.sqlite_path)
    push_client = AppPushClient()
    site_alpha_sync = SiteAlphaSyncService(state_repository, push_client)

    if args.push_monitoring_trips:
        payloads = site_alpha_sync.push_monitoring_trips(dry_run=args.dry_run)
        _summarize_payloads(payloads, "monitoring")
        return 0

    if args.sync_closed_trips:
        if bool(args.start_date) != bool(args.end_date):
            parser.error("--sync-closed-trips exige --start-date e --end-date juntos.")
        if args.start_date:
            payloads = site_alpha_sync.sync_closed_trips_period(
                _parse_brazilian_date(args.start_date, parser),
                _parse_brazilian_date(args.end_date, parser),
                dry_run=args.dry_run,
            )
        else:
            payloads = site_alpha_sync.sync_closed_trips(dry_run=args.dry_run)
        _summarize_payloads(payloads, "closed")
        return 0

    if args.audit_closed_trips:
        if not args.start_date or not args.end_date:
            parser.error("--audit-closed-trips exige --start-date e --end-date.")
        missing = site_alpha_sync.audit_closed_trips(
            _parse_brazilian_date(args.start_date, parser),
            _parse_brazilian_date(args.end_date, parser),
        )
        if not missing:
            print("(auditoria) todas as viagens da Softlog no periodo constam no historico local.")
            return 0
        print(f"(auditoria) viagens da Softlog ausentes no historico local: {len(missing)}")
        for trip in missing:
            print(f"  viagem={trip['numero_viagem']} competencia={trip['data_competencia']}")
        return 2

    if args.closed_trips_status:
        statuses = state_repository.list_closed_trip_statuses(args.competence_date)
        if not statuses:
            print("(status) nenhuma viagem encerrada armazenada.")
            return 0
        for trip in statuses:
            print(
                f"viagem={trip['numero_viagem']} competencia={trip['data_competencia']} "
                f"status_api={trip['status_api']} aceita_em={trip['aceita_em']} "
                f"tentativas={trip['tentativas']} erro={trip['ultimo_erro']}"
            )
        return 0

    repository = MySQLRepository(create_mysql_engine())
    collector = CollectorService(repository)

    if args.poll_monitoring_trips or args.poll_reports:
        _poll_reports(site_alpha_sync)
        return 0

    if args.list:
        for site_name, report_name in collector.list_registered_jobs():
            report = REPORT_REGISTRY[(site_name, report_name)]
            print(f"{site_name} / {report_name} -> tabela {report.table_name}")
        return 0

    if args.scheduler:
        start_scheduler(collector, settings.app.timezone)
        return 0

    if args.run_all:
        for job in JOB_REGISTRY:
            if not job.enabled:
                continue
            collector.run_job(job.site_name, job.report_name, job.filters)
        return 0

    if args.site and args.report:
        filters = _parse_filters(args.filters, parser)
        collector.run_job(args.site, args.report, filters)
        return 0

    parser.print_help()
    return 1


def _parse_filters(raw_filters: str | None, parser: argparse.ArgumentParser) -> dict:
    if not raw_filters:
        return {}

    try:
        parsed = json.loads(raw_filters)
    except json.JSONDecodeError as exc:
        parser.error(f"JSON invalido em --filters: {exc}")

    if not isinstance(parsed, dict):
        parser.error("--filters deve ser um objeto JSON.")

    return parsed


def _parse_brazilian_date(value: str, parser: argparse.ArgumentParser):
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        parser.error("A data deve usar o formato DD/MM/AAAA.")


def _test_login(site_name: str) -> None:
    if site_name not in SITE_REGISTRY:
        raise ValueError(f"Site nao registrado: {site_name}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=settings.app.headless,
            slow_mo=settings.app.slow_mo_ms,
        )
        context = browser.new_context(locale="pt-BR")
        context.set_default_timeout(settings.app.default_timeout_ms)

        site_class = SITE_REGISTRY[site_name]
        site = site_class(context)

        try:
            site.login()
            print(f"Login realizado com sucesso: {site_name}")
            site.page.wait_for_timeout(10000)
        finally:
            site.close()
            context.close()
            browser.close()


def _test_monitoring_trips(site_name: str) -> None:
    if site_name not in SITE_REGISTRY:
        raise ValueError(f"Site nao registrado: {site_name}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=settings.app.headless,
            slow_mo=settings.app.slow_mo_ms,
        )
        context = browser.new_context(locale="pt-BR")
        context.set_default_timeout(settings.app.default_timeout_ms)

        site_class = SITE_REGISTRY[site_name]
        site = site_class(context)

        try:
            site.login()
            site.open_report("monitoring_trips", {})
            rows = site.extract_current_page("monitoring_trips")
            print(f"Total de veiculos em viagens: {len(rows)}")
            for row in rows:
                print(
                    f"placa={row['plate']} status={row['status']} inicio={_format_started_at(row['started_at'])} local={row['current_location']} peso={row['weight']} destino={row['destination']} coletado_em={_format_started_at(row['collected_at'])}"
                )
            site.page.wait_for_timeout(5000)
        finally:
            site.close()
            context.close()
            browser.close()


def _test_daily_trip_summary(site_name: str) -> None:
    if site_name not in SITE_REGISTRY:
        raise ValueError(f"Site nao registrado: {site_name}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=settings.app.headless,
            slow_mo=settings.app.slow_mo_ms,
        )
        context = browser.new_context(locale="pt-BR")
        context.set_default_timeout(settings.app.default_timeout_ms)

        site_class = SITE_REGISTRY[site_name]
        site = site_class(context)

        try:
            site.login()
            site.open_report("daily_trip_summary", {})
            rows = site.extract_current_page("daily_trip_summary")
            print(f"Total de veiculos com viagens encerradas no dia: {len(rows)}")
            for row in rows:
                print(
                    f"data={row['report_date']} placa={row['plate']} frota={row['fleet']} viagens={row['completed_trip_count']} km_sugerido={row['total_suggested_km']} km_rodado={row['total_driven_km']} coletado_em={_format_started_at(row['collected_at'])}"
                )
            site.page.wait_for_timeout(5000)
        finally:
            site.close()
            context.close()
            browser.close()


def _test_movimento_diario() -> None:
    service = SascarSyncService(AppPushClient())
    payloads = service.push_daily_movement(dry_run=True, vehicle_limit=1)
    _summarize_payloads(payloads, "movimento-diario")


def _push_movimento_diario(dry_run: bool) -> None:
    service = SascarSyncService(AppPushClient())
    payloads = service.push_daily_movement(dry_run=dry_run)
    _summarize_payloads(payloads, "movimento-diario")


def _push_distancia_percorrida(dry_run: bool) -> None:
    service = SascarSyncService(AppPushClient())
    payloads = service.push_traveled_distance(dry_run=dry_run)
    if not payloads:
        print("(distancia-percorrida) nenhum registro coletado.")
        return
    payload = payloads[0]
    print(
        f"(distancia-percorrida) lote={payload['lote_id']} "
        f"total de registros: {len(payload['registros'])}"
    )
    for registro in payload["registros"]:
        print(
            f"  placa={registro['placa']} data={registro['data_referencia']} "
            f"quilometragem={registro['quilometragem']}"
        )


def _format_started_at(value: object) -> str:
    if isinstance(value, datetime):
        timezone = ZoneInfo(settings.app.timezone)
        if value.tzinfo is None:
            return value.strftime("%d/%m/%Y %H:%M:%S")
        return value.astimezone(timezone).strftime("%d/%m/%Y %H:%M:%S")
    return str(value)


def _poll_reports(site_alpha_sync: SiteAlphaSyncService) -> None:
    jobs = _enabled_interval_jobs()
    for job_name, interval_seconds in jobs:
        _run_interval_job(site_alpha_sync, job_name)

    scheduler = BlockingScheduler(timezone=settings.app.timezone)
    for job_name, interval_seconds in jobs:
        register_interval_job(
            scheduler,
            _run_interval_job,
            settings.app.timezone,
            interval_seconds,
            site_alpha_sync,
            job_name,
        )
    scheduler.start()


def _enabled_interval_jobs() -> list[tuple[str, int]]:
    jobs: list[tuple[str, int]] = []
    if settings.monitoring_trips.poll_enabled:
        jobs.append(("monitoring_trips", settings.monitoring_trips.poll_interval_seconds))
    if settings.daily_trip_summary.poll_enabled:
        jobs.append(("closed_trips", settings.daily_trip_summary.poll_interval_seconds))
    return jobs


def _run_interval_job(site_alpha_sync: SiteAlphaSyncService, job_name: str) -> None:
    if job_name == "monitoring_trips":
        site_alpha_sync.push_monitoring_trips()
        return

    if job_name == "closed_trips":
        site_alpha_sync.sync_closed_trips()
        return

    raise ValueError(f"Job de intervalo nao suportado: {job_name}")


def _summarize_payloads(payloads: list[dict], kind: str) -> None:
    if not payloads:
        print(f"({kind}) nenhum registro coletado.")
        return

    print(f"({kind}) total de viagens: {len(payloads)}")
    for payload in payloads:
        if "km_sugerido" in payload:
            print(
                f"  viagem={payload.get('numero_viagem')} placa={payload.get('placa')} "
                f"destino={payload.get('destino')} inicio={payload.get('inicio')} "
                f"status={payload.get('status')} km_pago={payload.get('km_pago')} "
                f"km_sugerido={payload.get('km_sugerido')}"
            )
            continue
        if "tempo_movimento" in payload:
            print(
                f"  veiculo={payload.get('veiculo')} filial={payload.get('filial')} "
                f"dia={payload.get('dia')} km={payload.get('km')} "
                f"tempo_movimento={payload.get('tempo_movimento')} horas={len(payload.get('horas') or [])}"
            )
            continue
        print(
            f"  viagem={payload.get('numero_viagem')} placa={payload.get('placa')} "
            f"unidade={payload.get('unidade_negocio')} cliente={payload.get('cliente')} "
            f"inicio={payload.get('data_inicio')} fim={payload.get('data_fim')} "
            f"motorista1={payload.get('motorista1')} motorista2={payload.get('motorista2')}"
        )
