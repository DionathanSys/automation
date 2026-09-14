from __future__ import annotations

import time
from datetime import datetime, time as dt_time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from automation.config import settings
from automation.utils.logger import get_logger


logger = get_logger(__name__)


class SiteSascar:
    site_name = "sascar"
    LOGIN_URL = "/telemetria/pages/login.jsf"
    CONTROLLER_URL = "/telemetria/pages/controller.jsf"
    RADIO_DAILY_MOVEMENT = "controller:opcoes_relatorio:20"
    RADIO_TOTAL_DISTANCE = "controller:opcoes_relatorio:28"
    RADIO_TODAY = "controller:periodo:0"
    RADIO_DATE_RANGE = "controller:periodo:4"
    RADIO_POPUP_VIEW = "controller:formaVisualizacao:1"
    VEHICLE_SELECT = "#controller\\:comboVeiculo"
    DATE_START_INPUT = "#controller\\:dataInicioFiltroMenu"
    DATE_END_INPUT = "#controller\\:dataFinalFiltroMenu"
    VIEW_REPORT_BUTTON = "#controller\\:btnGeraRelatorio"
    REPORT_TABLE = "table.tabela_relatorio"
    TOTAL_DISTANCE_TABLE = "table:has(tr:first-child:has-text('Final Odometer'))"
    MINUTOS_POR_HORA = 6

    def __init__(self, context) -> None:
        self.context = context
        self.page: Page = context.new_page()

    def login(self) -> None:
        usuario = settings.sascar.usuario.strip()
        login = settings.sascar.login.strip()
        senha = settings.sascar.password

        if not usuario or not login or not senha:
            raise ValueError(
                "Credenciais da Sascar nao configuradas. Preencha SITE_SASCAR_USUARIO, "
                "SITE_SASCAR_LOGIN e SITE_SASCAR_PASSWORD."
            )

        self.page.goto(f"{self._base_url()}{self.LOGIN_URL}", wait_until="domcontentloaded")
        self.page.wait_for_selector("#form\\:btnOk", timeout=60000)
        self.page.fill("#form\\:usuario", usuario)
        self.page.fill("#form\\:login", login)
        self.page.fill("#form\\:senha", senha)
        self.page.click("button:has-text('Permitir')")
        self.page.wait_for_timeout(500)
        self.page.click("#form\\:btnOk")

        try:
            self.page.wait_for_selector("#popCloseBox", state="visible", timeout=60000)
        except PlaywrightTimeoutError:
            pass
        self.page.wait_for_timeout(2000)
        self._close_popups()

    def list_fleet_vehicles(self) -> list[dict[str, Any]]:
        self._open_controller()
        self._select_daily_movement()
        return self._read_vehicle_options()

    def generate_daily_movement(
        self,
        vehicle: dict[str, Any],
        inicio: datetime,
        fim: datetime,
    ) -> list[dict[str, Any]]:
        self._open_controller()
        self._select_daily_movement()
        self._set_period_and_view(inicio, fim)
        self.page.select_option(self.VEHICLE_SELECT, value=self._find_vehicle_option(vehicle["plate"]))
        self.page.wait_for_timeout(2000)
        self._close_popups()

        popup = self._submit_and_wait_report()
        try:
            return self._parse_report(popup, inicio, fim)
        finally:
            popup.close()

    def generate_traveled_distance(self) -> list[dict[str, Any]]:
        self._open_controller()
        self._select_traveled_distance()
        self.page.click(f"label[for='{self.RADIO_TODAY}']")
        self.page.click(f"label[for='{self.RADIO_POPUP_VIEW}']")
        self.page.wait_for_timeout(800)

        popup = self._submit_and_wait_traveled_distance()
        try:
            return self._parse_traveled_distance(popup)
        finally:
            popup.close()

    def close(self) -> None:
        self.page.close()

    def _base_url(self) -> str:
        return settings.sascar.base_url.rstrip("/")

    def _open_controller(self) -> None:
        self.page.goto(f"{self._base_url()}{self.CONTROLLER_URL}", wait_until="domcontentloaded")
        self.page.wait_for_selector("#controller", timeout=60000)
        self.page.wait_for_timeout(3000)
        self._close_popups()

    def _select_daily_movement(self) -> None:
        self.page.click(f"label[for='{self.RADIO_DAILY_MOVEMENT}']")
        self._wait_current_combo_stable()
        self.page.wait_for_timeout(500)

    def _select_traveled_distance(self) -> None:
        self.page.click(f"label[for='{self.RADIO_TOTAL_DISTANCE}']")
        self._wait_current_combo_stable()
        self.page.wait_for_timeout(500)

    def _parse_traveled_distance(self, popup: Page) -> list[dict[str, Any]]:
        if popup.locator(self.TOTAL_DISTANCE_TABLE).count() == 0:
            return []

        table = popup.locator(self.TOTAL_DISTANCE_TABLE).last
        rows: list[dict[str, Any]] = []
        for row_index in range(1, table.locator("tr").count()):
            cells = table.locator("tr").nth(row_index).locator("td").all()
            if len(cells) < 4:
                continue

            data_referencia = self._to_iso_date(cells[1].inner_text().strip())
            if data_referencia is None:
                continue

            plate_match = re.search(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}", cells[0].inner_text().upper())
            quilometragem = self._parse_odometer(cells[3].inner_text())
            if plate_match is None or quilometragem is None:
                continue

            rows.append(
                {
                    "placa": plate_match.group(0),
                    "data_referencia": data_referencia,
                    "quilometragem": quilometragem,
                }
            )
        return rows

    @staticmethod
    def _parse_odometer(value: str) -> int | None:
        text = value.strip().replace(" ", "").replace(",", ".")
        try:
            return int(Decimal(text).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except InvalidOperation:
            return None

    def _wait_current_combo_stable(self, timeout_ms: int = 10000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        previous = self._combo_signature()
        stable_rounds = 0
        while time.monotonic() < deadline:
            time.sleep(0.4)
            current = self._combo_signature()
            if current == previous:
                stable_rounds += 1
                if stable_rounds >= 4:
                    return
            else:
                stable_rounds = 0
                previous = current

    def _combo_signature(self) -> str:
        return self.page.evaluate(
            """() => {
                const sel = document.getElementById('controller:comboVeiculo');
                if (!sel) return '';
                return Array.from(sel.options).map((o) => o.value).join(',');
            }"""
        )

    def _read_vehicle_options(self) -> list[dict[str, Any]]:
        return self.page.evaluate(
            """() => {
                const sel = document.getElementById('controller:comboVeiculo');
                const items = [];
                for (const opt of sel.options) {
                    const text = opt.text.trim();
                    if (opt.value === '' || text === '' || /^Select/i.test(text)) {
                        continue;
                    }
                    items.push({ id: opt.value, plate: text });
                }
                return items;
            }"""
        )

    def _find_vehicle_option(self, plate: str) -> str:
        options = self._read_vehicle_options()
        if not options:
            raise RuntimeError("Combo de veiculos vazio ao selecionar veiculo.")
        for option in options:
            if option["plate"].strip() == plate:
                return option["id"]
        raise RuntimeError(f"Veiculo {plate} nao encontrado no combo de veiculos disponiveis.")

    def _set_period_and_view(self, inicio: datetime, fim: datetime) -> None:
        self.page.click(f"label[for='{self.RADIO_DATE_RANGE}']")
        self.page.wait_for_timeout(1200)
        self.page.fill(self.DATE_START_INPUT, inicio.strftime("%d/%m/%Y %H:%M"))
        self.page.fill(self.DATE_END_INPUT, fim.strftime("%d/%m/%Y %H:%M"))
        self.page.wait_for_timeout(500)
        self.page.click(f"label[for='{self.RADIO_POPUP_VIEW}']")
        self.page.wait_for_timeout(800)

    def _submit_and_wait_report(self) -> Page:
        with self.context.expect_page(timeout=20000) as popup_info:
            self.page.click(self.VIEW_REPORT_BUTTON, timeout=15000)
        popup = popup_info.value
        try:
            popup.wait_for_selector(self.REPORT_TABLE, timeout=30000)
        except PlaywrightTimeoutError:
            logger.info("Relatorio Movimento Diario retornou sem tabela de dados.")
        return popup

    def _submit_and_wait_traveled_distance(self) -> Page:
        with self.context.expect_page(timeout=20000) as popup_info:
            self.page.click(self.VIEW_REPORT_BUTTON, timeout=15000)
        popup = popup_info.value
        try:
            popup.wait_for_selector(self.TOTAL_DISTANCE_TABLE, timeout=30000)
        except PlaywrightTimeoutError:
            logger.info("Relatorio Distancia Percorrida retornou sem tabela de dados.")
        return popup

    def _parse_report(
        self,
        popup: Page,
        inicio: datetime,
        fim: datetime,
    ) -> list[dict[str, Any]]:
        if popup.locator(self.REPORT_TABLE).count() == 0:
            return []

        table = popup.locator(self.REPORT_TABLE)
        hours = self._read_hour_columns(table)
        rows: list[dict[str, Any]] = []

        for row_index in range(1, table.locator("tr").count()):
            cells = table.locator("tr").nth(row_index).locator("td").all()
            if len(cells) != 3 + len(hours):
                continue

            dia = self._to_iso_date(cells[0].inner_text().strip())
            if dia is None:
                continue

            horas = []
            for hour_index, hour in enumerate(hours):
                statuses = self._read_minuto_statuses(cells[3 + hour_index])
                if statuses is None:
                    continue
                horas.append({"hora": hour, "minutos": statuses})

            rows.append(
                {
                    "dia": dia,
                    "km": self._parse_float(cells[1].inner_text().strip()),
                    "tempo_movimento": cells[2].inner_text().strip(),
                    "horas": self._filter_horas(horas, dia, inicio, fim),
                }
            )

        return rows

    def _read_hour_columns(self, table) -> list[int]:
        header_cells = table.locator("tr").first.locator("td").all()
        hours: list[int] = []
        for index in range(3, len(header_cells)):
            hours.append(int(header_cells[index].inner_text().strip()))
        return hours

    def _read_minuto_statuses(self, cell) -> list[str] | None:
        divs = cell.locator("div[class^='minuto_']").all()
        if len(divs) != self.MINUTOS_POR_HORA:
            return None
        return [self._minuto_status(div.get_attribute("class")) for div in divs]

    @staticmethod
    def _minuto_status(css_class: str | None) -> str:
        if not css_class:
            return "0"
        for token in css_class.split():
            if token.startswith("minuto_"):
                return token.removeprefix("minuto_")
        return "0"

    @staticmethod
    def _filter_horas(
        horas: list[dict[str, Any]],
        dia: str,
        inicio: datetime,
        fim: datetime,
    ) -> list[dict[str, Any]]:
        if not horas:
            return []
        day_date = datetime.strptime(dia, "%Y-%m-%d").date()
        inicio_naive = inicio.replace(tzinfo=None)
        fim_naive = fim.replace(tzinfo=None)
        filtered = [
            entry
            for entry in horas
            if inicio_naive
            <= datetime.combine(day_date, dt_time(entry["hora"]))
            < fim_naive
        ]
        filtered.sort(key=lambda entry: entry["hora"])
        return filtered

    @staticmethod
    def _to_iso_date(value: str) -> str | None:
        try:
            return datetime.strptime(value.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return None

    @staticmethod
    def _parse_float(value: str) -> float | None:
        text = value.strip().replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None

    def _close_popups(self) -> None:
        self.page.evaluate("() => { try { hidePopWin(false); } catch (e) {} }")
        try:
            close_box = self.page.query_selector("#popCloseBox")
            if close_box and close_box.is_visible():
                close_box.click()
                self.page.wait_for_timeout(300)
        except PlaywrightTimeoutError:
            pass
        for page in list(self.context.pages):
            if page is not self.page and page.url.startswith("about:"):
                try:
                    page.close()
                except Exception:
                    pass
