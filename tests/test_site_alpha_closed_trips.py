import unittest
from datetime import date, datetime

from automation.collectors.daily_trip_summary import DailyTripSummaryCollector
from automation.collectors.site_alpha_closed_trips import SiteAlphaClosedTripsCollector


class FakeSiteSession:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.filters: dict[str, str] | None = None

    def __enter__(self) -> "FakeSiteSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def open_report(self, report_name: str, filters: dict[str, str]) -> None:
        self.filters = filters

    def extract_current_page(self, report_name: str) -> list[dict[str, object]]:
        return self.rows


class SiteAlphaClosedTripsCollectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.collector = SiteAlphaClosedTripsCollector()

    def test_filters_rows_by_requested_period_and_sorts_by_trip_number(self) -> None:
        rows = [
            {"trip_number": 100, "ended_at": datetime(2026, 8, 13, 1, 0)},
            {"trip_number": 90, "ended_at": datetime(2026, 8, 12, 2, 0)},
            {"trip_number": 101, "ended_at": datetime(2026, 8, 14, 1, 0)},
            {"trip_number": 80, "ended_at": datetime(2026, 8, 15, 1, 0)},
        ]

        filtered = self.collector._filter_rows(
            rows,
            date(2026, 8, 13),
            date(2026, 8, 14),
        )

        self.assertEqual([100, 101], [row["trip_number"] for row in filtered])

    def test_normalizes_site_fields_without_sending_data(self) -> None:
        row = {
            "trip_number": 123,
            "plate": " ABC1D23 ",
            "fleet": " Frota 1 ",
            "cliente": " Destino X ",
            "carga_cliente": " Carga 456 ",
            "motorista1": " Motorista 1 ",
            "motorista2": " ",
        }

        row["ended_at"] = datetime(2026, 8, 13, 12, 0)
        payload = self.collector._normalize_row(row)

        self.assertEqual("site_alpha:closed_trip:123", payload["external_id"])
        self.assertEqual("ABC1D23", payload["plate"])
        self.assertEqual("Destino X", payload["destination"])
        self.assertEqual("Carga 456", payload["cargo_reference"])
        self.assertIsNone(payload["driver_2"])
        self.assertEqual("13/08/2026", payload["report_date"])

    def test_queries_two_days_before_and_keeps_only_requested_end_dates(self) -> None:
        session = FakeSiteSession(
            [
                {"trip_number": 1, "ended_at": datetime(2026, 8, 10, 23, 0)},
                {"trip_number": 2, "ended_at": datetime(2026, 8, 13, 2, 0)},
                {"trip_number": 3, "ended_at": datetime(2026, 8, 14, 2, 0)},
                {"trip_number": 4, "ended_at": datetime(2026, 8, 15, 2, 0)},
            ]
        )
        self.collector._site_session = lambda: session

        result = self.collector.collect(date(2026, 8, 13), date(2026, 8, 14))

        self.assertEqual(["2", "3"], [row["trip_number"] for row in result])
        self.assertEqual(
            {"start_date": "11/08/2026", "end_date": "14/08/2026"},
            session.filters,
        )


class DailyTripSummaryCollectorTest(unittest.TestCase):
    def test_maps_closed_trip_to_laravel_contract(self) -> None:
        row = {
            "external_id": "site_alpha:closed_trip:123",
            "trip_number": "123",
            "plate": "ABC1D23",
            "destination": "Destino X",
            "driven_km": 119.8,
            "suggested_km": 120.5,
            "started_at": datetime(2026, 9, 19, 8, 0),
            "ended_at": datetime(2026, 9, 19, 12, 30),
            "driver_1": "Motorista 1",
            "driver_2": "Motorista 2",
        }

        payload = DailyTripSummaryCollector._normalize_row(row)

        self.assertEqual(
            {
                "external_id": "site_alpha:closed_trip:123",
                "numero_viagem": "123",
                "placa": "ABC1D23",
                "cliente": "Destino X",
                "destino": "Destino X",
                "km_rodado": 119.8,
                "km_pago": 120.5,
                "data_competencia": "2026-09-19",
                "data_inicio": "2026-09-19 08:00:00",
                "data_fim": "2026-09-19 12:30:00",
                "possui_pendencia": False,
                "pendencias": [],
                "motoristas": ["Motorista 1", "Motorista 2"],
            },
            payload,
        )


if __name__ == "__main__":
    unittest.main()
