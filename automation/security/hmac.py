from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from automation.config import settings
from automation.db.automation_repository import AutomationRepository


@dataclass(frozen=True)
class AuthenticatedClient:
    id: str
    code: str
    scopes: frozenset[str]
    allowed_collectors: frozenset[str]
    callback_url: str | None


class HmacSigner:
    @staticmethod
    def canonical_string(
        method: str,
        path_with_query: str,
        timestamp: str,
        nonce: str,
        raw_body: bytes,
    ) -> str:
        body_hash = hashlib.sha256(raw_body).hexdigest()
        return "\n".join(
            [method.upper(), path_with_query, timestamp, nonce, body_hash]
        )

    @classmethod
    def sign(
        cls,
        secret: str,
        method: str,
        path_with_query: str,
        timestamp: str,
        nonce: str,
        raw_body: bytes,
    ) -> str:
        canonical = cls.canonical_string(
            method,
            path_with_query,
            timestamp,
            nonce,
            raw_body,
        )
        return hmac.new(
            secret.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


class HmacAuthenticator:
    def __init__(self, repository: AutomationRepository) -> None:
        self.repository = repository

    def authenticate(
        self,
        *,
        client_code: str | None,
        timestamp: str | None,
        nonce: str | None,
        signature: str | None,
        signature_version: str | None,
        method: str,
        path_with_query: str,
        raw_body: bytes,
    ) -> AuthenticatedClient:
        if not client_code or not timestamp or not nonce or not signature:
            raise HmacAuthenticationError("INVALID_SIGNATURE", "Assinatura ausente.")
        if signature_version != "v1":
            raise HmacAuthenticationError(
                "INVALID_SIGNATURE", "Versao de assinatura nao suportada."
            )

        try:
            timestamp_value = int(timestamp)
        except ValueError as exc:
            raise HmacAuthenticationError(
                "REPLAY_DETECTED", "Timestamp invalido."
            ) from exc

        if abs(int(time.time()) - timestamp_value) > settings.automation.hmac_timestamp_tolerance_seconds:
            raise HmacAuthenticationError(
                "REPLAY_DETECTED", "Timestamp fora da janela permitida."
            )

        client = self.repository.get_client(client_code)
        if client is None or not client["is_active"]:
            raise HmacAuthenticationError("CLIENT_FORBIDDEN", "Cliente inativo ou inexistente.")

        configured_client_id = settings.automation.client_id.strip()
        configured_secret = settings.automation.client_secret
        if client_code != configured_client_id or not configured_secret:
            raise HmacAuthenticationError(
                "INVALID_SIGNATURE", "Credencial do cliente nao configurada."
            )

        configured_hashes = {
            hashlib.sha256(configured_secret.encode("utf-8")).hexdigest(),
        }
        if settings.automation.previous_client_secret:
            configured_hashes.add(
                hashlib.sha256(
                    settings.automation.previous_client_secret.encode("utf-8")
                ).hexdigest()
            )
        stored_hashes = {str(client["secret_hash"])}
        if client.get("previous_secret_hash"):
            stored_hashes.add(str(client["previous_secret_hash"]))
        if not configured_hashes.intersection(stored_hashes):
            raise HmacAuthenticationError("INVALID_SIGNATURE", "Segredo invalido.")

        if self.repository.nonce_exists(str(client["id"]), nonce):
            raise HmacAuthenticationError("REPLAY_DETECTED", "Nonce ja utilizado.")

        supplied_signature = signature.removeprefix("sha256=")
        candidate_secrets = [configured_secret]
        if settings.automation.previous_client_secret:
            candidate_secrets.append(settings.automation.previous_client_secret)
        if not any(
            hmac.compare_digest(
                HmacSigner.sign(
                    candidate_secret,
                    method,
                    path_with_query,
                    timestamp,
                    nonce,
                    raw_body,
                ),
                supplied_signature,
            )
            for candidate_secret in candidate_secrets
        ):
            raise HmacAuthenticationError("INVALID_SIGNATURE", "Assinatura invalida.")

        if not self.repository.save_nonce(
            str(client["id"]), nonce, settings.automation.nonce_ttl_seconds
        ):
            raise HmacAuthenticationError("REPLAY_DETECTED", "Nonce ja utilizado.")
        return AuthenticatedClient(
            id=str(client["id"]),
            code=str(client["code"]),
            scopes=frozenset(client.get("scopes") or []),
            allowed_collectors=frozenset(client.get("allowed_collectors") or []),
            callback_url=client.get("callback_url"),
        )


class HmacAuthenticationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
