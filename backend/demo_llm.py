"""A deterministic scripted model for the no-key WorkGraph demo.

This is not an LLM. It chooses one registered action from the visitor's message,
then writes an answer from the action receipt. The same module is used by the
local FastAPI demo router and by the tests. The demo is a local-development
fallback only; a production deployment uses the server-side live assistant.
"""

from __future__ import annotations

import json
import re
from typing import Any

MODEL = "workgraph-demo"
PLAN_TEMPLATE = [
    {"name": "Scope", "depends_on": []},
    {"name": "Design", "depends_on": ["Scope"]},
    {"name": "Build", "depends_on": ["Design"]},
    {"name": "Handover", "depends_on": ["Build"]},
]
SKILLS = {
    "design": "Design systems",
    "design-system": "Design systems",
    "design system": "Design systems",
    "research": "User research",
    "front-end": "Front-end build",
    "front end": "Front-end build",
    "build": "Front-end build",
}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return " ".join(parts)
    return str(value or "")


def _messages(payload: dict) -> list[dict]:
    messages = payload.get("messages")
    return messages if isinstance(messages, list) else []


def _last_user(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return _text(message.get("content")).strip()
    return ""


def _offered(payload: dict) -> set[str]:
    offered = set()
    for tool in payload.get("tools") or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict) and function.get("name"):
            offered.add(str(function["name"]))
    return offered


def _refusal(message: str) -> str | None:
    lower = message.lower()
    card = re.search(r"\b(?:card|credit card)\b", lower)
    charge = re.search(r"\b(?:charge|pay|record|take|send|make)\b", lower)
    if card and charge:
        return (
            "I can't charge a card, take real money, or send email from WorkGraph. "
            "This site records sample payments only. I can show the blocked paths, "
            "invoices and paid history."
        )
    if any(
        phrase in lower
        for phrase in (
            "paypal",
            "real money",
            "bank transfer",
            "wire transfer",
            "real payment",
            "send a payment",
            "make a payment",
        )
    ) or re.search(r"\bwire\b", lower):
        return (
            "I can't charge a card, take real money, or send email from WorkGraph. "
            "This site records sample payments only. I can show the blocked paths, "
            "invoices and paid history."
        )
    if "email" in lower and re.search(r"\b(?:send|email)\b", lower):
        return (
            "I can't send email from WorkGraph. The project page and the sample graph are "
            "the only places to act here. I can show the blocked paths, invoices and paid history."
        )
    if "mark" in lower and "invoice" in lower and re.search(r"\bpaid\b", lower):
        return (
            "I can't mark an invoice paid directly. Ask me to record the sample payment and "
            "confirm the dialog; the graph changes only after you confirm."
        )
    if re.search(
        r"\b(?:create|add|delete|remove|update|set|write|save|change|rename)\b", lower
    ) and re.search(r"\b(?:project|milestone|status|graph|invoice|deliverable)\b", lower):
        if "accept" not in lower and not re.search(r"\brecord\b", lower):
            return (
                "I can't create, change or delete graph data directly. Draft a plan and accept "
                "it, or record a sample payment, and confirm the dialog. I can also show the "
                "projects, blocked paths and paid history."
            )
    if re.search(r"\bunlock\b", lower) and "deliverable" in lower:
        return (
            "Unlocking a deliverable happens only through a confirmed sample payment. "
            "The payment unlocks only that milestone's deliverable."
        )
    return None


def _skill_for(message: str) -> str | None:
    lower = message.lower()
    for needle, skill in SKILLS.items():
        if needle in lower:
            return skill
    return None


def _invoice_number(message: str) -> str | None:
    match = re.search(r"\bWG-\d+\b", message.upper())
    return match.group(0) if match else None


def _project_name(message: str) -> str:
    lower = message.lower()
    if "brand" in lower:
        return "Brand refresh"
    if "research" in lower:
        return "Research project"
    return "New project"


def _choose(message: str, offered: set[str]) -> tuple[str | None, dict]:
    lower = message.lower()
    if "accept" in lower and "plan" in lower:
        return "website_accept_plan", {
            "projectName": _project_name(message),
            "milestones": PLAN_TEMPLATE,
        }
    if re.search(r"\brecord\b", lower) and "payment" in lower:
        return "website_get_graph_state", {}
    if re.search(r"\bfill\b", lower) and ("draft" in lower or "plan" in lower):
        return "website_fill_draft", {"brief": message}
    if "plan" in lower or "propose" in lower or "draft" in lower:
        return "website_propose_plan", {"brief": message}
    if (
        ("blocked" in lower or "decline" in lower)
        and ("until" in lower or "paid" in lower or "invoice" in lower)
    ) or "decline path" in lower:
        invoice = _invoice_number(message)
        if invoice:
            return "website_get_decline_path", {"invoice": invoice}
        return "website_get_graph_state", {}
    if any(
        phrase in lower
        for phrase in ("similar", "who has been paid", "paid for", "worked before", "worked on")
    ):
        skill = _skill_for(message)
        if skill is None:
            return None, {"clarify": "skill"}
        return "website_search_similar_work", {"skill": skill}
    if any(
        phrase in lower
        for phrase in ("blocked", "waiting", "unpaid", "dependency", "depends", "depend on")
    ):
        return "website_get_graph_state", {}
    if "tool" in lower and "available" in lower:
        return None, {}
    return "website_get_graph_state", {}


def _receipt(content: Any) -> dict | None:
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (TypeError, ValueError):
        return None
    if isinstance(data, list):
        data = data[-1] if data else None
    return data if isinstance(data, dict) else None


def _find_invoice(result: dict, number: str | None) -> dict | None:
    for project in result.get("projects") or []:
        for milestone in project.get("milestones") or []:
            invoice = milestone.get("invoice")
            if not invoice or invoice.get("status") != "SENT":
                continue
            if number is None or invoice.get("number") == number:
                return {
                    **invoice,
                    "project_id": project.get("id"),
                    "milestone_id": milestone.get("id"),
                }
    return None


def _blocked_cause(blocker: dict) -> str:
    if blocker.get("reason") == "unpaid_invoice":
        return (
            f"unpaid invoice {blocker.get('invoice')}, "
            f"{blocker.get('amount_cents')} cents"
        )
    path = blocker.get("path") or []
    return f"{path[-1] if path else 'a prerequisite'} is not marked done"


def _answer_graph_state(result: dict, message: str) -> str:
    projects = result.get("projects") or []
    focus_blocked = any(
        phrase in message.lower()
        for phrase in ("blocked", "waiting", "unpaid", "dependency", "depend")
    )
    if focus_blocked:
        blocked_lines = []
        clear_projects = []
        for project in projects:
            entries = []
            for milestone in project.get("milestones") or []:
                for blocker in milestone.get("blocked_by") or []:
                    entries.append(
                        f"{milestone.get('name')} [{milestone.get('id')}] is blocked by "
                        f"{blocker.get('path', [''])[-1]} ({_blocked_cause(blocker)})"
                    )
            if entries:
                blocked_lines.append(f"{project.get('name')}: " + "; ".join(entries) + ".")
            else:
                clear_projects.append(str(project.get("name")))
        if not blocked_lines:
            return "No milestones are blocked in the sample graph."
        tail = ""
        if clear_projects:
            tail = f" {', '.join(clear_projects)} has no blocked milestones."
        return " ".join(blocked_lines) + tail

    lines = []
    for project in projects:
        stats = project.get("stats") or {}
        milestones = project.get("milestones") or []
        states = ", ".join(
            f"{milestone.get('name')} [{milestone.get('id')}] {milestone.get('status')}"
            for milestone in milestones
        )
        lines.append(
            f"{project.get('name')} [{project.get('id')}]: {stats.get('done')}/"
            f"{stats.get('milestones')} done, {stats.get('blocked')} blocked, "
            f"{stats.get('paid_cents')} of {stats.get('total_cents')} cents paid. {states}."
        )
    return " ".join(lines) or "The graph has no projects."


def _answer_similar(result: dict) -> str:
    skill = result.get("skill") or "that skill"
    work = result.get("work") or []
    if not work:
        return f"No paid milestone uses {skill} in the sample graph."
    rows = []
    for row in work:
        rows.append(
            f"{row.get('party')} on {row.get('project')}, {row.get('milestone')}, "
            f"invoice [{row.get('invoice')}], {row.get('amount_cents')} cents"
        )
    return f"Paid work for {skill}: " + "; ".join(rows) + "."


def _answer_plan(result: dict) -> str:
    draft = result
    milestones = draft.get("milestones") or []
    names = [str(milestone.get("name")) for milestone in milestones]
    dependencies = []
    for milestone in milestones:
        for parent in milestone.get("depends_on") or []:
            dependencies.append(f"{milestone.get('name')} after {parent}")
    similar = draft.get("similar_work") or []
    similar_text = ""
    if similar:
        rows = [
            f"{row.get('party')} on {row.get('project')} ({row.get('milestone')})"
            for row in similar[:3]
        ]
        similar_text = " Similar paid work: " + "; ".join(rows) + "."
    return (
        f"Draft plan for {draft.get('projectName') or 'a new project'}: "
        f"{' -> '.join(names)}. "
        f"Dependencies: {', '.join(dependencies) if dependencies else 'none'}. "
        f"No amounts are proposed.{similar_text} "
        "This is a draft only, so the graph did not change. Ask me to accept it and confirm "
        "the dialog when you are ready."
    )


def _answer_draft(result: dict) -> str:
    stored = result.get("draft")
    draft = stored if isinstance(stored, dict) else result
    names = [str(milestone.get("name")) for milestone in draft.get("milestones") or []]
    return (
        f"Saved a draft plan for {draft.get('projectName') or 'a new project'} in this tab: "
        f"{' -> '.join(names)}. The graph did not change. Ask me to accept it and confirm "
        "the dialog when you are ready."
    )


def _answer_decline(result: dict) -> str:
    invoice = result.get("invoice") or {}
    blocked = result.get("blocked") or []
    if not blocked:
        return f"Invoice [{invoice.get('number')}] has no downstream milestones waiting on it."
    rows = [
        f"{row.get('blocked')} [{row.get('blocked_id')}] {row.get('status')}"
        for row in blocked
    ]
    return (
        f"Until invoice [{invoice.get('number')}] for {invoice.get('amount_cents')} cents is "
        f"paid, these milestones stay blocked: " + "; ".join(rows) + "."
    )


def _answer_accept(result: dict) -> str:
    project = (result.get("project") or {}).get("project") or {}
    ids = result.get("node_ids") or {}
    milestones = ", ".join(ids.get("milestones") or [])
    return (
        f"Accepted the plan and created {project.get('name')} [{project.get('id')}]. "
        f"Milestone ids: {milestones}. The graph changed; no real money moved."
    )


def _answer_payment(result: dict) -> str:
    unlocked = ", ".join(
        f"{item.get('name')} [{item.get('id')}]" for item in result.get("unlocked") or []
    )
    return (
        f"Recorded sample payment [{result.get('payment_id')}] for invoice "
        f"[{result.get('invoice_id')}] at {result.get('amount_cents')} cents. "
        f"Unlocked: {unlocked or 'nothing'}. No real money moved."
    )


def _answer_from_tool(receipt: dict, message: str) -> str:
    status = receipt.get("status")
    if status == "cancelled":
        return "You declined the action, so nothing changed."
    if status == "unknown":
        return "That action had an unknown outcome. Check the page before doing anything else; do not retry."
    if status != "succeeded":
        return "The site did not return a completed result, so I will not guess."

    result = receipt.get("result")
    if not isinstance(result, dict):
        return "The site returned no usable data, so I will not guess."
    if result.get("ok") is False:
        return f"The site refused: {result.get('reason') or 'no reason was given'}. Nothing changed."

    action = str(receipt.get("action") or "")
    if action.endswith("get_graph_state"):
        return _answer_graph_state(result, message)
    if action.endswith("get_decline_path"):
        return _answer_decline(result)
    if action.endswith("search_similar_work"):
        return _answer_similar(result)
    if action.endswith("propose_plan"):
        return _answer_plan(result)
    if action.endswith("fill_draft"):
        return _answer_draft(result)
    if action.endswith("accept_plan"):
        return _answer_accept(result)
    if action.endswith("record_payment"):
        return _answer_payment(result)
    return "The site returned data I do not know how to present, so I will not guess."


def demo_reply(payload: dict) -> dict:
    """Return the next scripted reply for an OpenAI-compatible chat request."""
    messages = _messages(payload)
    user = _last_user(messages)
    offered = _offered(payload)

    tool_messages = [message for message in messages if message.get("role") == "tool"]
    if tool_messages:
        receipt = _receipt(tool_messages[-1].get("content"))
        if receipt is None:
            content = "I could not read the tool result, so I will not guess."
            return {"content": content, "tool_call": None, "model": MODEL}
        action = str(receipt.get("action") or "")
        if action.endswith("get_graph_state") and re.search(
            r"\brecord\b", user.lower()
        ) and "payment" in user.lower():
            result = receipt.get("result") or {}
            invoice = _find_invoice(result, _invoice_number(user))
            if invoice is None:
                return {
                    "content": (
                        "I could not find an open invoice with that number, so nothing changed. "
                        "Ask for a project or invoice from the graph first."
                    ),
                    "tool_call": None,
                    "model": MODEL,
                }
            return {
                "content": "",
                "tool_call": {
                    "id": "call_demo_payment",
                    "name": "website_record_payment",
                    "arguments": {
                        "invoiceId": invoice.get("id"),
                        "amountCents": invoice.get("amount_cents"),
                    },
                },
                "model": MODEL,
            }
        content = _answer_from_tool(receipt, user)
        return {"content": content, "tool_call": None, "model": MODEL}

    refusal = _refusal(user)
    if refusal:
        return {"content": refusal, "tool_call": None, "model": MODEL}

    action, arguments = _choose(user, offered)
    if action is None:
        if arguments.get("clarify") == "skill":
            return {
                "content": (
                    "I can search only the skills on this graph: Design systems, User research "
                    "and Front-end build. Which one should I look up?"
                ),
                "tool_call": None,
                "model": MODEL,
            }
        return {
            "content": "I can read the WorkGraph sample graph, but that action is not available here.",
            "tool_call": None,
            "model": MODEL,
        }
    if action not in offered:
        return {
            "content": (
                "That read action is not connected on this page, so I cannot answer from the "
                "graph. Nothing changed."
            ),
            "tool_call": None,
            "model": MODEL,
        }
    return {
        "content": "",
        "tool_call": {"id": "call_demo_1", "name": action, "arguments": arguments},
        "model": MODEL,
    }
