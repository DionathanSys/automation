from __future__ import annotations

import json
import time
from urllib import error, parse, request
from uuid import uuid4

from automation.config import settings
from automation.db.automation_repository import AutomationRepository, utc_now
from automation.security.hmac import HmacSigner
from automation.utils.logger import get_logger


logger = get_logger(__name__)
RETRY_DELAYS_SECONDS = (60, 300, 900, 3600, 21600, 86400)


class WebhookService:
    def __init__(self, repository: AutomationRepository, enqueue=None) -> None:
        self.repository = repository
        self.enqueue = enqueue

    def deliver(self, event_id: str) -> None:
        event = self.repository.get_event(event_id)
        if event is None:
            logger.warning("Evento inexistente para webhook. event_id=%s", event_id)
            return
        client = self.repository.get_client_by_id(str(event["client_id"]))
        callback_url = client.get("callback_url") if client else None
        attempt_number = self.repository.next_webhook_attempt(event_id)
        delivery_id = self.repository.create_webhook_delivery(event_id, attempt_number)

        if not callback_url:
            self.repository.finish_webhook_delivery(
                delivery_id,
                "FAILED",
                None,
                "Callback URL nao configurada.",
                None,
            )
            return
        if not settings.automation.webhook_secret:
            self.repository.finish_webhook_delivery(
                delivery_id,
                "FAILED",
                None,
                "Segredo de webhook nao configurado.",
                None,
            )
            return

        body = json.dumps(
            event["payload_json"],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        parsed_url = parse.urlparse(callback_url)
        path_with_query = parsed_url.path or "/"
        if parsed_url.query:
            path_with_query = f"{path_with_query}?{parsed_url.query}"
        timestamp = str(int(time.time()))
        nonce = uuid4().hex
        signature = HmacSigner.sign(
            settings.automation.webhook_secret,
            "POST",
            path_with_query,
            timestamp,
            nonce,
            body,
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Client-ID": settings.automation.webhook_client_id,
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
            "X-Signature": signature,
            "X-Signature-Version": "v1",
            "X-Request-ID": f"webhook-{event_id}-{attempt_number}",
        }
        http_status: int | None = None
        response_excerpt: str | None = None
        try:
            req = request.Request(callback_url, data=body, headers=headers, method="POST")
            with request.urlopen(req, timeout=settings.automation.webhook_timeout_seconds) as response:
                http_status = response.status
                response_excerpt = response.read(500).decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            http_status = exc.code
            response_excerpt = exc.read(500).decode("utf-8", errors="replace")
        except (error.URLError, TimeoutError) as exc:
            response_excerpt = str(exc)

        if http_status is not None and 200 <= http_status < 300:
            self.repository.finish_webhook_delivery(
                delivery_id,
                "DELIVERED",
                http_status,
                response_excerpt,
                None,
            )
            return

        retryable = http_status is None or http_status in {408, 425, 429} or http_status >= 500
        if retryable and attempt_number <= len(RETRY_DELAYS_SECONDS):
            delay_seconds = RETRY_DELAYS_SECONDS[attempt_number - 1]
            next_attempt_at = utc_now()
            from datetime import timedelta

            next_attempt_at += timedelta(seconds=delay_seconds)
            self.repository.finish_webhook_delivery(
                delivery_id,
                "RETRYING",
                http_status,
                response_excerpt,
                next_attempt_at,
            )
            if self.enqueue is not None:
                try:
                    self.enqueue(event_id, delay_seconds * 1000)
                except Exception:
                    logger.exception("Falha ao reagendar webhook. event_id=%s", event_id)
            return

        self.repository.finish_webhook_delivery(
            delivery_id,
            "FAILED",
            http_status,
            response_excerpt,
            None,
        )
