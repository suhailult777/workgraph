// Registers WorkGraph's read operations with the agent runtime.
// Phase 0 exposes reads only. Writes and confirmation arrive in Phase 1.

const json = async (url) => {
  const response = await fetch(url, { headers: { accept: "application/json" } });
  if (!response.ok) {
    return { ok: false, reason: `The graph service answered ${response.status}.` };
  }
  return response.json();
};

class SiteActions {
  static registerActions(actions) {
    actions.register(SiteActions.graphStateAction());
    actions.register(SiteActions.blockedAction());
    actions.register(SiteActions.similarAction());
  }

  static graphStateAction() {
    return {
      name: "get_graph_state",
      description:
        "Read the sample graph's node counts, projects and milestone statuses from the WorkGraph service.",
      effect: "read",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      execute: () => json("/api/graph/summary"),
    };
  }

  static blockedAction() {
    return {
      name: "get_blocked_milestones",
      description:
        "List milestones that depend, in one to three DEPENDS_ON hops, on a milestone whose invoice is SENT and unpaid. Returns the blocked milestone, the milestone it waits on, the invoice number and the amount in integer cents.",
      effect: "read",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      execute: () => json("/api/graph/blocked"),
    };
  }

  static similarAction() {
    return {
      name: "search_similar_work",
      description:
        "Find paid milestones on sample projects that list a skill, with the party who worked on the project and the amount in integer cents.",
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
            description: "Skill name exactly as the graph spells it, for example Design systems.",
          },
        },
      },
      execute: (args) => json(`/api/graph/similar?skill=${encodeURIComponent(args.skill)}`),
    };
  }
}

export const registerActions = SiteActions.registerActions;
