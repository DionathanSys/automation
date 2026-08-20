from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any
from uuid import uuid4
from urllib import error, parse, request

from automation.config import settings


class AppPushClient:
    def __init__(self) -> None:
        self.base_url = settings.receiver.base_url.rstrip("/")
        self.api_key = settings.receiver.api_key
        self.webhook_secret = settings.receiver.webhook_secret
        self.timeout_seconds = settings.receiver.timeout_seconds

    def push_viagem_atual(self, payload: dict[str, Any]) -> None:
        self._post_json(settings.receiver.viagem_atual_path, self._serialize_row(payload), signed=True)

    def push_movimento_diario(self, payload: dict[str, Any]) -> None:
        self._post_json(settings.receiver.movimento_diario_path, self._serialize_row(payload), signed=True)

    def push_historico_quilometragem(self, payload: dict[str, Any]) -> None:
        self._post_json(settings.receiver.historico_quilometragem_path, payload, signed=True)

    def push_closed_trips(self, lote_id: str, rows: list[dict[str, Any]]) -> None:
        payload = {
            "lote_id": lote_id,
            "viagens": self._serialize(rows),
        }
        self._post_json(settings.receiver.closed_trips_path, payload, signed=True)

    def _post_json(self, path: str, payload: dict[str, Any], signed: bool = False) -> None:
        if not self.base_url:
            raise ValueError("RECEIVER_BASE_URL nao configurada.")

        url = parse.urljoin(f"{self.base_url}/", path.lstrip("/"))
        raw_body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        body = raw_body.encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if signed:
            headers.update(self._build_signed_headers(raw_body))

        req = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"Falha ao enviar payload para {url}: HTTP {response.status}")
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Falha ao enviar payload para {url}: HTTP {exc.code} {response_body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Falha ao conectar em {url}: {exc.reason}") from exc

    def _build_signed_headers(self, raw_body: str) -> dict[str, str]:
        if not self.webhook_secret:
            raise ValueError("RECEIVER_WEBHOOK_SECRET nao configurado.")

        timestamp = str(int(time.time()))
        signed_payload = f"{timestamp}.{raw_body}".encode("utf-8")
        digest = hmac.new(
            self.webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": f"sha256={digest}",
            "X-Request-Id": str(uuid4()),
        }

    def _serialize(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self._serialize_row(row) for row in rows]

    def _serialize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, datetime):
                payload[key] = value.isoformat()
            else:
                payload[key] = value
        return payload
