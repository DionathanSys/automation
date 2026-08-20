from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from playwright.sync_api import sync_playwright

from automation.config import settings
from automation.state import SQLiteStateRepository
from automation.services.push_client import AppPushClient
from automation.sites import SITE_REGISTRY
from automation.utils.logger import get_logger


logger = get_logger(__name__)


class SiteAlphaSyncService:
    def __init__(self, state_repository: SQLiteStateRepository, push_client: AppPushClient) -> None:
        self.state_repository = state_repository
        self.push_client = push_client

    def push_monitoring_trips(self, dry_run: bool = False) -> list[dict[str, Any]]:
        with self._site_session() as site:
            site.open_report("monitoring_trips", {})
            rows = site.extract_current_page("monitoring_trips")

        if not rows:
            logger.info("Nenhuma viagem em andamento encontrada.")
            return []

        payloads: list[dict[str, Any]] = []
        for row in rows:
            try:
                payloads.append(self._build_viagem_atual_payload(row))
            except ValueError as exc:
                logger.warning(
                    "Ignorando viagem em andamento invalida. placa=%s viagem=%s erro=%s",
                    row.get("plate"),
                    row.get("trip_number"),
                    exc,
                )

        if not payloads:
            logger.info("Nenhuma viagem em andamento valida encontrada.")
            return []

        for payload in payloads:
            if not dry_run:
                self.push_client.push_viagem_atual(payload)
        logger.info("Monitoramento coletado com %s registros.", len(payloads))
        return payloads

    def sync_closed_trips(self, dry_run: bool = False) -> list[dict[str, Any]]:
        cutoff_date = self._parse_cutoff_date()
        checkpoint = self.state_repository.get_checkpoint("closed_trips")
        current_date = self._parse_date(checkpoint.checkpoint_date) if checkpoint else cutoff_date
        return self._sync_closed_trips(current_date, self._today(), dry_run=dry_run, save_checkpoint=True)

    def sync_closed_trips_period(
        self,
        start_date: date,
        end_date: date,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        if end_date < start_date:
            raise ValueError("A data final deve ser maior ou igual a data inicial.")
        return self._sync_closed_trips(start_date, end_date, dry_run=dry_run, save_checkpoint=False)

    def _sync_closed_trips(
        self,
        current_date: date,
        end_date: date,
        dry_run: bool,
        save_checkpoint: bool,
    ) -> list[dict[str, Any]]:
        all_payloads: list[dict[str, Any]] = []

        with self._site_session() as site:
            while current_date <= end_date:
                report_date = self._format_date(current_date)
                report_start_date = self._format_date(current_date - timedelta(days=1))
                site.open_report(
                    "closed_trips",
                    {"start_date": report_start_date, "end_date": report_date},
                )
                rows = site.extract_current_page("closed_trips")
                rows = self._filter_closed_trips(rows, current_date)

                if not rows:
                    if current_date < end_date:
                        current_date = current_date + timedelta(days=1)
                        if save_checkpoint and not dry_run:
                            self.state_repository.save_checkpoint("closed_trips", self._format_date(current_date), None)
                        continue

                    logger.info("Nenhuma viagem nova encontrada para %s.", report_date)
                    return all_payloads

                payload_rows = [self._build_closed_trip_payload(report_date, row) for row in rows]
                pending_payloads = payload_rows if dry_run else self.state_repository.record_closed_trips(payload_rows)
                for batch in self._batch(pending_payloads, settings.receiver.closed_trips_batch_size):
                    lote_id = self._build_lote_id(report_date, batch)
                    all_payloads.extend(batch)
                    if not dry_run:
                        trip_numbers = [str(payload["numero_viagem"]) for payload in batch]
                        try:
                            self.push_client.push_closed_trips(lote_id, batch)
                        except Exception as exc:
                            self.state_repository.mark_closed_trips_failed(trip_numbers, lote_id, str(exc))
                            raise
                        self.state_repository.mark_closed_trips_accepted(trip_numbers, lote_id)

                if save_checkpoint and not dry_run:
                    self.state_repository.save_checkpoint(
                        "closed_trips", report_date, int(rows[-1]["trip_number"])
                    )

                if current_date < end_date:
                    current_date = current_date + timedelta(days=1)
                    if save_checkpoint and not dry_run:
                        self.state_repository.save_checkpoint("closed_trips", self._format_date(current_date), None)
                    continue

                logger.info("Sincronizacao de viagens encerradas concluiu com %s registros.", len(all_payloads))
                return all_payloads

        return all_payloads

    def audit_closed_trips(self, start_date: date, end_date: date) -> list[dict[str, str]]:
        if end_date < start_date:
            raise ValueError("A data final deve ser maior ou igual a data inicial.")

        missing: list[dict[str, str]] = []
        current_date = start_date
        with self._site_session() as site:
            while current_date <= end_date:
                report_date = self._format_date(current_date)
                site.open_report(
                    "closed_trips",
                    {
                        "start_date": self._format_date(current_date - timedelta(days=1)),
                        "end_date": report_date,
                    },
                )
                rows = self._filter_closed_trips(site.extract_current_page("closed_trips"), current_date)
                trip_numbers = [str(row["trip_number"]) for row in rows]
                missing_numbers = set(self.state_repository.missing_closed_trip_numbers(trip_numbers))
                missing.extend(
                    {
                        "numero_viagem": trip_number,
                        "data_competencia": datetime.strptime(report_date, "%d/%m/%Y").strftime("%Y-%m-%d"),
                    }
                    for trip_number in trip_numbers
                    if trip_number in missing_numbers
                )
                current_date += timedelta(days=1)

        return missing

    def _site_session(self):
        return _SiteAlphaSession()

    def _parse_cutoff_date(self) -> date:
        raw_date = settings.receiver.closed_trips_cutoff_date.strip()
        if not raw_date:
            raise ValueError("CLOSED_TRIPS_CUTOFF_DATE nao configurada.")
        return self._parse_date(raw_date)

    def _parse_date(self, value: str) -> date:
        return datetime.strptime(value, "%d/%m/%Y").date()

    def _format_date(self, value: date) -> str:
        return value.strftime("%d/%m/%Y")

    def _today(self) -> date:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(settings.app.timezone)).date()

    def _filter_closed_trips(
        self,
        rows: list[dict[str, Any]],
        current_date: date,
    ) -> list[dict[str, Any]]:
        normalized_rows = []
        for row in rows:
            ended_at = row.get("ended_at")
            if not isinstance(ended_at, datetime):
                continue
            if ended_at.date() != current_date:
                continue
            normalized_rows.append(row)

        return sorted(normalized_rows, key=lambda row: int(row["trip_number"]))

    def _batch(self, rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
        if batch_size <= 0:
            raise ValueError("CLOSED_TRIPS_BATCH_SIZE deve ser maior que zero.")
        return [rows[index : index + batch_size] for index in range(0, len(rows), batch_size)]

    def _build_lote_id(self, report_date: str, rows: list[dict[str, Any]]) -> str:
        date_token = datetime.strptime(report_date, "%d/%m/%Y").strftime("%Y%m%d")
        extraction_token = datetime.now().strftime("%Y%m%d%H%M%S%f")
        first_trip = int(rows[0]["numero_viagem"])
        last_trip = int(rows[-1]["numero_viagem"])
        return f"scraping-{date_token}-{extraction_token}-{first_trip}-{last_trip}"

    def _build_monitoring_lote_id(self) -> str:
        return f"scraping-monitoramento-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    def _build_viagem_atual_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        started_at = self._format_payload_datetime(row.get("started_at"), "data_inicio")
        plate = str(row.get("plate") or "").strip()
        if not plate:
            raise ValueError("Viagem em andamento sem placa nao pode ser enviada para a integracao.")

        destination = self._clean_optional(row.get("destination") or row.get("cliente"))
        if not destination:
            raise ValueError("Viagem em andamento sem destino nao pode ser enviada para a integracao.")

        suggested_km = self._parse_km(row.get("km_programado"))
        if suggested_km is None:
            raise ValueError("Viagem em andamento sem km sugerido nao pode ser enviada para a integracao.")

        return {
            "placa": plate,
            "numero_viagem": str(row["trip_number"]),
            "destino": destination,
            "local_atual": self._clean_optional(row.get("current_location")),
            "peso": row.get("weight"),
            "km_pago": suggested_km,
            "km_sugerido": suggested_km,
            "inicio": started_at,
            "status": self._clean_optional(row.get("status")),
        }

    @staticmethod
    def _parse_km(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        try:
            return float(text.replace(".", "").replace(",", "."))
        except ValueError:
            return None

    def _build_closed_trip_payload(self, report_date: str, row: dict[str, Any]) -> dict[str, Any]:
        started_at = self._format_payload_datetime(row.get("started_at"), "data_inicio")
        ended_at = self._format_payload_datetime(row.get("ended_at"), "data_fim")
        plate = str(row.get("plate") or "").strip()
        if not plate:
            raise ValueError("Viagem sem placa nao pode ser enviada para a integracao.")

        return {
            "numero_viagem": str(row["trip_number"]),
            "placa": plate,
            "unidade_negocio": settings.receiver.default_business_unit,
            "cliente": settings.receiver.default_customer,
            "destino": self._clean_optional(row.get("cliente")),
            "documento_transporte": self._clean_optional(row.get("carga_cliente")),
            "numero_interno": self._clean_optional(row.get("numero_interno")),
            "km_rodado": row.get("driven_km"),
            "km_pago": row.get("suggested_km"),
            "data_competencia": started_at[:10],
            "data_inicio": started_at,
            "data_fim": ended_at,
            "total_destinos": row.get("quantidade"),
            "possui_pendencia": False,
            "pendencias": [],
            "motorista1": self._clean_optional(row.get("motorista1")),
            "motorista2": self._clean_optional(row.get("motorista2")),
        }

    def _format_payload_datetime(self, value: Any, field_name: str) -> str:
        if not isinstance(value, datetime):
            raise ValueError(f"Campo obrigatorio ausente para integracao: {field_name}.")
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def _clean_optional(self, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        cleaned = self._repair_mojibake(cleaned)
        return cleaned or None

    @staticmethod
    def _repair_mojibake(value: str) -> str:
        try:
            repaired = value.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value
        return repaired if repaired != value else value


class _SiteAlphaSession:
    def __enter__(self):
        self.site = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=settings.app.headless,
            slow_mo=settings.app.slow_mo_ms,
        )
        self._context = self._browser.new_context()
        self._context.set_default_timeout(settings.app.default_timeout_ms)
        site_class = SITE_REGISTRY["site_alpha"]
        self.site = site_class(self._context)
        self.site.login()
        return self.site

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.site is not None:
            self.site.close()
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
