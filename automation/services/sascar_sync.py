from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from automation.config import settings
from automation.services.push_client import AppPushClient
from automation.sites import SITE_REGISTRY
from automation.utils.logger import get_logger


logger = get_logger(__name__)


class SascarSyncService:
    def __init__(self, push_client: AppPushClient) -> None:
        self.push_client = push_client

    def push_daily_movement(
        self,
        dry_run: bool = False,
        vehicle_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        inicio, fim = self._window()
        lote_id = self._build_lote_id()
        all_payloads: list[dict[str, Any]] = []

        with self._sascar_session() as site:
            vehicles = site.list_fleet_vehicles()
            if vehicle_limit is not None:
                vehicles = vehicles[:vehicle_limit]
            if not vehicles:
                logger.info("Nenhum veiculo encontrado para a filial %s.", settings.sascar.filial_veiculo)
                return all_payloads

            for vehicle in vehicles:
                try:
                    rows = site.generate_daily_movement(vehicle, inicio, fim)
                except Exception:
                    logger.exception("Falha ao gerar movimento diario do veiculo %s.", vehicle["plate"])
                    continue

                for row in rows:
                    payload = self._build_payload(lote_id, vehicle, row, inicio, fim)
                    all_payloads.append(payload)
                    if not dry_run:
                        try:
                            self.push_client.push_movimento_diario(payload)
                        except Exception:
                            logger.exception(
                                "Falha ao enviar movimento diario do veiculo %s, dia %s.",
                                vehicle["plate"],
                                row["dia"],
                            )
                logger.info("Movimento diario coletado para %s (%s registro(s)).", vehicle["plate"], len(rows))

        return all_payloads

    def push_traveled_distance(self, dry_run: bool = False) -> list[dict[str, Any]]:
        with self._sascar_session() as site:
            registros = site.generate_traveled_distance()

        valid_registros: list[dict[str, Any]] = []
        for registro in registros:
            try:
                quilometragem = float(registro["quilometragem"])
            except (KeyError, TypeError, ValueError):
                logger.warning("Ignorando registro de quilometragem invalido: %s", registro)
                continue
            if quilometragem <= 0:
                logger.warning(
                    "Ignorando quilometragem nao positiva. placa=%s valor=%s",
                    registro.get("placa"),
                    registro.get("quilometragem"),
                )
                continue
            valid_registros.append(registro)

        if not valid_registros:
            logger.info(
                "Nenhuma quilometragem encontrada para hoje na filial %s.",
                settings.sascar.filial_veiculo,
            )
            return []

        payload = {
            "lote_id": self._build_odometer_lote_id(),
            "registros": valid_registros,
        }
        if not dry_run:
            self.push_client.push_historico_quilometragem(payload)
        logger.info("Distancia percorrida coletada (%s registro(s)).", len(valid_registros))
        return [payload]

    def _sascar_session(self):
        return _SascarSession()

    def _window(self) -> tuple[datetime, datetime]:
        inicio = datetime.now(ZoneInfo(settings.app.timezone)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        fim = inicio + timedelta(hours=settings.sascar.window_hours)
        return inicio, fim

    @staticmethod
    def _build_lote_id() -> str:
        now = datetime.now(ZoneInfo(settings.app.timezone))
        return f"sascar-movimento-diario-{now.strftime('%Y%m%d-%H%M%S')}"

    @staticmethod
    def _build_odometer_lote_id() -> str:
        now = datetime.now(ZoneInfo(settings.app.timezone))
        return f"sascar-quilometragem-{now.strftime('%Y%m%d-%H%M%S')}"

    def _build_payload(
        self,
        lote_id: str,
        vehicle: dict[str, Any],
        row: dict[str, Any],
        inicio: datetime,
        fim: datetime,
    ) -> dict[str, Any]:
        return {
            "lote_id": lote_id,
            "veiculo": vehicle["plate"].split("-", 1)[0].strip(),
            "filial": settings.sascar.filial_veiculo,
            "inicio": inicio.strftime("%Y-%m-%d %H:%M:%S"),
            "fim": fim.strftime("%Y-%m-%d %H:%M:%S"),
            "dia": row["dia"],
            "km": row["km"],
            "tempo_movimento": row["tempo_movimento"],
            "horas": row["horas"],
        }


class _SascarSession:
    def __enter__(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=settings.app.headless,
            slow_mo=settings.app.slow_mo_ms,
        )
        self._context = self._browser.new_context(locale="pt-BR")
        self._context.set_default_timeout(settings.app.default_timeout_ms)
        site_class = SITE_REGISTRY["sascar"]
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
