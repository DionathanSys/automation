from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from automation.config import settings
from automation.models import HtmlTableSelectors
from automation.sites.base import BaseHtmlTableSite


class SiteAlpha(BaseHtmlTableSite):
    site_name = "site_alpha"
    base_url = settings.site_softlog.base_url
    report_selectors = {
        "financial_summary": HtmlTableSelectors(
            report_path="/reports/financial-summary",
            table="table",
            next_page="button.next-page",
            loading_indicator=".loading",
        ),
        "open_titles": HtmlTableSelectors(
            report_path="/reports/open-titles",
            table="table",
            next_page="button.next-page",
            loading_indicator=".loading",
        ),
        "monitoring_trips": HtmlTableSelectors(
            report_path="#veiculos/monitoramento",
            table="[id^='tableview-']",
        ),
        "daily_trip_summary": HtmlTableSelectors(
            report_path="#veiculos/monitoramento",
            table="[id^='tableview-']",
        ),
        "closed_trips": HtmlTableSelectors(
            report_path="#veiculos/monitoramento",
            table="[id^='tableview-']",
        ),
    }

    def __init__(self, context) -> None:
        super().__init__(context)
        self._daily_trip_summary_report_date = self._today_date_string()

    def login(self) -> None:
        username = settings.site_softlog.username.strip()
        password = settings.site_softlog.password

        if not username or not password:
            raise ValueError(
                "Credenciais do site_softlog nao configuradas. Preencha SITE_SOFTLOG_USERNAME e SITE_SOFTLOG_PASSWORD."
            )

        self.page.goto(self.base_url, wait_until="domcontentloaded")
        self.page.wait_for_function(
            """
            () => Boolean(
                window.Ext
                && Ext.ComponentQuery
                && Ext.ComponentQuery.query('coreLogin form').length
            )
            """
        )
        submit_result = self.page.evaluate(
            """
            ({ username, password }) => {
                const loginView = Ext.ComponentQuery.query('coreLogin')[0];
                if (!loginView) {
                    return { ok: false, error: 'Tela de login nao encontrada.' };
                }

                const form = loginView.down('form');
                if (!form) {
                    return { ok: false, error: 'Formulario de login nao encontrado.' };
                }

                const fields = form.query('textfield');
                const userField = fields.find((field) => field.inputType !== 'password');
                const passwordField = fields.find((field) => field.inputType === 'password');
                if (!userField || !passwordField) {
                    return { ok: false, error: 'Campos de usuario/senha nao encontrados.' };
                }

                userField.setValue(username);
                passwordField.setValue(password);

                const keepLoggedField = form.down('checkboxfield');
                if (keepLoggedField) {
                    keepLoggedField.setValue(false);
                }

                const controller = loginView.getController && loginView.getController();
                if (!controller || typeof controller.onLoginSubmit !== 'function') {
                    return { ok: false, error: 'Controller de login nao encontrado.' };
                }

                const submitButton = form.down('button[cls*=auth-login-button]') || form.down('button');
                controller.onLoginSubmit(submitButton || form);
                return { ok: true };
            }
            """,
            {"username": username, "password": password},
        )
        if not submit_result.get("ok"):
            raise RuntimeError(submit_result["error"])

        try:
            self.page.wait_for_function(
                """
                () => {
                    const hasToken = Boolean(
                        window.sessionStorage.getItem('accessToken')
                        || window.localStorage.getItem('accessToken')
                    );
                    const appLoaded = Boolean(
                        window.Ext
                        && Ext.ComponentQuery
                        && Ext.ComponentQuery.query('coreApp').length
                    );
                    return hasToken && appLoaded;
                }
                """,
                timeout=45000,
            )
        except PlaywrightTimeoutError as exc:
            error_message = self.page.evaluate(
                """
                () => {
                    if (!window.Ext || !Ext.ComponentQuery) {
                        return '';
                    }

                    const messageBox = Ext.ComponentQuery.query('messagebox')[0];
                    if (messageBox) {
                        return messageBox.msg || messageBox.message || messageBox.title || '';
                    }

                    const alerts = Array.from(document.querySelectorAll('.x-message-box, .x-mask-msg-text'))
                        .map((node) => node.textContent?.trim())
                        .filter(Boolean);
                    return alerts[0] || '';
                }
                """
            )
            if error_message:
                raise RuntimeError(f"Falha no login do site_alpha: {error_message}") from exc
            raise RuntimeError(
                "Falha no login do site_alpha: a aplicacao nao concluiu o carregamento apos autenticar."
            ) from exc

    def open_report(self, report_name: str, filters: dict[str, object]) -> None:
        if report_name == "monitoring_trips":
            self._open_monitoring_trips()
            return

        if report_name == "daily_trip_summary":
            self._open_daily_trip_summary(filters)
            return

        if report_name == "closed_trips":
            self._open_closed_trips(filters)
            return

        if report_name != "monitoring_trips":
            super().open_report(report_name, filters)
            return

    def extract_current_page(self, report_name: str) -> list[dict[str, object]]:
        if report_name == "monitoring_trips":
            return self._extract_monitoring_trips_rows()

        if report_name == "daily_trip_summary":
            return self._extract_daily_trip_summary_rows()

        if report_name == "closed_trips":
            return self._extract_closed_trips_rows()

        if report_name != "monitoring_trips":
            return super().extract_current_page(report_name)

        return []

    def _extract_monitoring_trips_rows(self) -> list[dict[str, object]]:
        self._wait_for_monitoring_trips_grid()
        rows = self.page.evaluate(
            """
            () => {
                const grid = Array.from(Ext.ComponentQuery.query('gridpanel')).find((candidate) => {
                    if (!candidate?.isVisible?.() || candidate.isHidden?.()) {
                        return false;
                    }
                    const store = candidate.getStore?.();
                    if (!store || store.getCount() === 0) {
                        return false;
                    }
                    const sample = store.getAt?.(0);
                    if (!sample) {
                        return false;
                    }
                    const data = sample.getData();
                    return Boolean(data.statusNome && data.dataInicio && data.veiculoId && data.viagemId);
                });

                if (!grid) {
                    throw new Error('Grid de viagens em andamento nao encontrada.');
                }

                const store = grid.getStore();
                const rows = [];
                for (let index = 0; index < store.getCount(); index += 1) {
                    const record = store.getAt(index);
                    if (!record) {
                        continue;
                    }
                    const data = record.getData();
                    rows.push({
                        external_id: `${data.viagemId}:${data.veiculoId}`,
                        trip_number: data.viagemId ?? null,
                        trip_id: data.viagemId ?? null,
                        plate: data.placa || '',
                        started_at: data.dataInicio || null,
                        current_location: data.localizacao || '',
                        status: data.statusNome || '',
                        weight: data.peso || null,
                        destination: data.proximoDestino?.nome || data.ultimoDestinoNome || '',
                        cliente: data.ultimoDestinoNome || null,
                        motorista1: data.condutorNome || data.condutor?.nome || null,
                        km_programado: data.kmProgramado ?? null,
                        raw_payload: data,
                    });
                }
                return rows;
            }
            """
        )

        collected_at = datetime.now(UTC).astimezone(self._timezone()).replace(tzinfo=None)
        for row in rows:
            if row.get("trip_number") is None:
                raise RuntimeError(
                    "Nao foi possivel identificar o numero da viagem em uma ou mais linhas do monitoramento de viagens."
                )
            row["started_at"] = self._normalize_datetime_value(row.get("started_at"))
            row["collected_at"] = collected_at
        return rows

    def _extract_daily_trip_summary_rows(self) -> list[dict[str, object]]:
        self._wait_for_daily_trip_summary_grid()
        report_date = self._daily_trip_summary_report_date
        rows = self.page.evaluate(
            """
            (reportDate) => {
                const parseNumber = (value) => {
                    if (value === null || value === undefined || value === '') {
                        return 0;
                    }
                    if (typeof value === 'number') {
                        return value;
                    }
                    const normalized = String(value).replace(/\\./g, '').replace(',', '.');
                    const parsed = Number.parseFloat(normalized);
                    return Number.isFinite(parsed) ? parsed : 0;
                };

                const grid = Ext.ComponentQuery.query('gridpanel').find((candidate) => {
                    if (!candidate?.isVisible?.() || candidate.isHidden?.() || !candidate.id?.includes('GridEncerradas')) {
                        return false;
                    }
                    const store = candidate.getStore?.();
                    return Boolean(store && store.getCount() >= 0 && !store.isLoading?.());
                });

                if (!grid) {
                    throw new Error('Grid de viagens encerradas nao encontrada.');
                }

                const store = grid.getStore();
                const aggregated = new Map();
                for (let index = 0; index < store.getCount(); index += 1) {
                    const record = store.getAt(index);
                    if (!record) {
                        continue;
                    }
                    const data = record.getData();
                    const quantity = parseNumber(data.quantidade);
                    if (quantity <= 0) {
                        continue;
                    }

                    const plate = data.placa || '';
                    const vehicleId = data.veiculoId || null;
                    const key = `${reportDate}:${vehicleId || plate}`;
                    const current = aggregated.get(key) || {
                        external_id: key,
                        report_date: reportDate,
                        plate,
                        fleet: data.frota || '',
                        vehicle_id: vehicleId,
                        completed_trip_count: 0,
                        total_suggested_km: 0,
                        total_driven_km: 0,
                    };

                    current.completed_trip_count += 1;
                    current.total_suggested_km += parseNumber(data.kmProgramado);
                    current.total_driven_km += parseNumber(data.kmRodado);
                    current.total_suggested_km = Number(current.total_suggested_km.toFixed(2));
                    current.total_driven_km = Number(current.total_driven_km.toFixed(2));
                    aggregated.set(key, current);
                }

                return Array.from(aggregated.values()).sort((left, right) => left.plate.localeCompare(right.plate));
            }
            """,
            report_date,
        )

        collected_at = datetime.now(UTC).astimezone(self._timezone()).replace(tzinfo=None)
        for row in rows:
            row["collected_at"] = collected_at
        return rows

    def _extract_closed_trips_rows(self) -> list[dict[str, object]]:
        self._wait_for_daily_trip_summary_grid()
        rows = self.page.evaluate(
            """
            () => {
                const parseNumber = (value) => {
                    if (value === null || value === undefined || value === '') {
                        return null;
                    }
                    if (typeof value === 'number') {
                        return Number.isFinite(value) ? value : null;
                    }
                    const normalized = String(value).replace(/\\./g, '').replace(',', '.');
                    const parsed = Number.parseFloat(normalized);
                    return Number.isFinite(parsed) ? parsed : null;
                };

                const parseInteger = (value) => {
                    if (value === null || value === undefined || value === '') {
                        return null;
                    }
                    const digits = String(value).replace(/\\D/g, '');
                    if (!digits) {
                        return null;
                    }
                    const parsed = Number.parseInt(digits, 10);
                    return Number.isFinite(parsed) ? parsed : null;
                };

                const grid = Ext.ComponentQuery.query('gridpanel').find((candidate) => {
                    if (!candidate?.isVisible?.() || candidate.isHidden?.() || !candidate.id?.includes('GridEncerradas')) {
                        return false;
                    }
                    const store = candidate.getStore?.();
                    return Boolean(store && !store.isLoading?.());
                });

                if (!grid) {
                    throw new Error('Grid de viagens encerradas nao encontrada.');
                }

                const store = grid.getStore();
                const rows = [];
                for (let index = 0; index < store.getCount(); index += 1) {
                    const record = store.getAt(index);
                    if (!record) {
                        continue;
                    }
                    const data = record.getData();
                    const tripNumber = parseInteger(
                        data.numeroViagem
                        ?? data.nrViagem
                        ?? data.viagemNumero
                        ?? data.viagemId
                        ?? data.id
                    );

                    rows.push({
                        external_id: `${data.viagemId ?? data.id ?? index}:${data.veiculoId ?? data.placa ?? ''}`,
                        trip_number: tripNumber,
                        trip_id: data.viagemId ?? data.id ?? null,
                        plate: data.placa || '',
                        fleet: data.frota || '',
                        vehicle_id: data.veiculoId || null,
                        status: data.statusNome || data.status || '',
                        suggested_km: parseNumber(data.kmProgramado),
                        driven_km: parseNumber(data.kmRodado),
                        started_at: data.dataInicio || null,
                        ended_at: data.dataFim || data.dataEncerramento || data.dataTermino || null,
                        cliente: data.ultimoDestinoNome || null,
                        carga_cliente: data.cargaCliente ?? data.carga_cliente ?? null,
                        motorista1: data.condutorNome || data.condutor?.nome || null,
                        motorista2: null,
                        numero_interno: data.strViagem || null,
                        quantidade: parseNumber(data.quantidade),
                        raw_payload: data,
                    });
                }

                return rows;
            }
            """
        )

        collected_at = datetime.now(UTC).astimezone(self._timezone()).replace(tzinfo=None)
        for row in rows:
            if row.get("trip_number") is None:
                raise RuntimeError(
                    "Nao foi possivel identificar o numero da viagem em uma ou mais linhas do relatorio de viagens encerradas."
                )
            row["started_at"] = self._normalize_datetime_value(row.get("started_at"))
            row["ended_at"] = self._normalize_datetime_value(row.get("ended_at"))
            row["collected_at"] = collected_at

        return rows

    def go_to_next_page(self, report_name: str) -> bool:
        if report_name in {"monitoring_trips", "daily_trip_summary", "closed_trips"}:
            return False
        return super().go_to_next_page(report_name)

    def _open_monitoring_trips(self) -> None:
        self._open_monitoring_base()
        self._select_trip_panel_button("Em Andamento")
        self._wait_for_monitoring_trips_grid()

    def _open_daily_trip_summary(self, filters: dict[str, Any]) -> None:
        self._open_monitoring_base()
        self._select_trip_panel_button("Encerradas")
        report_date = self._today_date_string()
        start_date = str(filters.get("start_date") or report_date)
        end_date = str(filters.get("end_date") or report_date)
        self._daily_trip_summary_report_date = start_date if start_date == end_date else f"{start_date}..{end_date}"
        self._daily_trip_summary_filter = (start_date, end_date)
        self._apply_trip_date_filter(start_date, end_date)
        self._wait_for_daily_trip_summary_grid()

    def _open_closed_trips(self, filters: dict[str, Any]) -> None:
        self._open_daily_trip_summary(filters)

    def _open_monitoring_base(self) -> None:
        self._wait_for_menu_ready()
        self._expand_left_menu()
        self.page.locator(".x-treelist-item-text", has_text="Monitoramento").click()
        self.page.wait_for_url("**/#veiculos/monitoramento")
        self.page.locator(".x-btn[data-qtip='Viagens']").click()
        self.page.wait_for_timeout(1000)

    def _select_trip_panel_button(self, label: str) -> None:
        self.page.locator(".x-btn-inner", has_text=label).click()

    def _apply_trip_date_filter(self, start_date: str, end_date: str) -> None:
        self.page.locator(".x-btn-inner", has_text="Opções de filtro").last.click()
        self.page.locator("input[name='dateInicio']").fill(start_date)
        self.page.locator("input[name='dateFim']").fill(end_date)
        self.page.locator(".x-btn-inner", has_text="Aplicar").click()

    def _wait_for_menu_ready(self) -> None:
        self.page.wait_for_function(
            """
            () => {
                const button = document.querySelector('#button-1020-btnInnerEl');
                return button && button.textContent && button.textContent.trim() !== 'CARREGANDO...';
            }
            """
        )
        self.page.locator("#ext-element-20").wait_for(state="attached")

    def _expand_left_menu(self) -> None:
        monitoramento = self.page.locator("#ext-element-20")
        if monitoramento.is_visible():
            return

        self.page.locator("#button-1024").click()
        monitoramento.wait_for(state="visible")

    def _wait_for_monitoring_trips_grid(self) -> None:
        self.page.wait_for_function(
            """
            () => {
                if (!window.Ext || !Ext.ComponentQuery) {
                    return false;
                }

                return Ext.ComponentQuery.query('gridpanel').some((candidate) => {
                    if (!candidate?.isVisible?.() || candidate.isHidden?.()) {
                        return false;
                    }
                    const store = candidate.getStore?.();
                    if (!store || store.getCount() === 0) {
                        return false;
                    }
                    const sample = store.getAt?.(0);
                    if (!sample) {
                        return false;
                    }
                    const data = sample.getData();
                    return Boolean(data.statusNome && data.dataInicio && data.veiculoId && data.viagemId);
                });
            }
            """,
            timeout=45000,
        )

    def _wait_for_daily_trip_summary_grid(self) -> None:
        self.page.wait_for_function(
            """
            () => {
                if (!window.Ext || !Ext.ComponentQuery) {
                    return false;
                }

                const grid = Ext.ComponentQuery.query('gridpanel').find((candidate) => {
                    if (!candidate?.isVisible?.() || candidate.isHidden?.() || !candidate.id?.includes('GridEncerradas')) {
                        return false;
                    }
                    const store = candidate.getStore?.();
                    return Boolean(store && !store.isLoading?.());
                });

                if (!grid) {
                    return false;
                }

                const store = grid.getStore();
                if (store.isLoading?.()) {
                    return false;
                }

                return true;
            }
            """,
            timeout=45000,
        )

    def _to_iso_date(self, value: str) -> str | None:
        try:
            return datetime.strptime(value, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return None

    def _normalize_datetime_value(self, value: object) -> object:
        if isinstance(value, datetime):
            return value.astimezone(self._timezone()).replace(tzinfo=None)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return value
            if parsed.tzinfo is None:
                return parsed
            return parsed.astimezone(self._timezone()).replace(tzinfo=None)
        return value

    def _timezone(self):
        from zoneinfo import ZoneInfo

        return ZoneInfo(settings.app.timezone)

    def _today_date_string(self) -> str:
        return datetime.now(self._timezone()).strftime("%d/%m/%Y")
