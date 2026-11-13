import json

from backend.demo_llm import demo_reply

TOOLS = [
    {"type": "function", "function": {"name": name}}
    for name in (
        "website_get_graph_state",
        "website_search_similar_work",
        "website_propose_plan",
        "website_fill_draft",
        "render_cruse",
    )
]

STATE_RECEIPT = {
    "action": "website_get_graph_state",
    "status": "succeeded",
    "result": {
        "projects": [
            {
                "name": "Harbour rebrand",
                "status": "active",
                "stats": {"milestones": 4, "done": 1, "blocked": 2, "paid_cents": 180000, "total_cents": 830000},
                "milestones": [
                    {"name": "Discovery", "status": "DONE", "blocked_by": []},
                    {
                        "name": "Build",
                        "status": "BLOCKED",
                        "blocked_by": [
                            {
                                "path": ["Build", "Design system"],
                                "reason": "unpaid_invoice",
                                "invoice": "WG-1002",
                                "amount_cents": 240000,
                            }
                        ],
                    },
                ],
            },
            {
                "name": "Atlas dashboard",
                "status": "paid",
                "stats": {"milestones": 2, "done": 2, "blocked": 0, "paid_cents": 380000, "total_cents": 380000},
                "milestones": [],
            },
        ]
    },
}


def test_card_charge_is_refused_without_a_tool_call():
    reply = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Record a real card payment for the design system."}
            ],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"] is None
    assert "can't charge a card" in reply["content"]
    assert "sample payments" in reply["content"]


def test_card_and_email_paraphrases_are_refused():
    for message, phrase in (
        ("Can you do a card charge for the design system?", "can't charge a card"),
        ("Charge my credit card for the design system.", "can't charge a card"),
        ("Please email the invoice to the client.", "can't send email"),
        ("Send the invoice by email.", "can't send email"),
        ("Mark the invoice as paid.", "can't mark an invoice paid"),
    ):
        reply = demo_reply(
            {"messages": [{"role": "user", "content": message}], "tools": TOOLS}
        )
        assert reply["tool_call"] is None, message
        assert phrase in reply["content"], message


def test_unknown_skill_asks_for_a_known_skill():
    reply = demo_reply(
        {
            "messages": [{"role": "user", "content": "Who has been paid for accounting work before?"}],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"] is None
    assert "Design systems" in reply["content"]
    assert "User research" in reply["content"]


def test_fulfill_does_not_trigger_the_fill_draft_action():
    reply = demo_reply(
        {
            "messages": [{"role": "user", "content": "How do I fulfill the plan?"}],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"]["name"] == "website_propose_plan"


def test_generic_graph_write_requests_are_refused():
    for message in (
        "Create a new project called Brand X.",
        "Delete the Build milestone.",
        "Update the Design system status to DONE.",
        "Add a milestone called Launch.",
    ):
        reply = demo_reply(
            {"messages": [{"role": "user", "content": message}], "tools": TOOLS}
        )
        assert reply["tool_call"] is None, message
        assert "can't create, change or delete graph data" in reply["content"], message


def test_supported_read_questions_are_not_refused():
    for message in (
        "Which deliverables are unlocked?",
        "Which card payment is unpaid?",
        "Which invoice was emailed to the client?",
        "Which payments are recorded?",
    ):
        reply = demo_reply(
            {"messages": [{"role": "user", "content": message}], "tools": TOOLS}
        )
        assert reply["tool_call"] is not None, message
        assert reply["tool_call"]["name"] == "website_get_graph_state", message


def test_blocked_question_calls_the_graph_state_tool():
    reply = demo_reply(
        {
            "messages": [{"role": "user", "content": "Which milestones are blocked by an unpaid invoice?"}],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"]["name"] == "website_get_graph_state"


def test_similar_work_question_calls_the_skill_tool():
    reply = demo_reply(
        {
            "messages": [{"role": "user", "content": "Who has been paid for design-system work before?"}],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"]["name"] == "website_search_similar_work"
    assert reply["tool_call"]["arguments"] == {"skill": "Design systems"}


def test_plan_question_calls_the_plan_tool():
    reply = demo_reply(
        {
            "messages": [{"role": "user", "content": "Propose a plan for a new brand project."}],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"]["name"] == "website_propose_plan"
    assert reply["tool_call"]["arguments"]["brief"] == "Propose a plan for a new brand project."


def test_draft_a_plan_question_also_proposes_it_first():
    reply = demo_reply(
        {
            "messages": [{"role": "user", "content": "Draft a four-step plan for a new brand project."}],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"]["name"] == "website_propose_plan"


def test_draft_question_calls_the_draft_tool():
    reply = demo_reply(
        {
            "messages": [{"role": "user", "content": "Fill in a draft plan for a new brand project."}],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"]["name"] == "website_fill_draft"


def test_accept_plan_is_refused_without_a_tool_call():
    reply = demo_reply(
        {
            "messages": [{"role": "user", "content": "Accept the plan and write it to the graph."}],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"] is None
    assert "not available" in reply["content"]
    assert "project page" in reply["content"]


def test_graph_state_result_produces_a_grounded_blocked_answer():
    reply = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Which milestones are blocked by an unpaid invoice?"},
                {
                    "role": "tool",
                    "name": "website_get_graph_state",
                    "content": json.dumps(STATE_RECEIPT),
                },
            ],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"] is None
    assert "Harbour rebrand" in reply["content"]
    assert "Build" in reply["content"]
    assert "WG-1002" in reply["content"]
    assert "240000" in reply["content"]
    assert "Atlas dashboard has no blocked milestones" in reply["content"]


def test_similar_result_produces_a_grounded_answer():
    receipt = {
        "action": "website_search_similar_work",
        "status": "succeeded",
        "result": {
            "skill": "Design systems",
            "work": [
                {
                    "party": "Jules Okafor",
                    "project": "Atlas dashboard",
                    "milestone": "Audit",
                    "invoice": "WG-1003",
                    "amount_cents": 120000,
                }
            ],
        },
    }
    reply = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Who has been paid for design-system work before?"},
                {"role": "tool", "name": "website_search_similar_work", "content": json.dumps(receipt)},
            ],
            "tools": TOOLS,
        }
    )
    assert "Jules Okafor" in reply["content"]
    assert "WG-1003" in reply["content"]
    assert "120000" in reply["content"]


def test_cancelled_and_unknown_receipts_are_not_retried():
    for status, phrase in (("cancelled", "declined"), ("unknown", "do not retry")):
        reply = demo_reply(
            {
                "messages": [
                    {"role": "user", "content": "Do the thing."},
                    {
                        "role": "tool",
                        "name": "website_get_graph_state",
                        "content": json.dumps({"action": "website_get_graph_state", "status": status}),
                    },
                ],
                "tools": TOOLS,
            }
        )
        assert reply["tool_call"] is None
        assert phrase in reply["content"].lower()


def test_plan_and_draft_results_use_the_returned_milestones():
    draft = {
        "draft": True,
        "brief": "A new brand project.",
        "projectName": "Brand refresh",
        "milestones": [
            {"name": "Scope", "depends_on": []},
            {"name": "Design", "depends_on": ["Scope"]},
        ],
        "similar_work": [],
    }
    plan_reply = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Propose a plan."},
                {
                    "role": "tool",
                    "name": "website_propose_plan",
                    "content": json.dumps(
                        {"action": "website_propose_plan", "status": "succeeded", "result": {"ok": True, **draft}}
                    ),
                },
            ],
            "tools": TOOLS,
        }
    )
    assert "Brand refresh" in plan_reply["content"]
    assert "Scope -> Design" in plan_reply["content"]
    assert "No amounts are proposed" in plan_reply["content"]

    fill_reply = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Fill the draft."},
                {
                    "role": "tool",
                    "name": "website_fill_draft",
                    "content": json.dumps(
                        {
                            "action": "website_fill_draft",
                            "status": "succeeded",
                            "result": {"ok": True, "saved": True, "draft": draft},
                        }
                    ),
                },
            ],
            "tools": TOOLS,
        }
    )
    assert "Saved a draft plan" in fill_reply["content"]
    assert "Scope -> Design" in fill_reply["content"]
