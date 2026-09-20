import unittest

from automation.services.sascar_sync import SascarCollectorService


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
        service = SascarCollectorService()
        service._sascar_session = lambda: FakeSascarSession(
            [
                {"placa": "ABC1D23", "data_referencia": "2026-09-14", "quilometragem": 120},
                {"placa": "XYZ9Z99", "data_referencia": "2026-09-14", "quilometragem": 0},
            ]
        )

        registros = service.collect_traveled_distance()

        self.assertEqual(1, len(registros))
        self.assertEqual("ABC1D23", registros[0]["placa"])


if __name__ == "__main__":
    unittest.main()
