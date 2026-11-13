"""Server-side assistant proxy for OpenRouter free models.

The browser runtime still owns the tool loop and the confirmation dialog. This
service only forwards the chat request to an allowlisted free model, enforces a
per-IP and global daily cap, and falls back to the next free model on 429/5xx.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

DEFAULT_FREE_MODELS = (
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
)
OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class AssistantError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def free_models() -> list[str]:
    configured = os.environ.get("OPENROUTER_FREE_MODELS", "")
    models = [part.strip() for part in configured.split(",") if part.strip()]
    models = [model for model in models if model.endswith(":free")]
    return models or list(DEFAULT_FREE_MODELS)


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _completion(model: str, content: str, tool_calls: list[dict] | None = None) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    finish = "stop"
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = ""
        finish = "tool_calls"
    return {
        "id": "chatcmpl-workgraph",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": None,
    }


def completion_to_sse(completion: dict) -> str:
    choice = (completion.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    model = completion.get("model") or "workgraph-live"
    tool_calls = message.get("tool_calls") or []
    events: list[dict] = []
    if tool_calls:
        for index, call in enumerate(tool_calls):
            events.append(
                {
                    "model": model,
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": index,
                                        "id": call.get("id") or f"call_live_{index}",
                                        "type": "function",
                                        "function": {
                                            "name": call.get("function", {}).get("name", ""),
                                            "arguments": call.get("function", {}).get(
                                                "arguments", "{}"
                                            ),
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )
        events.append(
            {"model": model, "choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
        )
    else:
        events.append(
            {
                "model": model,
                "choices": [
                    {
                        "delta": {"content": message.get("content") or ""},
                        "finish_reason": "stop",
                    }
                ],
            }
        )
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return body + "data: [DONE]\n\n"


class AssistantService:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        models: list[str] | None = None,
        quota: Callable[[str, str, int, int], dict] | None = None,
        transport: httpx.BaseTransport | None = None,
        mock: bool = False,
        ip_cap: int | None = None,
        global_cap: int | None = None,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self.models = models or free_models()
        self.quota = quota
        self.transport = transport
        self.mock = mock
        self.ip_cap = ip_cap if ip_cap is not None else int(os.environ.get("ASSISTANT_IP_DAILY_CAP", "20"))
        self.global_cap = (
            global_cap
            if global_cap is not None
            else int(os.environ.get("ASSISTANT_GLOBAL_DAILY_CAP", "300"))
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key) or self.mock

    def _quota_check(self, ip: str, day: str) -> None:
        if self.quota is None:
            return
        result = self.quota(ip, day, self.ip_cap, self.global_cap)
        if result.get("allowed"):
            return
        reason = result.get("reason")
        if reason == "ip_daily_cap":
            raise AssistantError(
                "quota_exhausted",
                f"This IP has used its {self.ip_cap} assistant calls for today. Try again tomorrow.",
                429,
            )
        raise AssistantError(
            "quota_exhausted",
            f"The site has used its {self.global_cap} assistant calls for today. Try again tomorrow.",
            429,
        )

    def _upstream(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": 900,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://workgraph.local",
            "X-Title": "WorkGraph",
        }
        with httpx.Client(transport=self.transport, timeout=45) as client:
            response = client.post(f"{OPENROUTER_BASE}/chat/completions", json=body, headers=headers)
        if response.status_code in (429,) or response.status_code >= 500:
            raise _RetryModel()
        if response.status_code in (401, 403):
            raise AssistantError(
                "upstream_auth",
                "The assistant provider rejected the server key. Check OPENROUTER_API_KEY.",
                502,
            )
        if response.status_code >= 400:
            raise AssistantError(
                "upstream_error",
                f"The assistant provider answered {response.status_code}.",
                502,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise AssistantError("upstream_error", "The assistant provider returned invalid JSON.") from exc
        if not isinstance(data, dict) or not data.get("choices"):
            raise AssistantError("upstream_error", "The assistant provider returned no choices.")
        return data

    def chat(self, payload: dict, ip: str, day: str | None = None) -> dict:
        if not self.configured:
            raise AssistantError(
                "assistant_not_configured",
                "The live assistant is not configured on this deployment.",
                503,
            )
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise AssistantError("invalid_request", "messages must be a non-empty list.", 422)
        if len(messages) > 40:
            raise AssistantError("invalid_request", "Too many messages in one request.", 422)
        tools = payload.get("tools") or []
        if not isinstance(tools, list) or len(tools) > 24:
            raise AssistantError("invalid_request", "Too many tools in one request.", 422)

        day = day or _utc_day()
        self._quota_check(ip, day)

        requested = str(payload.get("model") or "")
        allowed = [model for model in self.models if model.endswith(":free")]
        if not allowed:
            raise AssistantError(
                "assistant_not_configured",
                "No free assistant model is configured.",
                503,
            )
        start = allowed.index(requested) if requested in allowed else 0
        ordered = allowed[start:] + allowed[:start]

        if self.mock:
            from backend.demo_llm import demo_reply

            reply = demo_reply(payload)
            tool_call = reply.get("tool_call")
            if tool_call:
                return _completion(
                    ordered[0],
                    "",
                    [
                        {
                            "id": tool_call.get("id") or "call_live_mock",
                            "type": "function",
                            "function": {
                                "name": tool_call.get("name"),
                                "arguments": json.dumps(tool_call.get("arguments") or {}),
                            },
                        }
                    ],
                )
            return _completion(ordered[0], reply.get("content") or "")

        for model in ordered:
            try:
                data = self._upstream(model, messages, tools)
            except _RetryModel:
                continue
            data.setdefault("model", model)
            return data
        raise AssistantError(
            "upstream_unavailable",
            "Every free assistant model is busy or unavailable. Try again shortly.",
            502,
        )


class _RetryModel(Exception):
    pass
