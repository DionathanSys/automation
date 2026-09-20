import unittest
from unittest.mock import Mock

from automation.services.sascar_sync import SascarSyncService


class FakeSascarSession:
    def __init__(self, registros: list[dict[str, object]]) -> None:
        self.registros = registros

    def __enter__(self) -> "FakeSascarSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def generate_traveled_distance(self) -> list[dict[str, object]]:
        return self.registros


class SascarSyncTest(unittest.TestCase):
    def test_skips_non_positive_odometer_before_sending(self) -> None:
        push_client = Mock()
        service = SascarSyncService(push_client)
        service._sascar_session = lambda: FakeSascarSession(
            [
                {"placa": "ABC1D23", "data_referencia": "2026-09-14", "quilometragem": 120},
                {"placa": "XYZ9Z99", "data_referencia": "2026-09-14", "quilometragem": 0},
            ]
        )

        payloads = service.push_traveled_distance()

        self.assertEqual(1, len(payloads[0]["registros"]))
        self.assertEqual("ABC1D23", payloads[0]["registros"][0]["placa"])
        push_client.push_historico_quilometragem.assert_called_once_with(payloads[0])


if __name__ == "__main__":
    unittest.main()
