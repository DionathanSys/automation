from datetime import date, datetime
import tempfile
import unittest

from automation.services.site_alpha_sync import SiteAlphaSyncService
from automation.state import SQLiteStateRepository


class ClosedTripsFilterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SiteAlphaSyncService(state_repository=None, push_client=None)

    def test_keeps_late_trip_with_number_below_previous_checkpoint(self) -> None:
        rows = [
            {
                "trip_number": 100,
                "ended_at": datetime(2026, 8, 13, 1, 0),
            },
            {
                "trip_number": 90,
                "ended_at": datetime(2026, 8, 13, 2, 0),
            },
        ]

        filtered = self.service._filter_closed_trips(rows, date(2026, 8, 13))

        self.assertEqual([90, 100], [row["trip_number"] for row in filtered])

    def test_uses_end_date_as_competence_criterion(self) -> None:
        rows = [
            {
                "trip_number": 100,
                "started_at": datetime(2026, 8, 12, 22, 0),
                "ended_at": datetime(2026, 8, 13, 2, 0),
            },
            {
                "trip_number": 101,
                "started_at": datetime(2026, 8, 13, 20, 0),
                "ended_at": datetime(2026, 8, 14, 1, 0),
            },
        ]

        filtered = self.service._filter_closed_trips(rows, date(2026, 8, 13))

        self.assertEqual([100], [row["trip_number"] for row in filtered])


class MonitoringTripPayloadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SiteAlphaSyncService(state_repository=None, push_client=None)

    def test_includes_current_location_and_weight(self) -> None:
        row = {
            "trip_number": 123,
            "plate": "ABC1D23",
            "started_at": datetime(2026, 8, 13, 8, 30),
            "destination": "Cliente X",
            "km_programado": 118.5,
            "current_location": "BR-277, km 100",
            "weight": 28500.0,
            "status": "Em andamento",
        }

        payload = self.service._build_viagem_atual_payload(row)

        self.assertEqual("BR-277, km 100", payload["local_atual"])
        self.assertEqual(28500.0, payload["peso"])


class ClosedTripPayloadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SiteAlphaSyncService(state_repository=None, push_client=None)

    def test_uses_customer_cargo_start_date_and_quantity(self) -> None:
        row = {
            "trip_number": 123,
            "plate": "ABC1D23",
            "started_at": datetime(2026, 8, 14, 22, 30),
            "ended_at": datetime(2026, 8, 15, 2, 0),
            "carga_cliente": "Carga 456",
            "cliente": "Destino X",
            "quantidade": 2,
        }

        payload = self.service._build_closed_trip_payload("15/08/2026", row)

        self.assertEqual("Carga 456", payload["documento_transporte"])
        self.assertEqual("BRF S.A. CHAPECO/SC", payload["cliente"])
        self.assertEqual("Destino X", payload["destino"])
        self.assertEqual("2026-08-14", payload["data_competencia"])
        self.assertEqual(2, payload["total_destinos"])

    def test_builds_lote_id_from_closed_trip_payloads(self) -> None:
        lote_id = self.service._build_lote_id(
            "15/08/2026",
            [{"numero_viagem": "100"}, {"numero_viagem": "200"}],
        )

        self.assertTrue(lote_id.startswith("scraping-20260815-"))
        self.assertTrue(lote_id.endswith("-100-200"))


class ClosedTripStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SQLiteStateRepository(f"{self.tempdir.name}/state.sqlite3")
        self.trip = {
            "numero_viagem": "123",
            "placa": "ABC1D23",
            "data_competencia": "2026-08-13",
            "data_inicio": "2026-08-13 08:00:00",
            "data_fim": "2026-08-13 12:00:00",
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_marks_trip_as_accepted_and_does_not_resend_unchanged_payload(self) -> None:
        self.assertEqual([self.trip], self.repository.record_closed_trips([self.trip]))

        self.repository.mark_closed_trips_accepted(["123"], "batch-1")

        self.assertEqual([], self.repository.record_closed_trips([self.trip]))
        status = self.repository.list_closed_trip_statuses()[0]
        self.assertEqual("accepted", status["status_api"])
        self.assertEqual(1, status["tentativas"])
        self.assertEqual([], self.repository.missing_closed_trip_numbers(["123"]))

    def test_changed_or_failed_trip_is_queued_for_another_send(self) -> None:
        self.repository.record_closed_trips([self.trip])
        self.repository.mark_closed_trips_failed(["123"], "batch-1", "HTTP 503")

        self.assertEqual([self.trip], self.repository.record_closed_trips([self.trip]))

        self.repository.mark_closed_trips_accepted(["123"], "batch-2")
        changed_trip = {**self.trip, "cliente": "Cliente atualizado"}
        self.assertEqual([changed_trip], self.repository.record_closed_trips([changed_trip]))
        self.assertEqual("pending", self.repository.list_closed_trip_statuses()[0]["status_api"])


if __name__ == "__main__":
    unittest.main()
