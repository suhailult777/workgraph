"""PayPal Orders v2, sandbox only.

The client refuses every host except api-m.sandbox.paypal.com. A local mock mode
exists for automated tests and the labelled dev checkout; production never
selects it unless PAYPAL_MOCK=1 is explicitly set outside production.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
SANDBOX_HOST = "api-m.sandbox.paypal.com"


class PayPalError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _assert_sandbox(url: str) -> None:
    parsed = httpx.URL(url)
    if parsed.scheme != "https" or parsed.host != SANDBOX_HOST:
        raise PayPalError(
            "paypal_host_refused",
            "PayPal calls are restricted to the sandbox host.",
            500,
        )


def verify_capture(
    order: dict,
    expected_order_id: str,
    amount_cents: int,
    currency: str,
) -> str:
    if order.get("id") != expected_order_id:
        raise PayPalError("paypal_order_mismatch", "PayPal returned a different order id.", 502)
    if order.get("status") != "COMPLETED":
        raise PayPalError(
            "paypal_not_completed",
            f"PayPal order is {order.get('status')}, not COMPLETED.",
            409,
        )
    try:
        capture = order["purchase_units"][0]["payments"]["captures"][0]
        value = capture["amount"]["value"]
        code = capture["amount"]["currency_code"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PayPalError("paypal_capture_missing", "PayPal returned no capture.", 502) from exc
    if capture.get("status") != "COMPLETED":
        raise PayPalError(
            "paypal_capture_not_completed",
            f"PayPal capture is {capture.get('status')}, not COMPLETED.",
            409,
        )
    if code != currency:
        raise PayPalError(
            "paypal_currency_mismatch",
            f"PayPal captured {code}; the invoice is {currency}.",
            409,
        )
    expected_value = f"{amount_cents / 100:.2f}"
    if str(value) != expected_value:
        raise PayPalError(
            "paypal_amount_mismatch",
            f"PayPal captured {value}; the invoice is {expected_value}.",
            409,
        )
    return str(capture.get("id") or "")


class PayPalClient:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        webhook_id: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        mock: bool = False,
        base_url: str = SANDBOX_BASE,
    ):
        _assert_sandbox(base_url)
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id if client_id is not None else os.environ.get("PAYPAL_CLIENT_ID", "")
        self.client_secret = (
            client_secret
            if client_secret is not None
            else os.environ.get("PAYPAL_CLIENT_SECRET", "")
        )
        self.webhook_id = (
            webhook_id if webhook_id is not None else os.environ.get("PAYPAL_WEBHOOK_ID", "")
        )
        self.transport = transport
        self.mock = mock
        self._token: str | None = None

    @property
    def configured(self) -> bool:
        return self.mock or bool(self.client_id and self.client_secret)

    def _http(self) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=30)

    def _access_token(self) -> str:
        if self.mock:
            return "mock-token"
        if self._token:
            return self._token
        if not self.configured:
            raise PayPalError(
                "paypal_not_configured",
                "PayPal sandbox is not configured on this deployment.",
                503,
            )
        with self._http() as client:
            response = client.post(
                f"{self.base_url}/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if response.status_code >= 400:
            raise PayPalError(
                "paypal_auth_failed",
                f"PayPal sandbox authentication answered {response.status_code}.",
                502,
            )
        try:
            token = response.json().get("access_token")
        except ValueError as exc:
            raise PayPalError("paypal_auth_failed", "PayPal returned invalid auth JSON.") from exc
        if not token:
            raise PayPalError("paypal_auth_failed", "PayPal returned no access token.")
        self._token = str(token)
        return self._token

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        _assert_sandbox(self.base_url + path)
        token = self._access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        with self._http() as client:
            response = client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=body,
            )
        if response.status_code >= 400:
            raise PayPalError(
                "paypal_request_failed",
                f"PayPal sandbox answered {response.status_code}.",
                502,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise PayPalError("paypal_request_failed", "PayPal returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise PayPalError("paypal_request_failed", "PayPal returned an unexpected payload.")
        return data

    def create_order(
        self,
        amount_cents: int,
        currency: str,
        reference_id: str,
        return_url: str,
        cancel_url: str,
    ) -> dict:
        if self.mock:
            order_id = f"MOCK-{uuid.uuid4().hex[:12].upper()}"
            return {
                "id": order_id,
                "status": "CREATED",
                "approve_url": f"/#/mock-paypal?order={order_id}",
                "mock": True,
            }
        value = f"{amount_cents / 100:.2f}"
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "amount": {"currency_code": currency, "value": value},
                }
            ],
            "application_context": {
                "return_url": return_url,
                "cancel_url": cancel_url,
                "user_action": "PAY_NOW",
            },
        }
        order = self._request("POST", "/v2/checkout/orders", body)
        approve = next(
            (link.get("href") for link in order.get("links", []) if link.get("rel") == "approve"),
            "",
        )
        if not order.get("id") or not approve:
            raise PayPalError("paypal_order_invalid", "PayPal returned no order id or approve link.")
        return {"id": order["id"], "status": order.get("status"), "approve_url": approve}

    def capture_order(
        self,
        order_id: str,
        amount_cents: int | None = None,
        currency: str | None = None,
    ) -> dict:
        if self.mock:
            value = f"{(amount_cents or 0) / 100:.2f}"
            return {
                "id": order_id,
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": f"CAP-{order_id}",
                                    "status": "COMPLETED",
                                    "amount": {
                                        "value": value,
                                        "currency_code": currency or "USD",
                                    },
                                }
                            ]
                        }
                    }
                ],
            }
        return self._request("POST", f"/v2/checkout/orders/{order_id}/capture", {})

    def get_order(self, order_id: str) -> dict:
        if self.mock:
            return {"id": order_id, "status": "CREATED"}
        return self._request("GET", f"/v2/checkout/orders/{order_id}")

    def verify_webhook(self, headers: dict[str, str], raw_body: bytes) -> bool | None:
        if not self.webhook_id:
            return None
        if self.mock:
            return True
        required = {
            "transmission_id": headers.get("paypal-transmission-id", ""),
            "transmission_time": headers.get("paypal-transmission-time", ""),
            "cert_url": headers.get("paypal-cert-url", ""),
            "auth_algo": headers.get("paypal-auth-algo", ""),
            "transmission_sig": headers.get("paypal-transmission-sig", ""),
        }
        if not all(required.values()):
            return False
        try:
            event = json.loads(raw_body)
        except ValueError:
            return False
        body = {
            **required,
            "webhook_id": self.webhook_id,
            "webhook_event": event,
        }
        result = self._request("POST", "/v1/notifications/verify-webhook-signature", body)
        return result.get("verification_status") == "SUCCESS"
