import json

import httpx
import pytest

from backend.assistant import AssistantError, AssistantService, completion_to_sse


def handler_for(records: list[dict], statuses: dict[str, int] | None = None):
    statuses = statuses or {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        records.append(body)
        status = statuses.get(body["model"], 200)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "busy"}})
        return httpx.Response(
            200,
            json={
                "id": "upstream-1",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Grounded answer."},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    return handler


def test_missing_key_is_a_clear_not_configured_error():
    service = AssistantService(api_key="", models=["a:free"], quota=None)
    with pytest.raises(AssistantError) as error:
        service.chat({"messages": [{"role": "user", "content": "hi"}]}, "127.0.0.1")
    assert error.value.code == "assistant_not_configured"
    assert error.value.status == 503


def test_a_disallowed_model_is_replaced_by_the_first_free_model():
    records: list[dict] = []
    service = AssistantService(
        api_key="test",
        models=["a:free", "b:free"],
        transport=httpx.MockTransport(handler_for(records)),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
    )
    completion = service.chat(
        {"model": "paid/model", "messages": [{"role": "user", "content": "hi"}]},
        "127.0.0.1",
    )
    assert completion["model"] == "a:free"
    assert records[0]["model"] == "a:free"


def test_a_429_falls_back_to_the_next_free_model():
    records: list[dict] = []
    service = AssistantService(
        api_key="test",
        models=["a:free", "b:free"],
        transport=httpx.MockTransport(handler_for(records, {"a:free": 429})),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
    )
    completion = service.chat(
        {"model": "a:free", "messages": [{"role": "user", "content": "hi"}]},
        "127.0.0.1",
    )
    assert completion["model"] == "b:free"
    assert [record["model"] for record in records] == ["a:free", "b:free"]


def test_all_5xx_responses_are_a_clear_upstream_error():
    records: list[dict] = []
    service = AssistantService(
        api_key="test",
        models=["a:free", "b:free"],
        transport=httpx.MockTransport(handler_for(records, {"a:free": 500, "b:free": 503})),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
    )
    with pytest.raises(AssistantError) as error:
        service.chat({"messages": [{"role": "user", "content": "hi"}]}, "127.0.0.1")
    assert error.value.code == "upstream_unavailable"
    assert error.value.status == 502
    assert "test" not in error.value.message


def test_quota_is_checked_before_the_provider_is_called():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"choices": []})

    service = AssistantService(
        api_key="test",
        models=["a:free"],
        transport=httpx.MockTransport(handler),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": False, "reason": "ip_daily_cap"},
    )
    with pytest.raises(AssistantError) as error:
        service.chat({"messages": [{"role": "user", "content": "hi"}]}, "203.0.113.9")
    assert error.value.code == "quota_exhausted"
    assert error.value.status == 429
    assert called is False


def test_tool_calls_are_returned_as_sse_deltas():
    completion = {
        "model": "a:free",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "website_get_graph_state",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    body = completion_to_sse(completion)
    assert "website_get_graph_state" in body
    assert '"finish_reason": "tool_calls"' in body
    assert body.endswith("data: [DONE]\n\n")
