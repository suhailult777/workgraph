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

def bundle_for(*ids):
    nodes = [
        {
            "id": "inv-h2",
            "kind": "Invoice",
            "title": "WG-1002",
            "status": "SENT",
            "amount_cents": 240000,
        },
        {
            "id": "ms-h3",
            "kind": "Milestone",
            "title": "Build",
            "status": "BLOCKED",
            "amount_cents": 320000,
        },
    ]
    matched = [node for node in nodes if node["id"] in ids] or nodes
    return {
        "matched": matched,
        "nodes": nodes,
        "edges": [],
        "terms": [],
        "context": "Graph context: " + ", ".join(node["id"] for node in nodes),
    }


def test_graph_context_is_added_and_missing_sources_are_appended():
    records: list[dict] = []
    service = AssistantService(
        api_key="test",
        models=["a:free"],
        transport=httpx.MockTransport(handler_for(records)),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
        retrieve=lambda question: bundle_for("inv-h2"),
    )
    completion = service.chat(
        {"messages": [{"role": "user", "content": "Which invoice blocks Build?"}]},
        "127.0.0.1",
    )
    sent = records[0]["messages"]
    assert any(
        message["role"] == "system" and "Graph context" in message["content"]
        for message in sent
    )
    content = completion["choices"][0]["message"]["content"]
    assert "Sources: [inv-h2]" in content
    assert completion["workgraph"]["citations"][0]["id"] == "inv-h2"


def test_a_question_with_no_graph_match_is_answered_without_a_provider_call():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500, json={"error": "should not run"})

    service = AssistantService(
        api_key="test",
        models=["a:free"],
        transport=httpx.MockTransport(handler),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
        retrieve=lambda question: {"matched": [], "nodes": [], "edges": [], "context": ""},
    )
    completion = service.chat(
        {"messages": [{"role": "user", "content": "What is the capital of France?"}]},
        "127.0.0.1",
    )
    assert called is False
    content = completion["choices"][0]["message"]["content"]
    assert content.startswith("not in the graph")


def test_mock_mode_returns_a_cited_graph_summary():
    service = AssistantService(
        mock=True,
        models=["a:free"],
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
        retrieve=lambda question: bundle_for("ms-h3"),
    )
    completion = service.chat(
        {"messages": [{"role": "user", "content": "Which milestone is blocked?"}]},
        "127.0.0.1",
    )
    content = completion["choices"][0]["message"]["content"]
    assert "[ms-h3]" in content
    assert completion["workgraph"]["citations"]

def test_a_retrieval_failure_refuses_to_answer_without_sources():
    service = AssistantService(
        api_key="test",
        models=["a:free"],
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
        retrieve=lambda question: (_ for _ in ()).throw(RuntimeError("store down")),
    )
    with pytest.raises(AssistantError) as error:
        service.chat(
            {"messages": [{"role": "user", "content": "Which invoice is open?"}]},
            "127.0.0.1",
        )
    assert error.value.code == "graph_unavailable"
    assert error.value.status == 503

def test_empty_content_is_retried_on_the_next_free_model():
    records: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        records.append(body["model"])
        if body["model"] == "a:free":
            return httpx.Response(
                200,
                json={
                    "id": "empty-1",
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "reasoning": "only reasoning tokens",
                            },
                            "finish_reason": "length",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "visible-1",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Visible answer."},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    service = AssistantService(
        api_key="test",
        models=["a:free", "b:free"],
        transport=httpx.MockTransport(handler),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
    )
    completion = service.chat(
        {"messages": [{"role": "user", "content": "Which milestone is blocked?"}]},
        "127.0.0.1",
    )
    assert records == ["a:free", "b:free"]
    assert completion["model"] == "b:free"
    assert completion["choices"][0]["message"]["content"] == "Visible answer."


def test_all_empty_content_reports_an_empty_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "", "reasoning": "thinking"},
                        "finish_reason": "length",
                    }
                ],
            },
        )

    service = AssistantService(
        api_key="test",
        models=["a:free", "b:free"],
        transport=httpx.MockTransport(handler),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
    )
    with pytest.raises(AssistantError) as error:
        service.chat(
            {"messages": [{"role": "user", "content": "Which milestone is blocked?"}]},
            "127.0.0.1",
        )
    assert error.value.code == "upstream_empty"
    assert error.value.status == 502


def test_a_tool_call_with_empty_content_is_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "website_get_graph_state", "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            },
        )

    service = AssistantService(
        api_key="test",
        models=["a:free", "b:free"],
        transport=httpx.MockTransport(handler),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
    )
    completion = service.chat(
        {"messages": [{"role": "user", "content": "Read the graph."}]},
        "127.0.0.1",
    )
    assert completion["choices"][0]["message"]["tool_calls"][0]["id"] == "call-1"

@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError])
def test_a_transport_timeout_is_retried_on_the_next_free_model(error):
    records: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        records.append(body["model"])
        if body["model"] == "a:free":
            raise error("slow or unreachable")
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "After timeout."},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    service = AssistantService(
        api_key="test",
        models=["a:free", "b:free"],
        transport=httpx.MockTransport(handler),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
    )
    completion = service.chat(
        {"messages": [{"role": "user", "content": "Which milestone is blocked?"}]},
        "127.0.0.1",
    )
    assert records == ["a:free", "b:free"]
    assert completion["model"] == "b:free"
    assert completion["choices"][0]["message"]["content"] == "After timeout."


def test_all_timeouts_return_a_clean_upstream_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    service = AssistantService(
        api_key="test",
        models=["a:free", "b:free"],
        transport=httpx.MockTransport(handler),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
    )
    with pytest.raises(AssistantError) as error:
        service.chat(
            {"messages": [{"role": "user", "content": "Which milestone is blocked?"}]},
            "127.0.0.1",
        )
    assert error.value.code == "upstream_timeout"
    assert error.value.status == 503


def test_the_total_deadline_stops_extra_model_attempts():
    records: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        records.append(body["model"])
        raise httpx.ReadTimeout("slow")

    service = AssistantService(
        api_key="test",
        models=["a:free", "b:free", "c:free"],
        transport=httpx.MockTransport(handler),
        quota=lambda ip, day, ip_cap, global_cap: {"allowed": True},
        attempt_timeout=5,
        total_timeout=0.01,
    )
    with pytest.raises(AssistantError) as error:
        service.chat(
            {"messages": [{"role": "user", "content": "Which milestone is blocked?"}]},
            "127.0.0.1",
        )
    assert error.value.code == "upstream_timeout"
    assert len(records) <= 1

def test_the_default_free_model_order_starts_with_the_faster_model():
    from backend.assistant import DEFAULT_FREE_MODELS

    assert DEFAULT_FREE_MODELS[0] == "google/gemma-4-26b-a4b-it:free"
    assert all(model.endswith(":free") for model in DEFAULT_FREE_MODELS)
