import json

import httpx
import pytest

from backend.paypal import PayPalClient, PayPalError, verify_capture


def paypal_handler(records: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            json.loads(request.content)
            if request.content and "application/json" in request.headers.get("content-type", "")
            else {}
        )
        records.append({"method": request.method, "path": request.url.path, "body": body})
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "sandbox-token"})
        if request.url.path == "/v2/checkout/orders":
            return httpx.Response(
                200,
                json={
                    "id": "ORDER-1",
                    "status": "CREATED",
                    "links": [
                        {"rel": "approve", "href": "https://sandbox.paypal.example/approve"}
                    ],
                },
            )
        if request.url.path.endswith("/capture"):
            return httpx.Response(
                200,
                json={
                    "id": "ORDER-1",
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "captures": [
                                    {
                                        "id": "CAP-1",
                                        "status": "COMPLETED",
                                        "amount": {"value": "2400.00", "currency_code": "USD"},
                                    }
                                ]
                            }
                        }
                    ],
                },
            )
        if request.url.path == "/v1/notifications/verify-webhook-signature":
            return httpx.Response(200, json={"verification_status": "SUCCESS"})
        return httpx.Response(404, json={"error": "not found"})

    return handler


def test_create_order_sends_the_invoice_amount_and_returns_the_approve_link():
    records: list[dict] = []
    client = PayPalClient(
        "id",
        "secret",
        transport=httpx.MockTransport(paypal_handler(records)),
    )
    order = client.create_order(
        240000,
        "USD",
        "inv-h2",
        "https://workgraph.example/return",
        "https://workgraph.example/cancel",
    )

    assert order["id"] == "ORDER-1"
    assert order["approve_url"].startswith("https://sandbox.paypal.example/")
    create = next(record for record in records if record["path"] == "/v2/checkout/orders")
    assert create["body"]["purchase_units"][0]["amount"] == {
        "currency_code": "USD",
        "value": "2400.00",
    }
    assert create["body"]["purchase_units"][0]["reference_id"] == "inv-h2"


def test_capture_is_verified_and_returns_the_capture_id():
    records: list[dict] = []
    client = PayPalClient(
        "id",
        "secret",
        transport=httpx.MockTransport(paypal_handler(records)),
    )
    order = client.capture_order("ORDER-1")
    capture_id = verify_capture(order, "ORDER-1", 240000, "USD")
    assert capture_id == "CAP-1"


def test_verify_capture_rejects_wrong_amount_currency_status_and_order():
    good = {
        "id": "ORDER-1",
        "status": "COMPLETED",
        "purchase_units": [
            {
                "payments": {
                    "captures": [
                        {
                            "id": "CAP-1",
                            "status": "COMPLETED",
                            "amount": {"value": "2400.00", "currency_code": "USD"},
                        }
                    ]
                }
            }
        ],
    }
    with pytest.raises(PayPalError) as error:
        verify_capture(good, "ORDER-1", 240001, "USD")
    assert error.value.code == "paypal_amount_mismatch"

    with pytest.raises(PayPalError) as error:
        verify_capture(good, "ORDER-1", 240000, "EUR")
    assert error.value.code == "paypal_currency_mismatch"

    with pytest.raises(PayPalError) as error:
        verify_capture({**good, "status": "APPROVED"}, "ORDER-1", 240000, "USD")
    assert error.value.code == "paypal_not_completed"

    with pytest.raises(PayPalError) as error:
        verify_capture(good, "ORDER-2", 240000, "USD")
    assert error.value.code == "paypal_order_mismatch"


def test_a_non_sandbox_host_is_refused():
    with pytest.raises(PayPalError) as error:
        PayPalClient("id", "secret", base_url="https://api-m.paypal.com")
    assert error.value.code == "paypal_host_refused"


def test_webhook_verification_is_skipped_without_an_id_and_calls_paypal_with_one():
    skipped = PayPalClient("id", "secret", webhook_id="")
    assert skipped.verify_webhook({}, b"{}") is None

    records: list[dict] = []
    client = PayPalClient(
        "id",
        "secret",
        webhook_id="WH-1",
        transport=httpx.MockTransport(paypal_handler(records)),
    )
    headers = {
        "paypal-transmission-id": "t-1",
        "paypal-transmission-time": "2026-11-13T00:00:00Z",
        "paypal-cert-url": "https://api.paypal.com/cert",
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-transmission-sig": "sig",
    }
    assert client.verify_webhook(headers, b'{"event_type":"PAYMENT.CAPTURE.COMPLETED"}') is True
    verify = next(
        record for record in records if record["path"].endswith("verify-webhook-signature")
    )
    assert verify["body"]["webhook_id"] == "WH-1"
    assert verify["body"]["webhook_event"]["event_type"] == "PAYMENT.CAPTURE.COMPLETED"


def test_mock_mode_never_calls_the_network():
    client = PayPalClient(mock=True)
    order = client.create_order(
        240000, "USD", "inv-h2", "https://workgraph.example/return", "https://workgraph.example/cancel"
    )
    assert order["id"].startswith("MOCK-")
    captured = client.capture_order(order["id"], 240000, "USD")
    assert verify_capture(captured, order["id"], 240000, "USD") == f"CAP-{order['id']}"
