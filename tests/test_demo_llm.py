import json

from backend.demo_llm import demo_reply

TOOLS = [
    {"type": "function", "function": {"name": name}}
    for name in (
        "website_get_graph_state",
        "website_search_similar_work",
        "website_get_decline_path",
        "website_propose_plan",
        "website_fill_draft",
        "website_accept_plan",
        "website_record_payment",
        "render_cruse",
    )
]

STATE_RECEIPT = {
    "action": "website_get_graph_state",
    "status": "succeeded",
    "result": {
        "projects": [
            {
                "id": "proj-harbour",
                "name": "Harbour rebrand",
                "status": "active",
                "stats": {"milestones": 4, "done": 1, "blocked": 2, "paid_cents": 180000, "total_cents": 830000},
                "milestones": [
                    {"id": "ms-h1", "name": "Discovery", "status": "DONE", "blocked_by": []},
                    {
                        "id": "ms-h2",
                        "name": "Design system",
                        "status": "SENT",
                        "invoice": {
                            "id": "inv-h2",
                            "number": "WG-1002",
                            "status": "SENT",
                            "amount_cents": 240000,
                        },
                        "blocked_by": [],
                    },
                    {
                        "id": "ms-h3",
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
                "id": "proj-atlas",
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


def test_accept_plan_calls_the_irreversible_action():
    reply = demo_reply(
        {
            "messages": [{"role": "user", "content": "Accept the plan and write it to the graph."}],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"]["name"] == "website_accept_plan"
    assert reply["tool_call"]["arguments"]["projectName"] == "New project"
    assert [step["name"] for step in reply["tool_call"]["arguments"]["milestones"]] == [
        "Scope",
        "Design",
        "Build",
        "Handover",
    ]


def test_decline_path_question_calls_the_invoice_traversal():
    reply = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Which milestones are blocked until WG-1002 is paid?"}
            ],
            "tools": TOOLS,
        }
    )
    assert reply["tool_call"]["name"] == "website_get_decline_path"
    assert reply["tool_call"]["arguments"] == {"invoice": "WG-1002"}


def test_record_payment_reads_the_state_then_asks_to_record_the_exact_invoice():
    first = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Record the sample payment for WG-1002."}
            ],
            "tools": TOOLS,
        }
    )
    assert first["tool_call"]["name"] == "website_get_graph_state"

    second = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Record the sample payment for WG-1002."},
                {
                    "role": "tool",
                    "name": "website_get_graph_state",
                    "content": json.dumps(STATE_RECEIPT),
                },
            ],
            "tools": TOOLS,
        }
    )
    assert second["tool_call"]["name"] == "website_record_payment"
    assert second["tool_call"]["arguments"] == {
        "invoiceId": "inv-h2",
        "amountCents": 240000,
    }


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

def test_decline_result_cites_the_invoice_and_blocked_ids():
    receipt = {
        "action": "website_get_decline_path",
        "status": "succeeded",
        "result": {
            "invoice": {"id": "inv-h2", "number": "WG-1002", "status": "SENT", "amount_cents": 240000},
            "milestone": {"id": "ms-h2", "name": "Design system"},
            "blocked": [
                {"blocked_id": "ms-h3", "blocked": "Build", "status": "BLOCKED", "reason": "unpaid_invoice"},
                {"blocked_id": "ms-h4", "blocked": "Handover", "status": "BLOCKED", "reason": "unpaid_invoice"},
            ],
            "blocked_count": 2,
        },
    }
    reply = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Which milestones are blocked until WG-1002 is paid?"},
                {"role": "tool", "name": "website_get_decline_path", "content": json.dumps(receipt)},
            ],
            "tools": TOOLS,
        }
    )
    assert "WG-1002" in reply["content"]
    assert "Build [ms-h3]" in reply["content"]
    assert "Handover [ms-h4]" in reply["content"]


def test_accept_result_cites_the_project_and_milestone_ids():
    receipt = {
        "action": "website_accept_plan",
        "status": "succeeded",
        "result": {
            "accepted": True,
            "project": {"project": {"id": "proj-new", "name": "Brand refresh"}},
            "node_ids": {
                "project": "proj-new",
                "milestones": ["ms-new-1", "ms-new-2", "ms-new-3", "ms-new-4"],
                "invoices": ["inv-new-1", "inv-new-2"],
            },
        },
    }
    reply = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Accept the plan for a brand project."},
                {"role": "tool", "name": "website_accept_plan", "content": json.dumps(receipt)},
            ],
            "tools": TOOLS,
        }
    )
    assert "Brand refresh [proj-new]" in reply["content"]
    assert "ms-new-1" in reply["content"]


def test_payment_result_cites_the_payment_invoice_and_deliverable():
    receipt = {
        "action": "website_record_payment",
        "status": "succeeded",
        "result": {
            "payment_id": "pay-test",
            "invoice_id": "inv-h2",
            "amount_cents": 240000,
            "unlocked": [{"id": "del-h2", "name": "Design system kit"}],
        },
    }
    reply = demo_reply(
        {
            "messages": [
                {"role": "user", "content": "Record the sample payment for WG-1002."},
                {"role": "tool", "name": "website_record_payment", "content": json.dumps(receipt)},
            ],
            "tools": TOOLS,
        }
    )
    assert "pay-test" in reply["content"]
    assert "inv-h2" in reply["content"]
    assert "Design system kit [del-h2]" in reply["content"]
