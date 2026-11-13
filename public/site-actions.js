// Registers WorkGraph's read actions and the local draft action with the agent runtime.
// No graph writes are registered in this milestone. The page's own buttons still use
// the FastAPI endpoints, and these reads call the same endpoints.
import { WorkGraphPage } from "./page-bridge.js";

class SiteActions {
  static registerActions(actions) {
    actions.register(SiteActions.graphStateAction());
    actions.register(SiteActions.similarAction());
    actions.register(SiteActions.declinePathAction());
    actions.register(SiteActions.planAction());
    actions.register(SiteActions.draftAction());
    actions.register(SiteActions.acceptPlanAction());
    actions.register(SiteActions.recordPaymentAction());
  }

  static graphStateAction() {
    return {
      name: "get_graph_state",
      description:
        "Read the sample projects, their milestones and statuses, blocked-by paths with invoice numbers and integer cents, invoices, payments, deliverables and the skill names on this site. Changes nothing.",
      effect: "read",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      execute: () => WorkGraphPage.getGraphState(),
    };
  }

  static similarAction() {
    return {
      name: "search_similar_work",
      description:
        "Find paid milestones on sample projects that need a skill and were worked by a party who has that skill. Returns the party, project, milestone, invoice number and integer cents. Changes nothing.",
      effect: "read",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["skill"],
        properties: {
          skill: {
            type: "string",
            minLength: 1,
            maxLength: 80,
            description:
              "Skill name exactly as website_get_graph_state returns it, for example Design systems.",
          },
        },
      },
      execute: (args) => WorkGraphPage.searchSimilarWork(args.skill),
    };
  }

  static declinePathAction() {
    return {
      name: "get_decline_path",
      description:
        "List every milestone that stays blocked until one invoice is paid, with the invoice number, amount in integer cents and each blocked milestone id and status. Changes nothing.",
      effect: "read",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["invoice"],
        properties: {
          invoice: {
            type: "string",
            minLength: 1,
            maxLength: 40,
            description: "Invoice number exactly as get_graph_state returns it, for example WG-1002.",
          },
        },
      },
      execute: (args) => WorkGraphPage.getDeclinePath(args.invoice),
    };
  }

  static planAction() {    return {
      name: "propose_plan",
      description:
        "Propose a four-step milestone plan and its dependencies from a short brief, with similar paid work from the graph. Amounts are not proposed. Changes nothing and does not accept the plan.",
      effect: "read",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["brief"],
        properties: {
          brief: {
            type: "string",
            minLength: 1,
            maxLength: 600,
            description: "The project brief in the visitor's words.",
          },
          projectName: {
            type: "string",
            minLength: 1,
            maxLength: 80,
            description: "A name for the draft project. Optional.",
          },
        },
      },
      execute: (args) => WorkGraphPage.proposePlan(args),
    };
  }

  static draftAction() {
    return {
      name: "fill_draft",
      description:
        "Save the proposed milestone plan as a local draft in this browser tab. It writes no graph data and does not accept the plan. Returns the saved draft.",
      effect: "write",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["brief"],
        properties: {
          brief: {
            type: "string",
            minLength: 1,
            maxLength: 600,
            description: "The project brief in the visitor's words.",
          },
          projectName: {
            type: "string",
            minLength: 1,
            maxLength: 80,
            description: "A name for the draft project. Optional.",
          },
        },
      },
      execute: (args) => WorkGraphPage.fillDraft(args),
    };
  }

  static acceptPlanAction() {
    return {
      name: "accept_plan",
      description:
        "Create the four-step sample project from the reviewed plan. This is irreversible and the browser shows a confirmation dialog first. Cancel changes nothing. Only the Scope, Design, Build, Handover template is accepted; the server assigns the sample amounts.",
      effect: "irreversible",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["projectName", "milestones"],
        properties: {
          projectName: {
            type: "string",
            minLength: 1,
            maxLength: 80,
            description: "The project name the visitor approved.",
          },
          milestones: {
            type: "array",
            minItems: 4,
            maxItems: 4,
            items: {
              type: "object",
              additionalProperties: false,
              required: ["name", "depends_on"],
              properties: {
                name: {
                  type: "string",
                  minLength: 1,
                  maxLength: 80,
                },
                depends_on: {
                  type: "array",
                  items: { type: "string", maxLength: 80 },
                },
              },
            },
            description: "The four plan steps and their dependencies, in order.",
          },
        },
      },
      execute: (args) => WorkGraphPage.acceptPlan(args),
    };
  }

  static recordPaymentAction() {
    return {
      name: "record_payment",
      description:
        "Record one sample ledger payment for an open invoice, using the exact invoice amount in integer cents. This is irreversible and the browser shows a confirmation dialog first. Cancel changes nothing. It unlocks only that milestone's deliverable. It never charges a card and never moves real money.",
      effect: "irreversible",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["invoiceId", "amountCents"],
        properties: {
          invoiceId: {
            type: "string",
            minLength: 1,
            maxLength: 80,
            description: "Invoice id from get_graph_state, for example inv-h2.",
          },
          amountCents: {
            type: "integer",
            minimum: 1,
            description: "The exact invoice amount in integer cents from get_graph_state.",
          },
        },
      },
      execute: (args) => WorkGraphPage.recordPayment(args),
    };
  }
}

export const registerActions = SiteActions.registerActions;
