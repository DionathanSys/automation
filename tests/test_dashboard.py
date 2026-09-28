from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from automation.config import ApiConfig, settings
from automation.dashboard import install_dashboard
from automation.db.automation_repository import AutomationRepository


class DashboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=__import__("sqlalchemy").pool.StaticPool)
        AutomationRepository(self.engine).create_schema_for_tests()

    def test_dashboard_is_disabled_without_credentials(self) -> None:
        with patch.object(settings, "api", ApiConfig(dashboard_username="", dashboard_password="")):
            app = FastAPI()
            install_dashboard(app, self.engine)
            response = TestClient(app).get("/dashboard")
        self.assertEqual(404, response.status_code)

    def test_dashboard_rejects_anonymous_and_reads_real_database_state(self) -> None:
        with patch.object(settings, "api", ApiConfig(dashboard_username="reader", dashboard_password="secret")):
            app = FastAPI()
            install_dashboard(app, self.engine)
            client = TestClient(app)
            self.assertEqual(401, client.get("/dashboard").status_code)
            response = client.get("/dashboard", auth=("reader", "secret"))
            self.assertEqual(200, response.status_code)
            self.assertIn("Visão geral", response.text)
            self.assertEqual("no-store", response.headers["cache-control"])
            self.assertEqual(200, client.get("/dashboard/jobs", auth=("reader", "secret")).status_code)
            self.assertEqual(404, client.get("/dashboard/jobs/missing", auth=("reader", "secret")).status_code)
            self.assertEqual(405, client.post("/dashboard/jobs", auth=("reader", "secret")).status_code)


if __name__ == "__main__":
    unittest.main()
