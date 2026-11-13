// Registers WorkGraph's read actions and the local draft action with the agent runtime.
// No graph writes are registered in this milestone. The page's own buttons still use
// the FastAPI endpoints, and these reads call the same endpoints.
import { WorkGraphPage } from "./page-bridge.js";

class SiteActions {
  static registerActions(actions) {
    actions.register(SiteActions.graphStateAction());
    actions.register(SiteActions.similarAction());
    actions.register(SiteActions.planAction());
    actions.register(SiteActions.draftAction());
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

  static planAction() {
    return {
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
        "Save the proposed milestone plan as a local draft in this browser tab. It writes no graph data and does not accept the plan. Returns the saved draft and a note that accepting it is not available yet.",
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
}

export const registerActions = SiteActions.registerActions;
